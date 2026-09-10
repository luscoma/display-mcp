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


@pytest.mark.asyncio
async def test_serves_panel_and_shuts_down_cleanly(tmp_path):
    settings = Settings(
        panel_bind=("127.0.0.1",),
        panel_port=_free_port(),
        mcp_host="127.0.0.1",
        mcp_port=_free_port(),
        state_dir=tmp_path / "state",
        font_dir=tmp_path / "fonts",
    )
    store = Store(settings.state_dir, settings.font_dir)

    specs = main_mod._build_servers(store, settings)
    # One server per listener: panel and MCP.
    assert len(specs) == 2
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
            resp = await client.get(f"http://127.0.0.1:{settings.panel_port}/healthz")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
    finally:
        for s in servers:
            s.should_exit = True
        await asyncio.wait_for(task, timeout=5)


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
