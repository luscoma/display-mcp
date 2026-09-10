#!/usr/bin/env python3
"""Regenerate the images in docs/images/ from the renderer itself.

The README's picture is produced here, so a change to the renderer shows up
as a diff in the image rather than as a README that quietly stops being true.
Run it after touching `display_mcp.render`:

    DISPLAY_MCP_FONT_DIR=./fonts python docs/images/generate.py

`sample.png` is the whole 1200x1600 canvas, halved on the way out — ample
for a README and light in the repo.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from display_mcp.render import render  # noqa: E402

FONT_DIR = Path(os.environ.get("DISPLAY_MCP_FONT_DIR", ROOT / "fonts"))


def emit(name: str, doc: dict) -> None:
    img, problems = render(doc, FONT_DIR)
    for p in problems:
        print(f"  {name}: {p}")
    img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
    out = HERE / f"{name}.png"
    img.save(out, optimize=True)
    print(f"  wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")


def main() -> int:
    if not FONT_DIR.is_dir():
        print(f"no font directory at {FONT_DIR}; run deploy/fetch-fonts.sh ./fonts")
        return 1
    emit("sample", json.loads((ROOT / "samples" / "display.json").read_text()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
