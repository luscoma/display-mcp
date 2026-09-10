from __future__ import annotations

import json
import threading

import pytest

from display_mcp import store as store_mod
from display_mcp.store import (
    MAX_DOC_BYTES,
    DisplayError,
    Store,
    UnknownDisplay,
)


@pytest.fixture(autouse=True)
def fake_render_check(monkeypatch):
    """render.check is a stub (raises NotImplementedError); fake it for these tests."""
    monkeypatch.setattr(store_mod.render, "check", lambda doc, font_dir: [])


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "state", tmp_path / "fonts")


def test_publish_stamps_hash_and_generated_and_minifies(store, sample_doc):
    result = store.publish(sample_doc, "default")
    assert result.hash
    assert result.etag == f'"{result.hash}"'
    assert result.warnings == []

    published = store.get("default")
    assert published.doc["meta"]["hash"] == result.hash
    assert "generated" in published.doc["meta"]
    # minified: byte-identical to json.dumps with the compact separators
    assert published.body == json.dumps(published.doc, separators=(",", ":")).encode()
    assert b"\n" not in published.body


def test_publish_defaults_v(store, sample_doc):
    doc = dict(sample_doc)
    doc.pop("v", None)
    store.publish(doc, "default")
    published = store.get("default")
    assert published.doc["v"] == 1


def test_write_is_atomic_no_stray_files_on_failure(store, sample_doc, monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(store_mod.os, "fsync", boom)

    with pytest.raises(OSError):
        store.publish(sample_doc, "default")

    state_dir = store.state_dir
    leftovers = list(state_dir.glob("*.tmp")) if state_dir.exists() else []
    assert leftovers == []
    # nothing was published either
    assert "default" not in store.names()


def test_reload_from_disk_restores_doc_and_fetch(tmp_path, sample_doc):
    state_dir = tmp_path / "state"
    s1 = Store(state_dir, tmp_path / "fonts")
    import display_mcp.render as render_mod

    orig_check = render_mod.check
    s1_result = None
    try:
        render_mod.check = lambda doc, font_dir: []
        s1_result = s1.publish(sample_doc, "default")
        s1.note_fetch("default", 200, "10.0.0.5")
    finally:
        render_mod.check = orig_check

    s2 = Store(state_dir, tmp_path / "fonts")
    published = s2.get("default")
    assert published.hash == s1_result.hash
    assert published.doc["meta"]["hash"] == s1_result.hash
    assert published.fetch.recent_fetch_ip == "10.0.0.5"
    assert published.fetch.recent_fetch_status == 200
    assert published.fetch.first_fetch_at is not None


def test_reload_skips_corrupt_files_without_being_fatal(tmp_path, sample_doc, caplog):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "default.json").write_text("{not json")
    (state_dir / "other.json").write_text(json.dumps(sample_doc))
    (state_dir / "other.meta.json").write_text("also not json")

    s = Store(state_dir, tmp_path / "fonts")
    assert "default" not in s.names()
    # "other" doc loaded fine even though its meta was corrupt
    assert "other" in s.names()
    published = s.get("other")
    assert published.doc == sample_doc


def test_hard_errors_raise_display_error(store):
    with pytest.raises(DisplayError):
        store.publish([1, 2, 3], "default")  # not a dict

    with pytest.raises(DisplayError):
        store.publish({"bg": "white"}, "default")  # no ops

    with pytest.raises(DisplayError):
        store.publish({"ops": "not-a-list"}, "default")  # ops not a list


def test_max_doc_bytes_enforced(store):
    huge_doc = {"ops": [{"type": "text", "text": "x" * (MAX_DOC_BYTES + 1000)}]}
    with pytest.raises(DisplayError):
        store.publish(huge_doc, "default")


def test_bad_names_rejected(store, sample_doc):
    with pytest.raises(DisplayError):
        store.publish(sample_doc, "Bad Name!")
    with pytest.raises(DisplayError):
        store.get("Bad Name!")
    with pytest.raises(DisplayError):
        store.clear("nope nope")
    with pytest.raises(DisplayError):
        store.note_fetch("nope nope", 200, "1.2.3.4")


def test_warnings_pass_through_never_raise(store, sample_doc, monkeypatch):
    monkeypatch.setattr(store_mod.render, "check", lambda doc, font_dir: ["unknown icon: foo"])
    result = store.publish(sample_doc, "default")
    assert result.warnings == ["unknown icon: foo"]


def test_check_exception_becomes_single_warning(store, sample_doc, monkeypatch):
    def boom(doc, font_dir):
        raise RuntimeError("fonts missing")

    monkeypatch.setattr(store_mod.render, "check", boom)
    result = store.publish(sample_doc, "default")
    assert len(result.warnings) == 1
    assert "validation unavailable" in result.warnings[0]
    assert "fonts missing" in result.warnings[0]


def test_publish_resets_first_fetch_at(store, sample_doc):
    store.publish(sample_doc, "default")
    store.note_fetch("default", 200, "1.2.3.4")
    assert store.get("default").fetch.first_fetch_at is not None

    store.publish(sample_doc, "default")
    assert store.get("default").fetch.first_fetch_at is None


def test_note_fetch_200_sets_first_fetch_once(store, sample_doc):
    store.publish(sample_doc, "default")
    store.note_fetch("default", 200, "1.2.3.4")
    first = store.get("default").fetch.first_fetch_at
    assert first is not None

    store.note_fetch("default", 200, "1.2.3.4")
    assert store.get("default").fetch.first_fetch_at == first  # unchanged

    store.note_fetch("default", 200, "9.9.9.9")
    fetch = store.get("default").fetch
    assert fetch.first_fetch_at == first
    assert fetch.recent_fetch_ip == "9.9.9.9"


def test_note_fetch_updates_recent_every_time(store, sample_doc):
    store.publish(sample_doc, "default")
    store.note_fetch("default", 304, "1.1.1.1")
    fetch = store.get("default").fetch
    assert fetch.recent_fetch_status == 304
    assert fetch.recent_fetch_ip == "1.1.1.1"
    assert fetch.recent_fetch_at is not None
    assert fetch.first_fetch_at is None  # 304 never sets it


def test_note_fetch_for_unknown_display_is_recorded_but_not_in_names(store):
    store.note_fetch("ghost", 503, "2.2.2.2")
    assert "ghost" not in store.names()
    meta_path = store.state_dir / "ghost.meta.json"
    assert meta_path.exists()
    data = json.loads(meta_path.read_text())
    assert data["recent_fetch_status"] == 503
    assert data["recent_fetch_ip"] == "2.2.2.2"

    with pytest.raises(UnknownDisplay):
        store.get("ghost")


def test_clear_removes_both_files(store, sample_doc):
    store.publish(sample_doc, "default")
    doc_path = store.state_dir / "default.json"
    meta_path = store.state_dir / "default.meta.json"
    assert doc_path.exists()
    assert meta_path.exists()

    assert store.clear("default") is True
    assert not doc_path.exists()
    assert not meta_path.exists()
    assert "default" not in store.names()

    with pytest.raises(UnknownDisplay):
        store.get("default")

    assert store.clear("default") is False


def test_names_sorted(store, sample_doc):
    store.publish(sample_doc, "zeta")
    store.publish(sample_doc, "alpha")
    store.publish(sample_doc, "mid")
    assert store.names() == ["alpha", "mid", "zeta"]


def test_thread_safety_smoke(tmp_path, sample_doc):
    state_dir = tmp_path / "state"
    s = Store(state_dir, tmp_path / "fonts")

    import display_mcp.render as render_mod

    orig_check = render_mod.check
    render_mod.check = lambda doc, font_dir: []
    try:
        errors: list[BaseException] = []

        def worker(i: int) -> None:
            try:
                for _ in range(10):
                    s.publish(sample_doc, "default")
                    s.note_fetch("default", 200, f"10.0.0.{i}")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        published = s.get("default")
        assert published.doc["meta"]["hash"] == published.hash
        assert published.fetch.recent_fetch_status == 200
    finally:
        render_mod.check = orig_check


def test_fetch_record_for_unpublished_name(tmp_path, monkeypatch):
    from display_mcp import store as store_mod

    monkeypatch.setattr(store_mod.render, "check", lambda doc, font_dir: [])
    s = store_mod.Store(tmp_path, tmp_path)
    assert s.fetch_record("ghost") is None
    s.note_fetch("ghost", 503, "10.0.0.9")
    rec = s.fetch_record("ghost")
    assert rec is not None
    assert rec.recent_fetch_status == 503
    assert rec.recent_fetch_ip == "10.0.0.9"
    assert rec.first_fetch_at is None
    assert "ghost" not in s.names()
