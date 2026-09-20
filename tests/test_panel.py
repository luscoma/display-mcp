from __future__ import annotations

import json
from datetime import UTC, datetime

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


def test_200_with_etag_after_publish(client, store, sample_doc):
    result = store.publish(sample_doc, "default")
    resp = client.get("/d/default.json")
    assert resp.status_code == 200
    assert resp.headers["ETag"] == result.etag
    assert resp.headers["Content-Type"] == "application/json"
    assert resp.headers["Cache-Control"] == "no-cache"
    assert resp.headers["Content-Length"] == str(len(resp.content))
    assert json.loads(resp.content) == store.get("default").doc


@pytest.mark.parametrize(
    "form",
    [
        pytest.param(lambda r: r.etag, id="quoted"),
        pytest.param(lambda r: r.hash, id="unquoted"),
        pytest.param(lambda r: f"W/{r.etag}", id="weak"),
    ],
)
def test_304_on_matching_if_none_match(client, store, sample_doc, form):
    """The three `If-None-Match` spellings `_etag_matches` accepts: the exact
    quoted ETag, the bare hash, and a weak (`W/`) prefix. All three are the
    same branch, which runs before the method check -- so a HEAD with a
    matching If-None-Match is this same 304, not a path of its own (HEAD's
    own behaviour is test_head_returns_headers_and_no_body's)."""
    result = store.publish(sample_doc, "default")
    resp = client.get("/d/default.json", headers={"If-None-Match": form(result)})
    assert resp.status_code == 304
    assert resp.headers["ETag"] == result.etag
    assert resp.headers["Content-Length"] == "0"
    assert resp.content == b""


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


# ---- the panel's X-Panel-* self-report ---------------------------------

PANEL_HEADERS = {
    "X-Panel-Battery": "82",
    "X-Panel-Volts": "4.04",
    "X-Panel-Last-Draw": "2026-09-19T14:03:11Z",
    "X-Panel-Wakes": "412",
}


def test_panel_headers_are_recorded_on_a_200(client, store, sample_doc):
    store.publish(sample_doc)
    client.get("/display.json", headers=PANEL_HEADERS)
    rec = store.fetch_record("default")
    assert rec.panel_battery == 82
    assert rec.panel_volts == pytest.approx(4.04)
    assert rec.panel_wakes == 412
    # "Z" means UTC, not the server's local zone.
    assert rec.panel_draw_at == pytest.approx(
        datetime(2026, 9, 19, 14, 3, 11, tzinfo=UTC).timestamp()
    )


def test_panel_headers_are_recorded_on_a_304(client, store, sample_doc):
    """The whole point: the cheap wake is the one that usually happens."""
    result = store.publish(sample_doc)
    headers = {**PANEL_HEADERS, "If-None-Match": result.etag}
    resp = client.get("/display.json", headers=headers)
    assert resp.status_code == 304
    assert store.fetch_record("default").panel_battery == 82


def test_panel_headers_are_recorded_for_an_unpublished_name(client, store):
    resp = client.get("/d/ghost.json", headers=PANEL_HEADERS)
    assert resp.status_code == 503
    assert store.fetch_record("ghost").panel_wakes == 412


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Panel-Battery": "not-a-number"},
        {"X-Panel-Battery": "999"},  # outside 0..100
        {"X-Panel-Battery": "-1"},
        {"X-Panel-Volts": ""},
        {"X-Panel-Volts": "1e309"},  # inf, outside the sanity bound
        {"X-Panel-Last-Draw": "yesterday"},
        {"X-Panel-Last-Draw": ""},
        {"X-Panel-Wakes": "12.5"},
        {"X-Panel-Wakes": "-3"},
    ],
)
def test_a_garbled_panel_header_never_breaks_the_fetch(client, store, sample_doc, headers):
    """This listener is unauthenticated: a bad header is hearsay, not a 500.

    Each case sends one bad header and no good ones, so this also covers a
    fetch carrying no usable panel self-report at all: it is still served a
    200, and every `panel_*` field stays null rather than being written some
    partial or coerced value (`_panel_report` reads a missing header and an
    empty one the same way).
    """
    store.publish(sample_doc)
    resp = client.get("/display.json", headers=headers)
    assert resp.status_code == 200
    rec = store.fetch_record("default")
    assert (rec.panel_battery, rec.panel_volts, rec.panel_draw_at, rec.panel_wakes) == (
        None,
        None,
        None,
        None,
    )


def test_a_missing_header_does_not_erase_the_last_good_value(client, store, sample_doc):
    """A wake whose ADC read NaN sends an empty header; the old reading stands."""
    store.publish(sample_doc)
    client.get("/display.json", headers=PANEL_HEADERS)
    client.get("/display.json", headers={"X-Panel-Wakes": "413"})
    rec = store.fetch_record("default")
    assert rec.panel_wakes == 413
    assert rec.panel_battery == 82


@pytest.mark.parametrize(
    "stamp",
    [
        "0001-01-01",  # -6.2e10; datetime.fromtimestamp cannot represent it
        "0001-01-01T00:00:00+23:59",
        "9999-12-31T23:59:59.999999-23:59",  # past year 9999 once shifted
        "1970-01-01T00:00:00Z",  # before the panel could plausibly have drawn
        "2200-01-01T00:00:00Z",
    ],
)
def test_an_out_of_range_draw_stamp_is_dropped(client, store, sample_doc, stamp):
    """One unauthenticated GET must not be able to poison the record.

    `status` formats this through `datetime.fromtimestamp`, which raises
    outside year 1..9999 -- and the value is persisted, so a single bad
    header would have broken the tool for every display until someone
    hand-edited the meta file.
    """
    store.publish(sample_doc)
    resp = client.get("/display.json", headers={"X-Panel-Last-Draw": stamp})
    assert resp.status_code == 200
    assert store.fetch_record("default").panel_draw_at is None


def test_healthz_reports_the_panel_report(client, store, sample_doc):
    store.publish(sample_doc)
    client.get("/display.json", headers=PANEL_HEADERS)
    entry = client.get("/healthz").json()["displays"][0]
    assert entry["panel_battery"] == 82
    assert entry["panel_volts"] == pytest.approx(4.04)
    assert entry["panel_wakes"] == 412
    assert entry["panel_draw_at"] is not None


def test_panel_report_survives_a_restart(store, settings, sample_doc, tmp_path):
    """The fields ride the meta file, like the rest of the fetch record."""
    store.publish(sample_doc)
    TestClient(build_panel_app(store, settings)).get("/display.json", headers=PANEL_HEADERS)
    reopened = Store(tmp_path / "state", tmp_path / "fonts")
    assert reopened.fetch_record("default").panel_battery == 82
