"""Tests for display_mcp.render.

Fixture note: `font_dir` and `sample_doc` come from tests/conftest.py. Any
test that renders real text needs `font_dir` and will skip cleanly (via that
fixture) if fonts/ hasn't been populated with the Instrument Sans pair.
"""

from __future__ import annotations

import copy
import re
import shutil
import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from display_mcp.render import (
    _POLY_MAX_COORD,
    _THICK_MAX,
    BEZEL_MARGIN,
    BUILTIN_MIXES,
    COLORS,
    FONTS,
    HEIGHT,
    ICON_SIZES,
    ICONS,
    INK,
    TIERS,
    WIDTH,
    Ctx,
    Ink,
    _grounds,
    bezel_problems,
    check,
    document_colors,
    draw_icon,
    fit_line,
    fonts_available,
    load_font,
    mix_on,
    render,
    render_hash,
    swatch_document,
    swatch_groups,
    wrap_lines,
)

SAMPLE_HASH = "3cd62aa76e731d2d"
ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# render_hash
# --------------------------------------------------------------------------


def test_hash_ignores_meta_generated(sample_doc):
    doc = copy.deepcopy(sample_doc)
    doc["meta"]["generated"] = "some other time entirely"
    assert render_hash(doc) == SAMPLE_HASH


def test_hash_changes_with_an_op(sample_doc):
    doc = copy.deepcopy(sample_doc)
    doc["ops"][0]["x"] += 1
    assert render_hash(doc) != SAMPLE_HASH


# --------------------------------------------------------------------------
# render() of the sample
# --------------------------------------------------------------------------


def test_render_sample_is_clean(sample_doc, font_dir):
    img, problems = render(sample_doc, font_dir)
    assert img.size == (WIDTH, HEIGHT)
    assert img.mode == "RGB"
    assert problems == []


def test_check_sample_is_clean(sample_doc, font_dir):
    assert check(sample_doc, font_dir) == []


# --------------------------------------------------------------------------
# fonts_available
# --------------------------------------------------------------------------


def test_fonts_available_true(font_dir):
    assert fonts_available(font_dir) is True


# --------------------------------------------------------------------------
# wrap / fit differential fixtures.
#
# Written as a flat parametrised table so a future C++ diff (the way
# fit_line/wrap/utf8_prev are diffed against display_list.h per docs/SPEC.md
# "Testing") has something simple to consume: (text, max_w, lines, expected).
# --------------------------------------------------------------------------

FIT_CASES = [
    # (id, text, max_w, expected) -- max_w "exact"/"third" is computed per
    # case from the text's own measured width, once the font is loaded.
    ("plain_fits", "Team standup", 800, "Team standup"),
    ("empty_string", "", 100, ""),
    ("multibyte_near_cut", "Design review — display list — 12° today", 40, None),
    ("single_word_longer_than_box", "Supercalifragilisticexpialidocious", 60, None),
    ("exact_fit_is_unchanged", "Team standup", "exact", "Team standup"),
    (
        "multibyte_truncation_keeps_valid_utf8",
        "Design review — the 72° display list for today's schedule",
        "third",
        None,
    ),
    (
        "none_max_w_is_unchanged",
        "Supercalifragilisticexpialidocious, quite unchanged",
        None,
        "Supercalifragilisticexpialidocious, quite unchanged",
    ),
]


@pytest.mark.parametrize("case_id,text,max_w,expected", FIT_CASES)
def test_fit_line_cases(font_dir, case_id, text, max_w, expected):
    """Every case pins the same invariants: valid UTF-8, text_width(result)
    <= max_w, a result shorter than the input ends with an ellipsis, and
    max_w=None never truncates."""
    from display_mcp.render import load_font, text_width

    font = load_font(font_dir, FONTS["sm"])
    if max_w == "exact":
        resolved_max_w = text_width(font, text)
    elif max_w == "third":
        resolved_max_w = text_width(font, text) // 3
    else:
        resolved_max_w = max_w
    result = fit_line(font, text, resolved_max_w)
    if expected is not None:
        assert result == expected
    result.encode("utf-8")  # would raise on a bad surrogate half
    if resolved_max_w is None:
        assert result == text
    else:
        assert text_width(font, result) <= resolved_max_w or result == "…"
    if len(result) < len(text):
        assert result.endswith("…")


def test_wrap_two_lines_with_overflow_ellipsis(font_dir):
    from display_mcp.render import load_font, text_width

    font = load_font(font_dir, FONTS["md"])
    s = "Order printer filament and a spare 0.4 nozzle for the workshop bench today"
    max_w = 300
    lines = wrap_lines(font, s, max_w, 2)
    assert len(lines) == 2
    for line in lines:
        assert text_width(font, line) <= max_w
    assert lines[-1].endswith("…")


def test_wrap_last_word_just_fits(font_dir):
    from display_mcp.render import load_font, text_width

    font = load_font(font_dir, FONTS["md"])
    words = ["Book", "the", "dentist"]
    s = " ".join(words)
    max_w = text_width(font, s)  # exactly enough for every word on one line
    lines = wrap_lines(font, s, max_w, 2)
    assert lines == [s]


def test_wrap_lines_equals_one(font_dir):
    from display_mcp.render import load_font, text_width

    font = load_font(font_dir, FONTS["md"])
    s = "Measure the driver board for the frame and order new screws"
    max_w = 250
    lines = wrap_lines(font, s, max_w, 1)
    assert len(lines) == 1
    assert text_width(font, lines[0]) <= max_w


# --------------------------------------------------------------------------
# `text` op: `w`/`lh`/`lines` that are null or the wrong type mean absent,
# the same way the firmware's `o["field"] | default` does (describe()
# advertises `null` as each one's default, and a caller that writes that
# literally must not crash validate()/preview()).
# --------------------------------------------------------------------------


def _text_op(**overrides):
    op = {"op": "text", "x": 10, "y": 10, "s": "hello there wide world of text",
          "f": "sm", "wrap": True, "w": 140, "lines": 3}
    op.update(overrides)
    return op


def test_text_lh_null_matches_lh_omitted(font_dir):
    doc_null = {"bg": "white", "ops": [_text_op(lh=None)]}
    doc_omitted = {"bg": "white", "ops": [{k: v for k, v in _text_op().items() if k != "lh"}]}
    img_null, problems = render(doc_null, font_dir)  # must not raise
    img_omitted, _ = render(doc_omitted, font_dir)
    assert problems == []
    assert img_null.tobytes() == img_omitted.tobytes()


def test_text_w_null_with_wrap_matches_w_omitted(font_dir):
    doc_null = {"bg": "white", "ops": [_text_op(w=None)]}
    doc_omitted = {"bg": "white", "ops": [{k: v for k, v in _text_op().items() if k != "w"}]}
    img_null, problems = render(doc_null, font_dir)  # must not raise
    img_omitted, _ = render(doc_omitted, font_dir)
    assert problems == []
    assert img_null.tobytes() == img_omitted.tobytes()


def test_text_w_non_numeric_matches_w_omitted(font_dir):
    """`wrap: true` stays set, but a `w` that isn't a number can't satisfy
    the firmware's `wrap && max_w > 0`, so this draws a single unwrapped
    line — same as the op with `w` left out entirely."""
    doc_bad = {"bg": "white", "ops": [_text_op(w="wide")]}
    doc_omitted = {"bg": "white", "ops": [
        {k: v for k, v in _text_op().items() if k != "w"}]}
    img_bad, problems = render(doc_bad, font_dir)  # must not raise
    img_omitted, _ = render(doc_omitted, font_dir)
    assert problems == []
    assert img_bad.tobytes() == img_omitted.tobytes()


def test_text_lines_null_matches_lines_omitted(font_dir):
    doc_null = {"bg": "white", "ops": [_text_op(lines=None)]}
    doc_omitted = {"bg": "white", "ops": [
        {k: v for k, v in _text_op().items() if k != "lines"}]}
    img_null, problems = render(doc_null, font_dir)  # must not raise
    img_omitted, _ = render(doc_omitted, font_dir)
    assert problems == []
    assert img_null.tobytes() == img_omitted.tobytes()


# --------------------------------------------------------------------------
# unknown `a` (alignment): warn, still fall back to left like the firmware
# --------------------------------------------------------------------------


def test_unknown_alignment_on_text_warns_and_falls_back_to_left(font_dir):
    doc_bad = {"bg": "white", "ops": [
        {"op": "text", "x": 10, "y": 10, "s": "hi", "f": "sm", "a": "top"}]}
    doc_left = {"bg": "white", "ops": [
        {"op": "text", "x": 10, "y": 10, "s": "hi", "f": "sm", "a": "left"}]}
    img_bad, problems = render(doc_bad, font_dir)
    img_left, _ = render(doc_left, font_dir)
    assert problems == ["ops[0] text: unknown alignment 'top', using left"]
    assert img_bad.tobytes() == img_left.tobytes()


def test_unknown_alignment_on_fmt_warns_too(font_dir):
    doc = {"bg": "white", "ops": [
        {"op": "fmt", "x": 10, "y": 10, "s": "{time}", "f": "xs", "a": "middle"}]}
    _, problems = render(doc, font_dir)
    assert problems == ["ops[0] fmt: unknown alignment 'middle', using left"]


def test_known_alignment_never_warns(font_dir):
    for a in ("left", "center", "right"):
        doc = {"bg": "white", "ops": [
            {"op": "text", "x": 10, "y": 10, "s": "hi", "f": "sm", "a": a}]}
        _, problems = render(doc, font_dir)
        assert problems == []


# --------------------------------------------------------------------------
# icon validation
# --------------------------------------------------------------------------


def _icon_doc(sample_doc, name, z):
    doc = copy.deepcopy(sample_doc)
    doc["ops"].append({"op": "icon", "x": 10, "y": 10, "n": name, "z": z, "c": "black"})
    return doc


def test_icon_bad_size_class_is_a_problem(sample_doc, font_dir):
    doc = _icon_doc(sample_doc, "check", "lg")
    _, problems = render(doc, font_dir)
    assert any("check/lg" in p and "not compiled in" in p for p in problems)


def test_icon_good_size_class_is_not_a_problem(sample_doc, font_dir):
    doc = _icon_doc(sample_doc, "check", "sm")
    _, problems = render(doc, font_dir)
    assert problems == []


def test_weather_snowy_is_valid(sample_doc, font_dir):
    doc = _icon_doc(sample_doc, "weather-snowy", "lg")
    _, problems = render(doc, font_dir)
    assert problems == []
    assert "weather-snowy" in ICONS
    assert "lg" in ICONS["weather-snowy"]


# --------------------------------------------------------------------------
# off-canvas
# --------------------------------------------------------------------------


def test_rect_off_canvas_beyond_tolerance(sample_doc, font_dir):
    doc = copy.deepcopy(sample_doc)
    doc["ops"].append({"op": "rect", "x": 1200, "y": 100, "w": 70, "h": 10, "c": "black"})
    _, problems = render(doc, font_dir)
    assert any("x+w" in p and "off-canvas" in p for p in problems)


def test_rect_exactly_at_tolerance_is_fine(sample_doc, font_dir):
    doc = copy.deepcopy(sample_doc)
    # x + w == 1200 exactly: within the +/-64 tolerance (<=1264), no problem.
    doc["ops"].append({"op": "rect", "x": 1100, "y": 100, "w": 100, "h": 10, "c": "black"})
    _, problems = render(doc, font_dir)
    assert not any("off-canvas" in p for p in problems)


# --------------------------------------------------------------------------
# rect corner radius (docs/plans/dragon-feedback.md D10, B2)
# --------------------------------------------------------------------------


def _rounded_rect_doc(r=None, fill=True, t=1, x=50, y=60, w=120, h=80, c="black", palette=None):
    op = {"op": "rect", "x": x, "y": y, "w": w, "h": h, "c": c, "fill": fill, "t": t}
    if r is not None:
        op["r"] = r
    return {"v": 1, "meta": {}, "bg": "white", "palette": palette or {}, "ops": [op]}


def test_rect_r_zero_is_pixel_identical_to_no_r(font_dir):
    no_r, problems_a = render(_rounded_rect_doc(r=None), font_dir)
    with_r0, problems_b = render(_rounded_rect_doc(r=0), font_dir)
    assert problems_a == problems_b == []
    assert no_r.tobytes() == with_r0.tobytes()


def test_rect_corner_pixel_is_ground_for_r_at_least_2(font_dir):
    x, y, w, h = 50, 60, 120, 80
    img, problems = render(_rounded_rect_doc(r=20, x=x, y=y, w=w, h=h), font_dir)
    assert problems == []
    px = img.load()
    for cx, cy in ((x, y), (x + w - 1, y), (x, y + h - 1), (x + w - 1, y + h - 1)):
        assert px[cx, cy] == INK["white"], (cx, cy)


def test_rect_r_larger_than_half_warns_and_clamps(font_dir):
    x, y, w, h = 50, 60, 40, 100
    max_r = max(0, (min(w, h) - 1) // 2)  # 19, not 20 -- see the sweep test below
    img, problems = render(_rounded_rect_doc(r=100, x=x, y=y, w=w, h=h), font_dir)
    clamped, _ = render(_rounded_rect_doc(r=max_r, x=x, y=y, w=w, h=h), font_dir)
    assert any(f"clamped to {max_r}" in p for p in problems), problems
    assert img.tobytes() == clamped.tobytes()


def test_rect_radius_sweep_stays_within_the_box(font_dir):
    """A corner disc is `2r + 1` px across, so `min(w, h) // 2` would let
    `r` at its own max ink one row/column past the nominal box on *both*
    sides, on an even `w` or `h` -- e.g. `w == 40`:
    a corner circle of `r == 20` is centred at `x + 20` and spans
    `[x, x + 40]`, one column wider than the box's own `[x, x + 39]`.
    `(min(w, h) - 1) // 2` is the actual safe bound (odd dimensions are
    unaffected: `min(w,h)-1` is already even there, so the two formulas
    agree).

    Drawn directly with `_draw_rounded_rect()` (not through `render()`,
    whose white background isn't zero so `Image.getbbox()` would just
    report the whole canvas) onto a small padded canvas — any ink straying
    outside `[pad, pad+w) x [pad, pad+h)` shows up in `getbbox()`. Even and
    odd `w`/`h`, `r` at 1, 2, the new clamp's own max, and one past it
    (which `render()`'s own clamp is responsible for catching before this
    function is ever called with it — not tested here again). Each edge's
    own row/column, away from the rounded corners, must stay fully inked —
    the ground a rounded box is judged against.
    """
    from PIL import Image, ImageDraw

    from display_mcp.render import _draw_rounded_rect

    pad = 5
    sizes = [(40, 40), (41, 41), (40, 30), (41, 31), (10, 10), (11, 11), (200, 80), (201, 81)]
    for w, h in sizes:
        max_r = max(0, (min(w, h) - 1) // 2)
        for r in sorted({1, 2, max_r}):
            if r < 1:
                continue
            img = Image.new("1", (w + 2 * pad, h + 2 * pad), 0)
            dr = ImageDraw.Draw(img)
            _draw_rounded_rect(dr, pad, pad, w, h, r, 1)
            bbox = img.getbbox()
            assert bbox is not None, (w, h, r)
            bx0, by0, bx1, by1 = bbox
            assert bx0 >= pad and by0 >= pad and bx1 <= pad + w and by1 <= pad + h, (
                w, h, r, bbox,
            )
            px = img.load()
            mid_x, mid_y = pad + w // 2, pad + h // 2
            assert px[mid_x, pad] and px[mid_x, pad + h - 1], (w, h, r, "top/bottom edge")
            assert px[pad, mid_y] and px[pad + w - 1, mid_y], (w, h, r, "left/right edge")


def test_rect_r_on_outline_warns_and_draws_square(font_dir):
    img, problems = render(_rounded_rect_doc(r=20, fill=False, t=2), font_dir)
    square, _ = render(_rounded_rect_doc(r=None, fill=False, t=2), font_dir)
    assert any("r is ignored on an outline; drawing square corners" in p for p in problems)
    assert img.tobytes() == square.tobytes()


def test_rect_non_integer_r_warns_and_is_treated_as_zero(font_dir):
    img, problems = render(_rounded_rect_doc(r=12.5), font_dir)
    square, _ = render(_rounded_rect_doc(r=0), font_dir)
    assert any("r=12.5" in p and "not a non-negative integer" in p for p in problems)
    assert img.tobytes() == square.tobytes()


def test_rect_negative_r_warns_and_is_treated_as_zero(font_dir):
    img, problems = render(_rounded_rect_doc(r=-5), font_dir)
    square, _ = render(_rounded_rect_doc(r=0), font_dir)
    assert any("r=-5" in p and "not a non-negative integer" in p for p in problems)
    assert img.tobytes() == square.tobytes()


def test_rect_mixed_rounded_fill_dithers_with_absolute_phase(font_dir):
    """What this pins is the rounded rect's *middle band* —
    the columns outside both corners' own radii, where the seven-shape
    construction draws a plain rectangle rather than a circle — against a
    plain, unrounded rect's fill of the same box and colour, pixel for
    pixel. Not a claim about the whole shape: the corners themselves are
    excluded, since PIL's `ellipse` and the firmware's midpoint circle
    round differently (D10's eyeball-parity note)."""
    palette = {"grey": {"c": "black", "c2": "white", "mix": 25}}
    x, y, w, h, r = 40, 40, 100, 100, 20
    rounded, problems = render(
        _rounded_rect_doc(r=r, x=x, y=y, w=w, h=h, c="grey", palette=palette), font_dir
    )
    plain, _ = render(
        _rounded_rect_doc(r=None, x=x, y=y, w=w, h=h, c="grey", palette=palette), font_dir
    )
    assert problems == []
    px_r, px_p = rounded.load(), plain.load()
    x0, x1 = x + r, x + w - r
    assert all(
        px_r[xx, yy] == px_p[xx, yy] for yy in range(y, y + h) for xx in range(x0, x1)
    )


def test_line_off_canvas_x2(sample_doc, font_dir):
    doc = copy.deepcopy(sample_doc)
    doc["ops"].append({"op": "line", "x": 0, "y": 0, "x2": 1300, "y2": 10, "c": "black"})
    _, problems = render(doc, font_dir)
    assert any("x2=1300" in p and "off-canvas" in p for p in problems)


def test_line_off_canvas_y2(sample_doc, font_dir):
    doc = copy.deepcopy(sample_doc)
    doc["ops"].append({"op": "line", "x": 0, "y": 0, "x2": 10, "y2": 1700, "c": "black"})
    _, problems = render(doc, font_dir)
    assert any("y2=1700" in p and "off-canvas" in p for p in problems)


# --------------------------------------------------------------------------
# palette alias resolution
# --------------------------------------------------------------------------


def test_palette_alias_chain_resolves(font_dir):
    doc = {
        "bg": "white",
        "palette": {"a": "b", "b": "c", "c": "red"},
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "a"}],
    }
    _, problems = render(doc, font_dir)
    assert problems == []


def test_palette_cycle_falls_back_to_black_no_hang(font_dir):
    doc = {
        "bg": "white",
        "palette": {"a": "b", "b": "a"},
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "a"}],
    }
    img, problems = render(doc, font_dir)
    assert any("unknown colour" in p for p in problems)
    # Falls back to black.
    assert img.getpixel((5, 5)) == (32, 32, 32)  # INK["black"]


def test_palette_deep_chain_capped_at_eight_hops(font_dir):
    # a->b->c->d->e->f->g->h->i->red: 9 hops to reach a base colour, beyond
    # the cap, so it must NOT resolve (mirrors resolve_color()'s hop cap).
    doc = {
        "bg": "white",
        "palette": {
            "a": "b",
            "b": "c",
            "c": "d",
            "d": "e",
            "e": "f",
            "f": "g",
            "g": "h",
            "h": "i",
            "i": "red",
        },
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "a"}],
    }
    _, problems = render(doc, font_dir)
    assert any("unknown colour" in p for p in problems)


# --------------------------------------------------------------------------
# unknown op / colour / font
# --------------------------------------------------------------------------


def test_unknown_colour_is_one_problem_no_raise(font_dir):
    doc = {"bg": "white", "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "mauve"}]}
    _, problems = render(doc, font_dir)
    assert len(problems) == 1
    assert "unknown colour" in problems[0]


def test_unknown_font_is_one_problem_no_raise(font_dir):
    doc = {
        "bg": "white",
        "ops": [{"op": "text", "x": 0, "y": 0, "s": "hi", "f": "huge"}],
    }
    _, problems = render(doc, font_dir)
    assert len(problems) == 1
    assert "unknown font" in problems[0]


def test_unknown_font_skips_the_op_nothing_drawn(font_dir):
    """The firmware's `text`/`fmt` branches `skipped++; continue` on an
    unknown font — nothing is drawn on the panel. The renderer must abandon
    the op the same way, not warn and still draw with the `md` fallback,
    which would show text on the preview the wall never draws: the warning
    stays, but the canvas is untouched."""
    doc = {
        "bg": "white",
        "ops": [{"op": "text", "x": 100, "y": 100, "s": "hi", "f": "huge"}],
    }
    img, problems = render(doc, font_dir)
    assert len(problems) == 1
    assert "unknown font" in problems[0]
    # Nothing drawn: pixel-identical to the same doc with no ops at all.
    blank_img, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank_img.tobytes()

    fmt_doc = {
        "bg": "white",
        "ops": [{"op": "fmt", "x": 100, "y": 100, "s": "{time}", "f": "huge"}],
    }
    fmt_img, fmt_problems = render(fmt_doc, font_dir)
    assert len(fmt_problems) == 1
    assert "unknown font" in fmt_problems[0]
    assert fmt_img.tobytes() == blank_img.tobytes()


# --------------------------------------------------------------------------
# check(): the bezel margin
# --------------------------------------------------------------------------


def test_text_inside_bezel_margin_is_flagged(sample_doc, font_dir):
    doc = copy.deepcopy(sample_doc)
    doc["ops"].append({"op": "text", "x": 8, "y": 300, "s": "hi", "f": "sm"})
    problems = check(doc, font_dir)
    assert any("left edge" in p and "bezel" in p for p in problems)


def test_right_aligned_text_is_judged_by_its_right_edge(sample_doc, font_dir):
    doc = copy.deepcopy(sample_doc)
    doc["ops"].append({"op": "text", "x": 1195, "y": 300, "s": "hi", "f": "sm", "a": "right"})
    problems = check(doc, font_dir)
    assert any("right edge" in p and "bezel" in p for p in problems)
    assert not any("left edge" in p for p in problems)


def test_icon_at_the_corner_is_flagged_by_check_only(sample_doc, font_dir):
    doc = _icon_doc(sample_doc, "check", "sm")  # x=10, y=10
    _, render_problems = render(doc, font_dir)
    assert render_problems == []
    problems = check(doc, font_dir)
    assert any("left and top edge" in p for p in problems)


def test_bezel_margin_ignores_fills_and_the_standard_footer(sample_doc, font_dir):
    # The sample's header bar is full bleed and its footer sits at the
    # published coordinates; neither is a bezel problem.
    assert bezel_problems(sample_doc) == []


# --------------------------------------------------------------------------
# check(): meta.hash staleness/absence
# --------------------------------------------------------------------------


def test_check_flags_stale_hash(sample_doc, font_dir):
    doc = copy.deepcopy(sample_doc)
    doc["meta"]["hash"] = "0000000000000000"
    problems = check(doc, font_dir)
    assert any("meta.hash is stale" in p for p in problems)


def test_check_does_not_flag_missing_hash(sample_doc, font_dir):
    doc = copy.deepcopy(sample_doc)
    del doc["meta"]["hash"]
    problems = check(doc, font_dir)
    assert problems == []


# --------------------------------------------------------------------------
# public surface sanity
# --------------------------------------------------------------------------


def test_colors_tuple():
    assert set(COLORS) == {"black", "white", "yellow", "red", "blue", "green"}


def test_fonts_keys():
    assert set(FONTS) == {"xl", "lg", "md", "sm", "xs", "mono"}


# --------------------------------------------------------------------------
# mono (JetBrains Mono, docs/plans/dragon-feedback.md D11/B3)
# --------------------------------------------------------------------------

# The measured ascent+descent for every face, at the size and weight
# instance the renderer actually loads (docs/plans/dragon-feedback.md D11,
# amended 2026-09-18). A font swap that silently moves these should fail
# this test, not quietly reflow every document.
_MEASURED_CELL_HEIGHTS = {
    "xl": 103,
    "lg": 59,
    "md": 44,
    "sm": 35,
    "xs": 28,
    "mono": 33,
}


def test_cell_height_matches_getmetrics(font_dir):
    for name in sorted(FONTS):
        face = FONTS[name]
        assert face.cell_height == _MEASURED_CELL_HEIGHTS[name], name
        f = load_font(font_dir, face)
        ascent, descent = f.getmetrics()
        assert face.cell_height == ascent + descent, name


def test_fonts_available_requires_mono_too(tmp_path):
    (tmp_path / "InstrumentSans-Regular.ttf").write_bytes(b"x")
    (tmp_path / "InstrumentSans-Bold.ttf").write_bytes(b"x")
    assert fonts_available(tmp_path) is False


def test_mono_ink_height_matches_a_measured_block_glyph(font_dir):
    """`ink_height` is measured, not derived from `cell_height` — render
    a full-height glyph (`█`) bilevel, the same target FreeType's mono
    rasterising uses on the panel, and count the rows with any ink at all.
    31, not `cell_height`'s 33 (ascent + descent, which is headroom no
    glyph actually inks) — the gap between them is a 2px hairline seam
    that stacking by `cell_height` would leave, unlike the pitch
    `test_mono_stacked_bars_meet_seamlessly_at_ink_height` pins below."""
    from PIL import Image, ImageDraw

    f = load_font(font_dir, FONTS["mono"])
    img = Image.new("1", (60, 80), 0)
    dr = ImageDraw.Draw(img)
    dr.text((10, 10), "█", font=f, fill=1)
    px = img.load()
    inked_rows = [y for y in range(80) if any(px[x, y] for x in range(60))]
    assert len(inked_rows) == FONTS["mono"].ink_height == 31


def test_mono_glyph_advance_is_a_constant_integer(font_dir):
    """The whole point of BASIC layout (D11's second finding): every glyph
    advances by the same integer width, `M`/`i`/a block character alike —
    not the fractional 14.4px raqm would use."""
    f = load_font(font_dir, FONTS["mono"])
    advances = {f.getlength(ch) for ch in ("M", "i", "█")}
    assert len(advances) == 1
    (advance,) = advances
    assert advance == int(advance)


def test_mono_angle_brackets_render_as_two_glyphs_not_a_ligature(font_dir):
    """Raqm's default layout turns `<>` into one ligature glyph; BASIC keeps
    it two, so its width equals `<` + `>` measured separately."""
    f = load_font(font_dir, FONTS["mono"])
    assert f.getlength("<>") == f.getlength("<") + f.getlength(">")


def test_mono_box_drawing_run_has_no_gap(font_dir):
    """`┌─┐` as one `text` op: the rule's row has one contiguous run of ink
    with no interior blank column — a fractional advance would have opened
    a 1px gap at the seam between glyphs (D11's second finding)."""
    doc = {
        "v": 1,
        "meta": {},
        "bg": "white",
        "palette": {},
        "ops": [{"op": "text", "x": 40, "y": 40, "s": "┌─┐", "f": "mono"}],
    }
    img, problems = render(doc, font_dir)
    assert problems == []
    px = img.load()
    box = img.getbbox()  # whole canvas is white except the glyphs
    x0, y0, x1, y1 = box
    # the row with the most ink is the horizontal rule's row
    best_y, best_n = None, -1
    for y in range(y0, y1):
        n = sum(px[x, y] != INK["white"] for x in range(x0, x1))
        if n > best_n:
            best_y, best_n = y, n
    inked = [x for x in range(x0, x1) if px[x, best_y] != INK["white"]]
    assert inked == list(range(inked[0], inked[-1] + 1))


def _ink_runs(ys: list[int]) -> list[tuple[int, int]]:
    """Contiguous runs of consecutive integers in sorted `ys`, as
    `[(start, end), ...]` — the "is this ink one connected run or several"
    helper the mono stacking tests share."""
    if not ys:
        return []
    runs = []
    start = prev = ys[0]
    for y in ys[1:]:
        if y != prev + 1:
            runs.append((start, prev))
            start = y
        prev = y
    runs.append((start, prev))
    return runs


def test_mono_stacked_bars_meet_seamlessly_at_ink_height(font_dir):
    """Stacking by `ink_height` (31), not `cell_height` (33), is the pitch
    that makes consecutive block-art rows meet exactly — the two bars' ink
    merges into a single contiguous run, touching with no gap and no
    overlap."""
    ink_height = FONTS["mono"].ink_height
    doc = {
        "v": 1,
        "meta": {},
        "bg": "white",
        "palette": {},
        "ops": [
            {"op": "text", "x": 40, "y": 100, "s": "│", "f": "mono"},
            {"op": "text", "x": 40, "y": 100 + ink_height, "s": "│", "f": "mono"},
        ],
    }
    img, problems = render(doc, font_dir)
    assert problems == []
    px = img.load()
    scan_y = range(90, 100 + ink_height + 40)
    col = max(range(40, 54), key=lambda x: sum(px[x, y] != INK["white"] for y in scan_y))
    ys = [y for y in scan_y if px[col, y] != INK["white"]]
    runs = _ink_runs(ys)
    assert len(runs) == 1, "expected the two bars to meet as a single run, not leave a seam"


def test_mono_missing_face_warns_and_draws_nothing(tmp_path, font_dir):
    """A font directory with Instrument Sans but no JetBrains Mono file
    still renders — `mono` ops are abandoned like an unknown font name,
    the same way the firmware skips an uncompiled one."""
    shutil.copy(font_dir / "InstrumentSans-Regular.ttf", tmp_path / "InstrumentSans-Regular.ttf")
    shutil.copy(font_dir / "InstrumentSans-Bold.ttf", tmp_path / "InstrumentSans-Bold.ttf")
    doc = {
        "v": 1,
        "meta": {},
        "bg": "white",
        "palette": {},
        "ops": [{"op": "text", "x": 40, "y": 40, "s": "hi", "f": "mono"}],
    }
    img, problems = render(doc, tmp_path)
    assert problems == [
        "ops[0] text: font 'mono' is not installed here "
        "(fonts/JetBrainsMono-Regular.ttf); skipped"
    ]
    blank, _ = render({"v": 1, "meta": {}, "bg": "white", "ops": []}, tmp_path)
    assert img.tobytes() == blank.tobytes()  # nothing drawn on the white canvas


def test_instrument_sans_missing_still_raises(tmp_path, font_dir):
    """Unlike `mono`, a missing Instrument Sans file is a hard failure at
    load time (there is nothing to abandon-and-skip a whole render for)."""
    shutil.copy(
        font_dir / "JetBrainsMono-Regular.ttf", tmp_path / "JetBrainsMono-Regular.ttf"
    )
    with pytest.raises(OSError):
        render({"v": 1, "meta": {}, "bg": "white", "ops": []}, tmp_path)


def _footer_ink(img, x0, y0, x1, y1):
    """Count non-background pixels in a box; the sample bg is ink white."""
    bg = img.getpixel((5, 1590))
    return sum(1 for x in range(x0, x1) for y in range(y0, y1) if img.getpixel((x, y)) != bg)


def test_fmt_op_substitutes_fields(font_dir):
    from datetime import datetime

    from display_mcp.render import expand_fields, system_fields

    doc = {"bg": "white", "ops": [{"op": "fmt", "x": 20, "y": 1550, "s": "{hash}@{time24} {time}"}]}
    fields = system_fields(doc, now=datetime(2026, 9, 9, 13, 43))
    assert fields["hash"] == render_hash(doc)[-5:]
    assert fields["battery"].endswith("%") and fields["battv"].endswith("V")
    assert fields["hash16"] == render_hash(doc)
    assert fields["time"] == "1:43 PM"
    assert fields["time24"] == "13:43"
    assert system_fields(doc, now=datetime(2026, 9, 9, 0, 5))["time"] == "12:05 AM"
    text, unknown = expand_fields("a {hash} b {nope} c", fields)
    assert text == f"a {fields['hash']} b {{nope}} c"
    assert unknown == ["nope"]
    img, problems = render(doc, font_dir, now=datetime(2026, 9, 9, 13, 43))
    assert problems == []
    assert _footer_ink(img, 20, 1550, 400, 1580) > 50
    # The values are not part of the hash: moving the op changes it, its text never can.
    moved = {"bg": "white", "ops": [{"op": "fmt", "x": 21, "y": 1550, "s": "{hash}"}]}
    assert render_hash(doc) != render_hash(moved)


def test_fmt_unknown_field_is_a_warning(font_dir):
    doc = {"bg": "white", "ops": [{"op": "fmt", "x": 20, "y": 1550, "s": "{nope}"}]}
    _, problems = render(doc, font_dir)
    assert any("unknown field {nope}" in p for p in problems)


def test_fmt_unknown_font_skips_before_field_expansion(font_dir):
    """The firmware checks the font first and never reaches expand_fmt()
    when it's bad, so a `fmt` op with both an unknown font and an unknown
    field warns about the font only — the same op-abandonment as `text`."""
    doc = {"bg": "white", "ops": [{"op": "fmt", "x": 20, "y": 1550, "s": "{nope}", "f": "huge"}]}
    _, problems = render(doc, font_dir)
    assert problems == ["ops[0] fmt: unknown font 'huge'"]


def test_stale_tone_key_warns_and_draws_full_ink(font_dir):
    """`tone` no longer exists. An op that still carries the key draws at
    full ink — same pixels as the same op without the key — but under D1
    the stray key is now an unknown-field warning rather than a silent
    pass."""
    full = {"bg": "white", "ops": [{"op": "text", "x": 20, "y": 1550, "s": "Rendered", "f": "xs"}]}
    with_stale_tone = {
        "bg": "white",
        "ops": [{"op": "text", "x": 20, "y": 1550, "s": "Rendered", "f": "xs", "tone": "light"}],
    }
    img_full, p1 = render(full, font_dir)
    img_stale, p2 = render(with_stale_tone, font_dir)
    assert p1 == []
    assert p2 == [
        "ops[0] text: no such field 'tone' (text takes x, y, s, c, f, a, w, wrap, lines, lh)"
    ]
    assert img_full.tobytes() == img_stale.tobytes()


def test_unknown_op_has_no_field_noise(font_dir):
    """An unknown op ("hash" -- the retired op, standing in for any
    unknown kind) gets its one "unknown op" problem and nothing else —
    OP_FIELDS is never consulted for a kind it doesn't cover."""
    doc = {"bg": "white", "ops": [{"op": "hash", "x": 1, "y": 1, "bogus": True}]}
    _, problems = render(doc, font_dir)
    assert problems == ["ops[0] hash: unknown op 'hash'"]


# --------------------------------------------------------------------------
# D1: op-level field validation (docs/plans/dragon-feedback.md)
#
# The report wrote c2/mix directly on an op and never saw a warning; the
# renderer silently read only `c`. These pin the fix: any field an op does
# not have is now a problem, c2/mix on an op points at the palette instead
# of the document, and a dict where `c` belongs warns and draws black
# rather than raising.
# --------------------------------------------------------------------------


def test_unknown_field_on_rect_warns(font_dir):
    doc = {"bg": "white", "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "nonsense": 1}]}
    _, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] rect: no such field 'nonsense' (rect takes x, y, w, h, c, fill, t, r)"
    ]


def test_typo_field_colour_warns(font_dir):
    doc = {
        "bg": "white",
        "ops": [{"op": "text", "x": 20, "y": 100, "s": "hi", "f": "sm", "colour": "red"}],
    }
    _, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] text: no such field 'colour' (text takes x, y, s, c, f, a, w, wrap, lines, lh)"
    ]


def test_c2_and_mix_on_an_op_point_at_the_palette_and_draw_unchanged(font_dir):
    with_stray_mix = {
        "bg": "white",
        "ops": [
            {
                "op": "rect",
                "x": 0,
                "y": 0,
                "w": 10,
                "h": 10,
                "c": "red",
                "c2": "yellow",
                "mix": 50,
            }
        ],
    }
    solid = {
        "bg": "white",
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "red"}],
    }
    img_mix, problems = render(with_stray_mix, font_dir)
    img_solid, _ = render(solid, font_dir)
    assert problems == [
        'ops[0] rect: mixes are palette entries — write palette: {name: {c, c2, mix}} '
        'and c: name (docs/SPEC.md "Mixes")'
    ]
    # One warning covers both stray keys, not two.
    assert img_mix.tobytes() == img_solid.tobytes()


def test_dict_in_c_warns_and_draws_black_instead_of_raising(font_dir):
    """Reproduces the report's TypeError (Ctx.ink() hashing a dict) and
    pins the fix: warn with the same palette hint, draw black."""
    doc = {
        "bg": "white",
        "ops": [
            {
                "op": "rect",
                "x": 0,
                "y": 0,
                "w": 10,
                "h": 10,
                "c": {"c": "red", "c2": "yellow", "mix": 50},
            }
        ],
    }
    img, problems = render(doc, font_dir)  # must not raise
    black = {"bg": "white", "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "black"}]}
    img_black, _ = render(black, font_dir)
    assert problems == [
        'ops[0] rect: mixes are palette entries — write palette: {name: {c, c2, mix}} '
        'and c: name (docs/SPEC.md "Mixes")'
    ]
    assert img.tobytes() == img_black.tobytes()


def test_op_field_table_covers_every_op_the_renderer_handles():
    """OP_FIELDS has exactly one entry per op render() dispatches on — the
    sample (checked clean elsewhere) and the many per-field warning tests
    above already exercise what each entry's own fields are."""
    from display_mcp.render import OP_FIELDS

    assert set(OP_FIELDS) == {
        "rect", "line", "circle", "text", "fmt", "icon", "sprite", "poly",
    }


# --------------------------------------------------------------------------
# sprite (docs/plans/dragon-feedback.md D9/B1): pixel art as rows of
# characters, one `cell`x`cell` square per character, coloured by `palette`.
# --------------------------------------------------------------------------


def _sprite_doc(**op_extra):
    op = {
        "op": "sprite", "x": 100, "y": 100, "cell": 10,
        "palette": {"K": "black", "O": "yellow"},
        "rows": ["KKOO..KK"],
    }
    op.update(op_extra)
    return {"bg": "white", "ops": [op]}


def test_sprite_row_draws_expected_rects_and_leaves_transparent_alone(font_dir):
    img, problems = render(_sprite_doc(), font_dir)
    assert problems == []
    px = img.load()
    # 'K' run at cols 0-1: centres x=105,115, y=105
    assert px[105, 105] == INK["black"]
    assert px[115, 105] == INK["black"]
    # 'O' run at cols 2-3: centres x=125,135
    assert px[125, 105] == INK["yellow"]
    assert px[135, 105] == INK["yellow"]
    # '.' run at cols 4-5: transparent, the white ground shows through
    assert px[145, 105] == INK["white"]
    assert px[155, 105] == INK["white"]
    # 'K' run at cols 6-7
    assert px[165, 105] == INK["black"]
    assert px[175, 105] == INK["black"]


def test_sprite_mirror_x_flips_the_row(font_dir):
    plain, _ = render(_sprite_doc(), font_dir)
    mirrored, problems = render(_sprite_doc(mirror="x"), font_dir)
    assert problems == []
    px_plain, px_mirror = plain.load(), mirrored.load()
    # The row is "KKOO..KK": mirrored it's "KK..OOKK", so the run that was
    # 'O' (cols 2-3) is now transparent (white), and cols 4-5 (was
    # transparent) are now 'O'.
    assert px_plain[125, 105] == INK["yellow"]
    assert px_mirror[125, 105] == INK["white"]
    assert px_plain[145, 105] == INK["white"]
    assert px_mirror[145, 105] == INK["yellow"]


def test_sprite_unknown_character_warns_once_and_draws_black(font_dir):
    doc = _sprite_doc(rows=["KQQ.Q"])
    img, problems = render(doc, font_dir)
    assert problems == ["ops[0] sprite: no palette entry for 'Q'; drawing black"]
    px = img.load()
    assert px[115, 105] == INK["black"]  # the 'Q' run drew black


def test_sprite_palette_entry_that_is_an_object_warns_with_the_mix_hint(font_dir):
    doc = _sprite_doc(palette={"K": {"c": "red", "c2": "yellow", "mix": 50}}, rows=["K"])
    img, problems = render(doc, font_dir)
    assert problems == [
        'ops[0] sprite: mixes are palette entries — write palette: {name: {c, c2, mix}} '
        'and c: name (docs/SPEC.md "Mixes")'
    ]
    assert img.getpixel((105, 105)) == INK["black"]


def test_sprite_ragged_rows_warn_once_and_pad_transparent(font_dir):
    doc = _sprite_doc(rows=["KKK", "K"])
    img, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] sprite: rows are ragged (widths 1..3); short rows padded transparent"
    ]
    px = img.load()
    # Row 1 (short, "K") is padded transparent past its own single 'K'.
    assert px[105, 115] == INK["black"]
    assert px[115, 115] == INK["white"]


def test_sprite_dot_and_space_are_transparent_even_if_palette_defines_them(font_dir):
    doc = _sprite_doc(palette={"K": "black", ".": "red", " ": "blue"}, rows=["K. K"])
    img, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] sprite: sprite palette cannot redefine '.'; it stays transparent",
        "ops[0] sprite: sprite palette cannot redefine ' '; it stays transparent",
    ]
    px = img.load()
    assert px[105, 105] == INK["black"]
    assert px[115, 105] == INK["white"]  # '.' stayed transparent, not red
    assert px[125, 105] == INK["white"]  # ' ' stayed transparent, not blue
    assert px[135, 105] == INK["black"]


@pytest.mark.parametrize(
    ("field", "value"),
    [("cell", 0), ("cell", 1.5), ("cell", True), ("rows", "KK"), ("rows", [1, 2]),
     ("palette", ["K"])],
)
def test_sprite_malformed_required_field_warns_once_and_draws_nothing(font_dir, field, value):
    doc = _sprite_doc(**{field: value})
    img, problems = render(doc, font_dir)
    assert len(problems) == 1
    assert "nothing to draw, skipped" in problems[0]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_sprite_off_canvas_on_the_far_edge_warns(font_dir):
    doc = _sprite_doc(x=1195, cell=40, rows=["KKK"])
    _, problems = render(doc, font_dir)
    assert any("x+cols*cell" in p and "off-canvas" in p for p in problems)


def test_sprite_mixed_cell_dithers_identically_to_a_rect(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"navymix": {"c": "black", "c2": "blue", "mix": 50}},
        "ops": [{"op": "sprite", "x": 40, "y": 40, "cell": 40,
                  "palette": {"K": "navymix"}, "rows": ["K"]}],
    }
    sprite_img, problems = render(doc, font_dir)
    rect_doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"navymix": {"c": "black", "c2": "blue", "mix": 50}},
        "ops": [{"op": "rect", "x": 40, "y": 40, "w": 40, "h": 40, "c": "navymix"}],
    }
    rect_img, _ = render(rect_doc, font_dir)
    assert problems == []
    assert sprite_img.tobytes() == rect_img.tobytes()


def test_sprite_25_percent_mix_on_1px_cell_gets_the_thin_mix_warning(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey25": {"c": "black", "c2": "white", "mix": 25}},
        "ops": [{"op": "sprite", "x": 0, "y": 0, "cell": 1,
                  "palette": {"K": "grey25"}, "rows": ["K"]}],
    }
    problems = check(doc, font_dir)
    assert any(
        "25% mix on a 1x1 fill is too thin to carry the density" in p for p in problems
    )


def test_sprite_c_field_is_no_such_field(font_dir):
    doc = _sprite_doc(c="red")
    _, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] sprite: no such field 'c' (sprite takes x, y, cell, rows, palette, mirror)"
    ]


# ---- sprite: further per-character and per-op edge cases ----


def test_sprite_two_character_palette_key_warns_and_is_ignored(font_dir):
    """A palette key that isn't exactly one character can't identify a
    cell, so it's dropped with a warning; a row that uses it then hits the
    ordinary unknown-character path."""
    doc = _sprite_doc(palette={"KK": "red"}, rows=["K"])
    img, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] sprite: palette key 'KK' is not one character; ignored",
        "ops[0] sprite: no palette entry for 'K'; drawing black",
    ]
    assert img.getpixel((105, 105)) == INK["black"]


def test_sprite_mixed_rows_type_skips_whole_op(font_dir):
    """Any non-string element in `rows` skips the whole op, same as
    `rows` not being a list of strings at all."""
    doc = _sprite_doc(rows=["KK", 5])
    img, problems = render(doc, font_dir)
    assert len(problems) == 1
    assert "nothing to draw, skipped" in problems[0]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_sprite_mirror_other_than_x_warns_and_is_not_mirrored(font_dir):
    """`"x"` is the only legal `mirror` value; anything else warns and
    draws exactly as if `mirror` had been omitted."""
    plain, _ = render(_sprite_doc(), font_dir)
    warned, problems = render(_sprite_doc(mirror="y"), font_dir)
    assert problems == [
        "ops[0] sprite: mirror must be \"x\"; got 'y', not mirrored"
    ]
    assert warned.tobytes() == plain.tobytes()


def test_sprite_drew_nothing_warns_when_the_grid_matches_its_ground(font_dir):
    """Like text/fmt/icon, a sprite that paints nothing visibly
    different from what's already there is a warning, not silence —
    white-on-white here rather than a fully transparent grid, so the
    check has a box to snapshot at all."""
    doc = {
        "bg": "white",
        "ops": [{"op": "sprite", "x": 100, "y": 100, "cell": 10,
                  "palette": {"K": "white"}, "rows": ["K"]}],
    }
    problems = check(doc, font_dir)
    assert any("drew nothing visible" in p for p in problems)


def test_sprite_thin_mix_check_only_fires_for_characters_a_row_actually_uses(font_dir):
    """An unused palette entry has no cell on the grid to be thin, so
    it must not earn the sub-2px density warning that a used one would."""
    doc = {
        "bg": "white",
        "palette": {"grey25": {"c": "black", "c2": "white", "mix": 25}},
        "ops": [{"op": "sprite", "x": 0, "y": 0, "cell": 1,
                  "palette": {"K": "black", "U": "grey25"}, "rows": ["K"]}],
    }
    problems = check(doc, font_dir)
    assert not any("too thin to carry the density" in p for p in problems)


# --------------------------------------------------------------------------
# icon containment
#
# The firmware draws icons with image->draw(), which blits exactly
# get_width() x get_height() with the off pixels skipped (chroma_key). A
# stand-in that spills, or that paints its own background, previews
# differently from what the panel draws.
# --------------------------------------------------------------------------

ICON_CASES = [(name, z) for name in sorted(ICONS) for z in sorted(ICONS[name])]
ICON_IDS = [f"{n}/{z}" for n, z in ICON_CASES]

PAD = 8  # ground left around the box, so spill on any side has room to show


def _draw_one(name, size, ground, ink):
    img = Image.new("RGB", (size + 2 * PAD, size + 2 * PAD), ground)
    draw_icon(ImageDraw.Draw(img), name, PAD, PAD, size, ink)
    return img


def _spill(img, size, ground):
    px = img.load()
    return [
        (x, y)
        for y in range(img.height)
        for x in range(img.width)
        if not (PAD <= x < PAD + size and PAD <= y < PAD + size) and px[x, y] != ground
    ]


@pytest.mark.parametrize(("name", "z"), ICON_CASES, ids=ICON_IDS)
def test_icon_stays_in_its_box_and_paints_only_ink(name, z):
    """The firmware draws icons with image->draw(), which blits exactly
    get_width() x get_height() with the off pixels skipped (chroma_key):
    an icon paints nothing outside its box, paints something inside it,
    and — drawn in ink X on a ground of X — leaves no trace at all, so a
    hole (the moon's crescent, the marker's eye, the bang in the alert
    triangle) stays unpainted rather than filled with white or black.
    """
    size = ICON_SIZES[z]
    ground, ink = (255, 255, 255), (0, 0, 0)
    img = _draw_one(name, size, ground, ink)
    spill = _spill(img, size, ground)
    assert not spill, f"{len(spill)} px outside {size}x{size}, e.g. {spill[:4]}"
    px = img.load()
    inside = sum(
        1
        for y in range(PAD, PAD + size)
        for x in range(PAD, PAD + size)
        if px[x, y] != ground
    )
    assert inside > 0, "drew nothing at all"

    same = (156, 46, 42)
    keyed = _draw_one(name, size, same, same)
    kpx = keyed.load()
    stray = [
        (x, y, kpx[x, y])
        for y in range(keyed.height)
        for x in range(keyed.width)
        if kpx[x, y] != same
    ]
    assert not stray, f"{len(stray)} non-glyph px, e.g. {stray[:4]}"


def test_unknown_icon_placeholder_stays_inside_its_box():
    size = ICON_SIZES["lg"]
    ground = (255, 255, 255)
    img = _draw_one("no-such-icon", size, ground, (0, 0, 0))
    assert not _spill(img, size, ground)


def test_weather_night_is_a_crescent_not_a_disc():
    """The bite out of the moon is transparent, so the ground shows through."""
    size = ICON_SIZES["lg"]
    ground = (255, 255, 255)
    px = _draw_one("weather-night", size, ground, (0, 0, 0)).load()
    cx = cy = PAD + size // 2
    assert px[cx - size // 8, cy] != ground, "left limb should be inked"
    assert px[cx + size // 8, cy] == ground, "crescent's bite should be untouched"


# --------------------------------------------------------------------------
# bilevel text — docs/plans/ink-mixing.md, decision 7
# --------------------------------------------------------------------------


def test_render_emits_only_the_six_inks(sample_doc, font_dir):
    """The panel's fonts are 1 bpp, so nothing it draws is ever a blend.

    Pillow anti-aliases text on an RGB image by default, which would put
    hundreds of impossible colours into the preview if left unguarded.
    """
    img, _ = render(sample_doc, font_dir)
    six = set(INK.values())
    px = img.load()
    strays = {px[x, y] for y in range(HEIGHT) for x in range(WIDTH)} - six
    assert not strays, f"{len(strays)} colours the panel cannot make, e.g. {list(strays)[:4]}"


# --------------------------------------------------------------------------
# ink mixing — docs/plans/ink-mixing.md, decisions 1 and 2
# --------------------------------------------------------------------------


def _share(img, ink, x0, y0, x1, y1):
    """Fraction of the pixels in a box that are exactly `ink`."""
    px = img.load()
    n = sum(px[x, y] == ink for y in range(y0, y1) for x in range(x0, x1))
    return n / ((x1 - x0) * (y1 - y0))


def _one_rect(palette, colour, w=40, h=40):
    return {
        "v": 1,
        "meta": {},
        "bg": "white",
        "palette": palette,
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": w, "h": h, "c": colour}],
    }


@pytest.mark.parametrize("pct,want", [(25, 0.25), (50, 0.50), (75, 0.75), (100, 1.0)])
def test_mix_on_density(pct, want):
    on = sum(mix_on(x, y, pct) for y in range(64) for x in range(64))
    assert on / 4096 == want


def test_mix_on_50_is_the_historic_tone_checkerboard():
    """tone: light has always knocked out (x + y) % 2 == 0. A 50% mix has to
    be that exact set, or every shipped document using tone shifts a pixel."""
    assert all(
        mix_on(x, y, 50) == ((x + y) % 2 == 0) for y in range(64) for x in range(64)
    )


def test_mixed_fill_interleaves_two_inks(font_dir):
    doc = _one_rect({"grey": {"c": "black", "c2": "white", "mix": 25}}, "grey", 100, 100)
    img, problems = render(doc, font_dir)
    assert problems == []
    assert _share(img, INK["white"], 10, 10, 90, 90) == 0.25
    assert _share(img, INK["black"], 10, 10, 90, 90) == 0.75


def test_mixed_text_keeps_both_inks(font_dir):
    """The case decision 3 turns on: a two-ink glyph on a ground that matches
    neither ink keeps full coverage, so both inks land in equal measure."""
    doc = {
        "v": 1,
        "meta": {},
        "bg": "white",
        "palette": {"plum": {"c": "red", "c2": "blue"}},
        "ops": [{"op": "text", "x": 40, "y": 40, "s": "Plum", "f": "xl", "c": "plum"}],
    }
    img, problems = render(doc, font_dir)
    assert problems == []
    px = img.load()
    red = sum(px[x, y] == INK["red"] for y in range(40, 160) for x in range(40, 400))
    blue = sum(px[x, y] == INK["blue"] for y in range(40, 160) for x in range(40, 400))
    assert red > 500 and blue > 500
    assert abs(red - blue) / (red + blue) < 0.05


def test_mixed_bg(font_dir):
    """The panel's fill() is a memset that never reaches draw_pixel_at, so a
    mixed bg is one ink laid down and the other interleaved over it."""
    doc = {
        "v": 1,
        "meta": {},
        "bg": "grey",
        "palette": {"grey": {"c": "black", "c2": "white"}},
        "ops": [],
    }
    img, problems = render(doc, font_dir)
    assert problems == []
    assert _share(img, INK["white"], 0, 0, 200, 200) == 0.5


def test_solid_colours_are_untouched_by_mixing(sample_doc, font_dir):
    """A document whose palette has no mix entries renders as flat ink,
    untouched by the mixing machinery."""
    img, problems = render(sample_doc, font_dir)
    assert problems == []
    px = img.load()
    # A flat stretch of the sample's black header, clear of its two text
    # lines: not one pixel may have been interleaved with anything.
    assert all(px[x, 130] == INK["black"] for x in range(48))


@pytest.mark.parametrize(
    "entry,fragment",
    [
        ({"c": "black"}, "no 'c2'"),
        ({"c": "red", "c2": "red"}, "c2 == c"),
        ({"c2": "red"}, "no 'c'"),
        ({"c": "red", "c2": "blue", "mix": 40}, "rounded to 50"),
        ({"c": "red", "c2": "blue", "mix": 400}, "using 50"),
        ({"c": "puce", "c2": "blue"}, "unknown colour"),
    ],
)
def test_malformed_mix_warns_and_still_draws(font_dir, entry, fragment):
    """Nothing here skips an op; the interpreter always draws something."""
    img, problems = render(_one_rect({"m": entry}, "m"), font_dir)
    assert any(fragment in p for p in problems), problems
    assert img.getpixel((20, 20)) != INK["white"], "the op was skipped"


def test_mixes_may_not_nest(font_dir):
    """A mix of mixes isn't representable in a 2x2 mask."""
    palette = {
        "inner": {"c": "black", "c2": "white"},
        "outer": {"c": "inner", "c2": "red"},
    }
    img, problems = render(_one_rect(palette, "outer"), font_dir)
    assert any("cannot nest" in p for p in problems), problems
    # falls back to inner's own base ink, so the fill is black against red
    assert _share(img, INK["red"], 5, 5, 35, 35) == 0.5
    assert _share(img, INK["black"], 5, 5, 35, 35) == 0.5


def test_mix_may_reference_an_alias(font_dir):
    palette = {"accent": "red", "m": {"c": "accent", "c2": "white"}}
    img, problems = render(_one_rect(palette, "m"), font_dir)
    assert problems == []
    assert _share(img, INK["red"], 5, 5, 35, 35) == 0.5


def test_builtin_mix_needs_no_palette(font_dir):
    """The point of decision 10: `"c": "navy"` works on its own."""
    doc = {"v": 1, "meta": {}, "bg": "white", "ops": [
        {"op": "rect", "x": 0, "y": 0, "w": 60, "h": 60, "c": "navy"}]}
    img, problems = render(doc, font_dir)
    assert problems == []
    assert _share(img, INK["blue"], 5, 5, 55, 55) == 0.5
    assert _share(img, INK["black"], 5, 5, 55, 55) == 0.5


def test_palette_shadows_a_builtin(font_dir):
    """Resolution is base inks -> palette -> built-ins, so a document can
    redefine a built-in name without a firmware change."""
    palette = {"navy": {"c": "red", "c2": "yellow", "mix": 50}}
    img, problems = render(_one_rect(palette, "navy", 60, 60), font_dir)
    assert problems == []
    assert _share(img, INK["red"], 5, 5, 55, 55) == 0.5
    assert _share(img, INK["yellow"], 5, 5, 55, 55) == 0.5


def test_palette_cannot_shadow_a_base_ink(font_dir):
    """The six inks are immutable; they resolve before the palette."""
    palette = {"red": {"c": "blue", "c2": "green", "mix": 50}}
    img, problems = render(_one_rect(palette, "red", 60, 60), font_dir)
    assert problems == []
    assert _share(img, INK["red"], 5, 5, 55, 55) == 1.0


def test_builtin_cannot_nest_inside_a_mix(font_dir):
    """A mix of mixes isn't representable, so a built-in used as c2 warns
    and contributes only its own base ink — matching resolve_solid()."""
    palette = {"m": {"c": "white", "c2": "navy", "mix": 50}}
    img, problems = render(_one_rect(palette, "m", 60, 60), font_dir)
    assert any("built-in mix" in p for p in problems), problems
    # navy degrades to black, so the fill is white + black
    assert _share(img, INK["black"], 5, 5, 55, 55) == 0.5


def test_every_builtin_renders_clean(font_dir):
    """No built-in may trip check() when used as a plain fill — a named
    colour that warns on correct use would be worse than no name at all."""
    for name in sorted(BUILTIN_MIXES):
        doc = {"v": 1, "meta": {}, "bg": "white", "ops": [
            {"op": "rect", "x": 100, "y": 100, "w": 80, "h": 80, "c": name}]}
        assert check(doc, font_dir) == [], name


# --------------------------------------------------------------------------
# ink-mixing warnings — docs/plans/ink-mixing.md "still open" / decisions 2-4
#
# All three are check()-only, the same way bezel_problems() is: render() on
# its own reports only what stops a document from drawing correctly, so a
# bare render() call is unaffected and every test above this block keeps
# passing unchanged.
# --------------------------------------------------------------------------


def _contrast_msgs(problems):
    return [p for p in problems if "below 3:1" in p]


def _mix_shift_msgs(problems):
    return [p for p in problems if "luminance gap" in p]


def _thin_mix_msgs(problems):
    return [p for p in problems if "coordinate parity" in p]


def test_ink_warnings_are_check_only(font_dir):
    """The ink-mixing warnings (contrast floor, an uncompiled glyph, an op
    that drew nothing) are surfaced by check(), not by a bare render()
    call — mirrors bezel_problems(), which behaves the same way. One
    document trips all three: red-on-blue text with an uncompiled arrow
    glyph, and a grey-on-grey line that draws nothing visible."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey": {"c": "black", "c2": "white"}},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "blue"},
            {"op": "text", "x": 20, "y": 20, "s": "Hi →", "f": "lg", "c": "red"},
            {"op": "rect", "x": 0, "y": 250, "w": 300, "h": 100, "c": "grey"},
            {"op": "text", "x": 20, "y": 270, "s": "Hi", "f": "lg", "c": "grey"},
        ],
    }
    _, problems = render(doc, font_dir)
    assert problems == []
    checked = check(doc, font_dir)
    assert _contrast_msgs(checked)
    assert _glyph_msgs(checked)
    assert _drew_nothing_msgs(checked)


# ---- warning 1: contrast floor on text/fmt/icon --------------------------


def test_contrast_warns_below_3_to_1(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "blue"},
            {"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "red"},
        ],
    }
    problems = check(doc, font_dir)
    msgs = _contrast_msgs(problems)
    assert len(msgs) == 1
    assert "ops[1] text: red on blue is 1.3:1 (below 3:1)" in msgs[0]


def test_contrast_does_not_warn_above_floor(font_dir):
    """Black on white — the sample's usual case — clears 3:1 comfortably."""
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [{"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "black"}],
    }
    assert _contrast_msgs(check(doc, font_dir)) == []


def test_contrast_samples_the_ground_a_rect_actually_painted(font_dir):
    """The ground is read off the real canvas, not the document bg — text
    over a yellow rect is judged against yellow, not white."""
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 400, "h": 200, "c": "yellow"},
            {"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "white"},
        ],
    }
    msgs = _contrast_msgs(check(doc, font_dir))
    assert len(msgs) == 1
    assert "white on yellow" in msgs[0]


def test_contrast_ignores_offcanvas_text(font_dir):
    """Nothing to sample: off-canvas text and a zero-area box (an empty
    string) both leave the contrast check with no box to judge."""
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "blue"},
            {"op": "text", "x": 5000, "y": 20, "s": "Hi", "f": "lg", "c": "red"},
        ],
    }
    assert _contrast_msgs(check(doc, font_dir)) == []
    zero_area = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "blue"},
            {"op": "text", "x": 20, "y": 20, "s": "", "f": "lg", "c": "red"},
        ],
    }
    assert _contrast_msgs(check(zero_area, font_dir)) == []


def test_contrast_applies_to_fmt(font_dir):
    """The contrast floor is not specific to `text` — `fmt` and `icon` are
    judged the same way, in the same document."""
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "blue"},
            {"op": "fmt", "x": 20, "y": 20, "s": "{time24}", "f": "lg", "c": "red"},
            {"op": "icon", "x": 20, "y": 100, "n": "check", "z": "sm", "c": "red"},
        ],
    }
    msgs = _contrast_msgs(check(doc, font_dir))
    assert any("ops[1] fmt" in m for m in msgs)
    assert any("ops[2] icon" in m for m in msgs)


def test_contrast_does_not_warn_a_grey_mix_on_white(font_dir):
    """Fixed by the max model. black+white 50% on white is the shipping
    footer stamp, legible on the wall — the old blend model scored it
    2.97:1 and warned on the project's own sample
    (docs/plans/ink-mixing.md, "Known limitation"). A dithered glyph is
    legible if either of its two inks stands out from the ground, so the
    effective ratio is max(contrast(black, white), contrast(white, white))
    = 12.06:1, comfortably above the floor."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey": {"c": "black", "c2": "white"}},
        "ops": [{"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "grey"}],
    }
    assert _contrast_msgs(check(doc, font_dir)) == []


def test_contrast_still_warns_a_mix_whose_both_inks_are_poor(font_dir):
    """The fix targets the check, it does not turn it off: yellow+white 50%
    on white has neither component clearing the floor (yellow-on-white and
    white-on-white are both poor alone), so max is poor too."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"pale": {"c": "yellow", "c2": "white"}},
        "ops": [{"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "pale"}],
    }
    msgs = _contrast_msgs(check(doc, font_dir))
    assert len(msgs) == 1
    assert "pale on white" in msgs[0]
    assert "1.6:1" in msgs[0]


def _grey_doc(order):
    """White `lg` text on a 50% black+white rect, with the mix declared in
    the given ink order. The two orders paint the same ground (a 50%
    checkerboard either way), so they must be judged the same."""
    a, b = order
    return {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey-mid": {"c": a, "c2": b}},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 400, "h": 200, "c": "grey-mid", "fill": True},
            {"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "white"},
        ],
    }


def test_contrast_ground_is_the_colour_a_mix_fuses_to(font_dir):
    """A mixed ground is judged as the single colour it fuses to, not as
    whichever of its inks happened to win a tie.

    White text on `grey-mid` is the case: sampled per pixel the ground is
    black and white tied 50/50, and the tie-break alone decided between
    12.06:1 (silent) and 1.00:1 (warns). Neither is the answer. The ground
    is a fill, and a fill averages its two inks (decision 3), so the ground
    is `#7F7F7C` and the ratio is 2.95 — which is the number SPEC.md's
    mid-tone tier already published for this colour."""
    msgs = _contrast_msgs(check(_grey_doc(("black", "white")), font_dir))
    assert len(msgs) == 1
    assert "white on black+white is 2.9:1" in msgs[0]


def test_contrast_ground_does_not_depend_on_ink_order(font_dir):
    """The same ground written the other way round is the same ground."""
    assert _contrast_msgs(check(_grey_doc(("black", "white")), font_dir)) == _contrast_msgs(
        check(_grey_doc(("white", "black")), font_dir)
    )


def test_contrast_warns_red_white_50_on_pink(font_dir):
    """The one mixed-ground case the wall has actually judged, and it judged
    it poor: docs/plans/ink-mixing.md decision 11, `red/white 50 on pink`,
    2.4:1. Every pixel of that glyph differs from the pixel beneath it — the
    dither lands in counter-phase — so no per-pixel rule catches it. It
    fails because the letterform fuses to the colour the ground fuses to."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"pink": {"c": "white", "c2": "red"}, "ink": {"c": "red", "c2": "white"}},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 400, "h": 200, "c": "pink", "fill": True},
            {"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "ink"},
        ],
    }
    msgs = _contrast_msgs(check(doc, font_dir))
    assert len(msgs) == 1
    assert "2.4:1" in msgs[0]


def test_contrast_does_not_warn_a_mix_on_a_ground_that_suits_it(font_dir):
    """The other side of the same rule: `pink` on `navy` is decision 3's
    "genuine pink" — neither of its inks matches either of the ground's, and
    fusing the ground does not change that."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"pink": {"c": "white", "c2": "red"}, "navy": {"c": "black", "c2": "blue"}},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 400, "h": 200, "c": "navy", "fill": True},
            {"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "pink"},
        ],
    }
    assert _contrast_msgs(check(doc, font_dir)) == []


def test_contrast_does_not_fuse_two_regions_the_eye_can_resolve(font_dir):
    """Fusing is a property of a 1 px dither, not of a box that happens to
    hold two colours. White text sitting mostly on a green rect, overlapping
    the white page at one edge, is judged against green (4.4:1) — averaging
    the whole box instead would invent a mid colour that is nowhere on the
    canvas and warn at 2.8:1. samples/display.json ops[43] is exactly this
    shape, which is how the case was found."""
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 400, "h": 100, "c": "green", "fill": True},
            {"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "white"},
        ],
    }
    assert _contrast_msgs(check(doc, font_dir)) == []


def test_contrast_judges_a_tied_ground_by_its_harder_half(font_dir):
    """When a box really does sit half on one ground and half on another,
    there is no majority to pick and no reason to flip a coin. Both halves
    hold text, so the harder half is the answer — the same rule the wrapped
    text block already follows across its lines."""
    # "Hi" at lg spans x 20..68, so a blue rect ending at x=44 covers
    # exactly half of it and the white page covers the rest.
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 44, "h": 200, "c": "blue", "fill": True},
            {"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "white"},
        ],
    }
    msgs = _contrast_msgs(check(doc, font_dir))
    assert len(msgs) == 1
    assert "white on white is 1.0:1" in msgs[0]


# ---- warning 2: a chromatic mix used as text shifts toward its lighter ink


def test_mix_as_text_warns_for_a_large_chromatic_gap(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"mustard": {"c": "black", "c2": "yellow"}},
        "ops": [{"op": "text", "x": 200, "y": 200, "s": "Hi", "f": "lg", "c": "mustard"}],
    }
    msgs = _mix_shift_msgs(check(doc, font_dir))
    assert len(msgs) == 1
    assert "'mustard'" in msgs[0] and "black+yellow" in msgs[0]
    assert "toward yellow" in msgs[0]


def test_mix_as_text_exempts_black_and_white(font_dir):
    """Grey text is the desired shift, not a defect — it is what the
    shipping footer stamp already relies on."""
    doc = {
        "v": 1, "meta": {}, "bg": "black",
        "palette": {"grey": {"c": "black", "c2": "white"}},
        "ops": [{"op": "text", "x": 200, "y": 200, "s": "Hi", "f": "lg", "c": "grey"}],
    }
    assert _mix_shift_msgs(check(doc, font_dir)) == []


def test_mix_as_text_does_not_warn_below_the_gap_threshold(font_dir):
    """plum (red+blue) has the smallest gap of any chromatic pair, .092 —
    well under the .2 threshold."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"plum": {"c": "red", "c2": "blue"}},
        "ops": [{"op": "text", "x": 200, "y": 200, "s": "Hi", "f": "lg", "c": "plum"}],
    }
    assert _mix_shift_msgs(check(doc, font_dir)) == []


def test_mix_as_text_does_not_apply_to_a_mixed_fill(font_dir):
    """The shift is specific to glyphs, which are too few pixels to
    average — a large fill of the same mix is unaffected."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"mustard": {"c": "black", "c2": "yellow"}},
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "mustard"}],
    }
    assert _mix_shift_msgs(check(doc, font_dir)) == []


# ---- warning: a character the panel has not compiled in (D11) -----------


def _glyph_msgs(problems: list[str]) -> list[str]:
    return [p for p in problems if "has not compiled" in p]


def test_uncompiled_glyphs_warn_on_a_proportional_face(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "ops": [{"op": "text", "x": 100, "y": 300, "s": "a → ☃ █ b", "f": "sm"}],
    }
    msgs = _glyph_msgs(check(doc, font_dir))
    assert len(msgs) == 1
    assert "3 character(s)" in msgs[0]
    assert "→ (U+2192)" in msgs[0]
    assert "☃ (U+2603)" in msgs[0]
    assert "█ (U+2588)" in msgs[0]
    assert "GF_Latin_Core only" in msgs[0]


def test_uncompiled_glyphs_silent_for_mono_block_element(font_dir):
    """`mono` compiles U+2500-U+259F on top of GF_Latin_Core, so the same
    block character that warns on `sm` above is silent here."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "ops": [{"op": "text", "x": 100, "y": 300, "s": "█", "f": "mono"}],
    }
    assert _glyph_msgs(check(doc, font_dir)) == []


def test_uncompiled_glyphs_silent_on_both_samples(sample_doc, sprite_sample_doc, font_dir):
    assert _glyph_msgs(check(sample_doc, font_dir)) == []
    assert _glyph_msgs(check(sprite_sample_doc, font_dir)) == []


def test_uncompiled_glyphs_ignore_fmt_braces_and_space(font_dir):
    """An unexpanded `fmt` field leaves its `{`/`}` literal — not a font
    question — and a space is never counted either, even though both are
    in GF_Latin_Core anyway."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "ops": [{"op": "fmt", "x": 100, "y": 300, "s": "{nope} value", "f": "xs"}],
    }
    assert _glyph_msgs(check(doc, font_dir)) == []


def test_uncompiled_glyphs_ignore_what_fit_line_would_drop(font_dir):
    """The check runs on the text actually drawn, after `fit_line` has
    already truncated it -- a character past the cut point never gets a
    chance to be counted."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "ops": [{"op": "text", "x": 1000, "y": 300, "s": "ok→", "f": "sm", "w": 20}],
    }
    assert _glyph_msgs(check(doc, font_dir)) == []


# ---- warning 3: a feature thinner than 2 px cannot carry 25%/75% ---------


def test_thin_mix_warns_a_1px_line(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey-25": {"c": "black", "c2": "white", "mix": 25}},
        "ops": [{"op": "line", "x": 10, "y": 10, "x2": 500, "y2": 10, "c": "grey-25", "t": 1}],
    }
    msgs = _thin_mix_msgs(check(doc, font_dir))
    assert len(msgs) == 1
    assert "ops[0] line: 25% mix on a 1px line renders at 0% or 50%" in msgs[0]


def test_thin_mix_does_not_warn_a_2px_line(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey-25": {"c": "black", "c2": "white", "mix": 25}},
        "ops": [{"op": "line", "x": 10, "y": 10, "x2": 500, "y2": 10, "c": "grey-25", "t": 2}],
    }
    assert _thin_mix_msgs(check(doc, font_dir)) == []


def test_thin_mix_warns_a_1px_rect_outline(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey-75": {"c": "black", "c2": "white", "mix": 75}},
        "ops": [{"op": "rect", "x": 10, "y": 10, "w": 40, "h": 40, "c": "grey-75",
                  "fill": False, "t": 1}],
    }
    msgs = _thin_mix_msgs(check(doc, font_dir))
    assert len(msgs) == 1
    assert "75% mix on a 1px rect outline renders at 50% or 100%" in msgs[0]


def test_thin_mix_warns_a_filled_rect_thin_in_one_dimension(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey-25": {"c": "black", "c2": "white", "mix": 25}},
        "ops": [{"op": "rect", "x": 10, "y": 10, "w": 1, "h": 40, "c": "grey-25"}],
    }
    msgs = _thin_mix_msgs(check(doc, font_dir))
    assert len(msgs) == 1
    assert "1x40 fill" in msgs[0]


def test_thin_mix_does_not_warn_a_filled_rect_at_least_2px_both_ways(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey-25": {"c": "black", "c2": "white", "mix": 25}},
        "ops": [{"op": "rect", "x": 10, "y": 10, "w": 2, "h": 2, "c": "grey-25"}],
    }
    assert _thin_mix_msgs(check(doc, font_dir)) == []


def test_thin_mix_does_not_warn_50_percent_at_1px(font_dir):
    """50% is parity-independent — exact at any thickness, which is why
    tone: light has never had this problem."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey": {"c": "black", "c2": "white"}},
        "ops": [{"op": "line", "x": 10, "y": 10, "x2": 500, "y2": 10, "c": "grey", "t": 1}],
    }
    assert _thin_mix_msgs(check(doc, font_dir)) == []


# ---- warning 4: the op drew nothing ---------------------------------------
#
# Contrast measures marginal legibility, not absolute invisibility. A mixed
# ink drawn over a ground that is the same two-ink mix, in phase, is
# pixel-identical to what was already there — and scores a comfortable
# contrast ratio while being completely invisible. Rather than model that,
# check() observes it directly: snapshot the op's box, draw, diff.


def _drew_nothing_msgs(problems):
    return [p for p in problems if "drew nothing" in p]


def test_drew_nothing_warns_text_on_a_matching_mixed_ground(font_dir):
    """The case docs/plans/ink-mixing.md's "What the glass showed" records:
    a mix used as both the fill and the text colour is in phase with
    itself, so the glyph vanishes into its own ground."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey": {"c": "black", "c2": "white"}},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 300, "h": 100, "c": "grey"},
            {"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "grey"},
        ],
    }
    msgs = _drew_nothing_msgs(check(doc, font_dir))
    assert len(msgs) == 1
    assert "ops[1] text" in msgs[0]


def test_drew_nothing_warns_icon_in_its_grounds_own_colour(font_dir):
    """Generalises past dithering: solid text/icon in exactly its ground's
    colour is just as invisible, and the same observed check catches it."""
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "black"},
            {"op": "icon", "x": 20, "y": 20, "n": "check", "z": "sm", "c": "black"},
        ],
    }
    msgs = _drew_nothing_msgs(check(doc, font_dir))
    assert len(msgs) == 1
    assert "ops[1] icon" in msgs[0]


def test_drew_nothing_stays_quiet_for_normal_text(font_dir):
    """The common case — text against a ground it actually contrasts with —
    must never trip this, nor an off-canvas op: it draws nothing for an
    uninteresting reason, the same off-canvas skip the contrast check gets."""
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [{"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "black"}],
    }
    assert _drew_nothing_msgs(check(doc, font_dir)) == []
    off_canvas = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [{"op": "text", "x": 5000, "y": 20, "s": "Hi", "f": "lg", "c": "black"}],
    }
    assert _drew_nothing_msgs(check(off_canvas, font_dir)) == []


def test_drew_nothing_stays_quiet_when_the_mix_does_not_match_the_ground(font_dir):
    """Same mixed ink, different ground: the glyph is visibly dithered
    against the plain white page, so nothing should fire."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey": {"c": "black", "c2": "white"}},
        "ops": [{"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "grey"}],
    }
    assert _drew_nothing_msgs(check(doc, font_dir)) == []


# --------------------------------------------------------------------------
# flat colours — render(dithered_colors=False), the MCP preview's mode
# --------------------------------------------------------------------------


# The three "named palette" headings in docs/SPEC.md, in the order they
# appear, mapped to the TIERS value each one means.
_TIER_HEADINGS = (
    ("Dark backgrounds", "dark"),
    ("Light backgrounds", "light"),
    ("Mid-tone", "mid"),
)


def _spec_palette_rows():
    """The named-palette table in docs/SPEC.md, as {name: (c, c2, mix, hex, tier)}.

    Parsed rather than duplicated: the point of the tests below is that the
    published tables, their tier headings, and the renderer cannot drift
    apart, which a second copy of any of this here would defeat. `tier` is
    decided by which of the three tier headings a row's chunk of text falls
    under — the same way a reader of SPEC.md would decide it.
    """
    spec = (ROOT / "docs" / "SPEC.md").read_text()
    section = spec[spec.index("## The named palette") :]
    marks = sorted(
        (m.start(), tier)
        for heading, tier in _TIER_HEADINGS
        for m in re.finditer(re.escape(heading), section)
    )
    rows: dict[str, tuple[str, str, int, str, str]] = {}
    for i, (start, tier) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(section)
        chunk = section[start:end]
        for n, a, b, p, h in re.findall(
            r"`([a-z-]+)` \| (\w+)\+(\w+) (\d+) \| `#([0-9A-F]{6})`", chunk
        ):
            rows[n] = (a, b, int(p), h.lower(), tier)
    return rows


def _spec_palette_hexes():
    """The named-palette table in docs/SPEC.md, as {name: (c, c2, mix, hex)}."""
    return {n: v[:4] for n, v in _spec_palette_rows().items()}


def test_spec_table_covers_every_builtin_mix():
    """Guard for the test below, which is parametrised over BUILTIN_MIXES.

    A name missing from SPEC.md fails loudly on its own (the lookup raises).
    The direction that would pass in silence is the other one: a mix dropped
    from BUILTIN_MIXES simply vanishes from the parametrisation while
    SPEC.md still advertises it. Set equality catches both, and catches a
    reformatted table too — the regex wants uppercase hex, so a changed row
    drops out of the dict rather than matching loosely.
    """
    assert set(_spec_palette_hexes()) == set(BUILTIN_MIXES)


def test_tiers_cover_every_builtin_mix():
    """Same guard as above, for TIERS: every built-in mix has a tier and
    every tier names a real mix — a name dropped from either side would
    otherwise vanish from the parametrised test below in silence."""
    assert set(TIERS) == set(BUILTIN_MIXES)


def test_tiers_match_the_spec_headings():
    """TIERS == {name: tier}, parsed from docs/SPEC.md's own headings
    grouping the named-palette table — not retyped, so the two cannot
    drift apart."""
    assert TIERS == {name: tier for name, (*_, tier) in _spec_palette_rows().items()}


def test_flat_render_lays_down_one_colour_not_a_checkerboard(font_dir):
    """The whole point: no dither to alias. A flat fill is uniform."""
    img, _ = render(_one_rect({}, "teal"), font_dir, dithered_colors=False)
    assert _share(img, img.load()[0, 0], 0, 0, 40, 40) == 1.0


def test_flat_render_leaves_solid_inks_untouched(sample_doc, font_dir):
    """Ink.avg of a solid is that ink, so a document with no mixes must be
    byte-identical in both modes.

    The sample is nearly that document and drives text, icons and lines
    through paint_op rather than the single rect these tests mostly use —
    but its footer stamp is `grey-mid`, a built-in mix (SPEC.md: black text
    on white reads 12.1:1 there). Swapping that one colour for a solid ink
    is what makes the document mix-free.
    """
    doc = copy.deepcopy(sample_doc)
    for op in doc["ops"]:
        if op.get("c") == "grey-mid":
            op["c"] = "black"
    assert all(op.get("c") != "grey-mid" for op in doc["ops"])
    dithered, _ = render(doc, font_dir)
    flat, _ = render(doc, font_dir, dithered_colors=False)
    assert dithered.tobytes() == flat.tobytes()


def test_ink_order_cannot_change_a_flat_mix(font_dir):
    """The bug this mode exists to kill.

    A 50% checkerboard of two inks is symmetric, so {c: blue, c2: green} and
    {c: green, c2: blue} are the same colour. Dithered they differ by one
    pixel of phase, which a viewer that scales the PNG down resolves to
    *opposite* solid inks — dark green versus blue-violet — and they read as
    unrelated colours. Flat, they are byte-identical.
    """
    ab = _one_rect({"m": {"c": "blue", "c2": "green", "mix": 50}}, "m")
    ba = _one_rect({"m": {"c": "green", "c2": "blue", "mix": 50}}, "m")
    flat_ab, _ = render(ab, font_dir, dithered_colors=False)
    flat_ba, _ = render(ba, font_dir, dithered_colors=False)
    assert flat_ab.tobytes() == flat_ba.tobytes()
    # ... and dithered they are genuinely one pixel out of phase, which is
    # correct and is exactly what aliases.
    dith_ab, _ = render(ab, font_dir)
    dith_ba, _ = render(ba, font_dir)
    assert dith_ab.tobytes() != dith_ba.tobytes()
    assert _share(dith_ab, INK["green"], 0, 0, 40, 40) == 0.5
    assert _share(dith_ba, INK["green"], 0, 0, 40, 40) == 0.5


def test_dithering_is_still_the_default(font_dir):
    """render() defaults to what the panel does, so check(), the CLI and the
    firmware-parity tests get the real thing without asking."""
    img, _ = render(_one_rect({}, "teal"), font_dir)
    assert _share(img, INK["green"], 0, 0, 40, 40) == 0.5
    assert _share(img, INK["blue"], 0, 0, 40, 40) == 0.5


def test_flat_mixed_background_is_uniform(font_dir):
    """The bg takes its own code path (a memset, not draw_pixel_at), so it
    needs its own guard against the interleave loop running anyway."""
    doc = {"v": 1, "meta": {}, "bg": "grey-mid", "palette": {}, "ops": []}
    img, _ = render(doc, font_dir, dithered_colors=False)
    assert _share(img, (127, 127, 124), 0, 0, WIDTH, HEIGHT) == 1.0


def test_ink_avg_agrees_with_the_ground_fusing_in_grounds(font_dir):
    """`Ink.avg` and `_grounds` compute the same physics by different routes.

    `Ink.avg` blends from the colour spec (two inks and a density) and is
    what a flat preview *paints*; `_grounds` averages the real pixels in a
    2x2 mask tile and is what `check()` *measures* contrast against. Neither
    can use the other — `_grounds` is handed arbitrary canvas pixels and has
    no Ink to consult, `Ink.avg` runs before anything is painted — so the
    agreement is a coincidence of two formulas rather than one definition,
    and nothing else would notice if they drifted apart.

    It matters because they meet in `preview`: the image is painted at
    Ink.avg and the warnings shipped beside it are judged against the fused
    ground. Drift means showing a colour we are not judging you against,
    which is the failure this whole tool change exists to remove.
    """
    for name in BUILTIN_MIXES:
        img, _ = render(_one_rect({}, name), font_dir)
        grounds = _grounds(img, (4, 4, 36, 36))
        assert len(grounds) == 1, f"{name}: a uniform fill should fuse to one colour"
        fused, _counts = grounds[0]
        spec = Ink(INK[BUILTIN_MIXES[name][0]], INK[BUILTIN_MIXES[name][1]], BUILTIN_MIXES[name][2])
        assert tuple(round(v) for v in fused) == spec.avg, name


def test_warn_ink_is_rejected_on_a_flat_canvas(font_dir):
    """The combination has no valid caller: a fused blend has no ink
    name, so allowing it would produce a garbled message like
    "white on ink is 3.0:1". Rejecting it keeps Ctx.name_of's invariant
    true rather than merely documented."""
    with pytest.raises(ValueError, match="dithered"):
        render(_one_rect({}, "teal"), font_dir, warn_ink=True, dithered_colors=False)


def test_flat_and_dithered_differ_in_colour_only_never_geometry(font_dir):
    """paint() claims a flat mix takes the same single-draw path a solid ink
    does, so flattening cannot move a pixel.

    Every op type that reaches paint_op, all drawn in `navy` (black+blue).
    Neither of its inks is the white page, so "differs from the background"
    is a faithful stencil in both modes — with a mix containing white, like
    `grey-mid`, half the dithered pixels are the background colour and the
    comparison measures the mix rather than the geometry.
    """
    doc = {
        "v": 1,
        "meta": {},
        "bg": "white",
        "palette": {},
        "ops": [
            {"op": "rect", "x": 40, "y": 40, "w": 300, "h": 120, "c": "navy"},
            {"op": "rect", "x": 40, "y": 200, "w": 300, "h": 120, "t": 4, "c": "navy"},
            {"op": "line", "x": 40, "y": 360, "x2": 340, "y2": 420, "t": 5, "c": "navy"},
            {"op": "circle", "x": 500, "y": 120, "r": 60, "c": "navy"},
            {"op": "circle", "x": 500, "y": 300, "r": 60, "t": 3, "c": "navy"},
            {"op": "text", "x": 40, "y": 470, "s": "Geometry", "f": "xl", "c": "navy"},
            {"op": "text", "x": 40, "y": 600, "w": 300, "s": "A wrapped block of text "
             "that runs to several lines", "f": "md", "c": "navy"},
            {"op": "fmt", "x": 40, "y": 800, "s": "hash {hash}", "f": "sm", "c": "navy"},
            {"op": "icon", "x": 700, "y": 120, "n": "weather-sunny", "z": "lg", "c": "navy"},
            {"op": "icon", "x": 700, "y": 300, "n": "check", "z": "sm", "c": "navy"},
        ],
    }
    dithered, pd = render(doc, font_dir)
    flat, pf = render(doc, font_dir, dithered_colors=False)
    assert pd == pf == []
    white = INK["white"]
    dp, fp = dithered.load(), flat.load()
    drawn_d = {(x, y) for y in range(HEIGHT) for x in range(WIDTH) if dp[x, y] != white}
    drawn_f = {(x, y) for y in range(HEIGHT) for x in range(WIDTH) if fp[x, y] != white}
    assert drawn_d and drawn_d == drawn_f


def test_render_no_longer_exposes_the_ideal_table(font_dir):
    """The flag's removal is pinned in test_cli; this pins the table, which
    is the half that a future caller could still reach."""
    import display_mcp.render as mod

    assert not hasattr(mod, "IDEAL")


# ---- the D1 rule, "warn and draw, never raise", at every JSON shape --------
#
# The first cut of D1 caught a dict in `c` and then raised one field to the
# left of it: a dict in `op` crashed the table lookup. These pin every
# non-string shape a document can put where the renderer expects a name or
# an object, so validate/preview report a problem instead of failing.


@pytest.mark.parametrize(
    "kind",
    [{"c": "red", "c2": "yellow", "mix": 50}, ["rect"], 7, None],
    ids=["dict", "list", "int", "null"],
)
def test_non_string_op_kind_warns_and_does_not_raise(font_dir, kind):
    doc = {"v": 1, "bg": "white", "ops": [{"op": kind, "x": 0, "y": 0, "w": 10, "h": 10}]}
    problems = check(doc, font_dir)
    assert len(problems) == 1 and "unknown op" in problems[0]


def test_list_valued_palette_entry_warns_and_draws_black(font_dir):
    doc = {
        "v": 1,
        "bg": "white",
        "palette": {"f": ["red"], "g": "h", "h": [1]},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "f"},
            {"op": "rect", "x": 20, "y": 0, "w": 10, "h": 10, "c": "g"},
        ],
    }
    img, problems = render(doc, font_dir)
    assert [p for p in problems if "unknown colour" in p] == [
        "ops[0] rect: unknown colour ['red']",
        "ops[1] rect: unknown colour [1]",
    ]
    assert img.getpixel((5, 5)) == INK["black"]


def test_palette_that_is_not_an_object_is_ignored_with_a_problem(font_dir):
    doc = {"v": 1, "bg": "white", "palette": ["red"], "ops": [
        {"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "navy"}]}
    img, problems = render(doc, font_dir)
    assert problems == ["palette: must be an object, not list"]
    assert img.getpixel((0, 0)) in (INK["black"], INK["blue"])  # navy still resolves


def test_op_that_is_not_an_object_is_skipped_with_a_problem(font_dir):
    doc = {"v": 1, "bg": "white", "ops": ["rect", None, {"op": "text", "x": 5, "y": 5, "s": "hi"}]}
    problems = check(doc, font_dir)
    assert problems[:2] == ["ops[0]: not an object, skipped", "ops[1]: not an object, skipped"]
    assert all("ops[2]" not in p or "bezel" in p for p in problems[2:])


def test_mix_hint_appears_once_when_c_is_an_object_and_c2_mix_are_also_present(font_dir):
    """The dragon's own shape, both mistakes at once: one hint, not two."""
    doc = {"v": 1, "bg": "white", "ops": [{
        "op": "rect", "x": 0, "y": 0, "w": 10, "h": 10,
        "c": {"c": "red", "c2": "yellow", "mix": 50}, "c2": "yellow", "mix": 50}]}
    problems = check(doc, font_dir)
    assert sum("mixes are palette entries" in p for p in problems) == 1


# --------------------------------------------------------------------------
# Ctx() — load_fonts / font_dir contract
# --------------------------------------------------------------------------


def test_ctx_with_no_font_dir_defaults_to_no_fonts_loaded():
    """`Ctx(doc)` with no `font_dir` is a valid colour-only context, not
    a `TypeError` out of `Path(None)`."""
    ctx = Ctx({"bg": "white"})
    assert ctx.fonts == {}


def test_ctx_load_fonts_true_without_font_dir_is_a_clear_valueerror():
    with pytest.raises(ValueError, match="load_fonts needs a font_dir"):
        Ctx({"bg": "white"}, load_fonts=True)


def test_ctx_font_dir_alone_still_loads_fonts_by_default(font_dir):
    ctx = Ctx({"bg": "white"}, font_dir)
    assert set(ctx.fonts) == set(FONTS)


# --------------------------------------------------------------------------
# document_colors() — the effective colour of every name a document meets,
# and the problems resolving them turned up
# --------------------------------------------------------------------------


def _hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def test_document_colors_covers_bg_op_colours_and_palette_keys():
    """Every name the document actually references shows up once: `bg`,
    every op's `c` (including a sprite's own palette and a poly's `c`), an
    `icon` op's `bgc`, and every palette key — even a palette entry
    nothing draws with."""
    doc = {
        "v": 1,
        "bg": "white",
        "palette": {
            "accent": "red",
            "flame": {"c": "red", "c2": "yellow", "mix": 50},
            "unused": "blue",
        },
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "accent"},
            {"op": "icon", "x": 0, "y": 0, "n": "check", "z": "sm", "bgc": "flame"},
            {"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "navy"},
            {"op": "sprite", "x": 0, "y": 0, "cell": 10,
             "palette": {"K": "black", "O": "flame"}, "rows": ["KO"]},
            {"op": "poly", "pts": [[0, 0], [10, 0], [5, 10]], "c": "teal"},
        ],
    }
    colors, problems = document_colors(doc)
    assert problems == []
    assert set(colors) == {"white", "accent", "flame", "navy", "unused", "black", "teal"}


def test_document_colors_builtin_mix_reports_its_recipe_and_the_spec_hex():
    """A built-in mix's recipe names its two base inks and density; its hex
    is exactly what docs/SPEC.md publishes for it (parsed, not retyped)."""
    doc = {"v": 1, "bg": "white", "ops": [
        {"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "navy"}]}
    c, c2, pct, want_hex = _spec_palette_hexes()["navy"]
    colors, _ = document_colors(doc)
    assert colors["navy"] == {
        "recipe": f"{c}+{c2} {pct}",
        "hex": f"#{want_hex.upper()}",
    }


def test_document_colors_document_palette_mix_reports_its_recipe():
    doc = {
        "v": 1,
        "bg": "white",
        "palette": {"flame": {"c": "red", "c2": "yellow", "mix": 50}},
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "flame"}],
    }
    colors, _ = document_colors(doc)
    got = colors["flame"]
    assert got["recipe"] == "red+yellow 50"
    assert got["hex"] == _hex(Ink(INK["red"], INK["yellow"], 50).avg)


def test_document_colors_alias_reports_what_it_resolves_to():
    doc = {
        "v": 1,
        "bg": "white",
        "palette": {"accent": "red"},
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "accent"}],
    }
    colors, _ = document_colors(doc)
    assert colors["accent"] == {"recipe": "ink", "hex": _hex(INK["red"])}


def test_document_colors_unknown_name_is_absent_and_still_a_check_warning(font_dir):
    doc = {"v": 1, "bg": "white", "ops": [
        {"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "nope"}]}
    colors, _ = document_colors(doc)
    assert "nope" not in colors
    assert any("unknown colour" in p for p in check(doc, font_dir))


def test_document_colors_skips_a_non_string_colour_value():
    """A dict in `c` (the dragon's own mistake) is skipped, not a key —
    `check()` still warns about it (D1); this just never raises resolving
    something that was never a name."""
    doc = {"v": 1, "bg": "white", "ops": [
        {"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10,
         "c": {"c": "red", "c2": "yellow", "mix": 50}}]}
    colors, _ = document_colors(doc)
    assert set(colors) == {"white"}


def test_document_colors_ignores_bgc_on_a_non_icon_op():
    """`bgc` is only a field `icon` reads; on any other op it is an unknown
    field (`_op_field_problems` already warns) and must not contribute a
    colour here."""
    doc = {"v": 1, "bg": "white", "ops": [
        {"op": "text", "x": 0, "y": 0, "s": "hi", "c": "black", "bgc": "red"}]}
    colors, _ = document_colors(doc)
    assert "red" not in colors


def test_document_colors_reads_bgc_on_an_icon_op():
    doc = {"v": 1, "bg": "white", "ops": [
        {"op": "icon", "x": 0, "y": 0, "n": "check", "z": "sm", "bgc": "red"}]}
    colors, _ = document_colors(doc)
    assert "red" in colors


def test_document_colors_reports_a_malformed_mix_entry_nothing_draws_with():
    """A palette entry no op ever references: `check()` has no reason to
    visit it, so today this reported as a plain (black) ink with no
    warning anywhere. document_colors() now surfaces the problem itself,
    `where`d as its own palette key so it reads as a palette complaint,
    not an op's."""
    doc = {"v": 1, "bg": "white", "palette": {"broken": {"c2": "red"}}, "ops": []}
    colors, problems = document_colors(doc)
    assert colors["broken"] == {"recipe": "ink", "hex": _hex(INK["black"])}
    assert problems == ["palette 'broken': mix 'broken' has no 'c'; using black"]


def test_document_colors_reports_an_unresolvable_alias_entry():
    doc = {"v": 1, "bg": "white", "palette": {"ghost": "nope"}, "ops": []}
    colors, problems = document_colors(doc)
    assert "ghost" not in colors
    assert problems == ["palette 'ghost': unknown colour 'nope'"]


def test_check_and_document_colors_merge_does_not_duplicate(font_dir):
    """validate()'s merge (mcp_server._merge_color_problems) is a plain
    function pinned directly in tests/test_mcp.py; this is the end-to-end
    half, against the real `check()`: an op that already uses a malformed
    palette mix must earn that warning once from check(), once (under a
    different `where`) from document_colors() — and the merge collapses
    them to one."""
    from display_mcp.mcp_server import _merge_color_problems

    doc = {
        "v": 1,
        "bg": "white",
        "palette": {"broken": {"c2": "red"}},
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "broken"}],
    }
    problems = check(doc, font_dir)
    assert any("mix 'broken' has no 'c'" in p for p in problems)  # check() saw it too
    _colors, color_problems = document_colors(doc)
    merged = _merge_color_problems(problems, color_problems)
    assert sum("mix 'broken' has no 'c'" in w for w in merged) == 1


@pytest.mark.parametrize(
    "doc",
    [
        None,
        "not a document",
        {},
        {"ops": "not-a-list"},
        {"bg": "white", "palette": ["not", "a", "dict"]},
        {"bg": 123, "ops": [1, None, "x", {"op": "rect"}]},
    ],
)
def test_document_colors_never_raises_on_a_malformed_document(doc):
    document_colors(doc)  # only requirement: no exception


# --------------------------------------------------------------------------
# swatch_document() / swatch_groups() — docs/plans/ink-mixing.md's closing
# coupon: every named colour as a chip, and the sheet is itself a document
# --------------------------------------------------------------------------


def test_swatch_document_validates_clean(font_dir):
    """The whole point of building it as an ordinary document: it has to
    pass the same bezel/contrast/off-canvas checks any other one does."""
    assert check(swatch_document(), font_dir) == []


def test_swatch_groups_covers_every_ink_and_builtin_exactly_once():
    groups = swatch_groups()
    labels = [label for _title, entries in groups for label, *_ in entries]
    assert sorted(labels) == sorted(set(COLORS) | set(BUILTIN_MIXES))
    assert len(labels) == len(COLORS) + len(BUILTIN_MIXES)  # no duplicate
    assert [title for title, _ in groups] == ["inks", "dark", "light", "mid"]


def test_every_builtin_flat_chip_matches_its_spec_hex(font_dir):
    """Renders swatch_document() flat once (dithered_colors=False, as the
    MCP tool renders it) and, for every built-in, checks BUILTIN_MIXES'
    recipe against docs/SPEC.md and the chip-centre pixel against the
    documented hex -- one render for the whole sheet rather than one per
    name. Also covers that every ink and builtin gets exactly one chip."""
    doc = swatch_document()
    rect_colors = {op["c"] for op in doc["ops"] if op["op"] == "rect"}
    assert rect_colors == set(COLORS) | {f"sw:{name}" for name in BUILTIN_MIXES}
    assert check(doc, font_dir) == []
    img, problems = render(doc, font_dir, dithered_colors=False)
    assert problems == []
    px = img.load()
    hexes = _spec_palette_hexes()
    for name in sorted(BUILTIN_MIXES):
        c, c2, pct, want = hexes[name]
        assert BUILTIN_MIXES[name] == (c, c2, pct), name
        chip = next(op for op in doc["ops"] if op["op"] == "rect" and op["c"] == f"sw:{name}")
        cx, cy = chip["x"] + chip["w"] // 2, chip["y"] + chip["h"] // 2
        assert _hex(px[cx, cy]).lower() == f"#{want}", name


def test_swatch_document_appends_a_documents_own_palette(font_dir):
    palette = {"flame": {"c": "red", "c2": "yellow", "mix": 50}}
    doc = swatch_document(palette=palette)
    assert check(doc, font_dir) == []
    labels = [op["s"] for op in doc["ops"] if op.get("f") == "sm"]
    assert "flame" in labels
    chip = next(op for op in doc["ops"] if op["op"] == "rect" and op["c"] == "flame")
    img, problems = render(doc, font_dir, dithered_colors=False)
    assert problems == []
    cx, cy = chip["x"] + chip["w"] // 2, chip["y"] + chip["h"] // 2
    assert _hex(img.load()[cx, cy]) == "#B56D2B"  # red+yellow 50, docs/SPEC.md "orange"'s recipe


def test_swatch_document_skips_an_unresolvable_palette_entry():
    groups = swatch_groups(palette={"flame": "red", "ghost": "nope"})
    title, entries = groups[-1]
    assert title == "document palette"
    assert [label for label, *_ in entries] == ["flame"]


def test_swatch_document_with_only_unresolvable_palette_entries_adds_no_group():
    groups = swatch_groups(palette={"ghost": "nope"})
    assert [title for title, _ in groups] == ["inks", "dark", "light", "mid"]


def test_swatch_document_a_shadowed_builtin_name_still_shows_canonically(font_dir):
    """SPEC.md: a document's own `navy` shadows the built-in one. The
    "document palette" group should show the document's own colour under
    that name; the canonical `navy` chip earlier on the sheet must not."""
    palette = {"navy": {"c": "red", "c2": "yellow", "mix": 50}}
    doc = swatch_document(palette=palette)
    assert check(doc, font_dir) == []
    canonical = next(op for op in doc["ops"] if op["op"] == "rect" and op["c"] == "sw:navy")
    shadowed = next(op for op in doc["ops"] if op["op"] == "rect" and op["c"] == "navy")
    img, problems = render(doc, font_dir, dithered_colors=False)
    assert problems == []
    px = img.load()
    c, cy = canonical["x"] + canonical["w"] // 2, canonical["y"] + canonical["h"] // 2
    sx, sy = shadowed["x"] + shadowed["w"] // 2, shadowed["y"] + shadowed["h"] // 2
    assert _hex(px[c, cy]) == "#272F50"  # docs/SPEC.md navy: black+blue 50
    assert _hex(px[sx, sy]) == "#B56D2B"  # the document's own red+yellow 50


def test_swatch_document_six_palette_entries_fit_with_no_more_line(font_dir):
    """A group small enough to fit in one row (the built-in groups'
    own size) needs no truncation."""
    palette = {f"c{i}": {"c": "red", "c2": "yellow", "mix": 50} for i in range(6)}
    doc = swatch_document(palette=palette)
    assert check(doc, font_dir) == []
    assert not any(
        op["op"] == "text" and "more not shown" in op["s"] for op in doc["ops"]
    )


@pytest.mark.parametrize("n", [12, 30])
def test_swatch_document_document_palette_overflow_fits_the_page(font_dir, n):
    """The appended "document palette" group is the one group whose
    size isn't fixed — 12 or 30 entries must still lay out only what fits
    `HEIGHT - BEZEL_MARGIN` and summarise the rest, rather than trip a
    bezel warning per row."""
    palette = {f"c{i}": {"c": "red", "c2": "yellow", "mix": 50} for i in range(n)}
    doc = swatch_document(palette=palette)
    assert check(doc, font_dir) == []

    more_ops = [
        op for op in doc["ops"] if op["op"] == "text" and op["s"].endswith("more not shown")
    ]
    assert len(more_ops) == 1
    match = re.match(r"\+(\d+) more not shown$", more_ops[0]["s"])
    assert match is not None
    hidden = int(match.group(1))
    assert hidden > 0

    shown_chips = [
        op
        for op in doc["ops"]
        if op["op"] == "rect" and op.get("fill", True) is not False and op["c"] in palette
    ]
    assert len(shown_chips) + hidden == n

    for op in doc["ops"]:
        if op["op"] == "rect":
            assert op["y"] + op["h"] <= HEIGHT
        else:
            size = FONTS[op.get("f", "xs")].size
            assert op["y"] + size <= HEIGHT


def test_swatch_chip_has_a_black_outline_and_still_validates_clean(font_dir):
    """Every chip — including `white`, otherwise invisible on the white
    page — gets a 1px black rule drawn just outside it, and that outline
    never trips check()'s contrast or bezel checks."""
    doc = swatch_document()
    chips = [
        op for op in doc["ops"] if op["op"] == "rect" and op.get("fill", True) is not False
    ]
    outlines = {
        (op["x"], op["y"]): op
        for op in doc["ops"]
        if op["op"] == "rect" and op.get("fill") is False
    }
    assert len(outlines) == len(chips)
    for chip in chips:
        outline = outlines[(chip["x"] - 1, chip["y"] - 1)]
        assert outline["w"] == chip["w"] + 2
        assert outline["h"] == chip["h"] + 2
        assert outline["c"] == "black"
        assert outline["t"] == 1
        assert outline["x"] > BEZEL_MARGIN  # x-1 stays outside the bezel margin
    assert check(doc, font_dir) == []

    img, problems = render(doc, font_dir, dithered_colors=False)
    assert problems == []
    white_chip = next(op for op in doc["ops"] if op["op"] == "rect" and op["c"] == "white")
    outline = outlines[(white_chip["x"] - 1, white_chip["y"] - 1)]
    assert _hex(img.load()[outline["x"], outline["y"]]) == _hex(INK["black"])


def test_swatch_document_reserved_sw_key_collision_favours_the_canonical_chip(font_dir):
    """A document palette entry literally named `sw:navy` must not
    shadow the reserved key `swatch_document()` uses for navy's own chip —
    the reserved key always wins."""
    palette = {"sw:navy": {"c": "red", "c2": "yellow", "mix": 50}}
    doc = swatch_document(palette=palette)
    assert check(doc, font_dir) == []
    assert doc["palette"]["sw:navy"] == {"c": "black", "c2": "blue", "mix": 50}

    groups = swatch_groups(palette=palette)
    # The one entry the caller passed collided with a reserved key and is
    # skipped rather than misrepresented, so there is nothing left to put
    # in a "document palette" group.
    assert [title for title, _ in groups] == ["inks", "dark", "light", "mid"]

    canonical = next(op for op in doc["ops"] if op["op"] == "rect" and op["c"] == "sw:navy")
    img, problems = render(doc, font_dir, dithered_colors=False)
    assert problems == []
    cx, cy = canonical["x"] + canonical["w"] // 2, canonical["y"] + canonical["h"] // 2
    assert _hex(img.load()[cx, cy]) == "#272F50"  # docs/SPEC.md navy, not the collision's recipe


# --------------------------------------------------------------------------
# poly (docs/plans/dragon-feedback.md D12): a point list, filled by the
# shared even-odd scanline rule or outlined edge by edge. The fill is
# pixel-diffed against the firmware in tests/test_firmware_parity.py; these
# pin the Python side's own behaviour — the geometry rule itself, the
# malformed-input handling, and how it shares the warnings every other op
# already has.
# --------------------------------------------------------------------------


def test_poly_fill_right_triangle_pixel_count_matches_the_closed_form(font_dir):
    """The rule itself (D12): for scanline y, the only two edges that cross
    it are the vertical leg (always at x=ox) and the hypotenuse (at
    `ox + W + (-y' * W) // H`, y' being the row within the triangle) — a
    closed-form sum over the fill rule, computed independently of
    `_poly_spans`, so this pins the *definition*, not just the code that
    implements it."""
    ox, oy, w, h = 20, 30, 60, 45
    pts = [[ox, oy], [ox + w, oy], [ox, oy + h]]
    expected = sum((w + (-y * w) // h) + 1 for y in range(h))
    doc = {"bg": "white", "ops": [{"op": "poly", "pts": pts, "c": "black"}]}
    img, problems = render(doc, font_dir)
    assert problems == []
    px = img.load()
    drawn = sum(
        1
        for y in range(oy - 2, oy + h + 3)
        for x in range(ox - 2, ox + w + 3)
        if px[x, y] == INK["black"]
    )
    assert drawn == expected


def test_poly_fill_concave_shape_leaves_the_notch_unfilled(font_dir):
    """An L-shaped hexagon: the missing quadrant — its concave notch —
    stays background, not the ground a bounding-box fill would give it."""
    doc = {
        "bg": "white",
        "ops": [
            {
                "op": "poly",
                "pts": [[0, 0], [80, 0], [80, 40], [40, 40], [40, 80], [0, 80]],
                "c": "black",
            }
        ],
    }
    img, problems = render(doc, font_dir)
    assert problems == []
    px = img.load()
    assert px[60, 60] == INK["white"]  # inside the missing quadrant
    assert px[20, 60] == INK["black"]  # the vertical arm of the L
    assert px[60, 20] == INK["black"]  # the horizontal arm of the L
    assert px[10, 10] == INK["black"]  # the outer corner


def test_poly_fill_bowtie_fills_both_lobes(font_dir):
    """Two triangles sharing a vertex, drawn as one self-touching path —
    both lobes fill solidly; only the shared vertex itself is a single
    point, never a hole."""
    doc = {
        "bg": "white",
        "ops": [{"op": "poly", "pts": [[0, 0], [40, 40], [0, 40], [40, 0]], "c": "red"}],
    }
    img, problems = render(doc, font_dir)
    assert problems == []
    px = img.load()
    assert px[10, 10] == INK["red"]  # top-left lobe
    assert px[30, 10] == INK["red"]  # top-right lobe
    assert px[10, 30] == INK["red"]  # bottom-left lobe
    assert px[30, 30] == INK["red"]  # bottom-right lobe
    assert px[20, 20] == INK["red"]  # the shared vertex itself


def test_poly_fill_even_odd_star_leaves_the_centre_empty(font_dir):
    """A self-overlapping five-point star, drawn as one path: even-odd
    fill leaves the pentagon at its centre unfilled, the classic case a
    non-zero winding-rule fill would get wrong."""
    import math

    cx, cy, r = 100, 100, 80
    pts = [
        [
            round(cx + r * math.cos(-math.pi / 2 + i * (4 * math.pi / 5))),
            round(cy + r * math.sin(-math.pi / 2 + i * (4 * math.pi / 5))),
        ]
        for i in range(5)
    ]
    doc = {"bg": "white", "ops": [{"op": "poly", "pts": pts, "c": "black"}]}
    img, problems = render(doc, font_dir)
    assert problems == []
    px = img.load()
    assert px[cx, cy] == INK["white"]  # the centre — hollow under even-odd
    assert px[cx, cy - r + 2] == INK["black"]  # an outer point — solid


@pytest.mark.parametrize(
    ("pts", "label"),
    [
        ([[1, 1], [2, 2]], "two points"),
        ([[1, 1], [2, 2], [3, "x"]], "a non-pair (bad value)"),
        ([[1, 1], [2, 2], [3, 4, 5]], "a non-pair (wrong length)"),
        ("not a list", "pts a string"),
        (None, "pts missing"),
    ],
)
def test_poly_malformed_pts_warns_once_and_draws_nothing(font_dir, pts, label):
    doc = {"bg": "white", "ops": [{"op": "poly", "pts": pts, "c": "black"}]}
    img, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] poly: poly needs at least three [x, y] points; nothing to draw, skipped"
    ], label
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes(), label


def test_poly_off_canvas_pts_warns(font_dir):
    doc = {
        "bg": "white",
        "ops": [{"op": "poly", "pts": [[-200, -200], [50, -100], [10, 50]], "c": "black"}],
    }
    _, problems = render(doc, font_dir)
    assert any("pts range" in p and "off-canvas" in p for p in problems)


def test_poly_on_canvas_pts_within_tolerance_does_not_warn(font_dir):
    """The same +/-64px tolerance every other op's x/y gets."""
    doc = {
        "bg": "white",
        "ops": [{"op": "poly", "pts": [[-50, -50], [50, -30], [10, 50]], "c": "black"}],
    }
    _, problems = render(doc, font_dir)
    assert problems == []


def test_poly_mixed_fill_dithers_with_absolute_phase_like_a_rect(font_dir):
    """An axis-aligned poly at an odd origin, filled with a mix, must be
    pixel-identical to a `rect` of the same box and colour — proof the
    fill goes through the same `paint()`/absolute-phase machinery, not a
    PIL primitive of its own."""
    x, y, w, h = 7, 11, 20, 14
    poly_doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"navymix": {"c": "black", "c2": "blue", "mix": 50}},
        "ops": [
            {
                "op": "poly",
                "pts": [[x, y], [x + w - 1, y], [x + w - 1, y + h], [x, y + h]],
                "c": "navymix",
            }
        ],
    }
    rect_doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"navymix": {"c": "black", "c2": "blue", "mix": 50}},
        "ops": [{"op": "rect", "x": x, "y": y, "w": w, "h": h, "c": "navymix"}],
    }
    poly_img, p1 = render(poly_doc, font_dir)
    rect_img, p2 = render(rect_doc, font_dir)
    assert p1 == [] and p2 == []
    assert poly_img.tobytes() == rect_img.tobytes()


def test_poly_c_field_resolves_like_any_other_op(font_dir):
    doc = {
        "bg": "white",
        "ops": [{"op": "poly", "pts": [[0, 0], [10, 0], [5, 10]], "c": "not-a-colour"}],
    }
    _, problems = render(doc, font_dir)
    assert problems == ["ops[0] poly: unknown colour 'not-a-colour'"]


def test_poly_unknown_field_warns(font_dir):
    doc = {
        "bg": "white",
        "ops": [{"op": "poly", "pts": [[0, 0], [10, 0], [5, 10]], "bogus": 1}],
    }
    _, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] poly: no such field 'bogus' (poly takes pts, c, fill, t)"
    ]




def test_bezel_problems_ignores_poly():
    """poly has no anchor for the bezel margin to judge — geometry, not
    text/fmt/icon — so bezel_problems() must not even look at it."""
    doc = {
        "bg": "white",
        "ops": [{"op": "poly", "pts": [[0, 0], [10, 0], [5, 10]], "c": "black"}],
    }
    assert bezel_problems(doc) == []


# --------------------------------------------------------------------------
# poly: coordinate and scanline bounds, non-bool `fill`, the thin-mix check
# for poly's fill, and thickness validation shared with line/rect/circle
# (docs/plans/dragon-feedback.md D12).
# --------------------------------------------------------------------------


def test_poly_extreme_coordinate_is_rejected_and_fast(font_dir):
    """A point past `_POLY_MAX_COORD` is malformed and the whole op is
    skipped, rather than the scanline fill walking every row between two
    far-apart y coordinates — e.g. `[[10, -5000000], [20, 5000000], [0, 0]]`
    would otherwise walk five million rows, checked in well under a
    second here."""
    doc = {
        "bg": "white",
        "ops": [{"op": "poly", "pts": [[10, -5000000], [20, 5000000], [0, 0]], "c": "black"}],
    }
    t0 = time.monotonic()
    problems = check(doc, font_dir)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, elapsed
    assert problems == [
        f"ops[0] poly: poly point out of range (|x|,|y| <= {_POLY_MAX_COORD}); "
        "nothing to draw, skipped"
    ]


@pytest.mark.parametrize(
    ("coord", "should_warn"),
    [
        (_POLY_MAX_COORD, False),
        (-_POLY_MAX_COORD, False),
        (_POLY_MAX_COORD + 1, True),
        (-_POLY_MAX_COORD - 1, True),
    ],
)
def test_poly_point_at_the_coordinate_bound(font_dir, coord, should_warn):
    """A point at exactly +/-`_POLY_MAX_COORD` is accepted; one past it
    is skipped."""
    doc = {
        "bg": "white",
        "ops": [{"op": "poly", "pts": [[coord, 0], [0, 100], [100, 100]], "c": "black"}],
    }
    problems = check(doc, font_dir)
    assert any("out of range" in p for p in problems) == should_warn


def test_fill_non_bool_warns_and_uses_true(font_dir):
    """ArduinoJson's `o["fill"] | true` yields the default for anything
    that isn't a JSON bool, while Python's own truthiness would read
    `0`/`null` as falsy — so a non-bool `fill` warns and uses the default
    (`true`) on both sides, for rect, circle and poly alike, instead of
    `"fill": 0` outlining on the panel and filling in the preview."""
    box = (30, 30)
    ops = [
        {"op": "rect", "x": 10, "y": 10, "w": 40, "h": 40, "c": "black", "fill": 0},
        {"op": "circle", "x": 30, "y": 30, "r": 15, "c": "black", "fill": 0},
        {"op": "poly", "pts": [[10, 10], [50, 10], [30, 50]], "c": "black", "fill": 0},
    ]
    for op in ops:
        doc = {"bg": "white", "ops": [op]}
        img, problems = render(doc, font_dir)
        assert any(
            "fill=0" in p and "using true" in p for p in problems
        ), (op["op"], problems)
        assert img.load()[box] == INK["black"], op["op"]


def test_thin_mix_warns_a_poly_fill_sliver(font_dir):
    """A degenerate zero-width poly (three collinear points) fills a
    single-pixel-wide vertical run for 40 scanlines — the same 2px-minimum
    rule a thin rect fill gets (docs/plans/ink-mixing.md decision 2),
    applied to poly's widest span and its scanline count."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey-25": {"c": "black", "c2": "white", "mix": 25}},
        "ops": [{"op": "poly", "pts": [[10, 10], [10, 30], [10, 50]], "c": "grey-25"}],
    }
    msgs = _thin_mix_msgs(check(doc, font_dir))
    assert len(msgs) == 1
    assert "1x40 fill" in msgs[0]


@pytest.mark.parametrize(
    "op",
    [
        {"op": "line", "x": 10, "y": 10, "x2": 400, "y2": 10, "c": "black"},
        {"op": "rect", "x": 10, "y": 10, "w": 40, "h": 40, "c": "black", "fill": False},
        {"op": "circle", "x": 30, "y": 30, "r": 20, "c": "black", "fill": False},
        {"op": "poly", "pts": [[10, 10], [50, 10], [30, 50]], "c": "black", "fill": False},
    ],
    ids=["line", "rect", "circle", "poly"],
)
class TestThicknessIsBoundedAndValidated:
    """A non-numeric `t` warns and uses 1, and a `t` above `_THICK_MAX`
    warns and clamps — one helper shared by line, rect, circle and poly,
    so a bad `t` never raises out of `render()` and never turns one op
    into a multi-second loop."""

    def test_string_t_warns_and_uses_1(self, font_dir, op):
        doc = {"bg": "white", "ops": [dict(op, t="thick")]}
        _, problems = render(doc, font_dir)
        assert any("t='thick'" in p and "using 1" in p for p in problems)

    def test_zero_t_warns_and_uses_1(self, font_dir, op):
        doc = {"bg": "white", "ops": [dict(op, t=0)]}
        _, problems = render(doc, font_dir)
        assert any("t=0" in p and "using 1" in p for p in problems)

    def test_huge_t_warns_and_clamps_fast(self, font_dir, op):
        doc = {"bg": "white", "ops": [dict(op, t=2_000_000)]}
        t0 = time.monotonic()
        _, problems = render(doc, font_dir)
        elapsed = time.monotonic() - t0
        assert elapsed < 2.0, elapsed
        assert any(f"larger than {_THICK_MAX}" in p and "clamped" in p for p in problems)
