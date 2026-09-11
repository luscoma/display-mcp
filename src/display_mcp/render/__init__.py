"""Renderer: draws a display list the way firmware/display_list.h does.

Port of epaper-display/server/dlpreview.py. The C++ in the firmware is
authoritative; where they differ, this is the bug — except for the three
deliberate fixes called out in docs/PLAN.md ("Renderer"):

1. ``weather-snowy`` is a valid, compiled-in icon (dlpreview.py was missing
   it). A procedural stand-in is drawn for it like the other weather icons.
2. Icons are validated as ``name/z`` pairs, the way the firmware keys its
   compiled icon table (``assets.icons["check/sm"]`` etc.) — an icon whose
   size class was never compiled in is now a problem, not a silent pass.
3. The off-canvas check also covers ``x+w``/``y+h`` for rects and
   ``x2``/``y2`` for lines, with the same +/-64px tolerance already applied
   to every op's ``x``/``y``.

Public surface (final):
    WIDTH, HEIGHT            1200, 1600
    FONTS                    {name: (size, bold)} for xl lg md sm xs
    ICONS                    {name: frozenset(size classes)} e.g. {"check": {"sm"}}
    ICON_SIZES               {size class: pixel size}
    COLORS                   the six ink names
    render_hash(doc) -> str  sha256 of canonical {bg, palette, ops}, first 16 hex
    render(doc, font_dir, dithered_colors=True) -> (PIL.Image.Image, list[str])
    check(doc, font_dir) -> list[str]   problems only, no image
    fit_line(font, s, max_w) / wrap_lines(font, s, max_w, max_lines)
    fonts_available(font_dir) -> bool
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1200, 1600

COLORS = ("black", "white", "yellow", "red", "blue", "green")

# name -> (size px, bold). Compiled into the firmware; changing one is a rebuild.
FONTS: dict[str, tuple[int, bool]] = {
    "xl": (84, True),
    "lg": (48, True),
    "md": (36, False),
    "sm": (28, False),
    "xs": (22, True),
}

# name -> size classes the firmware compiled. Keyed "name/z" on the panel.
ICONS: dict[str, frozenset[str]] = {
    "weather-sunny": frozenset({"lg"}),
    "weather-partly-cloudy": frozenset({"lg"}),
    "weather-cloudy": frozenset({"lg"}),
    "weather-rainy": frozenset({"lg"}),
    "weather-snowy": frozenset({"lg"}),
    "weather-night": frozenset({"lg"}),
    "check": frozenset({"sm"}),
    "map-marker": frozenset({"sm"}),
    "clock": frozenset({"sm"}),
    "alert": frozenset({"sm"}),
    "battery": frozenset({"sm"}),
}

ICON_SIZES = {"sm": 36, "md": 56, "lg": 88}

# The panel sits behind a printed bezel (mount/epaper_frame_bezel.scad)
# whose window is the active area less 1 mm per edge: ~6 px hidden, plus a
# couple of pixels of panel float and the shadow of the 45° bevel. Text and
# icons whose anchor lands inside this band are flagged by check(); fills and
# bars are meant to run full bleed and are not.
BEZEL_MARGIN = 24

# Roughly what those inks look like on a Spectra 6 panel. This is the only
# colour table: the panel is the thing being previewed, so an approximation
# of the glass beats the pure framebuffer RGB the driver writes (the old
# `--ideal` mode, removed — it was CLI-only and no MCP caller could reach it).
INK = {
    "black": (32, 32, 32),
    "white": (222, 222, 216),
    "yellow": (206, 172, 44),
    "red": (156, 46, 42),
    "blue": (46, 62, 128),
    "green": (72, 108, 66),
}

ANCHOR = {"left": "la", "center": "ma", "right": "ra"}

_NO_HASH_WARNING = (
    "no meta.hash — the panel will refresh on EVERY wake "
    "(~36 mAh/day, roughly half its battery life). Run with --stamp."
)


def _font_path(font_dir: Path, bold: bool) -> Path:
    name = "InstrumentSans-Bold.ttf" if bold else "InstrumentSans-Regular.ttf"
    return Path(font_dir) / name


def load_font(font_dir: Path, size: int, bold: bool) -> ImageFont.FreeTypeFont:
    """Load one face. `bold` also selects the variable font's "Bold" instance.

    Google Fonts ships Instrument Sans as a variable font: Pillow loads the
    default instance (Regular) unless the named instance is selected, and
    the wrong weight means text wraps in different places than the panel
    does. A static Bold face (nothing to select) is fine too.
    """
    f = ImageFont.truetype(str(_font_path(font_dir, bold)), size)
    if bold:
        try:
            f.set_variation_by_name("Bold")
        except Exception:
            pass  # a static Bold face: nothing to select
    return f


def _load_fonts(font_dir: Path) -> dict[str, ImageFont.FreeTypeFont]:
    return {name: load_font(font_dir, size, bold) for name, (size, bold) in FONTS.items()}


def fonts_available(font_dir: Path) -> bool:
    font_dir = Path(font_dir)
    return (font_dir / "InstrumentSans-Regular.ttf").exists() and (
        font_dir / "InstrumentSans-Bold.ttf"
    ).exists()


# The 2x2 ordered (Bayer) matrix behind every mix, indexed [y & 1][x & 1].
# Mirrors mix_on() in display_list.h; see docs/plans/ink-mixing.md decision 2.
_BAYER2 = ((0, 2), (3, 1))

DENSITIES = (25, 50, 75)


# The named mixes, compiled into the firmware as BUILTIN_MIXES in
# display_list.h and mirrored here. A document writes `"c": "navy"` with no
# palette entry (decision 10).
#
# This table is a permanent contract: these names mean these recipes, and the
# way to break one is to bump the document's `v`, never to redefine a name in
# place — the definitions live in the firmware rather than in `palette`, so
# they are outside `meta.hash` and a redefinition would change what an
# already-published document draws without changing its identity.
#
# tests/test_firmware_parity.py extracts the C++ table and diffs it against
# this one, so keep both machine-readable: one entry per line.
BUILTIN_MIXES: dict[str, tuple[str, str, int]] = {
    "navy": ("black", "blue", 50),
    "maroon": ("black", "red", 50),
    "plum": ("red", "blue", 50),
    "forest": ("black", "green", 50),
    "teal": ("blue", "green", 50),
    "brown": ("red", "green", 50),
    "grey-dark": ("black", "white", 25),
    "cream-pale": ("yellow", "white", 75),
    "cream": ("yellow", "white", 50),
    "sage-pale": ("green", "white", 75),
    "slate-pale": ("blue", "white", 75),
    "pink-pale": ("red", "white", 75),
    "grey-light": ("black", "white", 75),
    "sage": ("green", "white", 50),
    "pink": ("red", "white", 50),
    "slate": ("blue", "white", 50),
    "chartreuse": ("yellow", "green", 50),
    "grey-mid": ("black", "white", 50),
    "mustard": ("black", "yellow", 50),
    "orange": ("yellow", "red", 50),
    "olive": ("yellow", "blue", 50),
}


def mix_on(x: int, y: int, pct: int) -> bool:
    """True where the *second* ink of a mix goes.

    Phase is absolute — canvas coordinates, not the op's origin — so abutting
    fills tile without a seam and a knockout lands exactly on the mix beneath
    it. At pct=50 the matrix selects cells 0 and 1, which sit at (0,0) and
    (1,1), i.e. precisely `(x + y) % 2 == 0`: the test tone's knockout has
    always used. Existing documents therefore render unchanged.
    """
    return _BAYER2[y & 1][x & 1] < pct // 25


class Ink(NamedTuple):
    """A resolved colour: two inks and the percentage of `b` among them.

    A plain colour is `Ink(c, c, 100)`, so callers never branch on whether
    something is a mix — the solid case is a mix with nothing to interleave.
    """

    a: tuple
    b: tuple
    mix: int

    @property
    def solid(self) -> bool:
        return self.a == self.b

    @property
    def avg(self) -> tuple:
        """The single colour this mix averages to over a large enough area.

        What the eye integrates a dithered fill into, and what the panel's
        glass actually shows for anything bigger than a few pixels. For a
        solid ink `mix` is 100 and `a == b`, so this returns that ink
        unchanged and needs no special case.

        This is the colour `render(dithered_colors=False)` paints, and it
        reproduces every hex in the named-palette table in docs/SPEC.md
        exactly — tests/test_render.py pins that, so the table cannot drift
        away from the renderer.

        It is honest for a fill and optimistic for a glyph: a few pixels of
        stroke cannot average two inks, so text reads shifted toward the
        lighter one. That gap is what _check_mix_as_text() warns about, and
        it is why a flat preview has to carry its warnings with it.
        """
        w = self.mix / 100
        return tuple(round(self.a[i] * (1 - w) + self.b[i] * w) for i in range(3))


def _luminance(rgb: tuple) -> float:
    """WCAG relative luminance of an (r, g, b) triple, channels 0-255."""

    def lin(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast_ratio(rgb_a: tuple, rgb_b: tuple) -> float:
    """WCAG contrast ratio between two colours; always >= 1."""
    la, lb = _luminance(rgb_a), _luminance(rgb_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _clip_to_canvas(box: tuple) -> tuple | None:
    """Clip a box to the canvas as ints. None when there is no on-canvas
    area at all — an op drawn off-screen, a zero-size box (an empty
    string) — so callers skip rather than warn on those, per the
    false-positive list in the ink-mixing plan."""
    x0, y0, x1, y1 = box
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(WIDTH, int(x1)), min(HEIGHT, int(y1))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _grounds(img: Image.Image, box: tuple) -> list[tuple[tuple[float, ...], Counter]] | None:
    """The ground colour(s) under `box`, sampled at the scale the eye fuses at.

    A dither is two inks a pixel apart and fuses into one colour at reading
    distance; two regions side by side do not. So the sample is taken per
    2x2 mask tile — the mask's whole period (decision 2), 0.34 mm on the
    glass — averaging each tile into the colour it fuses to, and then taking
    the tile colour covering most of the box. Tiles align to the mask's own
    absolute phase, so a mixed fill sampled anywhere yields whole periods.

    That is `most_common` as it was always meant to work; what was wrong
    before was the scale, not the idea. Sampled per pixel, a 50% mix is two
    colours tied 50/50 and the tie-break decided whether white text on
    `grey-mid` scored 12.06:1 or 1.00:1. Sampled per tile there is no tie to
    break: every tile of that mix is the same fused grey. Sampling the
    canvas rather than reading the ink also means the density is whatever
    was really painted, parity trap (decision 2) included.

    When tile colours genuinely tie — a box sitting half on one rect and
    half on another — every tied colour comes back rather than one of them,
    so the caller can judge against the harder half instead of flipping a
    coin. Each comes with the tally of the inks behind it, because a fused
    colour is generally not an ink and the warning still has to name what is
    behind the text.

    None when the box has no on-canvas area at all — an op drawn off-screen,
    a zero-size box (an empty string) — so callers skip rather than warn on
    those, per the false-positive list in the ink-mixing plan.
    """
    clipped = _clip_to_canvas(box)
    if clipped is None:
        return None
    x0, y0, x1, y1 = clipped
    px = img.load()
    tiles: Counter = Counter()
    inks: dict[tuple, Counter] = {}
    for ty in range(y0 - (y0 % 2), y1, 2):
        for tx in range(x0 - (x0 % 2), x1, 2):
            cell = Counter(
                px[x, y]
                for y in range(max(ty, y0), min(ty + 2, y1))
                for x in range(max(tx, x0), min(tx + 2, x1))
            )
            n = sum(cell.values())
            fused = tuple(sum(c[i] * k for c, k in cell.items()) / n for i in range(3))
            tiles[fused] += n
            inks.setdefault(fused, Counter()).update(cell)
    most = max(tiles.values())
    return [(fused, inks[fused]) for fused, n in tiles.items() if n == most]


class Ctx:
    def __init__(self, doc: dict[str, Any], font_dir: Path, warn_ink: bool = False):
        self.palette = doc.get("palette") or {}
        self.table = INK
        self.table_rev = {v: k for k, v in self.table.items()}
        self.fonts = _load_fonts(Path(font_dir))
        self.problems: list[str] = []
        # The three ink-mixing authoring warnings (contrast floor, chromatic
        # mix as text, sub-2px density) are check()-only, the same way
        # bezel_problems() is check()-only — render() on its own reports
        # only what stops a document from drawing correctly. Gated so a bare
        # render() call is unaffected.
        self.warn_ink = warn_ink

    def name_of(self, rgb: tuple) -> str:
        """Reverse-lookup a raw canvas pixel to its ink name. Every pixel a
        *dithered* render paints is one of the six table entries verbatim —
        a mix interleaves two solid inks, it never averages them on canvas —
        so this always resolves for real pixels.

        `render(dithered_colors=False)` does paint blends, which have no ink
        name. It cannot reach here: every caller is behind `warn_ink`, and
        render() rejects `warn_ink` on a flat canvas for exactly this
        reason. The `"ink"` fallback is therefore unreachable, and kept only
        so a stray colour degrades a message rather than raising."""
        return self.table_rev.get(rgb, "ink")

    def ground_name(self, counts: Counter) -> str:
        """Name a sampled ground for a warning message: a solid one by its
        ink name, a dithered one as `black+white`. Ordered by how much of
        the ground each ink covers, darker ink first on a tie, so a 50/50
        mix is always named the same way round."""
        inks = sorted(counts, key=lambda c: (-counts[c], _luminance(c)))
        return "+".join(self.name_of(c) for c in inks)

    def ink(self, name: str, where: str = "") -> Ink:
        """Resolve a colour name to an Ink, following palette aliases.

        Mirrors resolve_ink() in display_list.h. Resolution is base inks ->
        the document's palette -> the built-in mixes, so the six ink names
        are immutable and a document can shadow a built-in one by declaring
        it. Every malformed case warns and still yields something drawable;
        nothing here skips an op.
        """
        n = name
        for _ in range(8):
            if n in self.table:
                return Ink(self.table[n], self.table[n], 100)
            entry = self.palette.get(n)
            if entry is None:
                builtin = BUILTIN_MIXES.get(n)
                if builtin is None:
                    break
                a, b, m = builtin
                return Ink(self.table[a], self.table[b], m)
            if isinstance(entry, dict):
                return self._mix(entry, n, where)
            n = entry
        self.problems.append(f"{where}: unknown colour {n!r}")
        black = self.table["black"]
        return Ink(black, black, 100)

    def _mix(self, entry: dict[str, Any], name: str, where: str) -> Ink:
        black = self.table["black"]
        c, c2 = entry.get("c"), entry.get("c2")
        if not isinstance(c, str):
            self.problems.append(f"{where}: mix {name!r} has no 'c'; using black")
            return Ink(black, black, 100)
        a = self._base(c, where)
        if not isinstance(c2, str):
            self.problems.append(f"{where}: mix {name!r} has no 'c2'; drawing solid")
            return Ink(a, a, 100)
        b = self._base(c2, where)
        if a == b:
            self.problems.append(f"{where}: mix {name!r} has c2 == c; drawing solid")
            return Ink(a, a, 100)
        return Ink(a, b, self._density(entry.get("mix"), name, where))

    def _base(self, name: str, where: str) -> tuple:
        """One ink. A mix inside a mix isn't representable in a 2x2 mask, so
        a nested one warns and contributes only its own base colour."""
        n = name
        for _ in range(8):
            if n in self.table:
                return self.table[n]
            entry = self.palette.get(n)
            if entry is None:
                builtin = BUILTIN_MIXES.get(n)
                if builtin is None:
                    break
                self.problems.append(
                    f"{where}: {n!r} is a built-in mix, not a plain colour here; "
                    "using its base ink"
                )
                n = builtin[0]
                continue
            if isinstance(entry, dict):
                self.problems.append(
                    f"{where}: {n!r} is a mix and mixes cannot nest; using its 'c'"
                )
                n = entry.get("c")
                if not isinstance(n, str):
                    break
                continue
            n = entry
        self.problems.append(f"{where}: unknown colour {n!r}")
        return self.table["black"]

    def _density(self, raw: Any, name: str, where: str) -> int:
        if raw is None:
            return 50
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not 0 <= raw <= 100:
            self.problems.append(f"{where}: mix {name!r} has mix={raw!r}; using 50")
            return 50
        pct = min(DENSITIES, key=lambda v: (abs(v - raw), v))
        if pct != raw:
            self.problems.append(
                f"{where}: mix {name!r} has mix={raw}, rounded to {pct} (25/50/75 only)"
            )
        return pct

    def color(self, name: str, where: str = ""):
        # Palette aliases resolve up to 8 hops, matching resolve_color() in
        # display_list.h; a cycle (or a chain deeper than that) falls back
        # to black with a problem instead of hanging.
        n = name
        for _ in range(8):
            if n in self.table:
                return self.table[n]
            nxt = self.palette.get(n)
            if nxt is None:
                break
            n = nxt
        self.problems.append(f"{where}: unknown colour {n!r}")
        return self.table["black"]

    def font(self, name: str, where: str = ""):
        """Resolve a font name, or None when it isn't compiled in.

        Mirrors the firmware's `assets.fonts.find()` miss: `text` and `fmt`
        both `skipped++; continue` there rather than draw with a substitute
        face, so a caller returning None here must abandon the op the same
        way rather than fall back to `md` — a fallback would draw in the
        preview something the panel never puts on the wall.
        """
        if name not in self.fonts:
            self.problems.append(f"{where}: unknown font {name!r}")
            return None
        return self.fonts[name]


def text_width(font, s: str) -> int:
    return font.getbbox(s)[2] - font.getbbox(s)[0]


def fit_line(font, s: str, max_w):
    """Truncate to max_w with an ellipsis. Mirrors dl_fit_line() in the header."""
    if max_w is None or text_width(font, s) <= max_w:
        return s
    ell = "…"
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if text_width(font, s[:mid] + ell) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo].rstrip() + ell


def wrap_lines(font, s: str, max_w, max_lines: int):
    """Greedy word wrap; last line ellipsized if it overflows. Mirrors dl_wrap()."""
    words = s.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = word if not cur else cur + " " + word
        if text_width(font, trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
            if len(lines) == max_lines:
                break
    if len(lines) < max_lines and cur:
        lines.append(cur)
    if len(lines) == max_lines:
        used = sum(len(line.split()) for line in lines)
        if used < len(words):
            lines[-1] = fit_line(font, lines[-1] + " " + words[used], max_w)
    # A single word longer than the box would otherwise escape unclipped.
    return [fit_line(font, line, max_w) for line in lines[:max_lines]]


def _icon_mask(name: str, size: int) -> Image.Image:
    """The glyph as a 1-bit `size x size` stencil: 1 wherever the ink goes.

    Every shape is drawn into this tile instead of onto the page, so no
    helper can paint outside the icon's box however PIL decides to cap a
    thick line or stroke an ellipse. Holes — the moon's crescent, the
    marker's eye, the bang in the alert triangle — are punched back to 0
    rather than painted white: the panel's icons are BINARY images drawn
    with `transparency: chroma_key`, so their off pixels are skipped, not
    filled with anything.
    """
    s = int(size)
    mask = Image.new("1", (s, s), 0)
    d = ImageDraw.Draw(mask)
    ON, OFF = 1, 0
    cx = cy = s / 2
    lw = max(2, round(s * 0.09))

    def sun(scale=1.0, ox=0.0, oy=0.0):
        r = s * 0.19 * scale
        px, py = cx + ox * s, cy + oy * s
        d.ellipse([px - r, py - r, px + r, py + r], fill=ON)
        for i in range(8):
            a = i * math.pi / 4
            d.line(
                [
                    px + math.cos(a) * r * 1.5,
                    py + math.sin(a) * r * 1.5,
                    px + math.cos(a) * r * 2.2,
                    py + math.sin(a) * r * 2.2,
                ],
                fill=ON,
                width=lw,
            )

    def cloud(ox=0.0, oy=0.0, scale=1.0):
        w = s * 0.72 * scale
        h = s * 0.42 * scale
        px, py = cx + ox * s, cy + oy * s
        d.ellipse([px - w / 2, py - h / 2, px - w / 2 + h, py + h / 2], fill=ON)
        d.ellipse([px + w / 2 - h, py - h / 2, px + w / 2, py + h / 2], fill=ON)
        d.rectangle([px - w / 2 + h / 2, py - h / 2, px + w / 2 - h / 2, py + h / 2], fill=ON)
        d.ellipse([px - w * 0.18, py - h * 0.95, px + w * 0.34, py + h * 0.35], fill=ON)

    if name == "weather-sunny":
        sun(1.25)
    elif name == "weather-partly-cloudy":
        sun(0.8, ox=0.16, oy=-0.20)
        cloud(ox=-0.04, oy=0.12, scale=0.95)
    elif name == "weather-cloudy":
        cloud(oy=0.02, scale=1.1)
    elif name == "weather-rainy":
        cloud(oy=-0.10, scale=1.0)
        for i in range(3):
            rx = cx + (i - 1) * s * 0.22
            d.line([rx, cy + s * 0.20, rx - s * 0.06, cy + s * 0.40], fill=ON, width=lw)
    elif name == "weather-snowy":
        # Same cloud as the other weather glyphs, with a few flake dots
        # instead of rain's diagonal streaks.
        cloud(oy=-0.10, scale=1.0)
        for i in range(3):
            fx = cx + (i - 1) * s * 0.24
            fy = cy + s * 0.30 + (i % 2) * s * 0.10
            rr = max(1.8, s * 0.05)
            d.ellipse([fx - rr, fy - rr, fx + rr, fy + rr], fill=ON)
    elif name == "weather-night":
        r = s * 0.30
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ON)
        # The crescent is the bite an offset disc takes out of that one.
        d.ellipse([cx - r * 0.45, cy - r * 1.30, cx + r * 1.65, cy + r * 0.60], fill=OFF)
    elif name == "map-marker":
        r = s * 0.26
        top = s * 0.14
        d.ellipse([cx - r, top, cx + r, top + 2 * r], fill=ON)
        d.polygon(
            [
                (cx - r * 0.78, top + r * 1.35),
                (cx + r * 0.78, top + r * 1.35),
                (cx, s * 0.92),
            ],
            fill=ON,
        )
        hr = r * 0.38
        d.ellipse([cx - hr, top + r - hr, cx + hr, top + r + hr], fill=OFF)
    elif name == "check":
        d.line([s * 0.20, s * 0.52, s * 0.42, s * 0.74], fill=ON, width=lw + 1)
        d.line([s * 0.42, s * 0.74, s * 0.80, s * 0.28], fill=ON, width=lw + 1)
    elif name == "clock":
        r = s * 0.36
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ON, width=lw)
        d.line([cx, cy, cx, cy - r * 0.55], fill=ON, width=lw)
        d.line([cx, cy, cx + r * 0.45, cy], fill=ON, width=lw)
    elif name == "alert":
        d.polygon([(cx, s * 0.14), (s * 0.92, s * 0.84), (s * 0.08, s * 0.84)], fill=ON)
        d.line([cx, s * 0.38, cx, s * 0.62], fill=OFF, width=lw)
        d.ellipse([cx - lw * 0.7, s * 0.68, cx + lw * 0.7, s * 0.68 + lw * 1.4], fill=OFF)
    elif name == "battery":
        bw, bh = s * 0.52, s * 0.76
        d.rectangle([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], outline=ON, width=lw)
        d.rectangle(
            [cx - bw * 0.18, cy - bh / 2 - lw * 1.6, cx + bw * 0.18, cy - bh / 2], fill=ON
        )
        d.rectangle(
            [cx - bw / 2 + lw, cy - bh * 0.10, cx + bw / 2 - lw, cy + bh / 2 - lw], fill=ON
        )
    else:
        d.rectangle([0, 0, s - 1, s - 1], outline=ON, width=lw)

    return mask


def draw_icon(d: ImageDraw.ImageDraw, name: str, x, y, size, fill):
    """Procedural stand-ins. The panel draws real MDI bitmaps.

    Stencilled into a `size x size` tile and blitted at (x, y), the way the
    firmware's `image->draw()` blits exactly get_width() x get_height():
    nothing lands outside [x, x+size) x [y, y+size), and the pixels the
    glyph does not set are left as they were.
    """
    d.bitmap((x, y), _icon_mask(name, size), fill=fill)


def render_hash(doc: dict[str, Any]) -> str:
    """Identity of what the document DRAWS: bg + palette + ops, nothing else.

    Must stay byte-identical to `document_id()` in firmware/display_list.h;
    the panel compares its own reading of meta.hash against what we stamp.
    samples/display.json hashes to 3cd62aa76e731d2d.
    """
    core = {k: doc.get(k) for k in ("bg", "palette", "ops")}
    canon = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


FIELD_RE = re.compile(r"\{([a-z0-9_]+)\}")


def system_fields(doc: dict[str, Any], now: datetime | None = None) -> dict[str, str]:
    """Values the `fmt` op can print. The firmware fills the same names.

    {hash}/{hash16} come from render_hash(doc), which equals meta.hash for a
    correctly stamped document. {time}/{time24} are the moment of drawing:
    here the preview's clock, on the panel its own SNTP-synced clock.
    {battery}/{battv} are the panel's ADC reading; stand-ins here.
    """
    h = render_hash(doc)
    t = now or datetime.now()
    hour12 = t.hour % 12 or 12
    return {
        "hash": h[-5:],
        "hash16": h,
        "time": f"{hour12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}",
        "time24": f"{t.hour:02d}:{t.minute:02d}",
        # The panel fills these from its ADC; the preview has no battery, so
        # it shows a stand-in that is obviously plausible rather than blank.
        "battery": "82%",
        "battv": "3.9V",
    }


def expand_fields(template: str, fields: dict[str, str]) -> tuple[str, list[str]]:
    """Substitute {field}s; unknown ones stay literal and are reported."""
    unknown: list[str] = []

    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name in fields:
            return fields[name]
        unknown.append(name)
        return m.group(0)

    return FIELD_RE.sub(sub, template), unknown


def draw_on(img: Image.Image) -> ImageDraw.ImageDraw:
    """An ImageDraw that rasterises glyphs the way the panel does.

    The compiled fonts are 1 bpp — `font::Font(..., 1)` in the generated
    firmware — so on the wall a glyph pixel is either full ink or nothing,
    and `font.cpp`'s blending branch never runs. Pillow defaults to an 8-bit
    glyph mask on an RGB image, which quietly made the preview softer than
    the panel for every piece of text it has ever drawn. `fontmode = "1"`
    turns that off and renders bilevel, as the panel does.
    """
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    return d


def paint(img: Image.Image, ink: Ink, draw_fn, dithered_colors: bool = True) -> None:
    """Run `draw_fn(draw, colour)`, interleaving two inks if `ink` is a mix.

    The firmware hands `print()` and the shape primitives a proxy Display
    that rewrites the colour inside draw_pixel_at (decision 6). PIL has no
    such hook, so the equivalent here is to rasterise the op once into a
    1-bit stencil and then lay the two inks down through it — same result,
    same absolute phase, and it works for glyphs without needing to know
    where the glyphs are.

    A solid ink draws straight onto the page, so every document that exists
    today takes exactly the path it took before and cannot shift by a pixel.

    With `dithered_colors=False` a mix is laid down once in `ink.avg`
    instead: the same single-draw path a solid ink takes, so the geometry is
    identical and only the colour differs.
    """
    if ink.solid or not dithered_colors:
        draw_fn(draw_on(img), ink.avg)
        return
    stencil = Image.new("1", img.size, 0)
    draw_fn(draw_on(stencil), 1)
    box = stencil.getbbox()
    if box is None:
        return
    sp, ip = stencil.load(), img.load()
    x0, y0, x1, y1 = box
    for yy in range(y0, y1):
        for xx in range(x0, x1):
            if sp[xx, yy]:
                ip[xx, yy] = ink.b if mix_on(xx, yy, ink.mix) else ink.a


def _check_contrast(img, ctx: Ctx, ink: Ink, fg_name: str, where: str, boxes: list[tuple]) -> None:
    """Warning: 3:1 contrast floor for text/fmt/icon against what is actually
    behind it (docs/plans/ink-mixing.md decision 4).

    The ground is sampled from the real canvas *before* this op draws, so a
    rect, a mixed fill or the page bg are all handled the same way. All five
    compiled font sizes are WCAG "large text", so one floor covers every
    size. `boxes` lets a wrapped text block check each line's own ground;
    the worst line is what gets reported. A no-op unless `ctx.warn_ink`
    (set by check(), not by a bare render() call -- see Ctx.__init__).

    A dithered glyph is legible if *either* of its two inks stands out from
    the ground — the contrasting pixels alone draw the letterform — so the
    effective contrast of a mixed ink is `max(contrast(a, ground),
    contrast(b, ground))`, not the contrast of their blend. Solid ink is
    unaffected: `max` over two identical colours is just that colour's
    contrast.

    The ground is measured the other way round, as the single colour it
    fuses to (`_grounds`). The two sides are asymmetric because the physics
    is: "a large fill averages the two; a 3 px stem has too few pixels to
    average" (decision 3). `max` on the ground as well would pass nearly
    anything — one lucky pairing out of four would carry the op — and in
    particular it would pass the one mixed-ground case the wall has judged,
    red/white 50 on pink, which is poor precisely because the letterform
    fuses to the colour the ground fuses to even though every pixel of it
    differs from the pixel beneath.
    """
    if not ctx.warn_ink:
        return
    worst = None
    for box in boxes:
        grounds = _grounds(img, box)
        if grounds is None:
            continue
        for bg, counts in grounds:
            ratio = max(_contrast_ratio(ink.a, bg), _contrast_ratio(ink.b, bg))
            if worst is None or ratio < worst[0]:
                worst = (ratio, counts)
    if worst is None:
        return
    ratio, counts = worst
    if ratio < 3.0:
        # Floored, not rounded, so a ratio just under the floor cannot print
        # as "3.0:1 (below 3:1)" — white on `grey-mid` is 2.95 and does.
        shown = int(ratio * 10) / 10
        ctx.problems.append(
            f"{where}: {fg_name} on {ctx.ground_name(counts)} is {shown:.1f}:1 "
            "(below 3:1) — will be hard to read"
        )


def _union_box(boxes: list[tuple]) -> tuple:
    """The smallest box containing every box in `boxes` — a wrapped text
    block's lines land at different y (and, centred/right-aligned, x)
    positions, so the op's own bounding box for the drew-nothing check is
    their union, not any single line's."""
    xs0, ys0, xs1, ys1 = zip(*boxes, strict=True)
    return min(xs0), min(ys0), max(xs1), max(ys1)


def _snapshot(img: Image.Image, box: tuple) -> tuple | None:
    """Crop `img` to `box` (clipped to the canvas) for a before/after diff.

    Returns `(clipped_box, pixel bytes)`, or None when the box has no
    on-canvas area — same skip rule as `_grounds`, and for the same
    reason: an off-screen op drawing nothing is not interesting.
    """
    clipped = _clip_to_canvas(box)
    if clipped is None:
        return None
    return clipped, img.crop(clipped).tobytes()


def _check_drew_nothing(img: Image.Image, ctx: Ctx, before: tuple | None, where: str) -> None:
    """Warning: the op changed not one pixel inside its own box
    (docs/plans/ink-mixing.md, "What the glass showed" / the contrast-check
    limitation this replaces).

    Contrast measures marginal legibility and cannot see absolute
    invisibility: text drawn over a ground that is a mix of the same two
    inks becomes pixel-identical to its background and vanishes completely,
    while still scoring a comfortable contrast ratio. Rather than model
    that, observe it — snapshot the op's box before drawing, draw, and diff.
    A no-op unless `ctx.warn_ink`, or when the op had no on-canvas area to
    begin with (`before` is None).
    """
    if not ctx.warn_ink or before is None:
        return
    clipped, before_bytes = before
    if img.crop(clipped).tobytes() == before_bytes:
        ctx.problems.append(
            f"{where}: drew nothing visible — every pixel in its box already "
            "matched what is behind it"
        )


def _check_mix_as_text(ctx: Ctx, ink: Ink, name: str, where: str) -> None:
    """Warning: a chromatic mix used as text shifts toward its lighter ink
    (docs/plans/ink-mixing.md decision 3).

    A fill has enough pixels to average two inks; a glyph does not, so the
    brighter ink dominates and the blend reads lighter than the swatch of
    the same mix. Achromatic (black+white) is exempt — there is no hue to
    lose, and the lightening is the point (it is what the shipping footer
    stamp already relies on). A no-op unless `ctx.warn_ink`.
    """
    if not ctx.warn_ink:
        return
    if ink.solid:
        return
    black, white = ctx.table["black"], ctx.table["white"]
    if {ink.a, ink.b} == {black, white}:
        return
    gap = abs(_luminance(ink.a) - _luminance(ink.b))
    if gap > 0.2:
        a_name, b_name = ctx.name_of(ink.a), ctx.name_of(ink.b)
        lighter = a_name if _luminance(ink.a) > _luminance(ink.b) else b_name
        ctx.problems.append(
            f"{where}: {name!r} mixes {a_name}+{b_name} (luminance gap "
            f"{gap:.2f}) — as text it will read shifted toward {lighter}, "
            "not the blend a fill of the same mix would show"
        )


_PARITY_OUTCOME = {25: "0% or 50%", 75: "50% or 100%"}


def _check_thin_mix(ctx: Ctx, ink: Ink, where: str, feature: str, **dims) -> None:
    """Warning: a feature thinner than 2 px cannot carry 25%/75%
    (docs/plans/ink-mixing.md decision 2).

    The mask is 2x2, so a one-pixel-wide run samples a single row or column
    of it and lands on 0/50/100% depending on which row or column that is —
    only 50% is parity-independent. `feature` is one of "line", "outline"
    (a rect drawn with fill: false) or "fill" (a filled rect too thin in one
    dimension); `dims` carries the measurements to report. A no-op unless
    `ctx.warn_ink`.
    """
    if not ctx.warn_ink:
        return
    if ink.solid or ink.mix not in _PARITY_OUTCOME:
        return
    outcome = _PARITY_OUTCOME[ink.mix]
    if feature in ("line", "outline"):
        t = dims["t"]
        if t >= 2:
            return
        noun = "line" if feature == "line" else "rect outline"
        ctx.problems.append(
            f"{where}: {ink.mix}% mix on a {t}px {noun} renders at {outcome}, "
            f"not {ink.mix}%, and which one depends on the op's coordinate "
            "parity"
        )
    else:
        w, h = dims["w"], dims["h"]
        if w >= 2 and h >= 2:
            return
        ctx.problems.append(
            f"{where}: {ink.mix}% mix on a {w}x{h} fill is too thin to carry "
            f"the density — renders at {outcome} depending on the op's "
            "coordinate parity"
        )


def render(
    doc: dict[str, Any],
    font_dir: Path,
    *,
    now: datetime | None = None,
    warn_ink: bool = False,
    dithered_colors: bool = True,
):
    """Return (PIL image, problems). Never raises on a bad op; it reports it.

    Everything after `font_dir` is keyword-only: docs/PLAN.md calls this
    surface final, and the three flags have grown and shuffled since, so an
    out-of-tree `render(doc, dir, True)` should fail loudly rather than
    quietly mean something new.

    `warn_ink` adds the three ink-mixing authoring warnings (contrast floor,
    chromatic mix as text, sub-2px density) to `problems`; it is off by
    default so every existing caller of render() is unaffected, and check()
    is the one caller that turns it on.

    `dithered_colors` defaults to True — the panel's own behaviour, and what
    the firmware is diffed against, so check() and the CLI get it without
    asking. False paints every mix as its `Ink.avg` instead. Only the MCP
    `preview` tool sets that, because its reader is judging a design rather
    than a framebuffer, and a 1px checkerboard aliases to a solid patch of
    one ink under any viewer that scales the PNG down.

    The two are mutually exclusive, and rejected rather than documented.
    `warn_ink` measures the canvas — _check_contrast() fuses the ground it
    samples, _check_drew_nothing() diffs raw pixels — so on a flat canvas it
    is measuring an image the panel never draws. It also feeds a blend to
    Ctx.name_of(), which can only name the six inks, so the warning comes
    out as "white on ink is 3.0:1". Forbidding the combination is what keeps
    that invariant true; take the warnings from check(), which always
    renders dithered and adds the bezel and stale-hash checks besides.
    """
    if warn_ink and not dithered_colors:
        raise ValueError("warn_ink measures the canvas, so it needs the dithered one")
    ctx = Ctx(doc, font_dir, warn_ink)
    # The panel's fill() is a framebuffer memset that never reaches
    # draw_pixel_at, so a mixed bg is one ink laid down and the other
    # interleaved over it — see decision 6.
    bg_ink = ctx.ink(doc.get("bg", "white"), "bg")
    img = Image.new("RGB", (WIDTH, HEIGHT), bg_ink.a if dithered_colors else bg_ink.avg)
    if not bg_ink.solid and dithered_colors:
        ip = img.load()
        for yy in range(HEIGHT):
            for xx in range(WIDTH):
                if mix_on(xx, yy, bg_ink.mix):
                    ip[xx, yy] = bg_ink.b
    d = draw_on(img)

    def paint_op(ink: Ink, draw_fn) -> None:
        """`paint()` with this render's canvas and colour mode already bound."""
        paint(img, ink, draw_fn, dithered_colors)

    fields = system_fields(doc, now)

    for i, op in enumerate(doc.get("ops", [])):
        where = f"ops[{i}] {op.get('op', '?')}"
        kind = op.get("op")
        ink = ctx.ink(op.get("c", "black"), where)

        if kind == "rect":
            x, y, w, h = op["x"], op["y"], op["w"], op["h"]
            if op.get("fill", True):
                _check_thin_mix(ctx, ink, where, "fill", w=w, h=h)
                paint_op(ink, lambda dr, col: dr.rectangle(
                    [x, y, x + w - 1, y + h - 1], fill=col))
            else:
                t = op.get("t", 1)
                _check_thin_mix(ctx, ink, where, "outline", t=t)
                paint_op(ink, lambda dr, col: dr.rectangle(
                    [x, y, x + w - 1, y + h - 1], outline=col, width=t))
            xr, yr = x + w, y + h
            if not (-64 <= xr <= WIDTH + 64):
                ctx.problems.append(f"{where}: x+w={xr} is off-canvas")
            if not (-64 <= yr <= HEIGHT + 64):
                ctx.problems.append(f"{where}: y+h={yr} is off-canvas")

        elif kind == "line":
            t = op.get("t", 1)
            _check_thin_mix(ctx, ink, where, "line", t=t)
            paint_op(ink, lambda dr, col: dr.line(
                [op["x"], op["y"], op["x2"], op["y2"]], fill=col, width=t))
            x2, y2 = op.get("x2"), op.get("y2")
            if isinstance(x2, (int, float)) and not (-64 <= x2 <= WIDTH + 64):
                ctx.problems.append(f"{where}: x2={x2} is off-canvas")
            if isinstance(y2, (int, float)) and not (-64 <= y2 <= HEIGHT + 64):
                ctx.problems.append(f"{where}: y2={y2} is off-canvas")

        elif kind == "circle":
            x, y, r = op["x"], op["y"], op["r"]
            box = [x - r, y - r, x + r, y + r]
            if op.get("fill", True):
                paint_op(ink, lambda dr, col: dr.ellipse(box, fill=col))
            else:
                t = op.get("t", 1)
                paint_op(ink, lambda dr, col: dr.ellipse(box, outline=col, width=t))

        elif kind == "text":
            c_name = op.get("c", "black")
            f = ctx.font(op.get("f", "md"), where)
            if f is None:
                # Matches the firmware's `skipped++; continue`: abandon the
                # op cleanly, nothing drawn, no tone/contrast checks run.
                continue
            anchor = ANCHOR.get(op.get("a", "left"), "la")
            max_w = op.get("w")
            if op.get("wrap"):
                lines = wrap_lines(f, op["s"], max_w, op.get("lines", 2))
                fname = op.get("f", "md")
                size = FONTS.get(fname, FONTS["md"])[0]
                lh = op.get("lh", round(size * 1.24))
                positions = [(op["x"], op["y"] + n * lh, line) for n, line in enumerate(lines)]
                boxes = [
                    d.textbbox((px, py), line, font=f, anchor=anchor) for px, py, line in positions
                ]
                _check_contrast(img, ctx, ink, c_name, where, boxes)
                _check_mix_as_text(ctx, ink, c_name, where)
                snap = _snapshot(img, _union_box(boxes)) if boxes else None
                for _x, ly, line in positions:
                    paint_op(ink, lambda dr, col, ly=ly, line=line: dr.text(
                        (op["x"], ly), line, font=f, fill=col, anchor=anchor))
                _check_drew_nothing(img, ctx, snap, where)
            else:
                text = fit_line(f, op["s"], max_w)
                box = d.textbbox((op["x"], op["y"]), text, font=f, anchor=anchor)
                _check_contrast(img, ctx, ink, c_name, where, [box])
                _check_mix_as_text(ctx, ink, c_name, where)
                snap = _snapshot(img, box)
                paint_op(ink, lambda dr, col: dr.text(
                    (op["x"], op["y"]), text, font=f, fill=col, anchor=anchor))
                _check_drew_nothing(img, ctx, snap, where)

        elif kind == "fmt":
            # text without wrap whose `s` is a template of system fields. The
            # values are never in the document, so meta.hash covers where and
            # how the line is drawn, never what it says.
            c_name = op.get("c", "black")
            f = ctx.font(op.get("f", "xs"), where)
            if f is None:
                # Same abandonment as `text`, and it matches the firmware:
                # the header checks the font before it ever calls
                # expand_fmt(), so an unknown-field warning never fires
                # either when the font is also bad.
                continue
            anchor = ANCHOR.get(op.get("a", "left"), "la")
            text, unknown = expand_fields(op.get("s", ""), fields)
            for field_name in unknown:
                ctx.problems.append(f"{where}: unknown field {{{field_name}}} (left literal)")
            box = d.textbbox((op["x"], op["y"]), text, font=f, anchor=anchor)
            _check_contrast(img, ctx, ink, c_name, where, [box])
            _check_mix_as_text(ctx, ink, c_name, where)
            snap = _snapshot(img, box)
            paint_op(ink, lambda dr, col: dr.text(
                (op["x"], op["y"]), text, font=f, fill=col, anchor=anchor))
            _check_drew_nothing(img, ctx, snap, where)

        elif kind == "icon":
            c_name = op.get("c", "black")
            name = op.get("n")
            z = op.get("z", "sm")
            key = f"{name}/{z}"
            if name not in ICONS or z not in ICONS[name]:
                ctx.problems.append(f"{where}: {key!r} is not compiled in")
            size = ICON_SIZES.get(z, 36)
            x, y = op["x"], op["y"]
            box = (x, y, x + size, y + size)
            _check_contrast(img, ctx, ink, c_name, where, [box])
            _check_mix_as_text(ctx, ink, c_name, where)
            snap = _snapshot(img, box)
            paint_op(ink, lambda dr, col: draw_icon(dr, name, op["x"], op["y"], size, col))
            _check_drew_nothing(img, ctx, snap, where)

        else:
            ctx.problems.append(f"{where}: unknown op {kind!r}")

        for k in ("x", "y"):
            v = op.get(k)
            bound = WIDTH if k == "x" else HEIGHT
            if isinstance(v, (int, float)) and not (-64 <= v <= bound + 64):
                ctx.problems.append(f"{where}: {k}={v} is off-canvas")

    return img, ctx.problems


def bezel_problems(doc: dict[str, Any]) -> list[str]:
    """Text, fmt and icon ops whose anchor sits inside the bezel margin.

    Only the anchor corner is judged (plus the right edge of right-aligned
    text and of icons, whose extent is known): glyph boxes carry their own
    padding, so measuring the far edge would flag the standard footer.
    """
    out: list[str] = []
    for i, op in enumerate(doc.get("ops") or []):
        kind = op.get("op")
        if kind not in ("text", "fmt", "icon"):
            continue
        x, y = op.get("x"), op.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            continue
        where = f"ops[{i}] {kind}"
        edges: list[str] = []
        right_aligned = kind != "icon" and op.get("a") == "right"
        if right_aligned:
            if x > WIDTH - BEZEL_MARGIN:
                edges.append("right")
        elif x < BEZEL_MARGIN:
            edges.append("left")
        if kind == "icon" and x + ICON_SIZES.get(op.get("z"), 0) > WIDTH - BEZEL_MARGIN:
            edges.append("right")
        if y < BEZEL_MARGIN:
            edges.append("top")
        if kind != "icon":
            size = FONTS.get(op.get("f", "md" if kind == "text" else "xs"), FONTS["md"])[0]
            if y + size > HEIGHT - BEZEL_MARGIN:
                edges.append("bottom")
        if edges:
            out.append(
                f"{where}: within {BEZEL_MARGIN} px of the {' and '.join(edges)} edge, "
                "under or shadowed by the bezel"
            )
    return out


def check(doc: dict[str, Any], font_dir: Path) -> list[str]:
    """Problems only. Same validation as render(), plus the bezel margin and hash-staleness.

    One deliberate asymmetry about meta.hash: a *missing* hash is never
    reported. Store.publish() (docs/PLAN.md) is the only thing that stamps
    it, so a draft passed to check()/validate() legitimately carries none
    yet — not worth surfacing to a library caller. A *present but stale*
    hash (a copy-pasted older document, or hand editing after `stamp`) is
    still flagged: that one means the document on disk no longer draws what
    its hash claims, which the panel would act on.
    """
    _, problems = render(doc, font_dir, warn_ink=True)
    problems = problems + bezel_problems(doc)
    stamped = (doc.get("meta") or {}).get("hash")
    if stamped:
        h = render_hash(doc)
        if stamped != h:
            problems = [f"meta.hash is stale ({stamped}) — re-run with --stamp"] + problems
    return problems
