"""Renderer: draws a display list the way firmware/display_list.h does.

Port of epaper-display/server/dlpreview.py. The C++ in the firmware is
authoritative; where they differ, this is the bug -- except for the five
deliberate fixes called out in docs/PLAN.md ("Renderer"):

1. ``weather-snowy`` is a valid, compiled-in icon (dlpreview.py was missing
   it). A procedural stand-in is drawn for it like the other weather icons.
2. Icons are validated as ``name/z`` pairs, the way the firmware keys its
   compiled icon table (``assets.icons["check/sm"]`` etc.) -- an icon whose
   size class was never compiled in is now a problem, not a silent pass.
3. The off-canvas check also covers ``x+w``/``y+h`` for rects and
   ``x2``/``y2`` for lines, with the same +/-64px tolerance already applied
   to every op's ``x``/``y``.
4. Circles are off-canvas-checked on ``x+r``/``x-r``/``y+r``/``y-r``, the
   same tolerance.
5. An op with a missing or mistyped required field is warned about and
   skipped, where the firmware's ``o["x"] | 0`` would draw it at 0 -- the
   preview refuses to show a wall the author did not ask for, and the
   warning is how they find out before the panel does.

This package is split by concern -- ``canvas.py`` (WIDTH, HEIGHT,
BEZEL_MARGIN, OFF_CANVAS_TOLERANCE: the one leaf every other module reads
canvas geometry from), ``colour.py`` (inks, mixes, Ctx, document_colors,
the ink-mixing authoring warnings), ``fonts.py`` (the Face table,
load_font, the uncompiled-glyph warning), ``shapes.py`` (rounded rect,
icon stencil, poly geometry, the device-safety limits), and
``swatches.py`` (swatch_document/swatch_groups) -- with this file left
holding ``render()``/``check()`` themselves, the op-field table, the fmt
template fields, and vocabulary(). Each submodule carries its own
docstring saying what it owns; the public surface below is unchanged by
the split and this is still the one place to import it from.

Public surface (final):
    WIDTH, HEIGHT            1200, 1600
    FONTS                    {canonical_name: Face(family, style, size, file,
                              weight, variation, italic, cell_height,
                              ink_height, extra_glyphs, layout, optional)} --
                              33 faces in B1 (instrument, instrument-bold,
                              mono, each at every SIZES entry). FONT_ALIASES
                              maps every other accepted spelling (a face's
                              own px spelling, plus the five legacy bare
                              names) to its FONTS key; resolve_font(name)
                              is the one lookup every caller uses.
                              Face.line_height is round(size * 1.24)
    GF_LATIN_CORE             frozenset[int]; the code points every compiled
                              face has, vendored in gf_latin_core.txt
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
    builtin_ink(name) -> Ink   a bare ink or built-in-mix name, no document
    recipe_of(ink) -> str   "ink" or "<a>+<b> <mix>", the one recipe formatter
    vocabulary(max_bytes) -> dict   the whole document vocabulary as one
        object; the MCP describe tool is a one-line wrapper around this
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
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .canvas import BEZEL_MARGIN, HEIGHT, WIDTH
from .colour import (
    _MIX_HINT,
    BUILTIN_MIXES,
    COLORS,
    DENSITIES,
    INK,
    TIERS,
    Ctx,
    Ink,
    _check_contrast,
    _check_drew_nothing,
    _check_mix_as_text,
    _check_thin_mix,
    _grounds,
    _snapshot,
    _union_box,
    builtin_ink,
    document_colors,
    hex_of,
    mix_on,
    recipe_of,
)
from .fonts import (
    ALIASES_BY_TARGET,
    FONT_ALIASES,
    FONT_FAMILIES,
    FONTS,
    GF_LATIN_CORE,
    GRID_FACE,
    SIZE_TO_SLOT,
    SIZES,
    SLOTS,
    Face,
    _check_uncompiled_glyphs,
    fonts_available,
    load_font,
    resolve_font,
    unknown_font_message,
)
from .shapes import (
    MAX_COORD,
    POLY_MAX_PTS,
    SPRITE_MAX_CELL,
    SPRITE_MAX_COLS,
    SPRITE_MAX_PALETTE,
    SPRITE_MAX_ROWS,
    TEXT_MAX_LEN,
    TEXT_MAX_LINES,
    THICK_MAX,
    _draw_rounded_rect,
    _off_canvas,
    _poly_spans,
    _resolved_fill,
    _resolved_rect_radius,
    _resolved_thickness,
    _thick_line_points,
    _valid_poly_points,
    draw_icon,
)
from .swatches import swatch_document, swatch_groups

# Every name this package hands out, defined here or re-exported from a
# submodule (colour.py/fonts.py/shapes.py/swatches.py): the split changes
# where each one lives, never what `display_mcp.render` itself exposes.
# Private names are included too -- tests and docs/plans/ import several
# of them directly (`_grounds`, `_draw_rounded_rect`, `_poly_spans`, ...),
# same as before the split.
__all__ = [
    "ICONS",
    "ICON_SIZES",
    "ANCHOR",
    "_NO_HASH_WARNING",
    "OP_FIELDS",
    "_MIX_HINT",
    "_op_field_problems",
    "_op_required_field_problem",
    "_op_optional_field_type_problem",
    "_coord_bound_problem",
    "vocabulary",
    "text_width",
    "fit_line",
    "wrap_lines",
    "render_hash",
    "FIELD_RE",
    "system_fields",
    "expand_fields",
    "draw_on",
    "paint",
    "_paint_glyph_op",
    "_optional_number",
    "_anchor_of",
    "_round_half_away_from_zero",
    "_deco_rule_geometry",
    "_clip_span",
    "_deco_rect",
    "_parse_deco",
    "render",
    "bezel_problems",
    "check",
    "GRID_COLOR",
    "grid_overlay",
    # canvas.py
    "WIDTH",
    "HEIGHT",
    "BEZEL_MARGIN",
    # colour.py
    "BUILTIN_MIXES",
    "COLORS",
    "DENSITIES",
    "INK",
    "TIERS",
    "Ctx",
    "Ink",
    "_check_contrast",
    "_check_drew_nothing",
    "_check_mix_as_text",
    "_check_thin_mix",
    "_grounds",
    "_snapshot",
    "_union_box",
    "builtin_ink",
    "document_colors",
    "hex_of",
    "mix_on",
    "recipe_of",
    # fonts.py
    "ALIASES_BY_TARGET",
    "FONT_ALIASES",
    "FONT_FAMILIES",
    "FONTS",
    "GF_LATIN_CORE",
    "GRID_FACE",
    "SIZE_TO_SLOT",
    "SIZES",
    "SLOTS",
    "Face",
    "_check_uncompiled_glyphs",
    "fonts_available",
    "load_font",
    "resolve_font",
    "unknown_font_message",
    # shapes.py
    "MAX_COORD",
    "POLY_MAX_PTS",
    "SPRITE_MAX_CELL",
    "SPRITE_MAX_COLS",
    "SPRITE_MAX_PALETTE",
    "SPRITE_MAX_ROWS",
    "TEXT_MAX_LEN",
    "TEXT_MAX_LINES",
    "THICK_MAX",
    "_draw_rounded_rect",
    "_off_canvas",
    "_poly_spans",
    "_resolved_fill",
    "_resolved_rect_radius",
    "_resolved_thickness",
    "_thick_line_points",
    "_valid_poly_points",
    "draw_icon",
    # swatches.py
    "swatch_document",
    "swatch_groups",
]

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


ANCHOR = {"left": "la", "center": "ma", "right": "ra"}


_NO_HASH_WARNING = (
    "no meta.hash — the panel will refresh on EVERY wake "
    "(~36 mAh/day, roughly half its battery life). Run display-mcp-cli stamp."
)


OP_FIELDS: dict[str, dict[str, Any]] = {
    "rect": {
        "required": ("x", "y", "w", "h"),
        "optional": {"c": "black", "fill": True, "t": 1, "r": 0},
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
            # docs/plans/fonts-and-icons.md Decision 5, landed as B5: `text`
            # only, never `fmt` -- `fmt` doesn't wrap and has no per-line
            # geometry to hang a rule off of, so a `deco` on it stays an
            # ordinary "no such field" warning from `_op_field_problems()`
            # (fmt's own OP_FIELDS entry doesn't list it either). Deliberately
            # absent from `_OPTIONAL_STRING_FIELDS` below: a bad `deco` warns
            # and draws the text undecorated, it never abandons the op the
            # way a bad `f`/`a` does, so it gets its own check inside the
            # `text` branch instead.
            "deco": None,
        },
    },
    "fmt": {
        "required": ("x", "y"),
        # `s` carries no default -- `None` here, like `text`'s `w`/`lh` --
        # but unlike those it is required *in practice*: an empty or
        # missing template has nothing to draw and is its own warning
        # (see the `fmt` branch below), not a silent no-op. It stays out
        # of `required` itself so that warning can name the real problem
        # rather than the generic "missing field" one every other required
        # field gets.
        "optional": {"c": "black", "f": "xs", "a": "left", "s": None},
    },
    "icon": {
        # `n` is required: `_op_required_field_problem()` catches a missing
        # or non-string `n` before dispatch, the same abandonment a missing
        # `s` on `text` gets. `bgc` is the one field listed that
        # render() never reads: docs/SPEC.md says it is accepted and
        # ignored (every compiled icon is chroma-keyed, so its off pixels
        # are skipped), and a caller who writes it must not be told it is
        # unknown.
        "required": ("x", "y", "n"),
        "optional": {"c": "black", "z": "sm", "bgc": None},
    },
    "sprite": {
        # `c` is deliberately absent: colour comes from `palette`, one
        # entry per distinct character, each resolved exactly the way any
        # other op's `c` is (docs/plans/dragon-feedback.md D9). Writing
        # `c` on a sprite is therefore an ordinary "no such field", the
        # same message any other stray key on any op gets.
        "required": ("x", "y", "cell", "rows", "palette"),
        "optional": {"mirror": None},
    },
    "poly": {
        # No `x`/`y` — a poly has no single anchor, only `pts`
        # (docs/plans/dragon-feedback.md D12). `t` is read but only used
        # for the outline (`fill: false`); listing it unconditionally
        # keeps this table the one place fields are enumerated, the way
        # `sprite`'s `mirror` is listed even though only one of its values
        # does anything.
        "required": ("pts",),
        "optional": {"c": "black", "fill": True, "t": 1},
    },
}


def _op_field_problems(op: dict[str, Any], kind: str | None, where: str) -> list[str]:
    """Warn on every key an op carries that isn't `op` and isn't in its
    field table (D1). Unknown ops get no field noise here — the single
    "unknown op" problem from render()'s dispatch is enough, and this
    returns [] for any kind not in OP_FIELDS.

    Each warning names the op's actual fields — required first, then
    optional, in the table's own order — e.g. "ops[0] text: no such field
    'colour' (text takes x, y, s, c, f, a, w, wrap, lines, lh, deco)", so the
    fix is in the warning itself rather than a second trip to `describe()`.

    `c2`/`mix` are special-cased to one palette hint instead of two
    "no such field" warnings, because that's the actual authoring mistake
    the table exists to catch — and it is left to Ctx.ink() when `c` is
    itself an object, so the same op never carries the hint twice.

    `kind` comes straight from JSON and may not be a string, so the table
    lookup only happens for a `str`; any other type returns `[]` rather
    than raising out of `OP_FIELDS.get`.
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


# The JSON type each required field must have to be usable at all, checked
# by `_op_required_field_problem()` before dispatch. Not every field an op
# can carry is listed — only the ones some op's `required` tuple names —
# and a field's presence here says nothing about which op(s) require it;
# OP_FIELDS is still the one table naming that. `t` is never in any op's
# `required` tuple, so it has no entry here -- `_resolved_thickness()` is
# its own, optional-field check, with a clamp rather than a skip.
_REQUIRED_NUMERIC_FIELDS = {"x", "y", "w", "h", "r", "x2", "y2", "cell"}
_REQUIRED_STRING_FIELDS = {"s", "n"}
_REQUIRED_LIST_FIELDS = {"rows", "pts"}
_REQUIRED_DICT_FIELDS = {"palette"}


def _op_required_field_problem(op: dict[str, Any], kind: str | None, where: str) -> str | None:
    """The one warning that abandons an op outright: a field in
    `OP_FIELDS[kind]["required"]` missing, or present with the wrong JSON
    type. Checked before dispatch, so render() never reads `op["x"]` (or a
    `.get()`d field it then assumes is usable) on an op that cannot supply
    what its own kind demands. The firmware's `o["x"] | 0` would draw at 0
    for a missing field — a silent wrong wall, not a loud one — and D1's
    rule for a thing that cannot draw as asked is warn and skip, the same
    abandonment an unknown font or icon already gets.

    Numeric fields (`x y w h r x2 y2 cell t`) must be an `int`/`float` and
    not a `bool` (JSON's `true`/`false` are not the number they happen to
    subclass in Python); string fields (`s`, `n`) an actual `str`; `rows`/
    `pts` a `list`; `palette` a `dict`. Only the *first* bad field is
    reported, in the table's own order, naming every required field the op
    takes so the fix is in the warning itself rather than a second trip to
    `describe()`.

    `sprite`/`poly`'s own, more specific required-field checks (an integer
    `cell` in range, three or more well-formed `pts`, ...) still run after
    this one, but only ever see a document that already passed this
    generic pass — a `sprite` missing `cell` entirely gets this message
    alone, not both.

    Returns `None` for an op this check doesn't apply to — an unknown
    `kind`, or one whose required fields are all present and well-typed —
    not a promise that the op will draw cleanly; `_op_field_problems()` and
    each op's own dispatch code still have their own checks to run.
    """
    spec = OP_FIELDS.get(kind) if isinstance(kind, str) else None
    if spec is None:
        return None
    required = list(spec["required"])
    needs = ", ".join(required)
    for field in required:
        if field not in op:
            return f"{where}: missing field {field!r} ({kind} needs {needs}); skipped"
        value = op[field]
        if field in _REQUIRED_NUMERIC_FIELDS:
            ok, noun = not isinstance(value, bool) and isinstance(value, (int, float)), "a number"
        elif field in _REQUIRED_STRING_FIELDS:
            ok, noun = isinstance(value, str), "a string"
        elif field in _REQUIRED_LIST_FIELDS:
            ok, noun = isinstance(value, list), "a list"
        elif field in _REQUIRED_DICT_FIELDS:
            ok, noun = isinstance(value, dict), "an object"
        else:  # pragma: no cover - every required field today is one of the above
            ok, noun = True, ""
        if not ok:
            return f"{where}: {field}={value!r} is not {noun} ({kind} needs {needs}); skipped"
    return None


# `f`/`a`/`z` are optional, but a value of the wrong JSON type there doesn't
# fail softly the way an unknown *value* does -- an unknown font name,
# alignment or icon size class each warn and either fall back or abandon the
# op through their own lookup. The lookup itself is what breaks first: `f`
# and `z` end up as a dict/set key (`ctx.fonts`, `ICONS[name]`/`ICON_SIZES`)
# and `a` as a dict-membership test (`ANCHOR`), and an unhashable value (a
# `list` or `dict`) raises `TypeError` out of `in`/`.get()` before any of
# those checks run. `n` needs no entry here — it is already a *required*
# field, covered above; sprite's `mirror` compares with `==`, never `in`, so
# it never hits this either.
_OPTIONAL_STRING_FIELDS = {"f", "a", "z"}


def _op_optional_field_type_problem(op: dict[str, Any], kind: str | None, where: str) -> str | None:
    """A present-but-wrong-typed `f`/`a`/`z` (`_OPTIONAL_STRING_FIELDS`):
    warn and abandon the op, the same way a missing or mistyped *required*
    field does. There's no "needs" clause here — the op still carries
    everything render() strictly requires, only this one optional field
    can't be used as given — so the message is plainer than
    `_op_required_field_problem()`'s.

    Only checked when `OP_FIELDS[kind]["optional"]` actually lists the
    field: an op that doesn't take `z` at all still gets its ordinary "no
    such field" warning from `_op_field_problems()`, not this one. Fields
    are checked in the op's own table order, so a `text` with both `f` and
    `a` wrong always reports `f` first.
    """
    spec = OP_FIELDS.get(kind) if isinstance(kind, str) else None
    if spec is None:
        return None
    for field in spec["optional"]:
        if field not in _OPTIONAL_STRING_FIELDS or field not in op:
            continue
        value = op[field]
        if not isinstance(value, str):
            return f"{where}: {field}={value!r} is not a string; skipped"
    return None


# The extra fields, beyond x/y, each op's own coordinate bound covers
# (docs/plans/firmware-bounds.md D4) -- rect's w/h, line's x2/y2, circle's
# r. poly has no x/y of its own and is judged by its own point-wise bound
# in its own branch instead, so it is absent here rather than mapped to [].
_COORD_BOUND_EXTRA_FIELDS = {"rect": ("w", "h"), "line": ("x2", "y2"), "circle": ("r",)}


def _coord_bound_problem(op: dict[str, Any], kind: str | None, where: str) -> str | None:
    """D4: `|v| <= MAX_COORD` for every coordinate and size field of every
    op -- mirrors the firmware's blanket check at the top of its op loop,
    which is what keeps a single op's drawing cost bounded regardless of
    what the rest of this file's per-op checks allow through.

    By the time this runs, `_op_required_field_problem()` has already
    guaranteed every field checked here is a real number for any op that
    requires it (x/y on every op but poly; w/h, x2/y2, r on rect/line/circle
    respectively) -- the `isinstance` guard below only matters for a field
    an op does not itself require (rect/line/circle's `x`/`y`, still
    required, are covered either way), mirroring ArduinoJson's `o[field] |
    0` for a present-but-wrong-typed one.

    `poly` has no `x`/`y` field of its own; returning `None` for it here
    leaves it to its own point-wise bound (the `poly` branch), the same
    division of labour the firmware has between this blanket check and
    draw_poly()'s own. `kind` comes straight from JSON and may not even be
    a string (let alone a known op) -- unhashable there is exactly the
    case `_op_field_problems()` already guards the same way.
    """
    if not isinstance(kind, str) or kind == "poly":
        return None
    for field in ("x", "y") + _COORD_BOUND_EXTRA_FIELDS.get(kind, ()):
        value = op.get(field, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            value = 0
        if abs(value) > MAX_COORD:
            # Text matches display_list.h's own ESP_LOGW wording verbatim
            # (modulo the "{where}: " prefix every message here carries) --
            # the repo convention every other shared warning already
            # follows (see poly's "out of range" message). `_g()`, not
            # `!r`: the firmware prints this value with `%g`.
            return f"{where}: {field}={_g(value)} out of range (|v| <= {MAX_COORD}); skipped"
    return None


def _int_coord(value: Any) -> int:
    """Truncate a coordinate/size field toward zero -- the Python mirror of
    the firmware's `static_cast<int>(double)` (docs/plans/firmware-bounds.md
    D4's review amendment): ArduinoJson's `o["x"] | 0` silently reads 0 for
    ANY float rather than truncating it, so the firmware now reads every
    such field as a `double`, bound-checks that, and only then casts to
    `int` -- `_coord_bound_problem()` above is this file's version of the
    bound check, run on the same untouched value; this is the cast that
    runs after it passes, so a legal fractional coordinate (`"x": 100.5`)
    lands on the same pixel column on both sides instead of Python handing
    it to Pillow as-is and the firmware never seeing anything but a whole
    number to begin with. `int()` on a `float` already truncates toward
    zero in Python, matching C++ -- unlike `math.floor()`, the two only
    disagree on a negative fraction (`-1.5` truncates to `-1`, floors to
    `-2`)."""
    return int(value)


def _g(value: int | float) -> str:
    """Format a bounded value the way the firmware's `ESP_LOGW(..., "%g",
    ...)` does, not Python's own `repr()` (docs/plans/firmware-bounds.md's
    review amendment): `%g` and Python's `'g'` format spec agree exactly
    for these magnitudes (`1e10` -> `"1e+10"`, `123456.789` -> `"123457"`),
    but `repr()` doesn't (`"10000000000.0"`, `"123456.789"`) -- every
    message here that names a document-supplied bounded value uses this,
    not an f-string's default `!r`, so the two sides print the identical
    warning text. `float()` first: `'g'` is a floating-point presentation
    type and raises on a plain `int`."""
    return format(float(value), "g")


# The two legal `text.deco` values (docs/plans/fonts-and-icons.md Decision 5,
# landed as B5). `fmt` doesn't take the field at all -- see OP_FIELDS.
_DECO_VALUES = ("underline", "strike")


def _round_half_away_from_zero(x: float) -> int:
    """`round()` half away from zero, matching C++'s `std::round()` --
    Python's builtin `round()` is banker's rounding (round-half-to-even) and
    disagrees with `std::round()` at an exact `.5` (docs/plans/
    fonts-and-icons.md Decision 5, sharpened by B5). No compiled face
    currently lands `t`/either vertical offset exactly on a `.5` -- checked
    against every face's real `f.font.height` (B5's review fix corrected an
    earlier claim here that `sm` did, which used `ascent + descent` instead
    of `f.font.height` and was therefore counting a size the firmware never
    computes) -- but the two roundings still have to agree in general, not
    only for today's ladder, so `deco`'s three geometry numbers (`t` and the
    two vertical offsets) all use this on both sides. It's
    `tests/parity/test_text_deco.py`'s brute-force sweep, which does include
    synthetic heights sitting exactly on the tie, that actually proves the
    two sides agree -- not any real compiled face. Every value these
    formulas produce today is non-negative, but this mirrors
    `std::round()`'s sign handling anyway rather than assume that forever."""
    return math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)


def _deco_rule_geometry(h: int, baseline: int, ly: int, underline: bool) -> tuple[int, int]:
    """`(top, t)` for one `deco` rule -- the Python mirror of the firmware's
    `deco_rule_geometry()` (docs/plans/fonts-and-icons.md Decision 5, B5):
    `t` is never 1px (a 1px rule can't hold a mixed ink), underline sits
    just below the baseline, strike just above it, both scaled off the
    font's own height, never the particular line's ink extent -- see
    `_round_half_away_from_zero()` for why both sides round the same way."""
    t = max(2, _round_half_away_from_zero(h / 14))
    if underline:
        top = ly + baseline + max(2, _round_half_away_from_zero(h * 0.06))
    else:
        top = ly + baseline - _round_half_away_from_zero(h * 0.30) - t // 2
    return top, t


def _clip_span(pos: int, size: int, bound: int) -> tuple[int, int]:
    """Mirror of the firmware's `clip_span()` (docs/plans/firmware-bounds.md
    D5): clip `[pos, pos + size)` to `[0, bound)`. `size` comes back `<= 0`
    when the span misses `[0, bound)` entirely, which the caller treats as
    "draw nothing on this axis" -- same contract as the C++."""
    if pos < 0:
        size += pos
        pos = 0
    if pos + size > bound:
        size = bound - pos
    return pos, size


def _deco_rect(
    deco: str, lx1: int, lw: int, ly: int, h: int, baseline: int
) -> tuple[int, int, int, int] | None:
    """The clipped `[x0, y0, x1, y1)` box (PIL's own half-open convention,
    matching `ImageDraw.textbbox()`) for one line's `deco` rule, or `None`
    when there's no ink to underline/strike or the clipped box is empty.
    `lx1`/`lw` are that line's already-measured inked left edge and width
    (the same `textbbox()` the op already computed for alignment) --
    `get_text_bounds()`'s role in the firmware mirror. Clipped to the
    canvas the way `clipped_filled_rectangle()` clips every fill (D5): the
    rule is derived geometry, not something a document directly aims off
    the edge the way a rect's `w`/`h` can be, so this silently bounds it
    rather than adding a second off-canvas warning next to the op's own."""
    if lw <= 0:
        return None
    top, t = _deco_rule_geometry(h, baseline, ly, deco == "underline")
    x0, w = _clip_span(lx1, lw, WIDTH)
    y0, hh = _clip_span(top, t, HEIGHT)
    if w <= 0 or hh <= 0:
        return None
    return (x0, y0, x0 + w, y0 + hh)


def _parse_deco(value: Any, where: str, ctx: Ctx) -> str | None:
    """Resolve `text`'s `deco` field: `"underline"`/`"strike"`, or `None`
    for absent/`null`. Any other value -- wrong type or an unrecognised
    string -- warns naming the value and the two legal ones and returns
    `None` so the text still draws, undecorated (docs/plans/
    fonts-and-icons.md Decision 5, landed as B5): unlike `f`/`a`, a bad
    `deco` is never reason to abandon the whole op, which is why this lives
    here rather than in `_op_optional_field_type_problem()` (that one does
    abandon the op for a bad `f`/`a`).

    A bad *string* is named with `!r` (`deco='bold'`), matching the
    firmware's `'%s'` exactly. A non-string value is named with
    `json.dumps()`, not `!r` (B5 review fix): the firmware names it with
    `serializeJson()`, which spells a JSON bool `true`/`false`, not
    Python's `True`/`False` -- the same "match the other side's spelling,
    not repr()" discipline `_g()` already applies to a bounded numeric
    field's `%g`. `None` never reaches here (handled above, silently)."""
    if value is None:
        return None
    if isinstance(value, str):
        if value in _DECO_VALUES:
            return value
        shown = repr(value)
    else:
        shown = json.dumps(value)
    ctx.problems.append(
        f"{where}: deco={shown} is not 'underline' or 'strike'; drawing undecorated"
    )
    return None


def vocabulary(max_bytes: int) -> dict[str, Any]:
    """The whole document vocabulary as one JSON-safe object: canvas size,
    the six inks and the built-in mixes with their hexes and tiers, the
    compiled fonts, the anchor values `text.a`/`fmt.a` accept, the icons
    and their size classes, the per-op field table, the `fmt` template
    fields, and the document byte ceiling. Built from this module's own
    tables at call time, so it can never say something `render()` doesn't
    do — the MCP `describe` tool is a one-line wrapper around this, the
    way `guide()` is a one-line wrapper around `compose.md`'s text.

    `max_bytes` is `store.MAX_DOC_BYTES`, passed in rather than imported:
    this module has no reason to know about the store, and `limits` is the
    one field nothing above it can derive from the renderer's own tables.

    `fonts` is keyed by canonical name (docs/plans/fonts-and-icons.md
    Decision 1: `family[-style]/size`, the slot spelling when `size` is one
    of the five slots, the pixel spelling otherwise). Each entry carries
    `px`, `slot` (the slot name, or `null` for a non-slot size), `aliases`
    (every other accepted spelling — a face's own pixel spelling plus,
    for the five Instrument Sans faces the old bare names always meant,
    the bare name itself), `family`, `style` (`""`/`"bold"`/`"italic"`),
    `line_height` (`Face.line_height`, what wrapped `text` uses when `lh`
    is unset), `cell_height` (ascent + descent of the loaded face — every
    face has one) and `ink_height` (how many rows a full-height glyph
    actually inks at 1bpp — the row pitch that makes block glyphs meet
    with no seam; `null` except for `mono`'s sizes — docs/plans/
    dragon-feedback.md D11). `resolve_font()` is the one place a
    document's own font name is turned into one of these keys.

    `font_families` is the constants that don't vary by size, keyed by
    family-style (`fonts[*].family`, plus `-style` for a non-regular one —
    the same key `fonts[*]` would join back to): `typeface` (the human
    name, e.g. "Instrument Sans"), `weight`, `italic` and `glyphs` (a short
    string naming the compiled glyph set — `"GF_Latin_Core"` for every
    family but `mono`, which adds box drawing and block elements:
    `"GF_Latin_Core + U+2500–U+259F"`; a character outside that set
    previews fine and has no glyph on the wall, which `check()` warns
    about). Split out from `fonts[*]` itself (B1 review, item 6) because
    every one of a family-style's eleven sizes repeated the identical
    `glyphs`/`weight`/`italic` — with 110 faces on the way, that repetition
    only gets more expensive. `variation` (the variable-font instance
    `load_font()` selects) is deliberately not published anywhere here:
    it's a Pillow loading detail with no meaning to a composer, who names
    fonts and sizes, never instances.

    In `ops`, an optional field whose default is `null` has no fixed
    default and may simply be omitted — `lh` is computed from the font
    size, `w` means no width limit, `sprite`'s `mirror` means no mirroring
    (its only other legal value is `"x"`), and `icon`'s `bgc` is accepted
    and ignored outright (every compiled icon is chroma-keyed, so its off
    pixels are skipped no matter what `bgc` says). `fmt`'s `s` is `null`
    too, but not for the same reason as the rest: it is required *in
    practice* — an empty or missing template has nothing to draw and is a
    `check()`/`validate()` warning, not a silent no-op.
    """
    mixes = {
        name: {
            "c": c,
            "c2": c2,
            "mix": mix,
            "hex": hex_of(builtin_ink(name).avg),
            "tier": TIERS[name],
        }
        for name, (c, c2, mix) in BUILTIN_MIXES.items()
    }
    fonts = {
        name: {
            "px": face.size,
            "slot": SIZE_TO_SLOT.get(face.size),
            "aliases": ALIASES_BY_TARGET.get(name, []),
            "family": face.family,
            "style": face.style,
            "line_height": face.line_height,
            "cell_height": face.cell_height,
            "ink_height": face.ink_height,
        }
        for name, face in FONTS.items()
    }
    ops = {
        op: {"required": list(spec["required"]), "optional": dict(spec["optional"])}
        for op, spec in OP_FIELDS.items()
    }
    # Only the size classes some compiled icon actually has — `md: 56` is
    # in ICON_SIZES for arithmetic elsewhere but has no icon behind it, and
    # advertising it here would invite `{"n": "check", "z": "md"}`, which
    # `check()` then has to reject as "not compiled in".
    used_sizes = {z for sizes in ICONS.values() for z in sizes}
    icon_sizes = {z: px for z, px in ICON_SIZES.items() if z in used_sizes}
    return {
        "canvas": {"w": WIDTH, "h": HEIGHT, "bezel_margin": BEZEL_MARGIN},
        "inks": {name: hex_of(rgb) for name, rgb in INK.items()},
        "mixes": mixes,
        "densities": list(DENSITIES),
        "fonts": fonts,
        "font_families": {key: dict(entry) for key, entry in FONT_FAMILIES.items()},
        "anchors": list(ANCHOR),
        "icons": {name: sorted(sizes) for name, sizes in ICONS.items()},
        "icon_sizes": icon_sizes,
        "ops": ops,
        "fmt_fields": list(system_fields({}).keys()),
        "limits": {"max_bytes": max_bytes},
    }


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


def _paint_glyph_op(
    img: Image.Image,
    ctx: Ctx,
    ink: Ink,
    c_name: str,
    where: str,
    boxes: list[tuple],
    draw_fn,
    dithered_colors: bool,
    after_mix_check=None,
) -> None:
    """The sequence every glyph-drawing op (wrapped text, plain text, fmt,
    icon) repeats: the contrast floor against what's actually behind it,
    the mix-as-text shift warning, a before-snapshot, the paint itself,
    and the drew-nothing diff against that snapshot. `boxes` is the op's
    box(es), for both the contrast sampling and (as their union) the
    drew-nothing snapshot — every caller but wrapped text passes a
    single-element list; wrapped text passes one box per line.

    `after_mix_check`, if given, runs between the mix-as-text warning and
    the snapshot, so warning order is unchanged; `icon` (no glyphs to
    check) omits it. `dithered_colors` is threaded through to `paint()`
    directly rather than through `render()`'s own `paint_op` closure,
    since this is a module-level function and can't see that closure.
    """
    _check_contrast(img, ctx, ink, c_name, where, boxes)
    _check_mix_as_text(ctx, ink, c_name, where)
    if after_mix_check is not None:
        after_mix_check()
    snap = _snapshot(img, _union_box(boxes)) if boxes else None
    paint(img, ink, draw_fn, dithered_colors)
    _check_drew_nothing(img, ctx, snap, where)


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
        required_problem = _op_required_field_problem(op, kind, where)
        if required_problem is not None:
            ctx.problems.append(required_problem)
            continue
        optional_problem = _op_optional_field_type_problem(op, kind, where)
        if optional_problem is not None:
            ctx.problems.append(optional_problem)
            continue
        coord_problem = _coord_bound_problem(op, kind, where)
        if coord_problem is not None:
            ctx.problems.append(coord_problem)
            continue
        ink = ctx.ink(op.get("c", "black"), where)

        try:
            # A last line of defence, after the specific checks above and
            # each branch's own: any shape this file's authors didn't
            # anticipate (docs/plans/dragon-feedback.md D1) must still warn
            # and move on, never take the whole render() down with it.
            if kind == "rect":
                x, y, w, h = (
                    _int_coord(op["x"]),
                    _int_coord(op["y"]),
                    _int_coord(op["w"]),
                    _int_coord(op["h"]),
                )
                if w <= 0 or h <= 0:
                    field, value = ("w", w) if w <= 0 else ("h", h)
                    ctx.problems.append(f"{where}: {field}={value!r} must be positive; skipped")
                    continue
                if _resolved_fill(op, where, ctx):
                    _check_thin_mix(ctx, ink, where, "fill", w=w, h=h)
                    r = _resolved_rect_radius(op.get("r", 0), w, h, where, ctx)
                    if r > 0:
                        paint_op(ink, lambda dr, col, x=x, y=y, w=w, h=h, r=r: _draw_rounded_rect(
                            dr, x, y, w, h, r, col))
                    else:
                        paint_op(ink, lambda dr, col: dr.rectangle(
                            [x, y, x + w - 1, y + h - 1], fill=col))
                else:
                    if op.get("r", 0):
                        ctx.problems.append(
                            f"{where}: r is ignored on an outline; drawing square corners"
                        )
                    t = _resolved_thickness(op.get("t", 1), where, ctx)
                    _check_thin_mix(ctx, ink, where, "outline", t=t)
                    paint_op(ink, lambda dr, col: dr.rectangle(
                        [x, y, x + w - 1, y + h - 1], outline=col, width=t))
                xr, yr = x + w, y + h
                if _off_canvas(xr, WIDTH):
                    ctx.problems.append(f"{where}: x+w={xr} is off-canvas")
                if _off_canvas(yr, HEIGHT):
                    ctx.problems.append(f"{where}: y+h={yr} is off-canvas")

            elif kind == "line":
                x, y = _int_coord(op["x"]), _int_coord(op["y"])
                x2, y2 = _int_coord(op["x2"]), _int_coord(op["y2"])
                t = _resolved_thickness(op.get("t", 1), where, ctx)
                _check_thin_mix(ctx, ink, where, "line", t=t)
                paint_op(ink, lambda dr, col: dr.line([x, y, x2, y2], fill=col, width=t))
                if _off_canvas(x2, WIDTH):
                    ctx.problems.append(f"{where}: x2={x2} is off-canvas")
                if _off_canvas(y2, HEIGHT):
                    ctx.problems.append(f"{where}: y2={y2} is off-canvas")

            elif kind == "circle":
                x, y, r = _int_coord(op["x"]), _int_coord(op["y"]), _int_coord(op["r"])
                box = [x - r, y - r, x + r, y + r]
                if _resolved_fill(op, where, ctx):
                    paint_op(ink, lambda dr, col: dr.ellipse(box, fill=col))
                else:
                    t = _resolved_thickness(op.get("t", 1), where, ctx)
                    paint_op(ink, lambda dr, col: dr.ellipse(box, outline=col, width=t))
                for label, v, bound in (
                    ("x+r", x + r, WIDTH),
                    ("x-r", x - r, WIDTH),
                    ("y+r", y + r, HEIGHT),
                    ("y-r", y - r, HEIGHT),
                ):
                    if _off_canvas(v, bound):
                        ctx.problems.append(f"{where}: {label}={v} is off-canvas")

            elif kind == "text":
                c_name = op.get("c", "black")
                font_name = op.get("f", "md")
                f = ctx.font(font_name, where)
                if f is None:
                    # Matches the firmware's `skipped++; continue`: abandon the
                    # op cleanly, nothing drawn, no tone/contrast checks run.
                    continue
                # docs/plans/firmware-bounds.md D6: past this length, whole
                # op skips rather than paying fit_line()'s/wrap()'s quadratic
                # cost (~7ms and a ~6KB word vector at the bound). Measured
                # in bytes, matching the firmware's std::string::size().
                s_bytes = len(op["s"].encode("utf-8"))
                if s_bytes > TEXT_MAX_LEN:
                    ctx.problems.append(
                        f"{where}: s is {s_bytes} bytes, more than {TEXT_MAX_LEN}; skipped"
                    )
                    continue
                x, y = _int_coord(op["x"]), _int_coord(op["y"])
                anchor = _anchor_of(op, ctx, where)
                # docs/plans/fonts-and-icons.md Decision 5, landed as B5:
                # parsed once per op, not per line, so every wrapped line of
                # the same op gets an identical rule. `h`/`baseline` are the
                # FACE's own metrics (one number per font, like Face.line_height
                # already is), not this particular string's ink extent -- the
                # firmware mirror is font_height()/font_baseline()'s "Ag"
                # measurement. Only measured when a rule will actually be
                # drawn.
                #
                # `h` is `f.font.height` (Pillow's own FreeType line height),
                # NOT `ascent + descent` (B5 review fix): the firmware's
                # font_height() returns ESPHome's compiled `height_`, which
                # `font/__init__.py` sets from FreeType's line-height metric --
                # 1px under `ascent + descent` on some faces (xs, sm, xl,
                # mono) and equal to it on others (md, lg), so there is no
                # single "+1"/"-1" correction that works for every face; only
                # `f.font.height` itself agrees with the panel on all of them.
                # `baseline` stays `getmetrics()[0]` (the ascent) -- that one
                # already agreed with the firmware's `font_baseline()` on
                # every compiled face.
                deco = _parse_deco(op.get("deco"), where, ctx)
                if deco is not None:
                    deco_baseline = f.getmetrics()[0]
                    deco_h = f.font.height
                # `w`/`lh`/`lines` mirror the firmware's `o["field"] | default`:
                # `describe()` advertises `null` as each one's default, so a
                # `None`, wrong-typed or (for `w`) non-positive value here means
                # exactly what omitting the field means — never a crash.
                max_w = _optional_number(op.get("w"))
                if max_w is not None and max_w <= 0:
                    max_w = None
                if op.get("wrap") and max_w is not None:
                    lines_n = _optional_number(op.get("lines", 2))
                    n_lines = int(lines_n) if lines_n is not None else 2
                    if n_lines < 1:
                        # wrap_lines() indexes lines[-1] once it has filled
                        # max_lines; 0 (or negative) leaves it empty and that
                        # indexing raises. A document that means "no lines"
                        # means "draw nothing", not a crash -- treated the
                        # same as the firmware's own unsigned `lines` field,
                        # which can't represent negative or zero either.
                        ctx.problems.append(
                            f"{where}: lines={lines_n!r} must be >= 1; using 1"
                        )
                        n_lines = 1
                    elif n_lines > TEXT_MAX_LINES:
                        # Clamped, not skipped -- the same warn-and-clamp
                        # THICK_MAX gives `t` (docs/plans/firmware-bounds.md
                        # D6), since a too-large `lines` is bounded by
                        # trimming it, not by abandoning the whole op.
                        ctx.problems.append(
                            f"{where}: lines={n_lines} is larger than "
                            f"{TEXT_MAX_LINES}; clamped to {TEXT_MAX_LINES}"
                        )
                        n_lines = TEXT_MAX_LINES
                    lines = wrap_lines(f, op["s"], max_w, n_lines)
                    lh = _optional_number(op.get("lh"))
                    if lh is None:
                        # font_name is guaranteed to resolve here -- ctx.font()
                        # above already abandoned the op (`continue`d) if it
                        # didn't -- so resolve_font() only ever re-derives the
                        # canonical name it already used to load `f`.
                        lh = FONTS[resolve_font(font_name)].line_height
                    # lh joins the bound too (docs/plans/firmware-bounds.md
                    # D4/D6 review amendment): with `lines` up to
                    # TEXT_MAX_LINES, `y + n * lh` below is exactly the
                    # size-field arithmetic D4 already covers for every
                    # other op -- an lh of, say, 2e9 would put positions
                    # far outside anything sane long before Pillow ever
                    # saw them.
                    if abs(lh) > MAX_COORD:
                        ctx.problems.append(
                            f"{where}: lh={_g(lh)} out of range (|v| <= {MAX_COORD}); skipped"
                        )
                        continue
                    lh = _int_coord(lh)
                    positions = [(x, y + n * lh, line) for n, line in enumerate(lines)]
                    boxes = [
                        d.textbbox((px, py), line, font=f, anchor=anchor)
                        for px, py, line in positions
                    ]
                    # `deco` decorates every wrapped line (docs/plans/
                    # fonts-and-icons.md Decision 5): one rule per line, from
                    # that line's own already-measured box above -- `box[0]`
                    # is the inked left edge under `anchor`, `box[2]-box[0]`
                    # its width, exactly what get_text_bounds() gives the
                    # firmware. An empty wrapped line measures a
                    # zero-or-negative width and contributes no rule.
                    deco_boxes = []
                    if deco is not None:
                        for (_px, ly, _line), box in zip(positions, boxes, strict=True):
                            db = _deco_rect(
                                deco, box[0], box[2] - box[0], ly, deco_h, deco_baseline
                            )
                            if db is not None:
                                deco_boxes.append(db)

                    def draw_fn(dr, col, positions=positions, deco_boxes=deco_boxes):
                        for px, ly, line in positions:
                            dr.text((px, ly), line, font=f, fill=col, anchor=anchor)
                        for x0, y0, x1, y1 in deco_boxes:
                            dr.rectangle([x0, y0, x1 - 1, y1 - 1], fill=col)

                    def check_glyphs(font_name=font_name, lines=lines, where=where):
                        _check_uncompiled_glyphs(ctx, font_name, "".join(lines), where)

                    _paint_glyph_op(
                        img, ctx, ink, c_name, where, boxes + deco_boxes, draw_fn,
                        dithered_colors, after_mix_check=check_glyphs,
                    )
                else:
                    text = fit_line(f, op["s"], max_w)
                    box = d.textbbox((x, y), text, font=f, anchor=anchor)
                    # `deco` on the single fitted line (docs/plans/
                    # fonts-and-icons.md Decision 5): `None` when there's no
                    # ink to decorate or the rule clips away entirely.
                    deco_box = (
                        _deco_rect(deco, box[0], box[2] - box[0], y, deco_h, deco_baseline)
                        if deco is not None
                        else None
                    )

                    def draw_fn(dr, col):
                        dr.text((x, y), text, font=f, fill=col, anchor=anchor)
                        if deco_box is not None:
                            x0, y0, x1, y1 = deco_box
                            dr.rectangle([x0, y0, x1 - 1, y1 - 1], fill=col)

                    def check_glyphs(font_name=font_name, text=text, where=where):
                        _check_uncompiled_glyphs(ctx, font_name, text, where)

                    boxes = [box] if deco_box is None else [box, deco_box]
                    _paint_glyph_op(
                        img, ctx, ink, c_name, where, boxes, draw_fn, dithered_colors,
                        after_mix_check=check_glyphs,
                    )

            elif kind == "fmt":
                # text without wrap whose `s` is a template of system fields. The
                # values are never in the document, so meta.hash covers where and
                # how the line is drawn, never what it says. `s` stays optional
                # in OP_FIELDS (an empty template is a legal, if useless, way to
                # write "draw nothing here"), but an empty or missing one really
                # has nothing to draw, so it gets its own message and the same
                # skip a missing required field gets, rather than drawing an
                # empty line that passes every other check silently.
                s = op.get("s", "")
                if not isinstance(s, str) or not s:
                    ctx.problems.append(f"{where}: fmt has no 's' template; nothing to draw")
                    continue
                c_name = op.get("c", "black")
                font_name = op.get("f", "xs")
                f = ctx.font(font_name, where)
                if f is None:
                    # Same abandonment as `text`, and it matches the firmware:
                    # the header checks the font before it ever calls
                    # expand_fmt(), so an unknown-field warning never fires
                    # either when the font is also bad.
                    continue
                # D6, same as `text`: measured on the template itself,
                # before expansion -- a short template that only expands to
                # something long (unlikely, since every system field is
                # short) is not what this bound is for.
                s_bytes = len(s.encode("utf-8"))
                if s_bytes > TEXT_MAX_LEN:
                    ctx.problems.append(
                        f"{where}: s is {s_bytes} bytes, more than {TEXT_MAX_LEN}; skipped"
                    )
                    continue
                x, y = _int_coord(op["x"]), _int_coord(op["y"])
                anchor = _anchor_of(op, ctx, where)
                text, unknown = expand_fields(s, fields)
                for field_name in unknown:
                    ctx.problems.append(f"{where}: unknown field {{{field_name}}} (left literal)")
                box = d.textbbox((x, y), text, font=f, anchor=anchor)
                draw_fn = lambda dr, col: dr.text(  # noqa: E731
                    (x, y), text, font=f, fill=col, anchor=anchor)

                def check_glyphs(font_name=font_name, text=text, where=where):
                    _check_uncompiled_glyphs(ctx, font_name, text, where)

                _paint_glyph_op(
                    img, ctx, ink, c_name, where, [box], draw_fn, dithered_colors,
                    after_mix_check=check_glyphs,
                )

            elif kind == "icon":
                c_name = op.get("c", "black")
                name = op.get("n")
                z = op.get("z", "sm")
                key = f"{name}/{z}"
                if name not in ICONS or z not in ICONS[name]:
                    ctx.problems.append(f"{where}: {key!r} is not compiled in")
                size = ICON_SIZES.get(z, 36)
                x, y = _int_coord(op["x"]), _int_coord(op["y"])
                box = (x, y, x + size, y + size)
                draw_fn = lambda dr, col: draw_icon(dr, name, x, y, size, col)  # noqa: E731
                _paint_glyph_op(img, ctx, ink, c_name, where, [box], draw_fn, dithered_colors)

            elif kind == "sprite":
                # Pixel art as rows of characters (docs/plans/dragon-feedback.md
                # D9). `cell`, `rows` and `palette` all have to be sensible
                # before there is anything to draw; unlike every other op, a
                # malformed one of these skips the whole op rather than
                # drawing something wrong — the one place a skip is allowed,
                # mirroring the firmware, which cannot draw a grid it cannot
                # parse either.
                x, y = _int_coord(op["x"]), _int_coord(op["y"])
                cell = op.get("cell")
                raw_rows = op.get("rows")
                raw_palette = op.get("palette")
                # `_op_required_field_problem()` has already guaranteed
                # `cell` a number, `raw_rows` a list and `raw_palette` a
                # dict before dispatch ever reaches here -- an
                # `isinstance(cell, bool)`/`not isinstance(raw_rows, list)`/
                # `not isinstance(raw_palette, dict)` clause here could
                # never fire. What's left to check: `cell` an *integer* (a
                # float like 1.5 is still a number) in range -- both sides
                # have to agree on what's too big to be sane, not just what
                # overflows int arithmetic; a `cell` bigger than the canvas
                # itself is malformed the same way a zero or fractional one
                # is, see SPRITE_MAX_CELL's own comment for why -- and every
                # element of `rows` an actual string.
                if (
                    not isinstance(cell, int)
                    or cell < 1
                    or cell > SPRITE_MAX_CELL
                    or not all(isinstance(r, str) for r in raw_rows)
                ):
                    ctx.problems.append(
                        f"{where}: sprite needs an integer cell >= 1 and <= "
                        f"{SPRITE_MAX_CELL} and rows (a list of strings); "
                        "nothing to draw, skipped"
                    )
                    continue

                # The grid's own dimensions, bounded independently of `cell`
                # (docs/plans/firmware-bounds.md D7): together with MAX_COORD
                # on the pixel box below, these keep the ragged-row walk to
                # at most SPRITE_MAX_COLS * SPRITE_MAX_ROWS cell visits,
                # however small `cell` itself is.
                # Message text below matches display_list.h's own ESP_LOGW
                # calls verbatim (modulo the "{where}: " prefix every
                # message here carries) -- the repo convention every other
                # shared warning already follows (see poly's "out of range"
                # message), and what lets a parity test assert full text
                # equality rather than a substring.
                if len(raw_rows) > SPRITE_MAX_ROWS:
                    ctx.problems.append(
                        f"{where}: sprite has {len(raw_rows)} rows, more than "
                        f"{SPRITE_MAX_ROWS}; skipped"
                    )
                    continue
                if len(raw_palette) > SPRITE_MAX_PALETTE:
                    ctx.problems.append(
                        f"{where}: sprite palette has {len(raw_palette)} entries, "
                        f"more than {SPRITE_MAX_PALETTE}; skipped"
                    )
                    continue

                widths = [len(r) for r in raw_rows]
                cols = max(widths, default=0)
                if cols > SPRITE_MAX_COLS:
                    ctx.problems.append(
                        f"{where}: sprite is {cols} columns wide, more than "
                        f"{SPRITE_MAX_COLS}; skipped"
                    )
                    continue

                # The pixel box this sprite would actually occupy
                # (docs/plans/firmware-bounds.md D4), checked here rather
                # than only relied on from the generic x/y bound every op
                # gets: `x`/`y` themselves are already covered by
                # `_coord_bound_problem()`, but the box's far edge is
                # sprite-specific arithmetic no other op does.
                x_edge, y_edge = x + cols * cell, y + len(raw_rows) * cell
                if abs(x_edge) > MAX_COORD or abs(y_edge) > MAX_COORD:
                    ctx.problems.append(
                        f"{where}: sprite pixel box out of range (|v| <= {MAX_COORD}); skipped"
                    )
                    continue

                if widths and min(widths) != cols:
                    ctx.problems.append(
                        f"{where}: rows are ragged (widths {min(widths)}.."
                        f"{cols}); short rows padded transparent"
                    )
                grid = [r.ljust(cols, ".") for r in raw_rows]
                mirror = op.get("mirror")
                if mirror == "x":
                    grid = [r[::-1] for r in grid]
                elif mirror is not None:
                    # `"x"` is the only legal value (docs/SPEC.md "sprite");
                    # anything else just doesn't mirror, same as omitting it.
                    ctx.problems.append(
                        f'{where}: mirror must be "x"; got {mirror!r}, not mirrored'
                    )

                # Resolve each palette character once, not per cell — the
                # same alias/mix/built-in walk an op's own `c` gets, via
                # ctx.ink() itself: a dict value earns the same mix hint `c`
                # does, and anything else that doesn't resolve is "unknown
                # colour", both already handled there. A key that isn't
                # exactly one character can't identify a cell at all, so it's
                # skipped up front — a row that uses it then falls into the
                # "no palette entry" path below, same as any other unknown
                # character.
                used_chars = {ch for row in raw_rows for ch in row} - {".", " "}
                char_ink: dict[str, Ink] = {}
                checked_inks: set[Ink] = set()
                for ch, value in raw_palette.items():
                    if len(ch) != 1:
                        ctx.problems.append(
                            f"{where}: palette key {ch!r} is not one character; ignored"
                        )
                        continue
                    if ch in (".", " "):
                        ctx.problems.append(
                            f"{where}: sprite palette cannot redefine {ch!r}; "
                            "it stays transparent"
                        )
                        continue
                    resolved = ctx.ink(value, where)
                    char_ink[ch] = resolved
                    # Only a character some row actually draws can be too thin
                    # to carry a density — an unused palette entry has no
                    # cell to be thin.
                    if ch in used_chars and resolved not in checked_inks:
                        checked_inks.add(resolved)
                        _check_thin_mix(ctx, resolved, where, "fill", w=cell, h=cell)

                black_ink = Ink(ctx.table["black"], ctx.table["black"], 100)
                warned_chars: set[str] = set()
                # Capped the same way the firmware caps it (docs/plans/
                # firmware-bounds.md D7): eight distinct offending
                # characters get their own line, a ninth gets one more
                # "...and more" line, and nothing after that adds to
                # `problems` -- a sprite with hundreds of stray characters
                # must not turn a single check() into hundreds of warnings.
                _MAX_WARNED_CHARS = 8
                warned_overflow = False
                box = (x, y, x + cols * cell, y + len(grid) * cell)
                snap = _snapshot(img, box)
                for r, row in enumerate(grid):
                    c0 = 0
                    while c0 < cols:
                        ch = row[c0]
                        c1 = c0 + 1
                        while c1 < cols and row[c1] == ch:
                            c1 += 1
                        run = c1 - c0
                        if ch not in (".", " "):
                            if ch in char_ink:
                                run_ink = char_ink[ch]
                            else:
                                # Checked, then added -- not the other way
                                # around (review amendment to docs/plans/
                                # firmware-bounds.md D7): adding first and
                                # capping only the appended *problems* left
                                # `warned_chars` itself unbounded, so a
                                # sprite with thousands of distinct
                                # offending characters would still grow the
                                # set without limit even though only eight
                                # lines were ever reported. Mirrors the
                                # same restructuring in draw_sprite().
                                if ch in warned_chars:
                                    pass
                                elif len(warned_chars) < _MAX_WARNED_CHARS:
                                    warned_chars.add(ch)
                                    ctx.problems.append(
                                        f"{where}: no palette entry for {ch!r}; "
                                        "drawing black"
                                    )
                                elif not warned_overflow:
                                    warned_overflow = True
                                    ctx.problems.append(
                                        f"{where}: ...and more characters with "
                                        "no palette entry"
                                    )
                                run_ink = black_ink
                            rx, ry = x + c0 * cell, y + r * cell
                            rw, rh = run * cell, cell

                            def draw_fn(dr, col, rx=rx, ry=ry, rw=rw, rh=rh):
                                dr.rectangle([rx, ry, rx + rw - 1, ry + rh - 1], fill=col)

                            paint_op(run_ink, draw_fn)
                        c0 = c1
                _check_drew_nothing(img, ctx, snap, where)

                xr, yr = x + cols * cell, y + len(grid) * cell
                if _off_canvas(xr, WIDTH):
                    ctx.problems.append(f"{where}: x+cols*cell={xr} is off-canvas")
                if _off_canvas(yr, HEIGHT):
                    ctx.problems.append(f"{where}: y+rows*cell={yr} is off-canvas")

            elif kind == "poly":
                # A point list, filled by the even-odd scanline rule
                # (docs/plans/dragon-feedback.md D12) or outlined edge by
                # edge. Like sprite, a malformed `pts` skips the whole op —
                # there's nothing sensible to draw from fewer than three
                # points, and the firmware bails the same way.
                raw_pts = op.get("pts")
                # docs/plans/firmware-bounds.md D8: too many points is its
                # own message, checked before `_valid_poly_points()` even
                # looks at them -- the firmware's mirror enforces this while
                # *parsing* pts, so its own vector never grows past
                # POLY_MAX_PTS; here the list already exists (ArduinoJson's
                # parser has no such equivalent to protect on this side),
                # but the same document is rejected the same way.
                if isinstance(raw_pts, list) and len(raw_pts) > POLY_MAX_PTS:
                    ctx.problems.append(
                        f"{where}: poly has more than {POLY_MAX_PTS} points; "
                        "nothing to draw, skipped"
                    )
                    continue

                pts = _valid_poly_points(raw_pts)
                if pts is None:
                    ctx.problems.append(
                        f"{where}: poly needs at least three [x, y] points; "
                        "nothing to draw, skipped"
                    )
                    continue

                # A coordinate this far out is malformed, not merely
                # off-canvas: reject it before the bounding box or the
                # scanline fill below ever has to reconcile a magnitude this
                # large. See MAX_COORD's own comment for why.
                if any(abs(px) > MAX_COORD or abs(py) > MAX_COORD for px, py in pts):
                    ctx.problems.append(
                        f"{where}: poly point out of range "
                        f"(|x|,|y| <= {MAX_COORD}); nothing to draw, skipped"
                    )
                    continue

                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                x0, x1 = min(xs), max(xs)
                y0, y1 = min(ys), max(ys)
                # There's no single x/y to check here (a poly has no anchor),
                # so the ordinary off-canvas check at the bottom of this loop
                # doesn't fire — this is its replacement, on the bounding box
                # of every point, same tolerance as everywhere else.
                if (
                    _off_canvas(x0, WIDTH)
                    or _off_canvas(x1, WIDTH)
                    or _off_canvas(y0, HEIGHT)
                    or _off_canvas(y1, HEIGHT)
                ):
                    ctx.problems.append(
                        f"{where}: pts range x {x0}..{x1}, y {y0}..{y1} is off-canvas"
                    )

                box = (x0, y0, x1 + 1, y1 + 1)
                snap = _snapshot(img, box)
                if _resolved_fill(op, where, ctx):
                    spans = _poly_spans(pts)
                    # `w`/`h` for the thin-mix check — a poly has no
                    # single fill box like a rect's `w x h`, so this stands in
                    # for it: the widest span (the narrowest a row of the fill
                    # ever gets, in the sense that matters — the maximum,
                    # since a warning should fire only when *every* row is too
                    # thin to carry the density) and how many scanlines have
                    # any fill at all.
                    if spans:
                        widest = max(xb - xa + 1 for _y, xa, xb in spans)
                        n_scanlines = len({yy for yy, _xa, _xb in spans})
                    else:
                        widest = n_scanlines = 0
                    _check_thin_mix(ctx, ink, where, "fill", w=widest, h=n_scanlines)

                    def draw_fn(dr, col, spans=spans):
                        for yy, xa, xb in spans:
                            dr.rectangle([xa, yy, xb, yy], fill=col)

                    paint_op(ink, draw_fn)
                else:
                    t = _resolved_thickness(op.get("t", 1), where, ctx)
                    _check_thin_mix(ctx, ink, where, "line", t=t)
                    n_pts = len(pts)

                    def draw_fn(dr, col, pts=pts, t=t, n_pts=n_pts):
                        for i in range(n_pts):
                            ex1, ey1 = pts[i]
                            ex2, ey2 = pts[(i + 1) % n_pts]
                            for px, py in _thick_line_points(ex1, ey1, ex2, ey2, t):
                                dr.point((px, py), fill=col)

                    paint_op(ink, draw_fn)
                _check_drew_nothing(img, ctx, snap, where)

            else:
                ctx.problems.append(f"{where}: unknown op {kind!r}")
        except Exception as exc:  # noqa: BLE001 - never let one op crash a publish
            ctx.problems.append(
                f"{where}: could not be drawn ({type(exc).__name__}: {exc}); skipped"
            )
            continue

        for k in ("x", "y"):
            v = op.get(k)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            v = _int_coord(v)
            bound = WIDTH if k == "x" else HEIGHT
            if _off_canvas(v, bound):
                ctx.problems.append(f"{where}: {k}={v} is off-canvas")

    return img, ctx.problems


def bezel_problems(doc: dict[str, Any]) -> list[str]:
    """Text, fmt and icon ops whose anchor sits inside the bezel margin.

    Only the anchor corner is judged (plus the right edge of right-aligned
    text and of icons, whose extent is known): glyph boxes carry their own
    padding, so measuring the far edge would flag the standard footer.

    Runs over the raw document, independently of render()'s own op loop --
    an op render() went on to skip (a bad `f`/`z`, say) is still judged
    here by its `x`/`y` alone, so a wrong-typed `f`/`z` falls back to the
    same default render()'s own required/optional-field checks would use,
    rather than reaching `FONTS`/`ICON_SIZES` as an unhashable dict key
    (docs/plans/dragon-feedback.md D1 follow-up) -- render()'s own check
    already reports the bad field itself; this one only needs geometry.
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
        if kind == "icon":
            z = op.get("z", "sm")
            if not isinstance(z, str):
                z = "sm"
            if x + ICON_SIZES.get(z, 0) > WIDTH - BEZEL_MARGIN:
                edges.append("right")
        if y < BEZEL_MARGIN:
            edges.append("top")
        if kind != "icon":
            font_name = op.get("f", "md" if kind == "text" else "xs")
            if not isinstance(font_name, str):
                font_name = "md" if kind == "text" else "xs"
            # A font name this check can't resolve falls back to `md` --
            # matching the pre-Decision-1 `FONTS.get(font_name, FONTS["md"])`
            # exactly, regardless of op kind -- rather than reaching FONTS
            # with a bad key: render()'s own checks are what report a bad
            # `f`, this one only needs a plausible size for the margin test.
            canonical = resolve_font(font_name) or resolve_font("md")
            face = FONTS[canonical]
            bottom_extent = face.size
            # A `deco` rule (docs/plans/fonts-and-icons.md Decision 5) can
            # reach past `size` -- `size` alone stands in for roughly the
            # cap height, but an underline's own bottom is
            # `baseline + gap + t - 1` below `y`, which for every compiled
            # face (checked against the real font_height()/font_baseline()
            # value for each, B5's review fix) stays at or under
            # `cell_height` (ascent + descent) -- confirmed for strike too,
            # whose rule sits entirely above the baseline and so is smaller
            # still. `cell_height` is already in this table with no font
            # file to load, unlike the exact `h`/`baseline` the drawing
            # code itself uses -- this function deliberately never opens a
            # font file (see its docstring), so this is the safe upper
            # bound available without one. `fmt` never draws a rule (`deco`
            # is `text`-only), so this only applies to `kind == "text"`.
            if kind == "text" and op.get("deco") in ("underline", "strike"):
                bottom_extent = face.cell_height
            if y + bottom_extent > HEIGHT - BEZEL_MARGIN:
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

    A `meta` that isn't an object at all (a document handed a string or a
    list there, same JSON-legality every other field is allowed) is never
    raised on either: warned about, once, and treated as empty, the same
    "never raise from a shape the JSON allows" rule `Ctx.__init__` already
    holds `palette` to.
    """
    _, problems = render(doc, font_dir, warn_ink=True)
    problems = problems + bezel_problems(doc)
    meta = doc.get("meta")
    if meta is not None and not isinstance(meta, dict):
        problems = problems + ["meta: must be an object; ignored"]
        meta = {}
    stamped = (meta or {}).get("hash")
    if stamped:
        h = render_hash(doc)
        if stamped != h:
            problems = [
                f"meta.hash is stale ({stamped}) — remove meta.hash, set_display stamps it"
            ] + problems
    return problems


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
    entirely off-canvas and disappear: a bordered canvas reads better than
    one whose last edge is invisible.

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

