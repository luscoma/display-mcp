"""Tests for display_mcp.cli (display-mcp-cli check|stamp|render)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from display_mcp import cli
from display_mcp.render import render_hash

SAMPLE_HASH = "3cd62aa76e731d2d"
SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "display.json"


def _run(argv, capsys):
    args = cli.build_parser().parse_args(argv)
    exit_code = args.func(args)
    out = capsys.readouterr()
    return exit_code, out.out, out.err


def test_check_sample_exits_0_and_prints_hash(font_dir, capsys):
    code, out, err = _run(["check", str(SAMPLE), "--font-dir", str(font_dir)], capsys)
    assert code == 0
    assert SAMPLE_HASH in out
    assert "ops," in out
    assert "bytes minified" in out


def test_check_reports_problems_and_exits_1(font_dir, tmp_path, capsys):
    doc = {"bg": "white", "ops": [{"op": "sparkle", "x": 0, "y": 0}]}
    f = tmp_path / "bad.json"
    f.write_text(json.dumps(doc))
    code, out, err = _run(["check", str(f), "--font-dir", str(font_dir)], capsys)
    assert code == 1
    assert "  ! " in out
    assert "unknown op" in out


def test_check_missing_fonts_exits_2(tmp_path, capsys, sample_doc):
    f = tmp_path / "doc.json"
    f.write_text(json.dumps(sample_doc))
    empty_font_dir = tmp_path / "no-fonts-here"
    empty_font_dir.mkdir()
    code, out, err = _run(["check", str(f), "--font-dir", str(empty_font_dir)], capsys)
    assert code == 2
    assert err  # a clear message on stderr


def test_stamp_writes_hash_back(sample_doc, tmp_path, capsys):
    doc = copy.deepcopy(sample_doc)
    del doc["meta"]["hash"]
    f = tmp_path / "unstamped.json"
    f.write_text(json.dumps(doc, indent=2) + "\n")

    code, out, err = _run(["stamp", str(f)], capsys)
    assert code == 0
    assert SAMPLE_HASH in out

    written = json.loads(f.read_text())
    assert written["meta"]["hash"] == SAMPLE_HASH
    assert f.read_text().endswith("\n")


def test_stamp_matches_render_hash_for_any_doc(tmp_path, capsys):
    doc = {"bg": "white", "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "red"}]}
    f = tmp_path / "doc.json"
    f.write_text(json.dumps(doc))
    _run(["stamp", str(f)], capsys)
    written = json.loads(f.read_text())
    assert written["meta"]["hash"] == render_hash(doc)


def test_stamp_never_adds_generated(tmp_path, capsys):
    """`stamp` writes meta.hash only. Unlike Store.publish(), it never stamps
    meta.generated -- see docs/SPEC.md and docs/PLAN.md's "one code path"
    rule. A file with no `generated` stays without one after stamping.
    """
    doc = {"bg": "white", "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "red"}]}
    f = tmp_path / "doc.json"
    f.write_text(json.dumps(doc))
    _run(["stamp", str(f)], capsys)
    written = json.loads(f.read_text())
    assert "generated" not in written["meta"]


def test_stamp_leaves_existing_generated_untouched(tmp_path, capsys):
    """A `generated` already on disk is the author's and stamp must not
    touch it -- only Store.publish() ever writes that field.
    """
    doc = {
        "bg": "white",
        "meta": {"generated": "hand-authored, not a publish timestamp"},
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "red"}],
    }
    f = tmp_path / "doc.json"
    f.write_text(json.dumps(doc))
    _run(["stamp", str(f)], capsys)
    written = json.loads(f.read_text())
    assert written["meta"]["generated"] == "hand-authored, not a publish timestamp"


def test_stamp_run_twice_is_a_true_no_op(tmp_path, capsys):
    """Because meta.hash excludes meta.generated and stamp never touches
    generated, restamping unchanged content changes nothing on disk at all
    -- unlike Store.publish(), which always moves meta.generated even for
    byte-identical input. Both are fine; this pins the difference.
    """
    doc = {"bg": "white", "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "red"}]}
    f = tmp_path / "doc.json"
    f.write_text(json.dumps(doc))
    _run(["stamp", str(f)], capsys)
    first = f.read_text()
    _run(["stamp", str(f)], capsys)
    second = f.read_text()
    assert first == second


def test_stamp_and_publish_agree_on_hash_despite_generated_asymmetry(
    tmp_path, capsys, monkeypatch
):
    """The two stamping paths disagree about meta.generated on purpose (see
    docs/SPEC.md), but they must never disagree about meta.hash -- that's
    the one identity the panel's change detection relies on.
    """
    from display_mcp import store as store_mod
    from display_mcp.store import Store

    doc = {"bg": "white", "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "red"}]}

    f = tmp_path / "doc.json"
    f.write_text(json.dumps(doc))
    _run(["stamp", str(f)], capsys)
    stamped = json.loads(f.read_text())

    monkeypatch.setattr(store_mod.render, "check", lambda doc, font_dir: [])
    store = Store(tmp_path / "state", tmp_path / "fonts")
    result = store.publish(dict(doc), "default")

    assert stamped["meta"]["hash"] == result.hash


def test_render_writes_png(font_dir, tmp_path, capsys, sample_doc):
    f = tmp_path / "doc.json"
    f.write_text(json.dumps(sample_doc))
    out_png = tmp_path / "out.png"
    code, out, err = _run(
        ["render", str(f), "-o", str(out_png), "--font-dir", str(font_dir)], capsys
    )
    assert code == 0
    assert out_png.exists()
    assert "wrote" in out
    from PIL import Image

    img = Image.open(out_png)
    assert img.size == (1200, 1600)


def test_render_ideal_flag(font_dir, tmp_path, capsys, sample_doc):
    f = tmp_path / "doc.json"
    f.write_text(json.dumps(sample_doc))
    out_png = tmp_path / "out.png"
    code, out, err = _run(
        ["render", str(f), "-o", str(out_png), "--ideal", "--font-dir", str(font_dir)], capsys
    )
    assert code == 0
    assert out_png.exists()


def test_render_missing_fonts_exits_2(tmp_path, capsys, sample_doc):
    f = tmp_path / "doc.json"
    f.write_text(json.dumps(sample_doc))
    empty_font_dir = tmp_path / "no-fonts-here"
    empty_font_dir.mkdir()
    code, out, err = _run(
        ["render", str(f), "--font-dir", str(empty_font_dir)], capsys
    )
    assert code == 2
    assert err


def test_render_reports_stale_hash(font_dir, tmp_path, capsys, sample_doc):
    doc = copy.deepcopy(sample_doc)
    doc["meta"]["hash"] = "0000000000000000"
    f = tmp_path / "stale.json"
    f.write_text(json.dumps(doc))
    out_png = tmp_path / "out.png"
    code, out, err = _run(
        ["render", str(f), "-o", str(out_png), "--font-dir", str(font_dir)], capsys
    )
    assert code == 1
    assert "meta.hash is stale" in out


def test_publish_through_in_process_server(monkeypatch, capsys, sample_doc, tmp_path):
    import json

    from mcp import Client

    from display_mcp import cli, mcp_server, render
    from display_mcp.config import Settings
    from fakes import FakeStore, fake_check, fake_render

    monkeypatch.setattr(render, "check", fake_check)
    monkeypatch.setattr(render, "render", fake_render)
    store = FakeStore()
    mcp = mcp_server.build_mcp(store, Settings(state_dir=tmp_path, font_dir=tmp_path))
    monkeypatch.setattr(cli, "_client", lambda url: Client(mcp))

    f = tmp_path / "doc.json"
    f.write_text(json.dumps(sample_doc))
    monkeypatch.setattr("sys.argv", ["display-mcp-cli", "publish", str(f)])
    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "published default: hash" in out
    assert store.get("default").hash in out

    # A bad name is a tool error, reported and exit 1.
    monkeypatch.setattr("sys.argv", ["display-mcp-cli", "publish", str(f), "--name", "Bad Name"])
    assert cli.main() == 1
