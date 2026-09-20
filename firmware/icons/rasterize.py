#!/usr/bin/env python3
"""Rasterise the lucide activity icons to committed 1-bit PNGs.

Sources: firmware/icons/src/<activity>.svg, lucide-static v1.47.0, ISC
licence (firmware/icons/src/LICENSE), fetched from
https://cdn.jsdelivr.net/npm/lucide-static@1.47.0/icons/<icon>.svg
(docs/plans/fonts-and-icons.md, Decision 4).

Run under ESPHome's own Python (it has `resvg_py`; the project venv does
not):

    /opt/homebrew/Cellar/esphome/2026.8.2/libexec/bin/python firmware/icons/rasterize.py

For every SVG and every font-slot pixel size (22 28 36 48 84) this calls
`resvg_py.svg_to_bytes(svg_path=..., width=px, height=px, dpi=100)` — the
exact call ESPHome's `components/file/image.py` makes for an SVG `file:`
image — then reproduces the rest of that module's `type: BINARY` path
(`components/image/__init__.py`'s `ImageBinary.convert`): take the alpha
channel and threshold it at 128 with no dithering, which is what
`Image.convert("1", dither=Image.Dither.NONE)` does. The result is written
back out as an RGBA PNG whose RGB is always zero and whose alpha is
exactly 0 or 255 — the shape `is_alpha_only()` recognises, so ESPHome
compiles the PNG through the same BINARY path an SVG would take, and the
preview's `draw_icon()` blits the identical bitmap.

Deterministic and idempotent: given the same SVGs this writes the same
bytes every time (no timestamp or other metadata is carried into the
output image), so a second run changes nothing. Takes no arguments; every
path is relative to this file.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
SRC_DIR = SCRIPT_DIR / "src"
REPO_ROOT = SCRIPT_DIR.parent.parent
OUT_DIR = REPO_ROOT / "src" / "display_mcp" / "render" / "icons"

# The eight activity names this repo uses (docs/plans/fonts-and-icons.md,
# "The question", item 2) -- a plain tuple, not the name -> lucide-icon-name
# mapping an earlier draft of this script kept here (C9, final review): the
# *value* half of that mapping was never read by anything below, only used
# as a comment on where each SVG under src/ originally came from, which
# belongs beside the file it names instead. That provenance, for the
# record: school-day <- book-open, daycare <- baby, taekwondo <- star,
# swim <- waves-ladder (not "waves" -- Decision 4's own note on why),
# helper <- user-round, appointment <- stethoscope, family-meeting <- users,
# closed <- calendar-off. `LUCIDE_ICONS` (display_mcp.render.shapes) is the
# renderer's own copy of this same set, independent on purpose --
# tests/renderer/test_icon_assets.py cross-checks this one against it.
ACTIVITIES = (
    "school-day",
    "daycare",
    "taekwondo",
    "swim",
    "helper",
    "appointment",
    "family-meeting",
    "closed",
)

# The five font slots' pixel sizes (Decision 4: icons share the font ladder).
SIZES = (22, 28, 36, 48, 84)


def rasterize_one(svg_path: Path, px: int) -> Image.Image:
    """Render `svg_path` at `px` x `px` exactly as ESPHome's `file:` image
    loader would, then apply the BINARY encoder's alpha threshold.

    `resvg_py` is imported here, not at module scope (C9, final review):
    it only exists under ESPHome's own Python, not this project's venv,
    and importing it at module scope made the whole module -- including
    `ACTIVITIES`/`SIZES`, which a plain test can use freely -- unimportable
    from the venv `tests/renderer/test_icon_assets.py` runs in."""
    try:
        import resvg_py
    except ImportError as exc:  # pragma: no cover - guidance for the wrong interpreter
        raise SystemExit(
            "resvg_py is not importable under this interpreter. Run this script "
            "with ESPHome's own Python, e.g.\n"
            "  /opt/homebrew/Cellar/esphome/2026.8.2/libexec/bin/python "
            "firmware/icons/rasterize.py"
        ) from exc

    raw = resvg_py.svg_to_bytes(svg_path=str(svg_path), width=px, height=px, dpi=100)
    rendered = Image.open(io.BytesIO(bytes(raw))).convert("RGBA")

    # esphome/components/image/__init__.py: ImageBinary.convert() takes the
    # alpha channel when the image is alpha-only (true here: black stroke,
    # transparent fill) and thresholds it at 128 with no dithering
    # (CONF_DITHER defaults to "NONE").
    # ESPHome takes the alpha channel *only* when is_alpha_only() holds --
    # some transparent pixel, and RGB zero everywhere. Anything else (a
    # filled glyph, an opaque background, a coloured stroke) it thresholds
    # on the colour data instead, and the PNG this script would write from
    # it would silently compile to different bits than the SVG. Refuse
    # rather than diverge; every lucide icon is a black stroke on nothing,
    # so this only fires on a pin bump or an icon swap that changes that.
    bands = rendered.split()
    if bands[-1].getextrema()[0] == 0xFF or any(b.getextrema()[1] for b in bands[:-1]):
        raise SystemExit(
            f"{svg_path.name} at {px}px is not alpha-only; ESPHome's BINARY path "
            "would not take the alpha channel, so the PNG would not match the SVG"
        )
    alpha = bands[-1]
    mask = alpha.convert("1", dither=Image.Dither.NONE).convert("L")

    out = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    out.putalpha(mask)
    return out


def png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    # No pnginfo/exif/dpi is ever attached to `image`, so this is the same
    # bytes on every run given the same pixels.
    image.save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for activity in sorted(ACTIVITIES):
        svg_path = SRC_DIR / f"{activity}.svg"
        if not svg_path.is_file():
            raise SystemExit(f"missing source SVG: {svg_path}")
        for px in SIZES:
            out_path = OUT_DIR / f"{activity}-{px}.png"
            data = png_bytes(rasterize_one(svg_path, px))
            if out_path.is_file() and out_path.read_bytes() == data:
                print(f"unchanged: {out_path.relative_to(REPO_ROOT)}")
                continue
            out_path.write_bytes(data)
            print(f"wrote:     {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
