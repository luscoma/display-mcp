"""`poly` (docs/plans/dragon-feedback.md D12): a point list, filled by the
shared even-odd scanline rule or outlined edge by edge. The fill is
pixel-diffed against the firmware in tests/parity/test_poly.py; these pin
the Python side's own behaviour -- the geometry rule itself, the
malformed-input handling, and how it shares the warnings every other op
already has.

Fixture note: `font_dir` comes from tests/conftest.py.
"""

from __future__ import annotations

import time

import pytest

from display_mcp.render import INK, POLY_MAX_COORD, bezel_problems, check, render

from .conftest import _thin_mix_msgs


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


def test_poly_extreme_coordinate_is_rejected_and_fast(font_dir):
    """A point past `POLY_MAX_COORD` is malformed and the whole op is
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
        f"ops[0] poly: poly point out of range (|x|,|y| <= {POLY_MAX_COORD}); "
        "nothing to draw, skipped"
    ]


@pytest.mark.parametrize(
    ("coord", "should_warn"),
    [
        (POLY_MAX_COORD, False),
        (-POLY_MAX_COORD, False),
        (POLY_MAX_COORD + 1, True),
        (-POLY_MAX_COORD - 1, True),
    ],
)
def test_poly_point_at_the_coordinate_bound(font_dir, coord, should_warn):
    """A point at exactly +/-`POLY_MAX_COORD` is accepted; one past it
    is skipped."""
    doc = {
        "bg": "white",
        "ops": [{"op": "poly", "pts": [[coord, 0], [0, 100], [100, 100]], "c": "black"}],
    }
    problems = check(doc, font_dir)
    assert any("out of range" in p for p in problems) == should_warn


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
