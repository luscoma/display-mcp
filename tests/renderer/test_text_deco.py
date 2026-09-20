"""`text.deco`: `"underline"`/`"strike"` (docs/plans/fonts-and-icons.md
Decision 5, landed as B5) -- the rule geometry, the bad-value warn-and-draw-
plain path, `fmt`'s unrelated unknown-field warning, and the rounding rule
the firmware and the renderer have to agree on.

Fixture note: `font_dir` comes from tests/conftest.py.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from display_mcp.render import (
    ANCHOR,
    FONTS,
    WIDTH,
    _deco_rect,
    _deco_rule_geometry,
    _round_half_away_from_zero,
    builtin_ink,
    check,
    load_font,
    render,
    resolve_font,
)


def _diff_rows(img_a: Image.Image, img_b: Image.Image, xs: range, ys: range) -> list[int]:
    """Rows in `ys` where `img_a`/`img_b` disagree at some `x` in `xs` --
    isolates exactly the pixels one render added over the other (the
    `deco` rule, when the two documents are otherwise identical), the same
    way `test_mono_box_drawing_run_has_no_gap` isolates a rule's row by
    scanning for the most-inked one."""
    pa, pb = img_a.load(), img_b.load()
    return [y for y in ys if any(pa[x, y] != pb[x, y] for x in xs)]


def _diff_cols(img_a: Image.Image, img_b: Image.Image, xs: range, ys: range) -> list[int]:
    pa, pb = img_a.load(), img_b.load()
    return [x for x in xs if any(pa[x, y] != pb[x, y] for y in ys)]


def _is_contiguous(values: list[int]) -> bool:
    return bool(values) and values == list(range(values[0], values[-1] + 1))


def test_strike_lands_between_baseline_and_x_height(font_dir):
    x, y, face = 40, 200, "lg"
    plain = {"bg": "white", "ops": [{"op": "text", "x": x, "y": y, "s": "Maximum", "f": face}]}
    deco = {**plain, "ops": [{**plain["ops"][0], "deco": "strike"}]}
    img_plain, p1 = render(plain, font_dir)
    img_deco, p2 = render(deco, font_dir)
    assert p1 == p2 == []

    rows = _diff_rows(img_plain, img_deco, range(x, x + 400), range(y, y + 150))
    assert _is_contiguous(rows), rows

    f = load_font(font_dir, FONTS[resolve_font(face)])
    ascent, _descent = f.getmetrics()
    x_top = ImageDraw.Draw(Image.new("L", (10, 10))).textbbox((0, 0), "x", font=f)[1]
    baseline_row, x_height_row = y + ascent, y + x_top
    assert x_height_row < rows[0]
    assert rows[-1] < baseline_row


def test_underline_lands_below_baseline_and_above_the_next_wrapped_line(font_dir):
    """Two wrapped lines, default `lh`: the first line's underline sits
    below its own baseline and clear of the second line's own ink. It
    crosses descenders (`p`, `y`, `g`) rather than clearing them -- a
    normal browser-style underline, not one that "sits below the
    descenders" (B5's review fix: that claim was false and compose.md no
    longer makes it) -- but it stays inside its own line box, so it never
    reaches the next wrapped line at the default `lh`."""
    x, y, face = 40, 200, "lg"
    text = "Happy Volcano"
    plain = {
        "bg": "white",
        "ops": [
            {"op": "text", "x": x, "y": y, "s": text, "f": face, "w": 220, "wrap": True, "lines": 2}
        ],
    }
    deco = {**plain, "ops": [{**plain["ops"][0], "deco": "underline"}]}
    img_plain, p1 = render(plain, font_dir)
    img_deco, p2 = render(deco, font_dir)
    assert p1 == p2 == []

    lh = FONTS[resolve_font(face)].line_height
    rows = _diff_rows(img_plain, img_deco, range(x, x + 400), range(y, y + 2 * lh + 20))
    assert rows

    # Two separate bands, one per wrapped line -- not one contiguous run.
    gaps = [b for a, b in zip(rows, rows[1:], strict=False) if b != a + 1]
    assert gaps, "expected two separate rule bands, one per wrapped line"
    line1_rows = rows[: rows.index(gaps[0])]
    assert _is_contiguous(line1_rows)

    f = load_font(font_dir, FONTS[resolve_font(face)])
    ascent, _descent = f.getmetrics()
    baseline_row = y + ascent
    assert line1_rows[0] > baseline_row, "underline should sit below the baseline"
    assert line1_rows[-1] < y + lh, "underline must clear the next wrapped line at the default lh"


def test_rule_spans_exactly_the_measured_line_under_each_alignment(font_dir):
    x, y, face, text = 300, 200, "lg", "MOTION"
    f = load_font(font_dir, FONTS[resolve_font(face)])
    d = ImageDraw.Draw(Image.new("L", (10, 10)))
    for a in ("left", "center", "right"):
        op = {"op": "text", "x": x, "y": y, "s": text, "f": face, "a": a}
        plain = {"bg": "white", "ops": [op]}
        deco = {**plain, "ops": [{**op, "deco": "underline"}]}
        img_plain, p1 = render(plain, font_dir)
        img_deco, p2 = render(deco, font_dir)
        assert p1 == p2 == []

        cols = _diff_cols(img_plain, img_deco, range(0, 1200), range(y, y + 80))
        assert _is_contiguous(cols), (a, cols)

        box = d.textbbox((x, y), text, font=f, anchor=ANCHOR[a])
        assert (cols[0], cols[-1] + 1) == (box[0], box[2]), a


def test_deco_on_a_wrapped_op_decorates_every_line(font_dir):
    x, y, face, text = 40, 200, "md", "One two three four five"
    doc = {
        "bg": "white",
        "ops": [
            {
                "op": "text", "x": x, "y": y, "s": text, "f": face, "w": 150,
                "wrap": True, "lines": 3, "deco": "strike",
            }
        ],
    }
    plain = {**doc, "ops": [{k: v for k, v in doc["ops"][0].items() if k != "deco"}]}
    img_plain, p1 = render(plain, font_dir)
    img_deco, p2 = render(doc, font_dir)
    assert p1 == p2 == []

    lh = FONTS[resolve_font(face)].line_height
    rows = _diff_rows(img_plain, img_deco, range(x, x + 400), range(y, y + 3 * lh + 20))
    bands = 1 + sum(1 for a, b in zip(rows, rows[1:], strict=False) if b != a + 1)
    assert bands == 3, f"expected one rule band per of the 3 wrapped lines, got {bands}"


def test_bad_deco_value_warns_and_renders_undecorated(font_dir):
    plain_op = {"op": "text", "x": 20, "y": 100, "s": "Reminder", "f": "sm"}
    doc_plain = {"bg": "white", "ops": [plain_op]}
    doc_bad = {"bg": "white", "ops": [{**plain_op, "deco": "bold"}]}
    img_plain, p1 = render(doc_plain, font_dir)
    img_bad, p2 = render(doc_bad, font_dir)
    assert p1 == []
    assert p2 == ["ops[0] text: deco='bold' is not 'underline' or 'strike'; drawing undecorated"]
    assert img_plain.tobytes() == img_bad.tobytes()


def test_bad_deco_type_warns_and_renders_undecorated(font_dir):
    plain_op = {"op": "text", "x": 20, "y": 100, "s": "Reminder", "f": "sm"}
    doc_plain = {"bg": "white", "ops": [plain_op]}
    doc_bad = {"bg": "white", "ops": [{**plain_op, "deco": 5}]}
    img_plain, p1 = render(doc_plain, font_dir)
    img_bad, p2 = render(doc_bad, font_dir)
    assert p1 == []
    assert p2 == ["ops[0] text: deco=5 is not 'underline' or 'strike'; drawing undecorated"]
    assert img_plain.tobytes() == img_bad.tobytes()


def test_bad_deco_bool_warns_with_json_spelling_not_python_repr(font_dir):
    """B5 review fix: the firmware names a non-string value with
    `serializeJson()`, which spells a JSON bool `true`/`false` -- Python's
    own `repr(True)` says `True`, which the firmware's warning never would.
    `_parse_deco()` uses `json.dumps()` for a non-string value instead."""
    plain_op = {"op": "text", "x": 20, "y": 100, "s": "Reminder", "f": "sm"}
    doc_plain = {"bg": "white", "ops": [plain_op]}
    doc_bad = {"bg": "white", "ops": [{**plain_op, "deco": True}]}
    img_plain, p1 = render(doc_plain, font_dir)
    img_bad, p2 = render(doc_bad, font_dir)
    assert p1 == []
    assert p2 == ["ops[0] text: deco=true is not 'underline' or 'strike'; drawing undecorated"]
    assert img_plain.tobytes() == img_bad.tobytes()


def test_deco_absent_or_null_draws_plain_with_no_warning(font_dir):
    op = {"op": "text", "x": 20, "y": 100, "s": "Reminder", "f": "sm"}
    doc_absent = {"bg": "white", "ops": [op]}
    doc_null = {"bg": "white", "ops": [{**op, "deco": None}]}
    img_absent, p1 = render(doc_absent, font_dir)
    img_null, p2 = render(doc_null, font_dir)
    assert p1 == p2 == []
    assert img_absent.tobytes() == img_null.tobytes()


def test_fmt_with_deco_warns_as_unknown_field_and_still_draws(font_dir):
    """`deco` is `text`-only (docs/plans/fonts-and-icons.md Decision 5):
    `fmt`'s OP_FIELDS entry doesn't list it, so this is the ordinary,
    pre-existing "no such field" warning (D1), not a new code path -- and
    `fmt` still draws, the same as any other stray field."""
    full = {"bg": "white", "ops": [{"op": "fmt", "x": 20, "y": 100, "s": "{battery}", "f": "xs"}]}
    with_deco = {**full, "ops": [{**full["ops"][0], "deco": "underline"}]}
    img_full, p1 = render(full, font_dir)
    img_deco, p2 = render(with_deco, font_dir)
    assert p1 == []
    assert p2 == [
        "ops[0] fmt: no such field 'deco' (fmt takes x, y, c, f, a, s)"
    ]
    assert img_full.tobytes() == img_deco.tobytes()


def test_describe_lists_deco_on_text_but_not_fmt(font_dir):
    from display_mcp.render import OP_FIELDS

    assert OP_FIELDS["text"]["optional"]["deco"] is None
    assert "deco" not in OP_FIELDS["fmt"]["optional"]


def test_check_sample_document_still_clean_with_deco_added(sample_doc, font_dir):
    """`deco` is additive -- a document that already passes `check()` keeps
    passing once a `text` op in it gains a legal `deco`."""
    doc = {**sample_doc, "meta": {}, "ops": list(sample_doc["ops"])}
    for i, op in enumerate(doc["ops"]):
        if op.get("op") == "text":
            doc["ops"][i] = {**op, "deco": "underline"}
            break
    else:  # pragma: no cover - the sample document has at least one text op
        raise AssertionError("sample document has no text op to decorate")
    assert check(doc, font_dir) == []


def test_bezel_check_catches_a_deco_rule_reaching_into_the_margin(font_dir):
    """B5 review fix: `bezel_problems()` estimated a text op's bottom as
    `y + size`, which is only the plain glyph box -- an underline's own
    bottom (`baseline + gap + t - 1` below `y`) reaches further down, up to
    11px lower at `xl`. `xl`'s `size` (84) put this exact document's
    bottom-edge estimate exactly on the boundary (`1492 + 84 == 1600 - 24`,
    not over it) without `deco`, so it slipped past `check()` -- the same
    document with `deco: "underline"` added has to be caught."""
    op = {"op": "text", "x": 100, "y": 1492, "s": "Pickup", "f": "xl"}
    doc_plain = {"bg": "white", "ops": [op]}
    doc_deco = {"bg": "white", "ops": [{**op, "deco": "underline"}]}
    assert check(doc_plain, font_dir) == []  # the plain text alone stays clear of the bezel
    problems = check(doc_deco, font_dir)
    assert any("within 24 px of the bottom edge" in p for p in problems), problems


def test_bezel_check_ignores_deco_on_fmt(font_dir):
    """`fmt` never draws a rule (`deco` is `text`-only), so a stray `deco`
    on one must not trigger the extended bottom-edge estimate."""
    op = {"op": "fmt", "x": 100, "y": 1492, "s": "{battery}", "f": "xl", "deco": "underline"}
    doc = {"bg": "white", "ops": [op]}
    problems = check(doc, font_dir)
    assert not any("bottom edge" in p for p in problems), problems


def test_deco_rect_clips_a_rule_that_starts_off_canvas_on_the_left():
    """`_deco_rect()` clips through `_clip_span()` the way the firmware's
    `clipped_filled_rectangle()` clips every fill (D5): a line whose inked
    left edge sits off-canvas draws only the on-canvas remainder, not a
    negative-origin rectangle."""
    box = _deco_rect("underline", lx1=-30, lw=50, ly=100, h=44, baseline=35)
    assert box is not None
    x0, y0, x1, y1 = box
    assert x0 == 0
    assert x1 == 20  # -30 + 50 == 20 on-canvas px remain


def test_deco_rect_clips_a_rule_that_extends_past_the_right_edge():
    box = _deco_rect("underline", lx1=WIDTH - 20, lw=200, ly=100, h=44, baseline=35)
    assert box is not None
    x0, y0, x1, y1 = box
    assert x0 == WIDTH - 20
    assert x1 == WIDTH


def test_deco_rect_returns_none_when_entirely_off_canvas():
    assert _deco_rect("underline", lx1=-500, lw=50, ly=100, h=44, baseline=35) is None
    assert _deco_rect("underline", lx1=100, lw=50, ly=-500, h=44, baseline=35) is None


def test_deco_rule_dithers_with_a_mixed_ink_and_is_sampled_by_the_contrast_check(font_dir):
    """The rule goes through the same `paint()` stencil pass as the glyphs
    (docs/plans/fonts-and-icons.md Decision 5): a mixed ink's rule row shows
    both component colours in the ink's own dithered pattern, not a flat
    average -- proof the rule is drawn through the op's own `ink`, and that
    its box is folded into the same `boxes` list `_paint_glyph_op()` feeds
    `_check_contrast()`/`_check_drew_nothing()` (`boxes + deco_boxes` in
    render()'s `text` branch), not a separate solid afterthought that would
    escape both checks."""
    x, y, face = 40, 300, "lg"
    op = {"op": "text", "x": x, "y": y, "s": "MOTION", "f": face, "c": "navy", "deco": "underline"}
    plain = {"bg": "white", "ops": [{k: v for k, v in op.items() if k != "deco"}]}
    doc = {"bg": "white", "ops": [op]}
    img_plain, p1 = render(plain, font_dir)
    img_deco, p2 = render(doc, font_dir)
    assert p1 == p2 == []

    rows = _diff_rows(img_plain, img_deco, range(x, x + 400), range(y, y + 100))
    assert rows

    navy = builtin_ink("navy")
    seen = {img_deco.load()[px, py] for py in rows for px in range(x, x + 400)}
    assert navy.a in seen and navy.b in seen, seen


def test_rule_thickness_is_at_least_2px_at_every_compiled_size(font_dir):
    """The write-up's own floor: a 1px rule can't hold a mixed ink, so `t`
    is never 1 even at the smallest compiled face (`xs`, 22px). Uses
    `f.font.height`, not `ascent + descent` (B5 review fix) -- see
    `test_deco_uses_the_freetype_line_height_not_ascent_plus_descent`."""
    for name, face in FONTS.items():
        f = load_font(font_dir, face)
        if f is None:  # a face whose file isn't present in this font_dir
            continue
        ascent, _descent = f.getmetrics()
        for underline in (True, False):
            _top, t = _deco_rule_geometry(f.font.height, ascent, 0, underline)
            assert t >= 2, (name, underline, t)


# ESPHome's compiled `height_` per legacy face, read off the generated
# `main.cpp` (`font::Font(glyphs, n, baseline, height, ...)`) of the
# 2026-09-19 build: the number `font_height()` returns on the panel and the
# `h` every deco rule is sized from. `f.font.height` must equal it.
_FIRMWARE_FONT_HEIGHTS = {"xl": 102, "lg": 59, "md": 44, "sm": 34, "xs": 27, "mono/24": 32}


def test_deco_uses_the_freetype_line_height_not_ascent_plus_descent(font_dir):
    """B5 review fix: the firmware's `font_height()` returns ESPHome's
    compiled `height_`, which `font/__init__.py` sets from FreeType's own
    line-height metric -- Pillow's `f.font.height`, not `ascent + descent`
    (`getmetrics()`'s sum, `Face.cell_height`). The two disagree by 1px on
    `xs`/`sm`/`xl`/`mono` and agree on `md`/`lg`, so there's no single
    "+1"/"-1" correction that covers every face -- proving that is the
    point of asserting both branches below, not just picking one. What
    actually matters is that render() itself measures the rule off
    `f.font.height`, checked by rendering, not by trusting a formula."""
    for name, firmware_height in _FIRMWARE_FONT_HEIGHTS.items():
        face = FONTS[resolve_font(name)]
        f = load_font(font_dir, face)
        if f is None:
            continue
        ascent, descent = f.getmetrics()
        # Pinned as data, not just relative to `getmetrics()`: a Pillow
        # upgrade or a refetched font that moved `f.font.height` would keep
        # a relative check green while the panel diverged (B5 re-review).
        assert f.font.height == firmware_height, name
        if name in ("md", "lg"):
            assert f.font.height == ascent + descent, name
        else:
            assert f.font.height == ascent + descent - 1, name

        x, y = 40, 300
        op = {"op": "text", "x": x, "y": y, "s": "Reminder", "f": name, "deco": "underline"}
        plain = {"bg": "white", "ops": [{k: v for k, v in op.items() if k != "deco"}]}
        deco_doc = {"bg": "white", "ops": [op]}
        img_plain, p1 = render(plain, font_dir)
        img_deco, p2 = render(deco_doc, font_dir)
        assert p1 == p2 == []

        rows = _diff_rows(img_plain, img_deco, range(x, x + 300), range(y, y + 150))
        expected_top, expected_t = _deco_rule_geometry(f.font.height, ascent, y, True)
        assert (rows[0], rows[-1]) == (expected_top, expected_top + expected_t - 1), name


def test_round_half_away_from_zero_ties_are_synthetic_not_from_a_real_face():
    """No compiled face currently lands `h / 14`, `h * 0.06` or `h * 0.30`
    exactly on a `.5` -- checked against every face's real `f.font.height`
    (B5 review fix: an earlier version of this test claimed `sm`'s 35 did,
    which used `ascent + descent` rather than the firmware's actual
    `font_height()`; `sm`'s real height is 34, and `34 / 14` is not a tie).
    The two roundings still have to agree in general, so this pins the
    function's own tie-breaking behaviour at a synthetic `.5`, and
    `tests/parity/test_text_deco.py` sweeps real synthetic ties (including
    `35`) differentially against the firmware."""
    assert FONTS[resolve_font("sm")].cell_height == 35
    f_sm_real_height = 34  # font.font.height, not Face.cell_height -- see above
    assert f_sm_real_height / 14 != 2.5
    assert round(2.5) == 2  # Python's builtin: round-half-to-even
    assert _round_half_away_from_zero(2.5) == 3  # matches C++'s std::round()
    assert _round_half_away_from_zero(-2.5) == -3
