"""Entrypoint: two uvicorn servers on one asyncio loop, sharing one Store.

Implemented by the core package.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import signal
import socket
import sys

import uvicorn

from .config import Settings, settings_from_env
from .mcp_server import build_mcp_app
from .panel import build_panel_app
from .store import Store

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _disable_own_signal_handling(server: uvicorn.Server) -> None:
    """uvicorn.Server.serve() wraps itself in a signal-capturing context manager.

    Two Server.serve() coroutines interleaved on one event loop each install
    their own SIGINT/SIGTERM handler via plain `signal.signal`; the second one
    silently clobbers the first, so only the last-started server would ever
    see a shutdown signal. We disable that per-server capture and install one
    shared handler in `_run` instead.
    """
    server.capture_signals = contextlib.nullcontext


WILDCARDS = {"", "0.0.0.0", "::", "*"}  # noqa: S104 - these are what we refuse


def check_panel_binds(settings: Settings) -> None:
    """The panel endpoint is unauthenticated: every bind must be a real address."""
    if not settings.panel_bind:
        raise SystemExit("refusing to start: DISPLAY_MCP_PANEL_BIND is empty")
    for addr in settings.panel_bind:
        if addr in WILDCARDS:
            raise SystemExit(
                f"refusing to start: DISPLAY_MCP_PANEL_BIND contains {addr!r}. "
                "The panel endpoint is unauthenticated and read-only; bind it to "
                "explicit addresses (the LAN address plus 127.0.0.1), never to all "
                "interfaces."
            )


def _is_loopback(addr: str) -> bool:
    if addr == "localhost":
        return True
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def check_mcp_binds(settings: Settings) -> None:
    """The MCP endpoint is loopback, plus at most a tunnel-only network address.

    A non-loopback address is how a cloudflared running elsewhere (its own
    container on a network only it and this host share) reaches the endpoint.
    Off loopback, auth.py's local-operator exemption never applies, so every
    request needs an Access JWT -- which is why such an address is refused
    while Access is unconfigured: authless is a loopback-only mode.
    """
    if not settings.mcp_bind:
        raise SystemExit("refusing to start: DISPLAY_MCP_MCP_HOST is empty")
    for addr in settings.mcp_bind:
        if addr in WILDCARDS:
            raise SystemExit(
                f"refusing to start: DISPLAY_MCP_MCP_HOST contains {addr!r}. Bind the "
                "MCP endpoint to 127.0.0.1, plus the tunnel network's address if "
                "cloudflared runs elsewhere, never to all interfaces."
            )
        if not _is_loopback(addr) and not settings.auth_enabled:
            raise SystemExit(
                f"refusing to start: DISPLAY_MCP_MCP_HOST contains {addr!r}, which is "
                "not loopback, and Cloudflare Access is not configured. Set "
                "DISPLAY_MCP_CF_ACCESS_TEAM_DOMAIN and DISPLAY_MCP_CF_ACCESS_AUD, or "
                "bind the MCP endpoint to 127.0.0.1 only."
            )


def _bind_sockets(addrs: tuple[str, ...], port: int) -> list[socket.socket]:
    """One pre-bound listening socket per address.

    Binding each address explicitly is the whole point: a socket bound to
    192.168.1.10 cannot answer on the host's global IPv6 address, and a v6
    socket is v6-only so it never quietly covers v4 as well.
    """
    socks: list[socket.socket] = []
    try:
        for addr in addrs:
            family = socket.AF_INET6 if ":" in addr else socket.AF_INET
            s = socket.socket(family, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s.bind((addr, port))
            s.listen(128)
            s.set_inheritable(True)
            socks.append(s)
    except OSError:
        for s in socks:
            s.close()
        raise
    return socks


def bind_panel_sockets(settings: Settings) -> list[socket.socket]:
    """One pre-bound listening socket per configured panel address."""
    check_panel_binds(settings)
    return _bind_sockets(settings.panel_bind, settings.panel_port)


def bind_mcp_sockets(settings: Settings) -> list[socket.socket]:
    """One pre-bound listening socket per configured MCP address."""
    check_mcp_binds(settings)
    return _bind_sockets(settings.mcp_bind, settings.mcp_port)


ServerSpec = tuple[uvicorn.Server, list[socket.socket] | None]


def _build_servers(store: Store, settings: Settings) -> list[ServerSpec]:
    panel_app = build_panel_app(store, settings)
    panel_socks = bind_panel_sockets(settings)
    panel_cfg = uvicorn.Config(
        panel_app,
        host=settings.panel_bind[0],
        port=settings.panel_port,
        log_config=None,
        access_log=False,
    )
    panel = uvicorn.Server(panel_cfg)
    _disable_own_signal_handling(panel)
    for addr in settings.panel_bind:
        shown = f"[{addr}]" if ":" in addr else addr
        print(f"panel: http://{shown}:{settings.panel_port}/display.json")

    mcp_app = build_mcp_app(store, settings)
    try:
        mcp_socks = bind_mcp_sockets(settings)
    except BaseException:
        for s in panel_socks:
            s.close()
        raise
    mcp_cfg = uvicorn.Config(
        mcp_app,
        host=settings.mcp_bind[0],
        port=settings.mcp_port,
        log_config=None,
        access_log=False,
    )
    mcp = uvicorn.Server(mcp_cfg)
    _disable_own_signal_handling(mcp)
    for addr in settings.mcp_bind:
        shown = f"[{addr}]" if ":" in addr else addr
        print(f"mcp: http://{shown}:{settings.mcp_port}{settings.mcp_path}")

    return [(panel, panel_socks), (mcp, mcp_socks)]


async def _run(settings: Settings) -> None:
    store = Store(settings.state_dir, settings.font_dir)
    servers = _build_servers(store, settings)

    if settings.auth_enabled:
        print("Cloudflare Access auth: enabled")
    else:
        logger.warning(
            "Cloudflare Access auth is NOT configured (DISPLAY_MCP_CF_ACCESS_TEAM_DOMAIN / "
            "DISPLAY_MCP_CF_ACCESS_AUD unset) -- the MCP endpoint is authless. "
            "This is fine for local dev; never run it this way over the internet."
        )
        print("Cloudflare Access auth: DISABLED (authless MCP endpoint)")

    loop = asyncio.get_running_loop()

    def _shutdown() -> None:
        logger.info("shutdown signal received")
        for server, _ in servers:
            server.should_exit = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _shutdown)

    await asyncio.gather(*(server.serve(sockets=socks) for server, socks in servers))


def main() -> None:
    _configure_logging()
    settings = settings_from_env()

    check_panel_binds(settings)
    check_mcp_binds(settings)
    asyncio.run(_run(settings))


if __name__ == "__main__":
    main()
