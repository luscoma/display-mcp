"""display-mcp-cli: the dlpreview.py command line, kept for the runbook gates.

    display-mcp-cli check  <file> [--font-dir DIR]
        validate, print "<n> ops, <bytes> bytes minified, render hash <h>"
        and each problem prefixed "  ! "; exit 1 if there were problems.

    display-mcp-cli stamp  <file> [--font-dir DIR]
        write meta.hash back into the file (indent=2, trailing newline),
        print it.

    display-mcp-cli render <file> [-o out.png] [--font-dir DIR]
        render to a PNG the way the panel draws it, mixes dithered, and
        also print what `check` prints.

    display-mcp-cli publish <file> [--name NAME] [--url URL]
        publish through the MCP endpoint (default http://127.0.0.1:8001/mcp,
        or DISPLAY_MCP_URL). The server validates and stamps; this prints the
        hash and any warnings. On the host itself no Access token is needed:
        the loopback endpoint treats an unproxied local peer as the operator.

    display-mcp-cli swatches [-o out.png] [--json out.json] [--dithered]
                              [--font-dir DIR]
        render every ink and built-in mix as a labelled chip and optionally
        write the document itself as JSON — the same one `swatches` (the
        MCP tool) and `render.swatch_document()` build. Flat by default
        (unlike every other CLI render): this is the one document whose
        whole purpose is judging colour, and a scaled, dithered PNG aliases
        every 50% mix to a single ink on screen. Pass `--dithered` for the
        panel-faithful render instead.

    display-mcp-cli font-metrics <font_dir>
        measure cell_height (every compiled face) and ink_height (mono
        sizes) from the real font files in <font_dir> and write
        render/font_metrics.json (docs/plans/fonts-and-icons.md Decision 3)
        -- run this after adding a family, a style or a size to
        fonts.py's FAMILIES/SIZES.

    display-mcp-cli firmware-vocabulary [yaml_path]  (alias: firmware-fonts)
        regenerate firmware/epaper-schedule.yaml's `font:`/`image:` blocks
        and the `a.fonts[...]`/`a.icons[...]` lines from fonts.py's
        FONTS/FONT_ALIASES and render's ICONS/ICON_SIZES (docs/plans/
        fonts-and-icons.md Decision 3/4) -- run this after font-metrics,
        whenever FAMILIES/SIZES/ICONS change. Rewrites the file's four
        generated fences in place; everything else is untouched. Defaults
        to firmware/epaper-schedule.yaml relative to the repo root. Named
        `firmware-fonts` through B4b, when it only touched fonts; the old
        name still works.

Font dir: --font-dir, else DISPLAY_MCP_FONT_DIR, else ./fonts. `check` and
`render` exit 2 with a clear message if the fonts aren't there.

Implemented by the renderer package.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import types
from pathlib import Path
from typing import Any


def _render() -> types.ModuleType:
    """Lazy import of `display_mcp.render` -- every command but
    `font-metrics` imports it strictly (a `SIZES`/`FAMILIES` edit not yet
    followed by a metrics re-run is a loud `RuntimeError` at import,
    Decision 3), so nothing here imports it at module load time: doing so
    would make it impossible for `cmd_font_metrics` to set
    `DISPLAY_MCP_FONT_METRICS_BOOTSTRAP` (see its own docstring) before the
    package's `FONTS` table is built for the first time (B3b re-review,
    item 3 -- the metrics bootstrap deadlock this fixes)."""
    import display_mcp.render as _render_module

    return _render_module


def _default_font_dir() -> Path:
    return Path(os.environ.get("DISPLAY_MCP_FONT_DIR", "./fonts"))


def _resolve_font_dir(args: argparse.Namespace) -> Path:
    return Path(args.font_dir) if args.font_dir else _default_font_dir()


def _load(path: str) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def _require_fonts(font_dir: Path) -> bool:
    r = _render()
    if r.fonts_available(font_dir):
        return True
    names = ", ".join(sorted({face.file for face in r.FONTS.values()}))
    print(
        f"fonts not found in {font_dir} (need {names}) — run "
        "deploy/fetch-fonts.sh or set --font-dir",
        file=sys.stderr,
    )
    return False


def _report_header(doc: dict[str, Any]) -> str:
    size = len(json.dumps(doc, separators=(",", ":")))
    h = _render().render_hash(doc)
    return f"{len(doc.get('ops', []))} ops, {size} bytes minified, render hash {h}"


def _print_problems(problems: list[str]) -> None:
    for p in problems:
        print("  !", p)


def cmd_check(args: argparse.Namespace) -> int:
    font_dir = _resolve_font_dir(args)
    if not _require_fonts(font_dir):
        return 2
    r = _render()
    doc = _load(args.file)
    problems = r.check(doc, font_dir)
    if not (doc.get("meta") or {}).get("hash"):
        problems.append(r._NO_HASH_WARNING)
    print(_report_header(doc))
    _print_problems(problems)
    return 1 if problems else 0


def cmd_stamp(args: argparse.Namespace) -> int:
    doc = _load(args.file)
    h = _render().render_hash(doc)
    doc.setdefault("meta", {})["hash"] = h
    with open(args.file, "w") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    print(f'meta.hash = {h}   (serve as ETag: "{h}")')
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    font_dir = _resolve_font_dir(args)
    if not _require_fonts(font_dir):
        return 2
    r = _render()
    doc = _load(args.file)
    img, _ = r.render(doc, font_dir)
    problems = r.check(doc, font_dir)
    if not (doc.get("meta") or {}).get("hash"):
        problems.append(r._NO_HASH_WARNING)
    print(_report_header(doc))
    _print_problems(problems)
    img.save(args.output)
    print(f"wrote {args.output}")
    return 1 if problems else 0


def cmd_swatches(args: argparse.Namespace) -> int:
    font_dir = _resolve_font_dir(args)
    if not _require_fonts(font_dir):
        return 2
    r = _render()
    doc = r.swatch_document()
    img, _ = r.render(doc, font_dir, dithered_colors=args.dithered)
    problems = r.check(doc, font_dir)
    print(_report_header(doc))
    _print_problems(problems)
    img.save(args.output)
    print(f"wrote {args.output}")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(doc, f, indent=2)
            f.write("\n")
        print(f"wrote {args.json}")
    return 1 if problems else 0


def cmd_font_metrics(args: argparse.Namespace) -> int:
    """`display-mcp-cli font-metrics <font_dir>`: regenerate
    render/font_metrics.json from the real fonts (docs/plans/
    fonts-and-icons.md Decision 3/B1 review item 9) -- moved here, off
    `python -m display_mcp.render.fonts`, because that form re-executes
    the module under `__main__` after `render/__init__.py` has already
    imported it under its real name, which Python warns about
    ("found in sys.modules ... before execution"); a CLI subcommand has
    no such double-import.

    Sets `DISPLAY_MCP_FONT_METRICS_BOOTSTRAP` before its own first import
    of `display_mcp.render.fonts` (B3b re-review, item 3): adding a size or
    a family to `SIZES`/`FAMILIES` means this very command has to run
    *before* a `font_metrics.json` row exists for the new faces, but
    `_build_fonts()` raises at import on exactly that missing row (Decision
    3's strict-by-default rule) -- which is exactly the situation this
    command exists to fix, so it can't also be blocked by it. The flag
    makes `_metrics_for()` hand out a placeholder instead of raising just
    long enough for `FONTS` to build with the right names/files/sizes;
    `_write_metrics()` then measures every one of them fresh from the real
    files below, so the placeholder never reaches the written file. Every
    other command, and a plain `import display_mcp.render`, stays strict."""
    os.environ["DISPLAY_MCP_FONT_METRICS_BOOTSTRAP"] = "1"
    try:
        from display_mcp.render.fonts import _METRICS_PATH, _write_metrics

        _write_metrics(Path(args.font_dir))
    finally:
        # An in-process caller (a test) must not be left with strictness
        # off for the rest of its process (B3b re-review nit).
        os.environ.pop("DISPLAY_MCP_FONT_METRICS_BOOTSTRAP", None)
    print(f"wrote {_METRICS_PATH}")
    return 0


def _default_yaml_path() -> Path:
    """firmware/epaper-schedule.yaml, relative to this file's place in the
    repo (src/display_mcp/cli.py -> ../../firmware/epaper-schedule.yaml) --
    a repo-relative default, since `firmware-vocabulary` (unlike
    font-metrics) has one obvious target and shouldn't require typing its
    path every time."""
    return Path(__file__).resolve().parents[2] / "firmware" / "epaper-schedule.yaml"


def cmd_firmware_vocabulary(args: argparse.Namespace) -> int:
    """`display-mcp-cli firmware-vocabulary [yaml_path]` (alias
    `firmware-fonts`): regenerate the YAML's four font/icon fences from
    FONTS/FONT_ALIASES and ICONS/ICON_SIZES (docs/plans/fonts-and-icons.md
    Decision 3/4, B2/B4b) -- in a CLI subcommand, not a bare script, for the
    same reason `font-metrics` is (see cmd_font_metrics's docstring)."""
    from display_mcp.render.firmware_yaml import generate_firmware_yaml

    path = Path(args.yaml_path) if args.yaml_path else _default_yaml_path()
    if not path.is_file():
        # An installed copy (site-packages on the host) has no firmware/
        # beside it; this command only makes sense from a checkout.
        print(
            f"error: {path} not found -- firmware-vocabulary runs from a repo checkout",
            file=sys.stderr,
        )
        return 2
    text = path.read_text()
    new_text = generate_firmware_yaml(text)
    # Write-then-rename so a crash mid-write cannot leave a truncated YAML
    # behind: the committed file is either the old text or the new one.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(new_text)
    os.replace(tmp, path)
    print(f"wrote {path}")
    return 0


def _default_url() -> str:
    return os.environ.get("DISPLAY_MCP_URL", "http://127.0.0.1:8001/mcp")


def _client(url: str):
    """The MCP client for `publish`; tests swap this for an in-process one."""
    from mcp import Client

    return Client(url)


def cmd_publish(args: argparse.Namespace) -> int:
    import asyncio

    doc = _load(args.file)

    async def run():
        async with _client(args.url) as c:
            return await c.call_tool("set_display", {"document": doc, "name": args.name})

    try:
        result = asyncio.run(run())
    except Exception as exc:  # connection refused, auth, ...
        print(f"publish failed: {exc}", file=sys.stderr)
        return 2
    if result.is_error:
        text = " ".join(getattr(b, "text", "") for b in result.content)
        print(f"publish rejected: {text}", file=sys.stderr)
        return 1
    out = result.structured_content
    print(f"published {out['name']}: hash {out['hash']}, {out['ops']} ops, {out['bytes']} bytes")
    _print_problems(out.get("warnings") or [])
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="display-mcp-cli")
    sub = ap.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="validate, print hash, exit 1 on problems")
    p_check.add_argument("file")
    p_check.add_argument("--font-dir")
    p_check.set_defaults(func=cmd_check)

    p_stamp = sub.add_parser("stamp", help="write meta.hash back into the file")
    p_stamp.add_argument("file")
    p_stamp.add_argument("--font-dir")
    p_stamp.set_defaults(func=cmd_stamp)

    p_render = sub.add_parser("render", help="render to a PNG")
    p_render.add_argument("file")
    p_render.add_argument("-o", "--output", default="preview.png")
    p_render.add_argument("--font-dir")
    p_render.set_defaults(func=cmd_render)

    p_pub = sub.add_parser("publish", help="publish through the MCP endpoint")
    p_pub.add_argument("file")
    p_pub.add_argument("--name", default="default")
    p_pub.add_argument("--url", default=_default_url())
    p_pub.set_defaults(func=cmd_publish)

    p_sw = sub.add_parser("swatches", help="render every named colour as a labelled chip")
    p_sw.add_argument("-o", "--output", default="swatches.png")
    p_sw.add_argument("--json", help="also write the swatch document as JSON")
    p_sw.add_argument(
        "--dithered",
        action="store_true",
        help="panel-faithful dithered mixes, instead of the flat default "
        "(this is the one render meant for judging colour on screen)",
    )
    p_sw.add_argument("--font-dir")
    p_sw.set_defaults(func=cmd_swatches)

    p_fm = sub.add_parser(
        "font-metrics",
        help="measure cell_height/ink_height from the real fonts and write font_metrics.json",
    )
    p_fm.add_argument("font_dir", help="directory holding the compiled .ttf files")
    p_fm.set_defaults(func=cmd_font_metrics)

    p_ff = sub.add_parser(
        "firmware-vocabulary",
        aliases=["firmware-fonts"],
        help="regenerate epaper-schedule.yaml's font:/image: blocks and "
        "a.fonts[...]/a.icons[...] lines",
    )
    p_ff.add_argument("yaml_path", nargs="?", help="defaults to firmware/epaper-schedule.yaml")
    p_ff.set_defaults(func=cmd_firmware_vocabulary)

    return ap


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
