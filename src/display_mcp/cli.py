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

Font dir: --font-dir, else DISPLAY_MCP_FONT_DIR, else ./fonts. `check` and
`render` exit 2 with a clear message if the fonts aren't there.

Implemented by the renderer package.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from display_mcp.render import _NO_HASH_WARNING, check, fonts_available, render, render_hash


def _default_font_dir() -> Path:
    return Path(os.environ.get("DISPLAY_MCP_FONT_DIR", "./fonts"))


def _resolve_font_dir(args: argparse.Namespace) -> Path:
    return Path(args.font_dir) if args.font_dir else _default_font_dir()


def _load(path: str) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def _require_fonts(font_dir: Path) -> bool:
    if fonts_available(font_dir):
        return True
    print(
        f"fonts not found in {font_dir} (need InstrumentSans-Regular.ttf and "
        "-Bold.ttf) — run deploy/fetch-fonts.sh or set --font-dir",
        file=sys.stderr,
    )
    return False


def _report_header(doc: dict[str, Any]) -> str:
    size = len(json.dumps(doc, separators=(",", ":")))
    h = render_hash(doc)
    return f"{len(doc.get('ops', []))} ops, {size} bytes minified, render hash {h}"


def _print_problems(problems: list[str]) -> None:
    for p in problems:
        print("  !", p)


def cmd_check(args: argparse.Namespace) -> int:
    font_dir = _resolve_font_dir(args)
    if not _require_fonts(font_dir):
        return 2
    doc = _load(args.file)
    problems = check(doc, font_dir)
    if not (doc.get("meta") or {}).get("hash"):
        problems.append(_NO_HASH_WARNING)
    print(_report_header(doc))
    _print_problems(problems)
    return 1 if problems else 0


def cmd_stamp(args: argparse.Namespace) -> int:
    doc = _load(args.file)
    h = render_hash(doc)
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
    doc = _load(args.file)
    img, _ = render(doc, font_dir)
    problems = check(doc, font_dir)
    if not (doc.get("meta") or {}).get("hash"):
        problems.append(_NO_HASH_WARNING)
    print(_report_header(doc))
    _print_problems(problems)
    img.save(args.output)
    print(f"wrote {args.output}")
    return 1 if problems else 0


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

    return ap


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
