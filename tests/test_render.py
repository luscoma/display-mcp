"""Tests for display_mcp.render.

Fixture note: `font_dir` and `sample_doc` come from tests/conftest.py. Any
test that renders real text needs `font_dir` and will skip cleanly (via that
fixture) if fonts/ hasn't been populated with the Instrument Sans pair.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from display_mcp.render import (
    BUILTIN_MIXES,
    COLORS,
    FONTS,
    HEIGHT,
    ICON_SIZES,
    ICONS,
    INK,
    WIDTH,
    Ink,
    _grounds,
    bezel_problems,
    check,
    draw_icon,
    fit_line,
    fonts_available,
    mix_on,
    render,
    render_hash,
    wrap_lines,
)

SAMPLE_HASH = "3cd62aa76e731d2d"
ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# render_hash
# --------------------------------------------------------------------------


def test_sample_hash(sample_doc):
    assert render_hash(sample_doc) == SAMPLE_HASH


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


def test_fonts_available_false(tmp_path):
    assert fonts_available(tmp_path) is False


# --------------------------------------------------------------------------
# wrap / fit differential fixtures.
#
# Written as a flat parametrised table so a future C++ diff (the way
# fit_line/wrap/utf8_prev are diffed against display_list.h per docs/SPEC.md
# "Testing") has something simple to consume: (text, max_w, lines, expected).
# --------------------------------------------------------------------------

FIT_CASES = [
    # (id, text, max_w, expected)
    ("plain_fits", "Team standup", 800, "Team standup"),
    ("exact_fit", "Team standup", None, "Team standup"),  # None => never truncated
    ("empty_string", "", 100, ""),
    ("multibyte_near_cut", "Design review — display list — 12° today", 40, None),
    ("single_word_overlong", "Supercalifragilisticexpialidocious", 60, None),
]


@pytest.mark.parametrize("case_id,text,max_w,expected", FIT_CASES)
def test_fit_line_cases(font_dir, case_id, text, max_w, expected):
    from display_mcp.render import load_font

    font = load_font(font_dir, *FONTS["sm"])
    result = fit_line(font, text, max_w)
    if expected is not None:
        assert result == expected
    # Never split a UTF-8 codepoint / always end clean.
    result.encode("utf-8")  # would raise on a bad surrogate half
    if max_w is not None:
        from display_mcp.render import text_width

        assert text_width(font, result) <= max_w or result == "…"


def test_fit_line_exact_fit_is_unchanged(font_dir):
    from display_mcp.render import load_font, text_width

    font = load_font(font_dir, *FONTS["sm"])
    s = "Team standup"
    w = text_width(font, s)
    assert fit_line(font, s, w) == s


def test_fit_line_multibyte_truncation_keeps_valid_utf8(font_dir):
    from display_mcp.render import load_font, text_width

    font = load_font(font_dir, *FONTS["sm"])
    s = "Design review — the 72° display list for today's schedule"
    # Pick a width that forces a cut somewhere in the middle of the string.
    max_w = text_width(font, s) // 3
    result = fit_line(font, s, max_w)
    result.encode("utf-8")
    assert result.endswith("…")
    assert text_width(font, result) <= max_w


def test_fit_line_single_word_longer_than_box(font_dir):
    from display_mcp.render import load_font, text_width

    font = load_font(font_dir, *FONTS["sm"])
    s = "Supercalifragilisticexpialidocious"
    max_w = 60
    result = fit_line(font, s, max_w)
    assert result.endswith("…")
    assert text_width(font, result) <= max_w


def test_fit_line_empty_string(font_dir):
    from display_mcp.render import load_font

    font = load_font(font_dir, *FONTS["sm"])
    assert fit_line(font, "", 100) == ""


def test_wrap_two_lines_with_overflow_ellipsis(font_dir):
    from display_mcp.render import load_font, text_width

    font = load_font(font_dir, *FONTS["md"])
    s = "Order printer filament and a spare 0.4 nozzle for the workshop bench today"
    max_w = 300
    lines = wrap_lines(font, s, max_w, 2)
    assert len(lines) == 2
    for line in lines:
        assert text_width(font, line) <= max_w
    assert lines[-1].endswith("…")


def test_wrap_last_word_just_fits(font_dir):
    from display_mcp.render import load_font, text_width

    font = load_font(font_dir, *FONTS["md"])
    words = ["Book", "the", "dentist"]
    s = " ".join(words)
    max_w = text_width(font, s)  # exactly enough for every word on one line
    lines = wrap_lines(font, s, max_w, 2)
    assert lines == [s]


def test_wrap_lines_equals_one(font_dir):
    from display_mcp.render import load_font, text_width

    font = load_font(font_dir, *FONTS["md"])
    s = "Measure the driver board for the frame and order new screws"
    max_w = 250
    lines = wrap_lines(font, s, max_w, 1)
    assert len(lines) == 1
    assert text_width(font, lines[0]) <= max_w


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


def test_unknown_op_is_one_problem_no_raise(font_dir):
    doc = {"bg": "white", "ops": [{"op": "sparkle", "x": 1, "y": 1}]}
    img, problems = render(doc, font_dir)
    assert len(problems) == 1
    assert "unknown op" in problems[0]
    assert img.size == (WIDTH, HEIGHT)


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
    """Finding 1: the firmware's `text`/`fmt` branches `skipped++; continue`
    on an unknown font — nothing is drawn on the panel. The renderer used to
    warn and still draw with the `md` fallback, which meant the preview
    showed text the wall never would. It must now abandon the op cleanly:
    the warning stays, but the canvas is untouched."""
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


def test_check_no_hash_at_all_in_doc(font_dir):
    doc = {"bg": "white", "ops": []}
    problems = check(doc, font_dir)
    assert problems == []


# --------------------------------------------------------------------------
# public surface sanity
# --------------------------------------------------------------------------


def test_colors_tuple():
    assert set(COLORS) == {"black", "white", "yellow", "red", "blue", "green"}


def test_fonts_keys():
    assert set(FONTS) == {"xl", "lg", "md", "sm", "xs"}


def test_icon_sizes_keys():
    assert set(ICON_SIZES) == {"sm", "md", "lg"}


def test_weather_snowy_in_icons():
    assert "weather-snowy" in ICONS


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
    """Finding 1: firmware checks the font first and never reaches
    expand_fmt() when it's bad, so a `fmt` op with both an unknown font and
    an unknown field warns about the font only — the same op-abandonment as
    `text`. (Previously this warned about both, because the renderer kept
    going past the bad font with the `md` fallback; that was the bug.)"""
    doc = {"bg": "white", "ops": [{"op": "fmt", "x": 20, "y": 1550, "s": "{nope}", "f": "huge"}]}
    _, problems = render(doc, font_dir)
    assert problems == ["ops[0] fmt: unknown font 'huge'"]


def test_stale_tone_key_is_ignored_and_draws_full_ink(font_dir):
    """`tone` no longer exists. An op that still carries the key draws at
    full ink, silently — no warning, and no different from the same op
    without the key."""
    full = {"bg": "white", "ops": [{"op": "text", "x": 20, "y": 1550, "s": "Rendered", "f": "xs"}]}
    with_stale_tone = {
        "bg": "white",
        "ops": [{"op": "text", "x": 20, "y": 1550, "s": "Rendered", "f": "xs", "tone": "light"}],
    }
    img_full, p1 = render(full, font_dir)
    img_stale, p2 = render(with_stale_tone, font_dir)
    assert p1 == [] and p2 == []
    assert img_full.tobytes() == img_stale.tobytes()


def test_hash_op_is_gone(font_dir):
    _, problems = render({"bg": "white", "ops": [{"op": "hash", "x": 1, "y": 1}]}, font_dir)
    assert any("unknown op 'hash'" in p for p in problems)


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
def test_icon_paints_nothing_outside_its_box(name, z):
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


def test_unknown_icon_placeholder_stays_inside_its_box():
    size = ICON_SIZES["lg"]
    ground = (255, 255, 255)
    img = _draw_one("no-such-icon", size, ground, (0, 0, 0))
    assert not _spill(img, size, ground)


@pytest.mark.parametrize(("name", "z"), ICON_CASES, ids=ICON_IDS)
def test_icon_paints_only_ink_pixels(name, z):
    """chroma_key: an icon in ink X on a ground of X leaves no trace.

    Holes — the moon's crescent, the marker's eye, the bang in the alert
    triangle — must be left unpainted, not filled with white or black.
    """
    ink = (156, 46, 42)
    img = _draw_one(name, ICON_SIZES[z], ink, ink)
    px = img.load()
    stray = [
        (x, y, px[x, y])
        for y in range(img.height)
        for x in range(img.width)
        if px[x, y] != ink
    ]
    assert not stray, f"{len(stray)} non-glyph px, e.g. {stray[:4]}"


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

    Pillow anti-aliases text on an RGB image by default, which used to put
    hundreds of impossible colours into the preview.
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


def test_mix_on_phase_is_absolute():
    """Tiles drawn at different origins interlock rather than seam."""
    assert mix_on(0, 0, 50) == mix_on(88, 0, 50) == mix_on(0, 88, 50)
    assert mix_on(7, 3, 25) == mix_on(9, 5, 25)


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
    """Every document that predates mixes must render exactly as it did."""
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


@pytest.mark.parametrize("name", sorted(BUILTIN_MIXES))
def test_every_builtin_renders_clean(name, font_dir):
    """No built-in may trip check() when used as a plain fill — a named
    colour that warns on correct use would be worse than no name at all."""
    doc = {"v": 1, "meta": {}, "bg": "white", "ops": [
        {"op": "rect", "x": 100, "y": 100, "w": 80, "h": 80, "c": name}]}
    assert check(doc, font_dir) == []


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


def test_render_does_not_include_ink_mixing_warnings(font_dir):
    """The three new warnings are surfaced by check(), not by a bare
    render() call — mirrors bezel_problems(), which behaves the same way."""
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "blue"},
            {"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "red"},
        ],
    }
    _, problems = render(doc, font_dir)
    assert problems == []
    assert _contrast_msgs(check(doc, font_dir))


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
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "blue"},
            {"op": "text", "x": 5000, "y": 20, "s": "Hi", "f": "lg", "c": "red"},
        ],
    }
    assert _contrast_msgs(check(doc, font_dir)) == []


def test_contrast_ignores_zero_area_box(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "blue"},
            {"op": "text", "x": 20, "y": 20, "s": "", "f": "lg", "c": "red"},
        ],
    }
    assert _contrast_msgs(check(doc, font_dir)) == []


def test_contrast_applies_to_fmt(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "blue"},
            {"op": "fmt", "x": 20, "y": 20, "s": "{time24}", "f": "lg", "c": "red"},
        ],
    }
    assert _contrast_msgs(check(doc, font_dir))


def test_contrast_applies_to_icon(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "blue"},
            {"op": "icon", "x": 20, "y": 20, "n": "check", "z": "sm", "c": "red"},
        ],
    }
    assert _contrast_msgs(check(doc, font_dir))


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


def test_contrast_max_model_reproduces_the_five_measured_cases():
    """The five rows of docs/plans/ink-mixing.md's contrast table — the
    cases with physical evidence behind them, and what makes `max` the
    defensible fix rather than a preference. `ground` for a mixed ground
    ("pink") is the average of its two inks, the way a large fill reads at
    a distance (decision 3); the ink under test is always the raw (a, b)
    pair, `max` never a blend."""
    from display_mcp.render import _contrast_ratio

    def avg(a, b):
        return tuple(round((x + y) / 2) for x, y in zip(a, b, strict=True))

    black, white = INK["black"], INK["white"]
    yellow, red = INK["yellow"], INK["red"]
    pink_ground = avg(red, white)

    # (ink a, ink b, ground, blend ratio, max ratio, legible on the wall)
    cases = [
        (black, white, white, 3.0, 12.1, True),  # black/white 50 on white (footer stamp)
        (black, white, black, 4.1, 12.1, True),  # black/white 50 on black
        (white, black, black, 4.1, 12.1, True),  # white/black 50 on black
        (red, white, pink_ground, 1.0, 2.4, False),  # red/white 50 on pink
        (yellow, white, white, 1.3, 1.6, False),  # yellow/white 50 on white
    ]
    for a, b, ground, want_blend, want_max, legible in cases:
        blend_ratio = _contrast_ratio(avg(a, b), ground)
        max_ratio = max(_contrast_ratio(a, ground), _contrast_ratio(b, ground))
        assert round(blend_ratio, 1) == pytest.approx(want_blend, abs=0.05)
        assert round(max_ratio, 1) == pytest.approx(want_max, abs=0.05)
        assert (max_ratio >= 3.0) == legible


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


def test_contrast_ratio_is_floored_not_rounded(font_dir):
    """A ratio just under the floor must not print as "3.0:1 (below 3:1)"."""
    msgs = _contrast_msgs(check(_grey_doc(("black", "white")), font_dir))
    assert "3.0:1" not in msgs[0]


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


def test_mix_as_text_does_not_apply_to_solid_colours(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [{"op": "text", "x": 200, "y": 200, "s": "Hi", "f": "lg", "c": "yellow"}],
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


def test_thin_mix_does_not_apply_to_solid_colours(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [{"op": "line", "x": 10, "y": 10, "x2": 500, "y2": 10, "c": "black", "t": 1}],
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


def test_drew_nothing_warns_fmt_on_a_matching_mixed_ground(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey": {"c": "black", "c2": "white"}},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 300, "h": 100, "c": "grey"},
            {"op": "fmt", "x": 20, "y": 20, "s": "{time24}", "f": "lg", "c": "grey"},
        ],
    }
    msgs = _drew_nothing_msgs(check(doc, font_dir))
    assert len(msgs) == 1
    assert "ops[1] fmt" in msgs[0]


def test_drew_nothing_stays_quiet_for_normal_text(font_dir):
    """The common case — text against a ground it actually contrasts with —
    must never trip this."""
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [{"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "black"}],
    }
    assert _drew_nothing_msgs(check(doc, font_dir)) == []


def test_drew_nothing_stays_quiet_when_the_mix_does_not_match_the_ground(font_dir):
    """Same mixed ink, different ground: the glyph is visibly dithered
    against the plain white page, so nothing should fire."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey": {"c": "black", "c2": "white"}},
        "ops": [{"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "grey"}],
    }
    assert _drew_nothing_msgs(check(doc, font_dir)) == []


def test_drew_nothing_stays_quiet_off_canvas(font_dir):
    """An off-screen op drawing nothing is not interesting — same skip rule
    as the contrast check's zero-area box."""
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [{"op": "text", "x": 5000, "y": 20, "s": "Hi", "f": "lg", "c": "black"}],
    }
    assert _drew_nothing_msgs(check(doc, font_dir)) == []


def test_drew_nothing_is_check_only(font_dir):
    """Like the other ink warnings, a bare render() call never sees it."""
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "black"},
            {"op": "icon", "x": 20, "y": 20, "n": "check", "z": "sm", "c": "black"},
        ],
    }
    _, problems = render(doc, font_dir)
    assert problems == []
    assert _drew_nothing_msgs(check(doc, font_dir))


def test_all_ink_mixing_warnings_clean_on_the_sample(sample_doc, font_dir):
    """samples/display.json predates ink mixing entirely (no mix in its
    palette) — check() must stay at zero problems."""
    assert check(sample_doc, font_dir) == []


# --------------------------------------------------------------------------
# flat colours — render(dithered_colors=False), the MCP preview's mode
# --------------------------------------------------------------------------


def _spec_palette_hexes():
    """The named-palette table in docs/SPEC.md, as {name: (c, c2, mix, hex)}.

    Parsed rather than duplicated: the point of the test below is that the
    published table and the renderer cannot drift apart, which a second copy
    of the numbers here would defeat.
    """
    spec = (ROOT / "docs" / "SPEC.md").read_text()
    rows = re.findall(r"`([a-z-]+)` \| (\w+)\+(\w+) (\d+) \| `#([0-9A-F]{6})`", spec)
    return {n: (a, b, int(p), h.lower()) for n, a, b, p, h in rows}


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


@pytest.mark.parametrize("name", sorted(BUILTIN_MIXES))
def test_flat_render_matches_the_documented_hex(name, font_dir):
    """A flat mix is exactly the hex docs/SPEC.md publishes for it.

    This is what makes the table load-bearing: `preview` shows these
    colours, the docs promise these colours, and neither can move without
    the other. It also pins the recipe, so a mix cannot be redefined in
    BUILTIN_MIXES while SPEC.md still advertises the old blend.
    """
    c, c2, pct, want = _spec_palette_hexes()[name]
    assert BUILTIN_MIXES[name] == (c, c2, pct)
    img, problems = render(_one_rect({}, name), font_dir, dithered_colors=False)
    assert problems == []
    got = {img.load()[x, y] for y in range(40) for x in range(40)}
    assert got == {tuple(int(want[i : i + 2], 16) for i in (0, 2, 4))}


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
    """The combination has no valid caller and used to produce garbled
    warnings — a fused blend has no ink name, so the message came out as
    "white on ink is 3.0:1". Rejecting it is what keeps Ctx.name_of's
    invariant true rather than merely documented."""
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
