"""Document- and op-level field validation: OP_FIELDS coverage, unknown
fields, the D1 "warn and draw, never raise" shape guards for every
malformed JSON shape a document can put where the renderer expects a name
or an object, and the thickness/fill validation shared by line, rect,
circle and poly. Also render_hash/render/check's own top-level contract
against the sample document.

Fixture note: `font_dir` and `sample_doc` come from tests/conftest.py.
"""

from __future__ import annotations

import copy
import time

import pytest
from PIL import ImageDraw

from display_mcp.render import (
    HEIGHT,
    INK,
    THICK_MAX,
    WIDTH,
    check,
    fonts_available,
    render,
    render_hash,
)

SAMPLE_HASH = "3cd62aa76e731d2d"


def test_hash_ignores_meta_generated(sample_doc):
    doc = copy.deepcopy(sample_doc)
    doc["meta"]["generated"] = "some other time entirely"
    assert render_hash(doc) == SAMPLE_HASH


def test_hash_changes_with_an_op(sample_doc):
    doc = copy.deepcopy(sample_doc)
    doc["ops"][0]["x"] += 1
    assert render_hash(doc) != SAMPLE_HASH


def test_render_sample_is_clean(sample_doc, font_dir):
    img, problems = render(sample_doc, font_dir)
    assert img.size == (WIDTH, HEIGHT)
    assert img.mode == "RGB"
    assert problems == []


def test_check_sample_is_clean(sample_doc, font_dir):
    assert check(sample_doc, font_dir) == []


def test_fonts_available_true(font_dir):
    assert fonts_available(font_dir) is True


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
        "ops[0] text: no such field 'tone' (text takes x, y, s, c, f, a, w, wrap, lines, lh, deco)"
    ]
    assert img_full.tobytes() == img_stale.tobytes()


def test_unknown_op_has_no_field_noise(font_dir):
    """An unknown op ("hash" -- the retired op, standing in for any
    unknown kind) gets its one "unknown op" problem and nothing else —
    OP_FIELDS is never consulted for a kind it doesn't cover."""
    doc = {"bg": "white", "ops": [{"op": "hash", "x": 1, "y": 1, "bogus": True}]}
    _, problems = render(doc, font_dir)
    assert problems == ["ops[0] hash: unknown op 'hash'"]


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
        "ops[0] text: no such field 'colour' "
        "(text takes x, y, s, c, f, a, w, wrap, lines, lh, deco)"
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
        "ops[0] rect: mixes are palette entries — put the mix in palette and name "
        "it in c (palette: {name: {c, c2, mix}}, c: name)"
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
        "ops[0] rect: mixes are palette entries — put the mix in palette and name "
        "it in c (palette: {name: {c, c2, mix}}, c: name)"
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


# ---- required fields: missing or mistyped, warn and skip -----------------


def test_missing_required_field_text_warns_and_skips(font_dir):
    """{"op": "text", "x": 100, "y": 100} with no `s` used to raise a bare
    KeyError out of render() (the dragon session's report); it now warns
    and the op is skipped, like an unknown font (docs/plans/
    dragon-feedback.md D1 follow-up)."""
    doc = {"bg": "white", "ops": [{"op": "text", "x": 100, "y": 100, "f": "xs"}]}
    img, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] text: missing field 's' (text needs x, y, s); skipped"
    ]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_mistyped_required_field_string_x_warns_and_skips(font_dir):
    doc = {"bg": "white", "ops": [{"op": "text", "x": "100", "y": 100, "s": "hi"}]}
    img, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] text: x='100' is not a number (text needs x, y, s); skipped"
    ]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_missing_required_field_rect_w_warns_and_skips(font_dir):
    doc = {"bg": "white", "ops": [{"op": "rect", "x": 0, "y": 0, "h": 10}]}
    img, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] rect: missing field 'w' (rect needs x, y, w, h); skipped"
    ]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_bool_required_field_rect_w_warns_and_skips(font_dir):
    """A JSON bool is not the number it subclasses in Python -- `w: true`
    must not be silently read as `1`."""
    doc = {"bg": "white", "ops": [{"op": "rect", "x": 0, "y": 0, "w": True, "h": 10}]}
    img, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] rect: w=True is not a number (rect needs x, y, w, h); skipped"
    ]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_missing_required_field_icon_n_warns_and_skips(font_dir):
    """`n` moved from optional to required (docs/plans/dragon-feedback.md
    D1 follow-up): a missing one no longer reaches render() as `None` and
    warns "'None/sm' is not compiled in" -- it is caught, and the op
    skipped, before dispatch."""
    doc = {"bg": "white", "ops": [{"op": "icon", "x": 0, "y": 0, "z": "sm"}]}
    img, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] icon: missing field 'n' (icon needs x, y, n); skipped"
    ]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_poly_pts_not_a_list_warns_and_skips(font_dir):
    doc = {"bg": "white", "ops": [{"op": "poly", "pts": "nope", "c": "black"}]}
    img, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] poly: pts='nope' is not a list (poly needs pts); skipped"
    ]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_fmt_with_no_s_warns_and_skips(font_dir):
    """`s` stays optional in OP_FIELDS -- a `fmt` legitimately has nothing
    else it must carry -- but an empty or missing template has nothing to
    draw, so it gets its own message and the same skip a missing required
    field gets."""
    doc = {"bg": "white", "ops": [{"op": "fmt", "x": 0, "y": 0}]}
    img, problems = render(doc, font_dir)
    assert problems == ["ops[0] fmt: fmt has no 's' template; nothing to draw"]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_fmt_with_empty_s_warns_and_skips(font_dir):
    doc = {"bg": "white", "ops": [{"op": "fmt", "x": 0, "y": 0, "s": ""}]}
    img, problems = render(doc, font_dir)
    assert problems == ["ops[0] fmt: fmt has no 's' template; nothing to draw"]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_required_field_check_never_raises_through_check(font_dir):
    """The whole family of malformed-required-field docs above, run
    through check() (what `validate` calls) rather than render() directly
    -- must never raise, only warn."""
    docs = [
        {"bg": "white", "ops": [{"op": "text", "x": 100, "y": 100}]},
        {"bg": "white", "ops": [{"op": "rect", "x": 100, "y": 100, "h": 10}]},
        {"bg": "white", "ops": [{"op": "icon", "x": 100, "y": 100}]},
        {"bg": "white", "ops": [{"op": "poly", "pts": "nope"}]},
        {"bg": "white", "ops": [{"op": "fmt", "x": 100, "y": 100}]},
    ]
    for doc in docs:
        problems = check(doc, font_dir)
        assert len(problems) == 1, doc


# ---- circle off-canvas -----------------------------------------------


def test_circle_off_canvas_x_plus_r(font_dir):
    doc = {"bg": "white", "ops": [{"op": "circle", "x": 1250, "y": 100, "r": 30, "c": "black"}]}
    _, problems = render(doc, font_dir)
    assert any("x+r=1280" in p and "off-canvas" in p for p in problems)


def test_circle_off_canvas_x_minus_r(font_dir):
    doc = {"bg": "white", "ops": [{"op": "circle", "x": -80, "y": 100, "r": 10, "c": "black"}]}
    _, problems = render(doc, font_dir)
    assert any("x-r=-90" in p and "off-canvas" in p for p in problems)


def test_circle_off_canvas_y_plus_r(font_dir):
    doc = {"bg": "white", "ops": [{"op": "circle", "x": 100, "y": 1650, "r": 30, "c": "black"}]}
    _, problems = render(doc, font_dir)
    assert any("y+r=1680" in p and "off-canvas" in p for p in problems)


def test_circle_off_canvas_y_minus_r(font_dir):
    doc = {"bg": "white", "ops": [{"op": "circle", "x": 100, "y": -80, "r": 10, "c": "black"}]}
    _, problems = render(doc, font_dir)
    assert any("y-r=-90" in p and "off-canvas" in p for p in problems)


def test_circle_within_tolerance_does_not_warn(font_dir):
    doc = {"bg": "white", "ops": [{"op": "circle", "x": -20, "y": 100, "r": 30, "c": "black"}]}
    _, problems = render(doc, font_dir)
    assert not any("off-canvas" in p for p in problems)


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
    """A non-numeric `t` warns and uses 1, and a `t` above `THICK_MAX`
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
        assert any(f"larger than {THICK_MAX}" in p and "clamped" in p for p in problems)


# ---- F1 fuzz: every JSON-legal shape that used to raise out of check() ---
#
# The dragon session's fuzzing turned up a handful of shapes the specific
# per-field checks above didn't cover: a rect with a zero/negative w or h
# (PIL's own ValueError), f/a/z holding an unhashable value like a list or
# object (TypeError out of a dict/set lookup), wrap:true with lines:0
# (wrap_lines() indexing an empty list) and meta not being an object
# (AttributeError). Each now warns exactly once through check() and never
# raises; coordinates are chosen clear of the 24px bezel margin so the
# warning pinned is the *only* one -- bezel_problems() reads an op's x/y
# straight off the document regardless of whether render() went on to skip
# that op.


@pytest.mark.parametrize(
    ("op", "expect_substrings"),
    [
        ({"op": "rect", "x": 100, "y": 100, "w": 0, "h": 10}, ["w=0", "must be positive"]),
        ({"op": "rect", "x": 100, "y": 100, "w": 10, "h": 0}, ["h=0", "must be positive"]),
        ({"op": "rect", "x": 100, "y": 100, "w": -5, "h": 10}, ["w=-5", "must be positive"]),
        (
            {"op": "text", "x": 100, "y": 100, "s": "hi", "f": []},
            ["f=[]", "is not a string"],
        ),
        (
            {"op": "text", "x": 100, "y": 100, "s": "hi", "a": []},
            ["a=[]", "is not a string"],
        ),
        (
            {"op": "icon", "x": 100, "y": 100, "n": "check", "z": []},
            ["z=[]", "is not a string"],
        ),
        (
            {"op": "text", "x": 100, "y": 100, "s": "hi", "w": 100, "wrap": True, "lines": 0},
            ["lines=0", "using 1"],
        ),
    ],
    ids=[
        "rect-w-zero",
        "rect-h-zero",
        "rect-w-negative",
        "text-f-list",
        "text-a-list",
        "icon-z-list",
        "text-wrap-lines-zero",
    ],
)
def test_fuzz_shape_yields_exactly_one_warning_through_check(font_dir, op, expect_substrings):
    """Each of these used to raise a bare exception out of check() (a PIL
    `ValueError`, a `TypeError: unhashable type`, or an `IndexError`); each
    now produces exactly one warning, naming the actual field and value,
    and never raises."""
    doc = {"bg": "white", "ops": [op]}
    problems = check(doc, font_dir)
    assert len(problems) == 1, problems
    for s in expect_substrings:
        assert s in problems[0], problems[0]


def test_fuzz_meta_not_an_object_warns_once_and_is_ignored(font_dir):
    """`meta: "x"` used to raise `AttributeError` out of check()'s own
    `(doc.get("meta") or {}).get("hash")` -- a non-empty string is
    truthy, so the `or {}` fallback never ran, and `str` has no `.get()`.
    Mirrors the same "never raise from a shape the JSON allows" rule
    `Ctx.__init__` already holds `palette` to."""
    doc = {"bg": "white", "meta": "x", "ops": []}
    problems = check(doc, font_dir)
    assert problems == ["meta: must be an object; ignored"]


def test_meta_missing_is_still_not_reported(font_dir):
    """The new `meta` guard must not disturb check()'s existing rule that
    a draft with no `meta` at all -- not present, not malformed -- gets no
    complaint about it."""
    doc = {"bg": "white", "ops": []}
    assert check(doc, font_dir) == []


def test_arbitrary_drawing_exception_gets_the_catchall_message_and_next_op_still_draws(
    font_dir, monkeypatch
):
    """The last line of defence, for a shape none of the specific checks
    above anticipated: an exception raised from deep inside PIL's own
    drawing code (simulated here) is still caught, reported with the op's
    own type and message, and the op after it draws exactly as if the
    first had never been there."""

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ImageDraw.ImageDraw, "ellipse", boom)
    doc = {
        "bg": "white",
        "ops": [
            {"op": "circle", "x": 100, "y": 100, "r": 20, "c": "black"},
            {"op": "rect", "x": 10, "y": 10, "w": 20, "h": 20, "c": "red"},
        ],
    }
    img, problems = render(doc, font_dir)
    assert problems == ["ops[0] circle: could not be drawn (RuntimeError: boom); skipped"]
    assert img.getpixel((15, 15)) == INK["red"]
