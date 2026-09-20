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

from conftest import SAMPLE_HASH  # tests/conftest.py -- the one SAMPLE_HASH (C5)
from display_mcp.render import (
    HEIGHT,
    INK,
    THICK_MAX,
    WIDTH,
    _name_bound_problem,
    check,
    fonts_available,
    render,
    render_hash,
)


def test_name_bound_problem_matrix():
    """`_name_bound_problem()` (C4, final review): unknown/no-name-field
    kinds are untouched; text/fmt check `f` (with their own default);
    icon checks `n`/`z` together, in one message naming both lengths."""
    assert _name_bound_problem({}, "rect", "ops[0] rect") is None
    assert _name_bound_problem({}, None, "ops[0]") is None

    long_name = "a" * 65
    assert _name_bound_problem({"f": long_name}, "text", "ops[0] text") == (
        "ops[0] text: f is 65 bytes, more than 64; skipped"
    )
    # No f at all -- text's own default ("md") is short, so no problem.
    assert _name_bound_problem({}, "text", "ops[0] text") is None
    assert _name_bound_problem({"f": long_name}, "fmt", "ops[0] fmt") == (
        "ops[0] fmt: f is 65 bytes, more than 64; skipped"
    )
    assert _name_bound_problem(
        {"n": long_name, "z": "md"}, "icon", "ops[0] icon"
    ) == "ops[0] icon: n/z longer than 64 bytes (65/2); skipped"
    assert _name_bound_problem(
        {"n": "check", "z": long_name}, "icon", "ops[0] icon"
    ) == "ops[0] icon: n/z longer than 64 bytes (5/65); skipped"
    assert _name_bound_problem({"n": "check"}, "icon", "ops[0] icon") is None


def test_name_bound_problem_is_checked_before_a_bad_c_or_a_missing_s(font_dir):
    """`_name_bound_problem()` moved into the pre-dispatch chain, ahead of
    every op-kind branch (final review, B7/F, item 5, pinning C4's
    hoisting): a `text`/`fmt` op with an over-long `f` never reaches the
    branch that would otherwise also complain about a malformed `c` or a
    missing `s` -- the op is abandoned at the name-bound check, one warning
    only, the same way a missing required field already abandons an op
    before any of its other fields are even looked at.

    Before C4, each of these checks lived inside its own op-kind branch, in
    whatever order that branch happened to read its fields -- `text` read
    `c` (building an Ink) before ever checking `f`'s length, so a document
    with both problems would have reported the `c` one, not this one. This
    pins the new order as deliberate, not an accident of refactoring."""
    long_name = "a" * 65

    # `c: 7` is not a string -- on its own (a short `f`) it warns "unknown
    # colour 7"; here `f` is also too long, and only the `f` bound fires.
    doc = {"v": 1, "bg": "white", "ops": [
        {"op": "text", "x": 0, "y": 0, "s": "hi", "f": long_name, "c": 7}
    ]}
    _img, problems = render(doc, font_dir)
    assert problems == ["ops[0] text: f is 65 bytes, more than 64; skipped"]

    # No `s` at all -- on its own (a short `f`) it warns "fmt has no 's'
    # template"; here `f` is also too long, and only the `f` bound fires.
    doc = {"v": 1, "bg": "white", "ops": [{"op": "fmt", "x": 0, "y": 0, "f": long_name}]}
    _img, problems = render(doc, font_dir)
    assert problems == ["ops[0] fmt: f is 65 bytes, more than 64; skipped"]


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


@pytest.mark.parametrize(
    ("op", "expected"),
    [
        # {"op": "text", ...} with no `s` used to raise a bare KeyError out
        # of render() (the dragon session's report); it now warns and the op
        # is skipped, like an unknown font (docs/plans/dragon-feedback.md D1
        # follow-up).
        (
            {"op": "text", "x": 100, "y": 100, "f": "xs"},
            "ops[0] text: missing field 's' (text needs x, y, s); skipped",
        ),
        # A required field present but the wrong JSON type.
        (
            {"op": "text", "x": "100", "y": 100, "s": "hi"},
            "ops[0] text: x='100' is not a number (text needs x, y, s); skipped",
        ),
        (
            {"op": "rect", "x": 0, "y": 0, "h": 10},
            "ops[0] rect: missing field 'w' (rect needs x, y, w, h); skipped",
        ),
        # A JSON bool is not the number it subclasses in Python -- `w: true`
        # must not be silently read as `1`.
        (
            {"op": "rect", "x": 0, "y": 0, "w": True, "h": 10},
            "ops[0] rect: w=True is not a number (rect needs x, y, w, h); skipped",
        ),
        # `n` moved from optional to required (docs/plans/dragon-feedback.md
        # D1 follow-up): a missing one no longer reaches render() as `None`
        # and warns `n=None z='sm' is not compiled in` -- it is caught, and
        # the op skipped, before dispatch.
        (
            {"op": "icon", "x": 0, "y": 0, "z": "sm"},
            "ops[0] icon: missing field 'n' (icon needs x, y, n); skipped",
        ),
        (
            {"op": "poly", "pts": "nope", "c": "black"},
            "ops[0] poly: pts='nope' is not a list (poly needs pts); skipped",
        ),
        # `s` stays optional in OP_FIELDS -- a `fmt` legitimately has nothing
        # else it must carry -- but an empty or missing template has nothing
        # to draw, so it gets its own message and the same skip a missing
        # required field gets.
        (
            {"op": "fmt", "x": 0, "y": 0},
            "ops[0] fmt: fmt has no 's' template; nothing to draw",
        ),
        (
            {"op": "fmt", "x": 0, "y": 0, "s": ""},
            "ops[0] fmt: fmt has no 's' template; nothing to draw",
        ),
    ],
    ids=[
        "text-missing-s-was-a-keyerror",
        "text-mistyped-string-x",
        "rect-missing-w",
        "rect-bool-w-is-not-a-number",
        "icon-missing-n-now-required",
        "poly-pts-not-a-list",
        "fmt-no-s-template",
        "fmt-empty-s-template",
    ],
)
def test_malformed_required_field_warns_and_skips(font_dir, op, expected):
    """One warning, naming the field and every required field the op takes,
    and the op abandoned outright -- the canvas is byte-identical to one
    that never carried the op at all."""
    img, problems = render({"bg": "white", "ops": [op]}, font_dir)
    assert problems == [expected]
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


@pytest.mark.parametrize(
    ("op", "edge"),
    [
        # Each of the four edges a circle's own x/y +/- r can cross, and the
        # extreme the warning has to name for it.
        ({"op": "circle", "x": 1250, "y": 100, "r": 30, "c": "black"}, "x+r=1280"),
        ({"op": "circle", "x": -80, "y": 100, "r": 10, "c": "black"}, "x-r=-90"),
        ({"op": "circle", "x": 100, "y": 1650, "r": 30, "c": "black"}, "y+r=1680"),
        ({"op": "circle", "x": 100, "y": -80, "r": 10, "c": "black"}, "y-r=-90"),
    ],
    ids=["x-plus-r", "x-minus-r", "y-plus-r", "y-minus-r"],
)
def test_circle_off_canvas(font_dir, op, edge):
    _, problems = render({"bg": "white", "ops": [op]}, font_dir)
    assert any(edge in p and "off-canvas" in p for p in problems)


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


def test_explicit_null_on_a_string_field_is_the_same_as_absent(font_dir):
    """`f: null`, `a: null`, `z: null` draw exactly as the field omitted --
    the firmware's `o["f"] | "md"` cannot tell an explicit null from an
    absent key, so the renderer must not either (B4b re-review; the same
    rule `lh: null` already follows). A non-null wrong type still skips."""
    from display_mcp.render import render

    for op, null_field in (
        ({"op": "text", "x": 40, "y": 40, "s": "Hello"}, "f"),
        ({"op": "text", "x": 40, "y": 40, "s": "Hello"}, "a"),
        ({"op": "icon", "x": 40, "y": 40, "n": "check"}, "z"),
    ):
        plain = {"bg": "white", "ops": [dict(op)]}
        nulled = {"bg": "white", "ops": [dict(op, **{null_field: None})]}
        img_a, p_a = render(plain, font_dir)
        img_b, p_b = render(nulled, font_dir)
        assert p_a == p_b == [], (null_field, p_a, p_b)
        assert img_a.tobytes() == img_b.tobytes(), null_field
        typed = {"bg": "white", "ops": [dict(op, **{null_field: 5})]}
        _, p_c = render(typed, font_dir)
        assert p_c and "is not a string; skipped" in p_c[0], (null_field, p_c)
