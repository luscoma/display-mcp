"""Entrypoint: two uvicorn servers on one asyncio loop, sharing one Store.

Implemented by the core package.
"""

from __future__ import annotations

import asyncio
import contextlib
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


def _bind_sockets(var: str, addrs: tuple[str, ...], port: int) -> list[socket.socket]:
    """One pre-bound listening socket per address, whatever the addresses are.

    Which interfaces each listener appears on is the deployment's call
    (deploy/CONTAINER.md). Binding each address explicitly means a socket
    bound to 192.168.1.10 cannot answer on the host's global IPv6 address,
    and a v6 socket is v6-only so it never quietly covers v4 as well.
    """
    if not addrs:
        raise SystemExit(f"refusing to start: {var} is empty")
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
    return _bind_sockets("DISPLAY_MCP_PANEL_BIND", settings.panel_bind, settings.panel_port)


def bind_mcp_sockets(settings: Settings) -> list[socket.socket]:
    """One pre-bound listening socket per configured MCP address."""
    return _bind_sockets("DISPLAY_MCP_SERVER_HOST", settings.mcp_bind, settings.mcp_port)


ServerSpec = tuple[uvicorn.Server, list[socket.socket] | None]


def _build_servers(store: Store, settings: Settings) -> list[ServerSpec]:
    panel_socks = bind_panel_sockets(settings)
    try:
        mcp_socks = bind_mcp_sockets(settings)
    except BaseException:
        for s in panel_socks:
            s.close()
        raise

    panel_app = build_panel_app(store, settings)
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

    asyncio.run(_run(settings))


if __name__ == "__main__":
    main()
