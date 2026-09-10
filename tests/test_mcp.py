"""mcp_server.py: tools, resources and the compose prompt, against FakeStore
and a fake renderer (both display_mcp.store.Store and display_mcp.render
are stubs on this branch)."""

from __future__ import annotations

import json

import pytest
from mcp import Client
from starlette.testclient import TestClient

from display_mcp import mcp_server, render
from display_mcp.config import Settings
from fakes import FakeStore, fake_check, fake_render


@pytest.fixture(autouse=True)
def _fake_renderer(monkeypatch):
    monkeypatch.setattr(render, "render", fake_render)
    monkeypatch.setattr(render, "check", fake_check)


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(state_dir=tmp_path / "state", font_dir=tmp_path / "fonts")


@pytest.fixture
def auth_settings(tmp_path) -> Settings:
    return Settings(
        state_dir=tmp_path / "state",
        font_dir=tmp_path / "fonts",
        cf_access_team_domain="https://example.cloudflareaccess.com",
        cf_access_aud="test-aud",
    )


@pytest.fixture
def mcp(store, settings):
    return mcp_server.build_mcp(store, settings)


def _text_of(result) -> str | None:
    for block in result.content:
        if block.type == "text":
            return block.text
    return None


# ---- tools ----------------------------------------------------------------


async def test_list_tools_and_annotations(mcp):
    async with Client(mcp) as c:
        tools = (await c.list_tools()).tools
    by_name = {t.name: t for t in tools}
    assert set(by_name) == {
        "set_display",
        "preview",
        "validate",
        "get_display",
        "status",
        "clear_display",
    }
    for name in ("preview", "validate", "get_display", "status"):
        assert by_name[name].annotations.read_only_hint is True
    assert by_name["set_display"].annotations.read_only_hint is False
    assert by_name["clear_display"].annotations.read_only_hint is False
    assert by_name["clear_display"].annotations.destructive_hint is True


async def test_set_display_shape_and_stamped_hash(mcp, store, sample_doc):
    async with Client(mcp) as c:
        result = await c.call_tool("set_display", {"document": sample_doc})
    assert result.is_error is not True
    data = result.structured_content
    assert set(data) == {"name", "hash", "etag", "ops", "bytes", "warnings"}
    assert data["name"] == "default"
    assert data["etag"] == f'"{data["hash"]}"'
    assert data["ops"] == len(sample_doc["ops"])
    assert data["warnings"] == []

    published = store.get("default")
    assert published.hash == data["hash"]
    assert published.hash == render.render_hash(published.doc)


async def test_set_display_named(mcp, store, sample_doc):
    async with Client(mcp) as c:
        result = await c.call_tool("set_display", {"document": sample_doc, "name": "kitchen"})
    assert result.structured_content["name"] == "kitchen"
    assert store.names() == ["kitchen"]


async def test_preview_published_returns_image_and_no_new_publish(mcp, store, sample_doc):
    store.publish(sample_doc)
    async with Client(mcp) as c:
        result = await c.call_tool("preview", {})
    assert result.is_error is not True
    assert any(block.type == "image" for block in result.content)


async def test_preview_draft_does_not_publish(mcp, store, sample_doc):
    async with Client(mcp) as c:
        result = await c.call_tool("preview", {"document": sample_doc})
    assert result.is_error is not True
    assert any(block.type == "image" for block in result.content)
    assert store.names() == []  # a draft preview publishes nothing


async def test_preview_no_document_and_nothing_published_is_error(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("preview", {})
    assert result.is_error is True


async def test_validate_returns_shape(mcp, sample_doc):
    async with Client(mcp) as c:
        result = await c.call_tool("validate", {"document": sample_doc})
    assert result.is_error is not True
    data = result.structured_content
    assert set(data) == {"hash", "ops", "bytes", "warnings"}
    assert data["hash"] == render.render_hash(sample_doc)
    assert data["ops"] == len(sample_doc["ops"])
    assert data["warnings"] == []
    assert data["bytes"] > 0


async def test_validate_stores_nothing(mcp, store, sample_doc):
    async with Client(mcp) as c:
        await c.call_tool("validate", {"document": sample_doc})
    assert store.names() == []


async def test_get_display_roundtrips(mcp, store, sample_doc):
    store.publish(sample_doc)
    async with Client(mcp) as c:
        result = await c.call_tool("get_display", {})
    assert result.is_error is not True
    assert result.structured_content["meta"]["hash"] == store.get("default").hash


async def test_status_single_display(mcp, store, sample_doc):
    store.publish(sample_doc)
    store.note_fetch("default", 200, "10.0.0.5")
    async with Client(mcp) as c:
        result = await c.call_tool("status", {"name": "default"})
    data = result.structured_content
    assert data["published"] is True
    assert data["name"] == "default"
    assert data["recent_fetch_status"] == 200
    assert data["recent_fetch_ip"] == "10.0.0.5"
    assert data["published_ago"].endswith("ago")
    assert data["first_fetch_ago"].endswith("ago")
    assert data["recent_fetch_ago"].endswith("ago")
    assert data["published_at"] is not None and "T" in data["published_at"]


async def test_status_all_displays(mcp, store, sample_doc, auth_settings):
    store.publish(sample_doc)
    async with Client(mcp) as c:
        result = await c.call_tool("status", {})
    data = result.structured_content
    assert "default" in data["displays"]
    assert data["displays"]["default"]["published"] is True
    assert data["auth"] == "none"

    # auth reflected in a server built with Cloudflare Access configured
    auth_mcp = mcp_server.build_mcp(store, auth_settings)
    async with Client(auth_mcp) as c:
        result2 = await c.call_tool("status", {})
    assert result2.structured_content["auth"] == "cloudflare-access"


async def test_status_unpublished_name_is_not_an_error(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("status", {"name": "nope"})
    assert result.is_error is not True
    data = result.structured_content
    assert data == {
        "published": False,
        "name": "nope",
        "hash": None,
        "ops": None,
        "bytes": None,
        "published_at": None,
        "published_ago": None,
        "first_fetch_at": None,
        "first_fetch_ago": None,
        "recent_fetch_at": None,
        "recent_fetch_ago": None,
        "recent_fetch_status": None,
        "recent_fetch_ip": None,
    }


async def test_clear_display(mcp, store, sample_doc):
    store.publish(sample_doc)
    async with Client(mcp) as c:
        result = await c.call_tool("clear_display", {})
    assert result.is_error is not True
    assert result.structured_content == {"name": "default", "cleared": True}
    assert store.names() == []


async def test_clear_display_already_absent(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("clear_display", {"name": "ghost"})
    assert result.structured_content == {"name": "ghost", "cleared": False}


# ---- errors -----------------------------------------------------------


async def test_bad_name_is_tool_error(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("get_display", {"name": "Not A Valid Name!"})
    assert result.is_error is True
    assert "bad display name" in (_text_of(result) or "")


async def test_unknown_display_get_is_tool_error(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("get_display", {"name": "nope"})
    assert result.is_error is True


# ---- resources --------------------------------------------------------


async def test_spec_resource(mcp):
    async with Client(mcp) as c:
        result = await c.read_resource("display://spec")
    text = result.contents[0].text
    assert "hash" in text.lower()
    assert result.contents[0].mime_type == "text/markdown"


async def test_sample_resource(mcp):
    async with Client(mcp) as c:
        result = await c.read_resource("display://sample")
    doc = json.loads(result.contents[0].text)
    assert doc["meta"]["hash"] == "21a77f4c46f1534d"


async def test_current_resource(mcp, store, sample_doc):
    store.publish(sample_doc)
    async with Client(mcp) as c:
        result = await c.read_resource("display://current/default")
    doc = json.loads(result.contents[0].text)
    assert doc["meta"]["hash"] == store.get("default").hash


# ---- prompt -------------------------------------------------------------


async def test_compose_prompt_listed(mcp):
    async with Client(mcp) as c:
        prompts = (await c.list_prompts()).prompts
    assert "compose_display" in {p.name for p in prompts}


async def test_compose_prompt_renders_without_args(mcp):
    async with Client(mcp) as c:
        result = await c.get_prompt("compose_display")
    text = result.messages[0].content.text
    assert "1200" in text and "1600" in text


async def test_compose_prompt_renders_with_args(mcp):
    async with Client(mcp) as c:
        result = await c.get_prompt(
            "compose_display", {"name": "kitchen", "context": "tomorrow's weather"}
        )
    text = result.messages[0].content.text
    assert "kitchen" in text
    assert "tomorrow's weather" in text


# ---- ASGI app / auth wiring --------------------------------------------


def test_build_mcp_app_returns_asgi_app(store, settings):
    app = mcp_server.build_mcp_app(store, settings)
    assert callable(app)


def test_build_mcp_app_401_without_token_when_auth_enabled(store, auth_settings):
    app = mcp_server.build_mcp_app(store, auth_settings)
    client = TestClient(app)
    resp = client.post(
        auth_settings.mcp_path,
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert resp.status_code == 401


def test_build_mcp_app_passes_through_without_auth(store, settings):
    app = mcp_server.build_mcp_app(store, settings)
    with TestClient(app) as client:  # enters the ASGI lifespan the session manager needs
        resp = client.post(
            settings.mcp_path,
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert resp.status_code != 401


async def test_status_unpublished_name_reports_panel_requests(mcp, store):
    store.note_fetch("ghost", 503, "172.17.0.5")
    async with Client(mcp) as c:
        result = await c.call_tool("status", {"name": "ghost"})
    assert result.is_error is not True
    data = result.structured_content
    assert data["published"] is False
    assert data["recent_fetch_status"] == 503
    assert data["recent_fetch_ip"] == "172.17.0.5"
    assert data["recent_fetch_ago"] is not None
