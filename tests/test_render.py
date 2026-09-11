"""Tests for display_mcp.render.

Fixture note: `font_dir` and `sample_doc` come from tests/conftest.py. Any
test that renders real text needs `font_dir` and will skip cleanly (via that
fixture) if fonts/ hasn't been populated with the Instrument Sans pair.
"""

from __future__ import annotations

import copy

import pytest
from PIL import Image, ImageDraw

from display_mcp.render import (
    COLORS,
    FONTS,
    HEIGHT,
    ICON_SIZES,
    ICONS,
    IDEAL,
    INK,
    WIDTH,
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

SAMPLE_HASH = "21a77f4c46f1534d"


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


def test_fmt_unknown_field_and_font_are_warnings(font_dir):
    doc = {"bg": "white", "ops": [{"op": "fmt", "x": 20, "y": 1550, "s": "{nope}", "f": "huge"}]}
    _, problems = render(doc, font_dir)
    assert any("unknown field {nope}" in p for p in problems)
    assert any("unknown font" in p for p in problems)


def test_tone_light_halves_ink_and_warns_on_unknown(font_dir):
    full = {"bg": "white", "ops": [{"op": "text", "x": 20, "y": 1550, "s": "Rendered", "f": "xs"}]}
    light_op = {"op": "text", "x": 20, "y": 1550, "s": "Rendered", "f": "xs", "tone": "light"}
    light = {"bg": "white", "ops": [light_op]}
    img_full, p1 = render(full, font_dir)
    img_light, p2 = render(light, font_dir)
    assert p1 == [] and p2 == []
    a = _footer_ink(img_full, 20, 1545, 200, 1585)
    b = _footer_ink(img_light, 20, 1545, 200, 1585)
    assert 0.35 * a < b < 0.65 * a
    bad = {"bg": "white", "ops": [{"op": "fmt", "x": 20, "y": 1550, "s": "{hash}", "tone": "bold"}]}
    _, problems = render(bad, font_dir)
    assert any("unknown tone" in p for p in problems)


def test_tone_light_uses_bgc_on_a_filled_rect(font_dir):
    def doc(tone):
        op = {"op": "text", "x": 20, "y": 1550, "s": "Rendered", "f": "xs", "c": "white"}
        op["bgc"] = "black"
        if tone:
            op["tone"] = tone
        rect = {"op": "rect", "x": 0, "y": 1500, "w": 400, "h": 100, "c": "black"}
        return {"bg": "white", "ops": [rect, op]}

    full, p1 = render(doc(None), font_dir)
    light, p2 = render(doc("light"), font_dir)
    assert p1 == [] and p2 == []
    black = full.getpixel((5, 1505))
    white = full.getpixel((5, 5))
    box = [(x, y) for x in range(20, 200) for y in range(1545, 1585)]
    # Where the full render was black, the light one must still be black:
    # the overlay used bgc, never the document bg. (Pillow antialiases
    # glyph edges, so intermediate shades exist here; the panel has none.)
    assert all(light.getpixel(pt) == black for pt in box if full.getpixel(pt) == black)
    n_full = sum(1 for pt in box if full.getpixel(pt) == white)
    n_light = sum(1 for pt in box if light.getpixel(pt) == white)
    assert 0.35 * n_full < n_light < 0.65 * n_full


def test_tone_light_on_icon_halves_ink(font_dir):
    full = {"bg": "white", "ops": [{"op": "icon", "x": 100, "y": 100, "n": "battery", "z": "sm"}]}
    light = {"bg": "white", "ops": [{"op": "icon", "x": 100, "y": 100, "n": "battery", "z": "sm",
                                     "tone": "light"}]}
    a = _footer_ink(render(full, font_dir)[0], 100, 100, 136, 136)
    b = _footer_ink(render(light, font_dir)[0], 100, 100, 136, 136)
    assert 0.35 * a < b < 0.65 * a


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


def test_ideal_render_emits_only_the_six_inks(sample_doc, font_dir):
    img, _ = render(sample_doc, font_dir, ideal=True)
    px = img.load()
    strays = {px[x, y] for y in range(HEIGHT) for x in range(WIDTH)} - set(IDEAL.values())
    assert not strays, f"{len(strays)} blended colours, e.g. {list(strays)[:4]}"


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


def test_tone_over_a_mixed_ground_reproduces_it(font_dir):
    """bgc naming a mix is why mixes live in the palette: the knockout is in
    phase with the fill, so it repaints exactly what was underneath."""
    doc = {
        "v": 1,
        "meta": {},
        "bg": "white",
        "palette": {"grey": {"c": "black", "c2": "white"}},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 300, "h": 100, "c": "grey"},
            {
                "op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg",
                "c": "black", "tone": "light", "bgc": "grey",
            },
        ],
    }
    img, problems = render(doc, font_dir)
    assert problems == []
    # ground away from the glyphs is still an unbroken 50/50 grey
    assert _share(img, INK["white"], 200, 20, 290, 90) == 0.5
