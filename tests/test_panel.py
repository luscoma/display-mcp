from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from display_mcp import store as store_mod
from display_mcp.config import Settings
from display_mcp.panel import build_panel_app
from display_mcp.store import Store


@pytest.fixture(autouse=True)
def fake_render(monkeypatch):
    monkeypatch.setattr(store_mod.render, "check", lambda doc, font_dir: [])


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "state", tmp_path / "fonts")


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(state_dir=tmp_path / "state", font_dir=tmp_path / "fonts")


@pytest.fixture
def client(store, settings) -> TestClient:
    app = build_panel_app(store, settings)
    return TestClient(app)


def test_503_before_publish(client):
    resp = client.get("/d/default.json")
    assert resp.status_code == 503
    assert resp.text == "no display list yet"


def test_503_is_recorded(client, store):
    client.get("/d/default.json")
    # unknown display still tracked via a meta record
    import json as _json

    meta_path = store.state_dir / "default.meta.json"
    assert meta_path.exists()
    data = _json.loads(meta_path.read_text())
    assert data["recent_fetch_status"] == 503


def test_200_with_etag_after_publish(client, store, sample_doc):
    result = store.publish(sample_doc, "default")
    resp = client.get("/d/default.json")
    assert resp.status_code == 200
    assert resp.headers["ETag"] == result.etag
    assert resp.headers["Content-Type"] == "application/json"
    assert resp.headers["Cache-Control"] == "no-cache"
    assert resp.headers["Content-Length"] == str(len(resp.content))
    assert json.loads(resp.content) == store.get("default").doc


def test_304_on_matching_if_none_match_quoted(client, store, sample_doc):
    result = store.publish(sample_doc, "default")
    resp = client.get("/d/default.json", headers={"If-None-Match": result.etag})
    assert resp.status_code == 304
    assert resp.headers["ETag"] == result.etag
    assert resp.headers["Content-Length"] == "0"
    assert resp.content == b""


def test_304_on_matching_if_none_match_unquoted(client, store, sample_doc):
    result = store.publish(sample_doc, "default")
    unquoted = result.hash
    resp = client.get("/d/default.json", headers={"If-None-Match": unquoted})
    assert resp.status_code == 304


def test_304_on_matching_if_none_match_weak(client, store, sample_doc):
    result = store.publish(sample_doc, "default")
    weak = f'W/{result.etag}'
    resp = client.get("/d/default.json", headers={"If-None-Match": weak})
    assert resp.status_code == 304


def test_200_on_mismatched_if_none_match(client, store, sample_doc):
    store.publish(sample_doc, "default")
    resp = client.get("/d/default.json", headers={"If-None-Match": '"deadbeefdeadbeef"'})
    assert resp.status_code == 200


def test_head_returns_headers_and_no_body(client, store, sample_doc):
    result = store.publish(sample_doc, "default")
    resp = client.head("/d/default.json")
    assert resp.status_code == 200
    assert resp.headers["ETag"] == result.etag
    assert resp.headers["Content-Length"] == str(result.bytes)
    assert resp.content == b""


def test_head_304(client, store, sample_doc):
    result = store.publish(sample_doc, "default")
    resp = client.head("/d/default.json", headers={"If-None-Match": result.etag})
    assert resp.status_code == 304
    assert resp.content == b""


def test_display_json_and_d_default_agree(client, store, sample_doc):
    store.publish(sample_doc, "default")
    a = client.get("/display.json")
    b = client.get("/d/default.json")
    assert a.status_code == b.status_code == 200
    assert a.headers["ETag"] == b.headers["ETag"]
    assert a.content == b.content


def test_bad_name_404_json_and_not_recorded(client, store):
    resp = client.get("/d/Not_Valid!.json")
    assert resp.status_code == 404
    assert "error" in resp.json()
    assert not (store.state_dir / "Not_Valid!.meta.json").exists()


def test_unknown_name_503_and_recorded(client, store):
    resp = client.get("/d/nonexistent.json")
    assert resp.status_code == 503
    assert resp.text == "no display list yet"
    assert "nonexistent" not in store.names()
    published_meta = store.state_dir / "nonexistent.meta.json"
    assert published_meta.exists()


def test_unmatched_path_404(client):
    resp = client.get("/nope")
    assert resp.status_code == 404


def test_healthz_shape_before_publish(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert isinstance(data["fonts_loaded"], bool)
    assert isinstance(data["state_dir_writable"], bool)
    assert data["displays"] == []


def test_healthz_shape_after_publish(client, store, sample_doc):
    store.publish(sample_doc, "default")
    client.get("/d/default.json")
    resp = client.get("/healthz")
    data = resp.json()
    assert len(data["displays"]) == 1
    entry = data["displays"][0]
    assert entry["name"] == "default"
    assert entry["hash"]
    assert entry["published_at"] is not None
    assert entry["first_fetch_at"] is not None
    assert entry["recent_fetch_at"] is not None
    assert entry["recent_fetch_status"] == 200


def test_store_fetch_record_reflects_each_request(client, store, sample_doc):
    store.publish(sample_doc, "default")

    client.get("/d/default.json")
    assert store.get("default").fetch.recent_fetch_status == 200

    result = store.get("default")
    client.get("/d/default.json", headers={"If-None-Match": result.etag})
    assert store.get("default").fetch.recent_fetch_status == 304

    client.get("/d/ghost.json")
    # ghost has no doc, but note_fetch still recorded status via the store
    ghost_meta = store.state_dir / "ghost.meta.json"
    assert ghost_meta.exists()


def test_head_does_not_count_as_a_fetch(client, store, sample_doc):
    store.publish(sample_doc)
    r = client.head("/display.json")
    assert r.status_code == 200
    rec = store.fetch_record("default")
    assert rec.first_fetch_at is None
    assert rec.recent_fetch_status is None
    client.get("/display.json")
    rec = store.fetch_record("default")
    assert rec.first_fetch_at is not None
    assert rec.recent_fetch_status == 200
