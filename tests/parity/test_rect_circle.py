"""The rounded rect (docs/plans/dragon-feedback.md D10) and the circle
outline's ring (D9's sibling constant, `t`), both differentially against
the shipped header, both through `rect_harness`/`circle_ring_harness` --
op-JSON in, an RGB raster out, same as sprite/poly. Eyeball, not pixel,
parity with the firmware is the standard for the corner/circle arcs
themselves (both docstrings below say so): PIL's `ellipse` and ESPHome's
own midpoint circle routine round their outlines slightly differently, so
the handful of pixels right at a curve can differ by a pixel between the
two renderers. What the two sides do promise to agree on -- the bounding
box, the straight bands, the ring's own annulus identity -- is pixel-exact
and is what's diffed here.

Needs a host C++ compiler; skips cleanly without one (see conftest.py).
"""

from __future__ import annotations

import math

import pytest
from PIL import Image, ImageDraw

from display_mcp.render import _draw_rounded_rect

from .conftest import WHITE

# --------------------------------------------------------------------------
# rounded rect
# --------------------------------------------------------------------------

#  even, odd, wide, tiny -- one of each shape this construction treats
# differently, not the full cross product.
_ROUNDED_RECT_SIZES = [(40, 40, 10), (41, 41, 20), (60, 30, 14), (7, 7, 3)]


def _cpp_rounded_rect(harness, x, y, w, h, r, pad=4):
    cw, ch = w + 2 * pad, h + 2 * pad
    op = {"x": x + pad, "y": y + pad, "w": w, "h": h, "r": r, "c": "black"}
    _drew, px, _logs = harness.run(op, cw, ch)
    return [[px[yy][xx] != WHITE for xx in range(cw)] for yy in range(ch)], pad


def _python_rounded_rect(x, y, w, h, r, pad=4):
    cw, ch = w + 2 * pad, h + 2 * pad
    img = Image.new("L", (cw, ch), 0)
    dr = ImageDraw.Draw(img)
    _draw_rounded_rect(dr, x + pad, y + pad, w, h, r, 1)
    px = img.load()
    return [[bool(px[xx, yy]) for xx in range(cw)] for yy in range(ch)]


@pytest.mark.parametrize("w,h,r", _ROUNDED_RECT_SIZES)
def test_rounded_rect_bounding_box_matches_the_python(rect_harness, w, h, r):
    """Both sides fill the same `[x, x+w) x [y, y+h)` box overall, whatever
    the corner arcs look like pixel for pixel."""
    x = y = 0
    cpp, pad = _cpp_rounded_rect(rect_harness, x, y, w, h, r)
    py = _python_rounded_rect(x, y, w, h, r, pad)

    def bbox(grid):
        xs = [xx for row in grid for xx, v in enumerate(row) if v]
        ys = [yy for yy, row in enumerate(grid) for v in row if v]
        return min(xs), min(ys), max(xs), max(ys)

    assert bbox(cpp) == bbox(py) == (x + pad, y + pad, x + pad + w - 1, y + pad + h - 1)


@pytest.mark.parametrize("w,h,r", _ROUNDED_RECT_SIZES)
def test_rounded_rect_straight_bands_match_the_python_exactly(rect_harness, w, h, r):
    """The middle band and the two side bands are plain rectangles on both
    sides -- no arc rasterisation involved -- so unlike the corners, these
    must be pixel-identical."""
    x = y = 0
    cpp, pad = _cpp_rounded_rect(rect_harness, x, y, w, h, r)
    py = _python_rounded_rect(x, y, w, h, r, pad)

    bands = []
    if w - 2 * r > 0:
        bands.append((x + r, y, x + w - r, y + h))  # middle band
    if h - 2 * r > 0:
        bands.append((x, y + r, x + r, y + h - r))  # left band
        bands.append((x + w - r, y + r, x + w, y + h - r))  # right band

    for bx0, by0, bx1, by1 in bands:
        for yy in range(by0 + pad, by1 + pad):
            for xx in range(bx0 + pad, bx1 + pad):
                assert cpp[yy][xx] == py[yy][xx], (xx - pad, yy - pad)


# --------------------------------------------------------------------------
# circle t -- draw_circle_ring() is diffed against the *compiled*
# Display::filled_circle() (via circle_ring_harness's own `_shape` field,
# not a Python reimplementation of the midpoint algorithm, which could
# itself disagree with ESPHome's by a pixel): stacking concentric filled
# circles of radius r, r-1, ... would leave single-pixel holes near the
# diagonals from t == 2 up; circle_half_widths()/draw_circle_ring() draw
# an annulus scanline instead.
# --------------------------------------------------------------------------


def _filled_circle_via_harness(harness, cx, cy, radius, n):
    if radius < 0:
        return [[False] * n for _ in range(n)]
    _drew, px, _logs = harness.run(
        {"_shape": "filled_circle", "x": cx, "y": cy, "r": radius, "c": "black"}, n, n
    )
    return [[px[y][x] != WHITE for x in range(n)] for y in range(n)]


def _ring_vs_filled_circles(harness, r: int, t: int, pad: int = 4):
    """(ring pixels, outer pixels, inner pixels), each an n*n bool grid, n
    the harness's own square canvas side. `outer`/`inner` come from the
    harness's `_shape: "filled_circle"` op -- Canvas::filled_circle called
    directly, not through draw_circle_ring -- so this stays an independent
    oracle, the same as when the two were two separate compiled programs."""
    n = 2 * r + 2 * pad + 1
    cx = cy = r + pad
    _drew, ring_px, _logs = harness.run({"x": cx, "y": cy, "r": r, "t": t, "c": "black"}, n, n)
    ring = [[ring_px[y][x] != WHITE for x in range(n)] for y in range(n)]
    outer = _filled_circle_via_harness(harness, cx, cy, r, n)
    inner = _filled_circle_via_harness(harness, cx, cy, r - t, n)
    return ring, outer, inner, n


@pytest.mark.parametrize("r", [0, 1, 2, 3, 6, 20, 60])
@pytest.mark.parametrize("t_offset", [2, 5])  # t relative to nothing; see below
def test_circle_ring_matches_filled_circle_difference(circle_ring_harness, r, t_offset):
    """The annulus equals filled_circle(r) minus filled_circle(r - t),
    pixel for pixel, for every t from 2 up to well past r (where there is
    no inner circle at all)."""
    t = t_offset
    ring, outer, inner, n = _ring_vs_filled_circles(circle_ring_harness, r, t)
    diffs = [
        (x, y)
        for y in range(n)
        for x in range(n)
        if ring[y][x] != (outer[y][x] and not inner[y][x])
    ]
    assert not diffs, diffs[:5]


@pytest.mark.parametrize("r", [5, 40])
def test_circle_ring_past_the_radius_equals_a_plain_filled_circle(circle_ring_harness, r):
    """t >= r + 1 leaves no inner circle at all -- the ring degenerates to
    exactly filled_circle(r), the same identity a t == 1 circle() call is
    kept exact to by not going through the ring at all."""
    t = r + 5
    ring, outer, inner, n = _ring_vs_filled_circles(circle_ring_harness, r, t)
    assert not any(any(row) for row in inner)
    assert ring == outer


@pytest.mark.parametrize("r,t", [(10, 2), (20, 3), (15, 4)])
def test_circle_ring_has_no_diagonal_holes(circle_ring_harness, r, t):
    """The bug this whole fix is for: stacking concentric filled circles of
    shrinking radius left single-pixel background holes near the 45-degree
    diagonals from t == 2 up. Walk the annulus's own outer edge (the
    outermost ring of the disc, taken from filled_circle(r) itself minus
    one step in) and check every one of those pixels is actually lit --
    a hole would show up here first, in the annulus's own boundary."""
    ring, outer, _inner, n = _ring_vs_filled_circles(circle_ring_harness, r, t)
    cx = cy = n // 2
    # Sample the ring at every angle along its own outer radius: this is
    # exactly the outer boundary of filled_circle(r), which the annulus
    # must fully cover (its outer half is that same boundary).
    holes = []
    for deg in range(360):
        th = math.radians(deg)
        x = cx + round(r * math.cos(th))
        y = cy + round(r * math.sin(th))
        if outer[y][x] and not ring[y][x]:
            holes.append((deg, x, y))
    assert not holes, holes[:8]
