from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import httpx
import pytest

from display_mcp import main as main_mod
from display_mcp.config import Settings, settings_from_env
from display_mcp.store import Store


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_settings_from_env_round_trip():
    env = {
        "DISPLAY_MCP_PANEL_BIND": "192.168.1.5",
        "DISPLAY_MCP_PANEL_PORT": "9090",
        "DISPLAY_MCP_MCP_HOST": "127.0.0.1",
        "DISPLAY_MCP_MCP_PORT": "9001",
        "DISPLAY_MCP_MCP_PATH": "/rpc",
        "DISPLAY_MCP_STATE_DIR": "/tmp/somewhere",
        "DISPLAY_MCP_FONT_DIR": "/tmp/fonts",
        "DISPLAY_MCP_CF_ACCESS_TEAM_DOMAIN": "https://team.cloudflareaccess.com",
        "DISPLAY_MCP_CF_ACCESS_AUD": "aud-tag",
    }
    settings = settings_from_env(env)
    assert settings.panel_bind == ("192.168.1.5",)
    assert settings.panel_port == 9090
    assert settings.mcp_host == "127.0.0.1"
    assert settings.mcp_port == 9001
    assert settings.mcp_path == "/rpc"
    assert settings.state_dir == Path("/tmp/somewhere")
    assert settings.font_dir == Path("/tmp/fonts")
    assert settings.cf_access_team_domain == "https://team.cloudflareaccess.com"
    assert settings.cf_access_aud == "aud-tag"
    assert settings.auth_enabled is True


def test_settings_from_env_defaults_are_authless():
    settings = settings_from_env({})
    assert settings.auth_enabled is False
    assert settings.panel_bind == ("127.0.0.1",)


def test_refuses_to_bind_panel_to_all_interfaces(monkeypatch):
    monkeypatch.setattr(
        main_mod,
        "settings_from_env",
        lambda: settings_from_env({"DISPLAY_MCP_PANEL_BIND": "0.0.0.0"}),
    )
    with pytest.raises(SystemExit):
        main_mod.main()


def test_panel_bind_parses_comma_list():
    settings = settings_from_env({"DISPLAY_MCP_PANEL_BIND": "192.168.1.5, 127.0.0.1,"})
    assert settings.panel_bind == ("192.168.1.5", "127.0.0.1")


@pytest.mark.parametrize("bad", ["0.0.0.0", "192.168.1.5,0.0.0.0", "::", "", " , "])
def test_wildcard_anywhere_in_bind_list_is_refused(bad):
    settings = settings_from_env({"DISPLAY_MCP_PANEL_BIND": bad})
    with pytest.raises(SystemExit):
        main_mod.check_panel_binds(settings)


def _ipv6_loopback_available() -> bool:
    import socket

    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.bind(("::1", 0))
        s.close()
        return True
    except OSError:
        return False


@pytest.mark.asyncio
async def test_panel_listens_on_every_configured_address(tmp_path):
    binds = ["127.0.0.1"] + (["::1"] if _ipv6_loopback_available() else [])
    settings = Settings(
        panel_bind=tuple(binds),
        panel_port=_free_port(),
        mcp_host="127.0.0.1",
        mcp_port=_free_port(),
        state_dir=tmp_path / "state",
        font_dir=tmp_path / "fonts",
    )
    store = Store(settings.state_dir, settings.font_dir)
    specs = main_mod._build_servers(store, settings)
    assert len(specs) == 2  # one server per listener: panel and MCP
    servers = [srv for srv, _ in specs]
    async def _serve_all() -> None:
        await asyncio.gather(*(srv.serve(sockets=socks) for srv, socks in specs))

    task = asyncio.create_task(_serve_all())
    try:
        for _ in range(200):
            if all(s.started for s in servers):
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("server did not start in time")
        async with httpx.AsyncClient() as client:
            for addr in binds:
                host = f"[{addr}]" if ":" in addr else addr
                resp = await client.get(f"http://{host}:{settings.panel_port}/healthz")
                assert resp.status_code == 200, addr
    finally:
        for s in servers:
            s.should_exit = True
        await asyncio.wait_for(task, timeout=5)


_ACCESS = {
    "DISPLAY_MCP_CF_ACCESS_TEAM_DOMAIN": "https://team.cloudflareaccess.com",
    "DISPLAY_MCP_CF_ACCESS_AUD": "aud-tag",
}


def test_mcp_host_parses_comma_list():
    settings = settings_from_env({"DISPLAY_MCP_MCP_HOST": "10.99.0.20, 127.0.0.1,"})
    assert settings.mcp_bind == ("10.99.0.20", "127.0.0.1")
    assert settings_from_env({}).mcp_bind == ("127.0.0.1",)


@pytest.mark.parametrize("bad", ["0.0.0.0", "10.99.0.20,0.0.0.0", "::", "", " , "])
def test_wildcard_anywhere_in_mcp_bind_list_is_refused(bad):
    settings = settings_from_env({"DISPLAY_MCP_MCP_HOST": bad, **_ACCESS})
    with pytest.raises(SystemExit):
        main_mod.check_mcp_binds(settings)


@pytest.mark.parametrize("addr", ["10.99.0.20", "fd00::20", "mcp.internal"])
def test_non_loopback_mcp_bind_needs_access(addr):
    authless = settings_from_env({"DISPLAY_MCP_MCP_HOST": f"{addr},127.0.0.1"})
    with pytest.raises(SystemExit, match="not loopback"):
        main_mod.check_mcp_binds(authless)
    main_mod.check_mcp_binds(
        settings_from_env({"DISPLAY_MCP_MCP_HOST": f"{addr},127.0.0.1", **_ACCESS})
    )


@pytest.mark.parametrize("addr", ["127.0.0.1", "127.0.0.2", "::1", "localhost"])
def test_loopback_mcp_bind_is_fine_authless(addr):
    main_mod.check_mcp_binds(settings_from_env({"DISPLAY_MCP_MCP_HOST": addr}))


def test_main_refuses_a_non_loopback_mcp_bind_without_access(monkeypatch):
    monkeypatch.setattr(
        main_mod,
        "settings_from_env",
        lambda: settings_from_env({"DISPLAY_MCP_MCP_HOST": "10.99.0.20"}),
    )
    with pytest.raises(SystemExit):
        main_mod.main()


@pytest.mark.asyncio
async def test_mcp_listens_on_every_configured_address(tmp_path):
    # 127.0.0.2 stands in for the tunnel network's address: a second,
    # distinct address the MCP listener must answer on, and one Linux routes
    # to loopback without any setup.
    binds = ["127.0.0.1", "127.0.0.2"]
    try:
        socket.create_server(("127.0.0.2", 0)).close()
    except OSError:
        pytest.skip("127.0.0.2 not bindable here")
    settings = Settings(
        panel_bind=("127.0.0.1",),
        panel_port=_free_port(),
        mcp_host=",".join(binds),
        mcp_port=_free_port(),
        state_dir=tmp_path / "state",
        font_dir=tmp_path / "fonts",
    )
    store = Store(settings.state_dir, settings.font_dir)
    specs = main_mod._build_servers(store, settings)
    servers = [srv for srv, _ in specs]

    async def _serve_all() -> None:
        await asyncio.gather(*(srv.serve(sockets=socks) for srv, socks in specs))

    task = asyncio.create_task(_serve_all())
    try:
        for _ in range(200):
            if all(s.started for s in servers):
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("server did not start in time")
        async with httpx.AsyncClient() as client:
            for addr in binds:
                # Any HTTP answer proves the listener is there; the protocol
                # itself is test_mcp.py's job.
                resp = await client.get(f"http://{addr}:{settings.mcp_port}/nope")
                assert resp.status_code == 404, addr
    finally:
        for s in servers:
            s.should_exit = True
        await asyncio.wait_for(task, timeout=5)
