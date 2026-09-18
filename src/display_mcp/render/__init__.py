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
    OP_FIELDS                {op: {required: [...], optional: {field: default}}}
    BUILTIN_MIXES            {name: (c, c2, mix)}; TIERS {name: "dark"/"light"/"mid"}
    render_hash(doc) -> str  sha256 of canonical {bg, palette, ops}, first 16 hex
    render(doc, font_dir, dithered_colors=True) -> (PIL.Image.Image, list[str])
    check(doc, font_dir) -> list[str]   problems only, no image
    document_colors(doc) -> (dict[str, dict], list[str])   every name's
        {recipe, hex}, plus the problems resolving them turned up; no fonts needed
    hex_of(rgb) -> str   "#RRGGBB"
    fit_line(font, s, max_w) / wrap_lines(font, s, max_w, max_lines)
    fonts_available(font_dir) -> bool
    grid_overlay(img, step=100, font=None) -> PIL.Image.Image   a coordinate
        grid drawn on a copy of `img`; never touches render()'s own output.
        `font` defaults to PIL's bitmap face; pass a real one (`load_font`)
        for labels that survive a client downscaling the PNG
    swatch_document(palette=None) -> dict   every ink and built-in mix as a
        labelled chip, an ordinary display-list document
    swatch_groups(palette=None) -> [(title, [(label, c, recipe, hex), ...])]
        the same chips, grouped, for a caller that wants the list rather
        than the picture
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

# Per-op field table: required fields, and optional fields with the default
# render() uses when they're absent. One entry per op render() knows how to
# draw; "required" is every field it reads with `op["x"]` (missing it is
# already a KeyError today), "optional" is every field it reads with
# `op.get("x", default)`. `op` itself is not listed — it's the dispatch key,
# not a datum an op draws with.
#
# This is the table check() warns against (a field on an op that isn't
# here, D1) and the one a later describe() tool returns verbatim, so the
# thing that tells a caller which fields exist and the check that enforces
# them cannot disagree. `lh`'s default of None means "computed from the
# font size (round(size * 1.24))", not literally absent.
OP_FIELDS: dict[str, dict[str, Any]] = {
    "rect": {
        "required": ("x", "y", "w", "h"),
        "optional": {"c": "black", "fill": True, "t": 1},
    },
    "line": {
        "required": ("x", "y", "x2", "y2"),
        "optional": {"c": "black", "t": 1},
    },
    "circle": {
        "required": ("x", "y", "r"),
        "optional": {"c": "black", "fill": True, "t": 1},
    },
    "text": {
        "required": ("x", "y", "s"),
        "optional": {
            "c": "black",
            "f": "md",
            "a": "left",
            "w": None,
            "wrap": False,
            "lines": 2,
            "lh": None,
        },
    },
    "fmt": {
        "required": ("x", "y"),
        "optional": {"c": "black", "f": "xs", "a": "left", "s": ""},
    },
    "icon": {
        "required": ("x", "y"),
        # `n` has no real default — an absent one already warns "'None/sm'
        # is not compiled in" — but render() reads it with `.get()`, not a
        # subscript, so it lists here rather than in `required`. `bgc` is
        # the one field listed that render() never reads: docs/SPEC.md says
        # it is accepted and ignored (every compiled icon is chroma-keyed,
        # so its off pixels are skipped), and a caller who writes it must
        # not be told it is unknown.
        "optional": {"c": "black", "n": None, "z": "sm", "bgc": None},
    },
}

# The report's whole "mixes don't render" section, in one sentence: `c2`
# and `mix` are fields of a *palette entry*, not of an op, and a `c` that
# is an object instead of a name is the same mistake written inline. Both
# get this exact message (docs/plans/dragon-feedback.md, D1).
_MIX_HINT = (
    'mixes are palette entries — write palette: {name: {c, c2, mix}} and '
    'c: name (docs/SPEC.md "Mixes")'
)


def _op_field_problems(op: dict[str, Any], kind: str | None, where: str) -> list[str]:
    """Warn on every key an op carries that isn't `op` and isn't in its
    field table (D1). Unknown ops get no field noise here — the single
    "unknown op" problem from render()'s dispatch is enough, and this
    returns [] for any kind not in OP_FIELDS.

    Each warning names the op's actual fields — required first, then
    optional, in the table's own order — e.g. "ops[0] text: no such field
    'colour' (text takes x, y, s, c, f, a, w, wrap, lines, lh)", so the
    fix is in the warning itself rather than a second trip to `describe()`.

    `c2`/`mix` are special-cased to one palette hint instead of two
    "no such field" warnings, because that's the actual authoring mistake
    the table exists to catch — and it is left to Ctx.ink() when `c` is
    itself an object, so the same op never carries the hint twice.

    `kind` comes straight from JSON and may not be a string; a dict there
    used to raise out of the table lookup, which is the failure D1 exists
    to remove.
    """
    spec = OP_FIELDS.get(kind) if isinstance(kind, str) else None
    if spec is None:
        return []
    required = list(spec["required"])
    optional = list(spec["optional"])
    known = set(required) | set(optional)
    fields = ", ".join(required + optional)
    stray_mix = {"c2", "mix"} & op.keys()
    stray = [k for k in op if k != "op" and k not in stray_mix and k not in known]
    problems = []
    if stray:
        # One line per op, however many typos it carries, so the field
        # list is said once rather than once per stray key.
        noun = "field" if len(stray) == 1 else "fields"
        names = ", ".join(repr(k) for k in stray)
        problems.append(f"{where}: no such {noun} {names} ({kind} takes {fields})")
    if stray_mix and not isinstance(op.get("c"), dict):
        problems.append(f"{where}: {_MIX_HINT}")
    return problems


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


# Which of the three docs/SPEC.md "named palette" tables each built-in mix
# is grouped under — what text reads well when the mix fills the space
# behind it, not how the mix reads as text (see SPEC.md "The named palette").
# One line per entry, grouped by tier to match the SPEC tables; `describe()`
# returns this alongside each mix's hex, and tests/test_render.py parses the
# SPEC headings themselves to pin it, so the two cannot drift apart.
TIERS: dict[str, str] = {
    "navy": "dark",
    "teal": "dark",
    "maroon": "dark",
    "plum": "dark",
    "brown": "dark",
    "forest": "dark",
    "grey-dark": "dark",
    "cream": "light",
    "cream-pale": "light",
    "sage": "light",
    "sage-pale": "light",
    "slate": "light",
    "slate-pale": "light",
    "pink": "light",
    "pink-pale": "light",
    "chartreuse": "light",
    "grey-light": "light",
    "grey-mid": "mid",
    "mustard": "mid",
    "orange": "mid",
    "olive": "mid",
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
    def __init__(
        self,
        doc: dict[str, Any],
        font_dir: Path | None = None,
        warn_ink: bool = False,
        load_fonts: bool | None = None,
    ):
        # The contract, made explicit rather than left to `Path(None)`
        # raising a bare TypeError: no `font_dir` means no fonts by
        # default (`Ctx(doc)` is a valid colour-only context), but asking
        # to load fonts with nothing to load them from is a caller error,
        # not a silent no-op.
        if load_fonts is None:
            load_fonts = font_dir is not None
        elif load_fonts and font_dir is None:
            raise ValueError("load_fonts needs a font_dir")
        palette = doc.get("palette") or {}
        self.problems: list[str] = []
        if not isinstance(palette, dict):
            # Never raise from a shape the JSON allows: a palette that is
            # not an object is ignored, with a problem, and every name then
            # resolves as if the document had none.
            self.problems.append(f"palette: must be an object, not {type(palette).__name__}")
            palette = {}
        self.palette = palette
        self.table = INK
        self.table_rev = {v: k for k, v in self.table.items()}
        # `load_fonts=False` skips the (comparatively expensive) face load
        # for callers that only resolve colours — document_colors() is the
        # one today — and never touch a font. `font_dir` is then unused and
        # may be omitted.
        self.fonts = _load_fonts(Path(font_dir)) if load_fonts else {}
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

        `name` is meant to be a string; a document that writes an inline
        `{c, c2, mix}` object where a colour *name* belongs — the report's
        actual mistake — used to raise `TypeError: unhashable type: 'dict'`
        here instead of warning, because a dict can't be looked up in
        `self.table`. Any non-string is now caught before that lookup: a
        dict gets the same palette hint `c2`/`mix`-on-an-op gets (D1), and
        anything else falls back to the ordinary "unknown colour" message.
        Either way this returns black rather than raising.
        """
        black = self.table["black"]
        if isinstance(name, dict):
            self.problems.append(f"{where}: {_MIX_HINT}")
            return Ink(black, black, 100)
        if not isinstance(name, str):
            self.problems.append(f"{where}: unknown colour {name!r}")
            return Ink(black, black, 100)
        n = name
        for _ in range(8):
            if not isinstance(n, str):
                break  # an alias that lands on a list/number: unknown, below
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
            if not isinstance(n, str):
                break
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
            if not isinstance(n, str):
                break
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


def _color_name_resolves(name: str, table: dict, palette: dict) -> bool:
    """Whether `name` reaches a base ink, a built-in mix, or a palette entry
    without raising — the same walk `Ctx.ink()` makes, kept separate so
    `document_colors()` can decide what to *list* without reading
    `Ctx.problems`, which conflates a name that resolves to nothing (the
    "unknown colour" case) with one that resolves but along the way warns
    about something else (a malformed mix still draws, and still belongs in
    the map). Mirrors the alias-chasing limit in `Ctx.ink()`."""
    n = name
    for _ in range(8):
        if not isinstance(n, str):
            return False
        if n in table:
            return True
        entry = palette.get(n)
        if entry is None:
            return n in BUILTIN_MIXES
        if isinstance(entry, dict):
            return True
        n = entry
    return False


def hex_of(rgb: tuple) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def document_colors(doc: dict[str, Any]) -> tuple[dict[str, dict[str, str]], list[str]]:
    """The effective colour of every name a document references, and the
    problems resolving them turned up along the way.

    `bg`, each op's `c` (and, `icon` ops only — `bgc` is a field of no
    other op, and writing it on one already earns its own "no such field"
    from `_op_field_problems`), and every `palette` key, each mapped to
    `{"recipe": ..., "hex": ...}` — `"ink"` for a base ink, `"<a>+<b>
    <mix>"` for a mix (built-in or from the document's own palette), and an
    alias's own recipe when a name points at one. `hex` is `Ink.avg`, the
    same colour `render(dithered_colors=False)` paints, so this cannot say
    something `preview` disagrees with.

    The second element is every problem resolution raised, `where`d
    `"palette '<name>'"` — so it reads as this function's own finding, not
    an op's — including for a palette entry nothing in `ops` ever points
    at (a malformed one `check()` has no reason to visit, since it only
    resolves names an op actually references). `validate` merges these
    into its `warnings`, deduping against what `check()` already reported
    for the same name.

    Resolution never touches fonts (`Ctx(..., load_fonts=False)`), so this
    is cheap enough to call on every `validate()`. It never raises: a
    document that isn't a dict, has no `ops` list, or has a non-dict
    `palette` simply yields fewer entries — the same tolerance `Ctx`
    already has for each of those shapes. A colour value that isn't a
    string is skipped, matching what `Ctx.ink()` does for one it meets
    while rendering. A name that doesn't resolve at all is left out of
    `colors` (same as today's "unknown colour" warning from `check()`),
    but still contributes the problem that says so.
    """
    if not isinstance(doc, dict):
        return {}, []
    ctx = Ctx(doc, load_fonts=False)

    order: dict[str, None] = {}

    def add(value: Any) -> None:
        if isinstance(value, str):
            order.setdefault(value, None)

    add(doc.get("bg", "white"))
    ops = doc.get("ops")
    if isinstance(ops, list):
        for op in ops:
            if isinstance(op, dict):
                add(op.get("c"))
                if op.get("op") == "icon":
                    add(op.get("bgc"))
    for key in ctx.palette:
        add(key)

    colors: dict[str, dict[str, str]] = {}
    for name in order:
        where = f"palette {name!r}"
        resolves = _color_name_resolves(name, ctx.table, ctx.palette)
        resolved = ctx.ink(name, where)
        if not resolves:
            continue
        colors[name] = {"recipe": _recipe_of(ctx, resolved), "hex": hex_of(resolved.avg)}
    return colors, ctx.problems


def _recipe_of(ctx: Ctx, ink: Ink) -> str:
    """`"ink"` for a base ink, `"<a>+<b> <mix>"` for a mix — the recipe half
    of `document_colors()`'s `{recipe, hex}`, factored out so
    `swatch_document()`'s appended palette group reports a name's recipe
    exactly the way `document_colors()` would."""
    if ink.solid:
        return "ink"
    return f"{ctx.name_of(ink.a)}+{ctx.name_of(ink.b)} {ink.mix}"


_SWATCH_CHIP_W = 182  # px; fits the widest recipe string ("yellow+green 50")
_SWATCH_COLS = 6


def swatch_groups(
    palette: dict[str, Any] | None = None,
) -> list[tuple[str, list[tuple[str, str, str, str]]]]:
    """The chips `swatch_document()` lays out and `swatches` (the MCP tool)
    lists as text — one source for both, so the picture and its caption
    cannot disagree.

    Returns `[(group_title, [(label, colour_field, recipe, hex), ...]), ...]`
    in the order docs/SPEC.md's "The named palette" groups them: `"inks"`,
    then the `dark`/`light`/`mid` tiers (`TIERS`). `colour_field` is what an
    op's `c` must say to draw that chip's colour in `swatch_document()`'s
    own palette — a plain ink or built-in name for the first four groups,
    always the reserved `"sw:<name>"` form for a built-in mix so a
    document's own `palette` can never shadow it (SPEC.md: a document
    redefining a built-in "shadows" it).

    With `palette` (a document's own `palette` field), a final
    `"document palette"` group is appended: each entry's recipe and hex are
    resolved exactly the way `document_colors()` resolves them (`_recipe_of`,
    the same `Ctx.ink()` walk), `colour_field` is the entry's own name, and
    an entry that doesn't resolve to anything drawable is left off rather
    than guessed at. Omitted (or empty), there is no fifth group. A palette
    key that is itself one of the reserved `"sw:<name>"` forms is also left
    off: `swatch_document()`'s `out_palette` always resolves that key to
    the built-in's own canonical mix (a collision, not a real entry), so
    listing whatever the document's *own* palette says at that name would
    show a recipe the sheet doesn't actually draw there.
    """
    groups: list[tuple[str, list[tuple[str, str, str, str]]]] = []

    groups.append(("inks", [(name, name, "ink", hex_of(INK[name])) for name in COLORS]))

    by_tier: dict[str, list[str]] = {"dark": [], "light": [], "mid": []}
    for name in BUILTIN_MIXES:
        by_tier[TIERS[name]].append(name)
    for tier in ("dark", "light", "mid"):
        entries = [
            (name, f"sw:{name}", f"{c}+{c2} {m}", hex_of(Ink(INK[c], INK[c2], m).avg))
            for name in by_tier[tier]
            for c, c2, m in [BUILTIN_MIXES[name]]
        ]
        groups.append((tier, entries))

    if palette:
        ctx = Ctx({"palette": palette}, load_fonts=False)
        entries = []
        for name in palette:
            if isinstance(name, str) and name.startswith("sw:"):
                continue
            if not _color_name_resolves(name, ctx.table, ctx.palette):
                continue
            resolved = ctx.ink(name)
            entries.append((name, name, _recipe_of(ctx, resolved), hex_of(resolved.avg)))
        if entries:
            groups.append(("document palette", entries))

    return groups


def swatch_document(palette: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every ink and every built-in mix as a labelled chip, as an ordinary
    display-list document — publish it with `set_display` and every named
    colour this renderer knows sits on the wall with its name under it
    (docs/plans/ink-mixing.md, "Still open"'s closing-coupon bullet).

    Chips come from `swatch_groups(palette)`, `_SWATCH_COLS` (6) to a row.
    A chip is a filled rect outlined by a 1px black rule drawn just outside
    it (`x-1, y-1, w+2, h+2`), so the `white` chip reads against the white
    page and every chip reads the same uniform way; the outline is a plain
    `black` stroke, never contrast- or bezel-checked the way a chip's own
    fill is. Its name, recipe and hex sit in three lines of `sm`/`xs` text
    on the white page underneath — never on the chip itself, where a light
    or mid-tone fill would trip the contrast floor `check()` enforces for
    every chip's own tier. Each line is its own plain `text` op with an
    explicit `y`, not a wrapped one: the firmware computes line height from
    the font it actually loaded, not the `round(px * 1.24)` estimate a
    wrapped op's default `lh` uses, so two lines stacked by hand here can
    never disagree with what the panel measures.

    The four built-in groups (`"inks"`, `"dark"`, `"light"`, `"mid"`) are
    fixed in size and always fit inside `HEIGHT - BEZEL_MARGIN`. A caller's
    own `palette` is not: the appended `"document palette"` group lays out
    only as many rows as still fit, and if any entries are left over, one
    final `xs` line reads `"+N more not shown"` at the row position the
    next row would have used — itself checked to fit before it is emitted.

    `out_palette` gives every reserved `"sw:<name>"` key priority over a
    same-named entry in `palette`, so a document whose own palette happens
    to define e.g. `"sw:navy"` still gets navy's canonical chip rather than
    having it silently redrawn as whatever that entry says (`swatch_groups`
    leaves that colliding entry out of the "document palette" listing for
    the same reason). Passing this document to `validate` will list those
    reserved `sw:<name>` keys in its `colors` — expected, since they are
    ordinary palette entries once this document leaves this function.
    """
    margin = 26
    chip_w, chip_h = _SWATCH_CHIP_W, 80
    gap_x = 10
    chip_gap, line_gap = 6, 2
    name_lh = round(FONTS["sm"][0] * 1.24)
    xs_lh = round(FONTS["xs"][0] * 1.24)
    row_gap = 8
    heading_lh, heading_gap = round(FONTS["xs"][0] * 1.24), 6
    # Roughly doubles the gap before a heading (row_gap, already left after
    # the previous group's last row) so it reads as belonging to the chips
    # below it rather than the group above (F9).
    heading_extra_gap = row_gap
    row_height = chip_h + chip_gap + name_lh + line_gap + xs_lh + line_gap + xs_lh + row_gap
    col_x = [margin + i * (chip_w + gap_x) for i in range(_SWATCH_COLS)]

    groups = swatch_groups(palette)

    reserved = {
        f"sw:{name}": {"c": c, "c2": c2, "mix": m} for name, (c, c2, m) in BUILTIN_MIXES.items()
    }
    out_palette: dict[str, Any] = {**(palette or {}), **reserved}

    ops: list[dict[str, Any]] = []
    y = margin

    def emit_row(row: list[tuple[str, str, str, str]], top: int) -> None:
        for (label, c_field, recipe, hexs), x in zip(row, col_x, strict=False):
            ops.append({"op": "rect", "x": x, "y": top, "w": chip_w, "h": chip_h, "c": c_field})
            ops.append(
                {
                    "op": "rect",
                    "x": x - 1,
                    "y": top - 1,
                    "w": chip_w + 2,
                    "h": chip_h + 2,
                    "c": "black",
                    "fill": False,
                    "t": 1,
                }
            )
            name_y = top + chip_h + chip_gap
            ops.append(
                {"op": "text", "x": x, "y": name_y, "s": label, "f": "sm", "c": "black",
                 "w": chip_w - 4}
            )
            recipe_y = name_y + name_lh + line_gap
            ops.append(
                {"op": "text", "x": x, "y": recipe_y, "s": recipe, "f": "xs", "c": "black",
                 "w": chip_w - 4}
            )
            hex_y = recipe_y + xs_lh + line_gap
            ops.append(
                {"op": "text", "x": x, "y": hex_y, "s": hexs, "f": "xs", "c": "black",
                 "w": chip_w - 4}
            )

    for gi, (title, entries) in enumerate(groups):
        if gi > 0:
            y += heading_extra_gap
        ops.append({"op": "text", "x": margin, "y": y, "s": title, "f": "xs", "c": "black"})
        y += heading_lh + heading_gap

        if title == "document palette":
            # The only group whose size isn't fixed (F1): lay out only the
            # rows that fit, reserving room for the "+N more" line itself
            # so it's never the thing that ends up off-canvas.
            avail = HEIGHT - BEZEL_MARGIN - y
            rows_needed = -(-len(entries) // _SWATCH_COLS)  # ceil
            if rows_needed * row_height <= avail:
                rows_fit = rows_needed
            else:
                rows_fit = max(0, (avail - xs_lh) // row_height)
            shown = entries[: rows_fit * _SWATCH_COLS]
            hidden = len(entries) - len(shown)
        else:
            shown, hidden = entries, 0

        for row_start in range(0, len(shown), _SWATCH_COLS):
            emit_row(shown[row_start : row_start + _SWATCH_COLS], y)
            y += row_height

        if hidden:
            ops.append(
                {"op": "text", "x": margin, "y": y, "s": f"+{hidden} more not shown", "f": "xs",
                 "c": "black"}
            )

    return {"v": 1, "bg": "white", "palette": out_palette, "ops": ops}


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


def _optional_number(value: Any) -> int | float | None:
    """`value` when it is a real, usable number; `None` otherwise.

    Mirrors the firmware's `o["field"] | default` for `text`'s `w`, `lh`
    and `lines`: `describe()` advertises `null` as each one's default, and
    a caller who writes that literally (or a wrong type) must get the
    default, not a `TypeError` out of `wrap_lines()`/`round()` arithmetic.
    `bool` is excluded — JSON's `true`/`false` are not the number they
    happen to subclass in Python.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _anchor_of(op: dict[str, Any], ctx: Ctx, where: str) -> str:
    """Resolve `a` to a PIL anchor code, warning (and falling back to left)
    on a value `ANCHOR` doesn't have — the firmware's `align_of()` falls
    back the same way, silently, so this keeps the fallback and adds the
    warning on the Python side only."""
    a_value = op.get("a", "left")
    if a_value not in ANCHOR:
        ctx.problems.append(f"{where}: unknown alignment {a_value!r}, using left")
    return ANCHOR.get(a_value, "la")


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
        if not isinstance(op, dict):
            # Matches the firmware, whose `for (JsonObject o : ops)` yields
            # a null object for a non-object element and draws nothing.
            ctx.problems.append(f"ops[{i}]: not an object, skipped")
            continue
        where = f"ops[{i}] {op.get('op', '?')}"
        kind = op.get("op")
        ctx.problems.extend(_op_field_problems(op, kind, where))
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
            anchor = _anchor_of(op, ctx, where)
            # `w`/`lh`/`lines` mirror the firmware's `o["field"] | default`:
            # `describe()` advertises `null` as each one's default, so a
            # `None`, wrong-typed or (for `w`) non-positive value here means
            # exactly what omitting the field means — never a crash.
            max_w = _optional_number(op.get("w"))
            if max_w is not None and max_w <= 0:
                max_w = None
            if op.get("wrap") and max_w is not None:
                lines_n = _optional_number(op.get("lines", 2))
                lines = wrap_lines(f, op["s"], max_w, int(lines_n if lines_n is not None else 2))
                fname = op.get("f", "md")
                size = FONTS.get(fname, FONTS["md"])[0]
                lh = _optional_number(op.get("lh"))
                if lh is None:
                    lh = round(size * 1.24)
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
            anchor = _anchor_of(op, ctx, where)
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
        kind = op.get("op") if isinstance(op, dict) else None
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


# Outside the six inks and every tier a mix fuses to (SPEC.md's named
# palette), so a grid line and a document's own colours can never be
# confused for one another. Chosen over the six-ink table rather than
# merely "a colour that happens not to appear today".
GRID_COLOR = (255, 0, 255)


def grid_overlay(
    img: Image.Image,
    step: int = 100,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont | None = None,
) -> Image.Image:
    """A coordinate grid drawn on a *copy* of `img`; `img` itself is untouched.

    Lines run every `step` px, heavier (2px vs 1px) every 5th line, in
    `GRID_COLOR` — a magenta that is none of the six inks and reads on both
    light and dark grounds. Each line is labelled with its coordinate along
    the canvas's top edge (x) and left edge (y); the label text sits on a
    small solid-black chip, sized to the label, so it stays legible over any
    fill underneath, the same problem `check()`'s contrast floor exists for.
    `WIDTH`/`HEIGHT` themselves are one past the last real pixel column/row,
    so the far edge is closed with an explicit, unlabelled border line at
    `w-1`/`h-1` instead — a coordinate line drawn at `w`/`h` would land
    entirely off-canvas and disappear, which is what this did before: a
    bordered canvas reads better than one whose last edge is invisible.

    `font` is normally a real face loaded through `load_font` at a size a
    caller has actually chosen to be legible once the 1200×1600 PNG is
    downscaled — PIL's `load_default()` bitmap face is a handful of pixels
    tall and disappears under any real-world scaling. Omit it (or pass
    `None`, the default) to fall back to `load_default()` anyway, so this
    function alone never needs a `font_dir` and never fails a preview when
    one isn't installed; `preview` is what supplies the real face and
    catches the load failing.

    This is meant to be called on `render()`'s *return value*, never from
    inside it: `render()`'s own output — what `test_render_emits_only_the_six_inks`
    pins and what the CLI writes — must stay exactly the six inks.
    """
    out = img.convert("RGB").copy()
    d = ImageDraw.Draw(out)
    font = font or ImageFont.load_default()
    w, h = out.size

    for x in range(0, w, step):
        d.line([(x, 0), (x, h - 1)], fill=GRID_COLOR, width=2 if x % (step * 5) == 0 else 1)
    d.line([(w - 1, 0), (w - 1, h - 1)], fill=GRID_COLOR, width=2)
    for y in range(0, h, step):
        d.line([(0, y), (w - 1, y)], fill=GRID_COLOR, width=2 if y % (step * 5) == 0 else 1)
    d.line([(0, h - 1), (w - 1, h - 1)], fill=GRID_COLOR, width=2)

    def label(text: str, x: int, y: int) -> None:
        pad = 1
        bx0, by0, bx1, by1 = d.textbbox((x, y), text, font=font)
        d.rectangle([bx0 - pad, by0 - pad, bx1 + pad, by1 + pad], fill=(0, 0, 0))
        d.text((x, y), text, font=font, fill=GRID_COLOR)

    for x in range(0, w - step + 1, step):
        label(str(x), x + 3, 2)
    for y in range(0, h - step + 1, step):
        label(str(y), 2, y + 3)

    return out
