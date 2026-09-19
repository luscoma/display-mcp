"""Shapes: rect (including the corner radius, D10/B2), line, circle, and
icons -- their off-canvas checks, and (folded in here rather than a
near-empty file of its own) the bezel margin, since icon placement is what
most of check()'s bezel judging touches.

Fixture note: `font_dir` and `sample_doc` come from tests/conftest.py.
"""

from __future__ import annotations

import copy

import pytest
from PIL import Image, ImageDraw

from display_mcp.render import (
    ICON_SIZES,
    ICONS,
    INK,
    MAX_COORD,
    bezel_problems,
    check,
    draw_icon,
    render,
)

from .conftest import _icon_doc


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


@pytest.mark.parametrize("field", ["x", "y", "w", "h"])
def test_rect_past_the_coordinate_bound_is_skipped(font_dir, field):
    """Full message text, matching display_list.h's own ESP_LOGW verbatim
    (docs/plans/firmware-bounds.md's review amendment) -- the repo
    convention every other shared warning already follows."""
    op = {"op": "rect", "x": 10, "y": 10, "w": 20, "h": 20, "c": "black"}
    op[field] = MAX_COORD + 1
    _, problems = render({"bg": "white", "ops": [op]}, font_dir)
    assert problems == [
        f"ops[0] rect: {field}={MAX_COORD + 1} out of range (|v| <= {MAX_COORD}); skipped"
    ]


def test_rect_at_the_coordinate_bound_is_accepted(font_dir):
    op = {"op": "rect", "x": MAX_COORD, "y": 10, "w": 20, "h": 20, "c": "black"}
    _, problems = render({"bg": "white", "ops": [op]}, font_dir)
    assert not any("out of range" in p for p in problems)


def test_rect_huge_float_coordinate_is_rejected(font_dir):
    """docs/plans/firmware-bounds.md D4's review amendment: ArduinoJson's
    `o["x"] | 0` would silently read 0 for a float like 1e10 -- any JSON
    float fails its `is<int>()` check -- drawing a full-bleed rect at the
    origin on the panel instead of being rejected. The firmware now reads
    every such field as a `double` and bound-checks that; this pins the
    Python mirror (`_coord_bound_problem()`, which already worked directly
    off the raw value) agrees and nothing is drawn."""
    op = {"op": "rect", "x": 1e10, "y": 10, "w": 20, "h": 20, "c": "black"}
    img, problems = render({"bg": "white", "ops": [op]}, font_dir)
    # "1e+10", matching the firmware's own %g -- not repr()'s "10000000000.0"
    # (docs/plans/firmware-bounds.md's review amendment).
    assert problems == [f"ops[0] rect: x=1e+10 out of range (|v| <= {MAX_COORD}); skipped"]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_rect_fractional_coordinate_truncates_toward_zero(font_dir):
    """A legal fractional coordinate lands on the same pixel both sides
    now agree on (docs/plans/firmware-bounds.md D4's review amendment):
    100.5 truncates to 100 and 10.9 to 10, matching C++'s
    `static_cast<int>(double)` -- not Pillow's own (different) rounding
    if the float were handed to it as-is, which is what happened before
    `_int_coord()` existed."""
    frac_doc = {
        "bg": "white",
        "ops": [{"op": "rect", "x": 100.5, "y": 10.9, "w": 20, "h": 20, "c": "black"}],
    }
    int_doc = {
        "bg": "white",
        "ops": [{"op": "rect", "x": 100, "y": 10, "w": 20, "h": 20, "c": "black"}],
    }
    frac_img, frac_problems = render(frac_doc, font_dir)
    int_img, int_problems = render(int_doc, font_dir)
    assert frac_problems == [] and int_problems == []
    assert frac_img.tobytes() == int_img.tobytes()


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


@pytest.mark.parametrize("field", ["x", "y", "x2", "y2"])
def test_line_past_the_coordinate_bound_is_skipped(font_dir, field):
    op = {"op": "line", "x": 0, "y": 0, "x2": 10, "y2": 10, "c": "black"}
    op[field] = MAX_COORD + 1
    _, problems = render({"bg": "white", "ops": [op]}, font_dir)
    assert problems == [
        f"ops[0] line: {field}={MAX_COORD + 1} out of range (|v| <= {MAX_COORD}); skipped"
    ]


def test_circle_past_the_coordinate_bound_is_skipped(font_dir):
    op = {"op": "circle", "x": 0, "y": 0, "r": MAX_COORD + 1, "c": "black"}
    _, problems = render({"bg": "white", "ops": [op]}, font_dir)
    assert problems == [
        f"ops[0] circle: r={MAX_COORD + 1} out of range (|v| <= {MAX_COORD}); skipped"
    ]


def test_circle_at_the_coordinate_bound_is_accepted(font_dir):
    op = {"op": "circle", "x": 0, "y": 0, "r": MAX_COORD, "c": "black"}
    _, problems = render({"bg": "white", "ops": [op]}, font_dir)
    assert not any("out of range" in p for p in problems)


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
