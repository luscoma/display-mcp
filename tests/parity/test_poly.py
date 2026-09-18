"""poly, differentially (docs/plans/dragon-feedback.md D12/B4). draw_poly()
and its own poly_spans() -- plus thick_line() and the shared Display::line()
-- are extracted verbatim, compiled, and diffed pixel-for-pixel against
display_mcp.render.render(). Unlike sprite, poly's fill is the one place
the two renderers could genuinely disagree (D12), and its outline is
diffed too, since display_mcp.render draws it with the same Bresenham walk
the header uses rather than PIL's `width=` (see
render.shapes._bresenham_points's own docstring for why that distinction
only matters here).

Needs a host C++ compiler; skips cleanly without one (see conftest.py).
"""

from __future__ import annotations

from display_mcp.render import check, render

from .conftest import _diff


def test_poly_triangle_matches_the_firmware(poly_harness, font_dir):
    op = {"op": "poly", "pts": [[5, 5], [55, 5], [30, 45]], "c": "black"}
    diffs, problems = _diff(poly_harness, font_dir, op, 60, 50)
    assert problems == []
    assert not diffs, diffs[:5]


def test_poly_concave_chevron_matches_the_firmware(poly_harness, font_dir):
    """A concave "V"-notch chevron -- the case a naive bounding-box fill
    would get wrong but the even-odd scanline gets right on both sides."""
    op = {
        "op": "poly",
        "pts": [[0, 0], [20, 0], [35, 20], [20, 40], [0, 40], [15, 20]],
        "c": "navy",
    }
    diffs, problems = _diff(poly_harness, font_dir, op, 40, 45)
    assert problems == []
    assert not diffs, diffs[:5]


def test_poly_bowtie_matches_the_firmware(poly_harness, font_dir):
    """Two triangles sharing a vertex, drawn as one self-touching path --
    the half-open crossing rule has to land the shared vertex on exactly
    one row without leaving a gap, on both sides identically."""
    op = {"op": "poly", "pts": [[0, 0], [40, 40], [0, 40], [40, 0]], "c": "red"}
    diffs, problems = _diff(poly_harness, font_dir, op, 45, 45)
    assert problems == []
    assert not diffs, diffs[:5]


def test_poly_horizontal_edge_matches_the_firmware(poly_harness, font_dir):
    """A pentagon with one flat top edge -- horizontal edges contribute no
    crossings on either side, so this pins that they're skipped the same
    way rather than one side tripping over a zero-length edge."""
    op = {
        "op": "poly",
        "pts": [[10, 0], [30, 0], [40, 20], [20, 35], [0, 20]],
        "c": "blue",
    }
    diffs, problems = _diff(poly_harness, font_dir, op, 45, 40)
    assert problems == []
    assert not diffs, diffs[:5]


def test_poly_negative_and_offcanvas_coords_matches_the_firmware(poly_harness, font_dir):
    """A triangle straddling the top-left corner, partly off-canvas on
    negative coordinates -- both sides have to clip it to the same
    pixels, not merely avoid crashing on it."""
    op = {"op": "poly", "pts": [[-100, -100], [30, -10], [10, 30]], "c": "green"}
    diffs, problems = _diff(poly_harness, font_dir, op, 40, 40)
    assert any("off-canvas" in p for p in problems)
    assert not diffs, diffs[:5]


def test_poly_mixed_fill_at_odd_origin_matches_a_rect(poly_harness, font_dir):
    """An axis-aligned poly at an odd (x, y) with a mixed ink, diffed
    against the C++ raster directly -- proof that poly_spans()'s fill
    dithers with the same absolute phase a `rect` fill does, the way
    test_sprite_3x3_mixed_block_matches_a_rect proves it for sprite.

    This is also the asymmetry docs/SPEC.md "poly" states: x is inclusive of both
    ends (the right edge sits at `x + w - 1`, same as a rect's own
    `[x, x+w-1]`), but the scanline that fills a row is half-open
    (`[min(y0,y1), max(y0,y1))`), so the bottom edge here is `y + h`, not
    `y + h - 1` -- one *past* where a rect's `h`th row would be -- and the
    fill still lands on exactly the same `h` rows a rect of this box would,
    because that last scanline (`y + h`) never gets a crossing.
    """
    x, y, w, h = 7, 11, 20, 14
    op = {
        "op": "poly",
        "pts": [[x, y], [x + w - 1, y], [x + w - 1, y + h], [x, y + h]],
        "c": "navy",
    }
    drew, cpp_px, logs = poly_harness.run(op, 40, 40)
    assert drew and not logs
    rect_doc = {
        "v": 1, "bg": "white",
        "ops": [{"op": "rect", "x": x, "y": y, "w": w, "h": h, "c": "navy"}],
    }
    img, problems = render(rect_doc, font_dir)
    assert problems == []
    px = img.load()
    diffs = [
        (xx, yy, cpp_px[yy][xx], px[xx, yy])
        for yy in range(40)
        for xx in range(40)
        if cpp_px[yy][xx] != px[xx, yy]
    ]
    assert not diffs, diffs[:5]


def test_poly_outline_t3_matches_the_firmware(poly_harness, font_dir):
    """`fill: false` with `t: 3`, including the closing edge."""
    op = {
        "op": "poly",
        "pts": [[10, 10], [50, 10], [50, 40], [10, 40]],
        "c": "black", "fill": False, "t": 3,
    }
    diffs, problems = _diff(poly_harness, font_dir, op, 60, 50)
    assert problems == []
    assert not diffs, diffs[:5]


def test_poly_two_point_pts_warns_and_skips_on_both_sides(poly_harness, font_dir):
    op = {"op": "poly", "pts": [[1, 1], [2, 2]], "c": "black"}
    drew, _px, logs = poly_harness.run(op, 10, 10)
    assert not drew
    assert any("at least three" in log for log in logs)
    problems = check({"v": 1, "bg": "white", "ops": [op]}, font_dir)
    assert any("nothing to draw, skipped" in p for p in problems)


def test_poly_point_out_of_range_warns_and_skips_on_both_sides(poly_harness, font_dir):
    """A point past `kPolyMaxCoord` / `POLY_MAX_COORD`
    (docs/plans/dragon-feedback.md D12) is malformed on both sides, not
    merely off-canvas, so a point millions of units away is rejected
    outright rather than making poly_spans() walk millions of scanlines."""
    op = {"op": "poly", "pts": [[10, -5000000], [20, 5000000], [0, 0]], "c": "black"}
    drew, _px, logs = poly_harness.run(op, 10, 10)
    assert not drew
    assert any("out of range" in log for log in logs)
    problems = check({"v": 1, "bg": "white", "ops": [op]}, font_dir)
    assert any("out of range" in p for p in problems)


def test_poly_canvas_spanning_pts_matches_the_firmware(poly_harness, font_dir):
    """The scanline-range and span-x clamp -- to `[0, height)` and
    `[0, width)`, applied *before* the loop on both sides -- must land on
    exactly the same visible pixels a naive, unclamped fill would have.
    Points well outside the harness's own small canvas (but inside
    `kPolyMaxCoord`) exercise the clamp on both sides identically: the
    firmware's `it.get_width()`/`get_height()` here is the harness's own
    small canvas, while the Python's clamp is always the real 1200x1600 --
    but since the fill is solid well past this window in every direction,
    the two must still agree on every sampled pixel."""
    op = {
        "op": "poly",
        "pts": [[-9000, -9000], [9000, -9000], [9000, 9000], [-9000, 9000]],
        "c": "black",
    }
    diffs, problems = _diff(poly_harness, font_dir, op, 80, 80)
    assert any("off-canvas" in p for p in problems)
    assert not diffs, diffs[:5]


def test_poly_fill_false_0_matches_the_firmware(poly_harness, font_dir):
    """`"fill": 0` is not a JSON bool, so ArduinoJson's `o["fill"] |
    true` reads the default (fills), and the Python side does the same,
    instead of `0`'s truthiness reading it as `fill: false`."""
    op = {
        "op": "poly",
        "pts": [[5, 5], [55, 5], [30, 45]],
        "c": "black",
        "fill": 0,
    }
    diffs, problems = _diff(poly_harness, font_dir, op, 60, 50)
    assert any("fill=0" in p and "using true" in p for p in problems)
    assert not diffs, diffs[:5]
