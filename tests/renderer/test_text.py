"""Text: fit/wrap, the `text`/`fmt` ops, the compiled font table, the
JetBrains Mono face (docs/plans/dragon-feedback.md D11/B3), and the
uncompiled-glyph warning.

Fixture note: `font_dir` and `sample_doc` come from tests/conftest.py. Any
test that renders real text needs `font_dir` and will skip cleanly (via
that fixture) if fonts/ hasn't been populated with the Instrument Sans
pair.
"""

from __future__ import annotations

import shutil
import time

import pytest

from display_mcp.render import (
    FONTS,
    INK,
    MAX_COORD,
    TEXT_MAX_LEN,
    TEXT_MAX_LINES,
    check,
    fit_line,
    fonts_available,
    load_font,
    render,
    render_hash,
    wrap_lines,
)

from .conftest import _glyph_msgs

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


def test_fonts_keys():
    assert set(FONTS) == {"xl", "lg", "md", "sm", "xs", "mono"}


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


# --------------------------------------------------------------------------
# Length and line-count bounds (docs/plans/firmware-bounds.md D6).
# --------------------------------------------------------------------------


def test_text_at_the_length_bound_is_accepted(font_dir):
    s = "a" * TEXT_MAX_LEN
    doc = {"bg": "white", "ops": [{"op": "text", "x": 10, "y": 10, "s": s, "f": "sm", "w": 100}]}
    _, problems = render(doc, font_dir)
    assert not any("bytes" in p and "skipped" in p for p in problems)


def test_text_past_the_length_bound_is_skipped_and_fast(font_dir):
    """A 200 KB `s`, the kind that would make fit_line()'s quadratic cost
    actually hurt, is skipped in well under a second."""
    s = "a" * (200 * 1024)
    doc = {"bg": "white", "ops": [{"op": "text", "x": 10, "y": 10, "s": s, "f": "sm", "w": 100}]}
    t0 = time.monotonic()
    img, problems = render(doc, font_dir)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, elapsed
    assert problems == [f"ops[0] text: s is {len(s)} bytes, more than {TEXT_MAX_LEN}; skipped"]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_fmt_past_the_length_bound_is_skipped(font_dir):
    """Measured on the template itself, before expansion -- {time} et al.
    are always short, so this is about the literal text an author wrote,
    not what it might expand to."""
    s = "{time}" + ("x" * (TEXT_MAX_LEN + 10))
    doc = {"bg": "white", "ops": [{"op": "fmt", "x": 10, "y": 10, "s": s, "f": "xs"}]}
    _, problems = render(doc, font_dir)
    assert problems == [f"ops[0] fmt: s is {len(s)} bytes, more than {TEXT_MAX_LEN}; skipped"]


def test_text_wrap_lines_past_the_bound_is_clamped_not_skipped(font_dir):
    """`lines` past `TEXT_MAX_LINES` is bounded the way `t` is bounded by
    `THICK_MAX` -- clamped with a warning, the op still draws."""
    doc_over = {"bg": "white", "ops": [
        {"op": "text", "x": 10, "y": 10, "s": "word " * 50, "f": "sm",
         "wrap": True, "w": 100, "lines": TEXT_MAX_LINES + 10}]}
    doc_clamped = {"bg": "white", "ops": [
        {"op": "text", "x": 10, "y": 10, "s": "word " * 50, "f": "sm",
         "wrap": True, "w": 100, "lines": TEXT_MAX_LINES}]}
    img_over, problems = render(doc_over, font_dir)
    img_clamped, _ = render(doc_clamped, font_dir)
    assert any(f"clamped to {TEXT_MAX_LINES}" in p for p in problems)
    assert img_over.tobytes() == img_clamped.tobytes()


def test_text_wrap_huge_lh_is_rejected(font_dir):
    """docs/plans/firmware-bounds.md's review amendment: `lh` joins the
    coordinate bound too -- with `lines` up to TEXT_MAX_LINES, `y + n * lh`
    is exactly the size-field arithmetic D4 already covers for every other
    op, and a `lh` like 2e9 would overflow that multiply in the firmware
    long before any print() call saw it."""
    doc = {"bg": "white", "ops": [
        {"op": "text", "x": 10, "y": 10, "s": "word " * 5, "f": "sm",
         "wrap": True, "w": 100, "lines": TEXT_MAX_LINES, "lh": 2e9}]}
    img, problems = render(doc, font_dir)
    # "2e+09", matching the firmware's own %g -- not repr()'s
    # "2000000000.0" (docs/plans/firmware-bounds.md's review amendment).
    assert problems == [f"ops[0] text: lh=2e+09 out of range (|v| <= {MAX_COORD}); skipped"]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


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
