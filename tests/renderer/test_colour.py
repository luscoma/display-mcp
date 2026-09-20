"""Colour: palette alias resolution, the ink-mixing mask and its four
check()-only authoring warnings (contrast floor, mix-as-text, thin mix,
drew-nothing), flat colours (render(dithered_colors=False)), the
docs/SPEC.md named-palette tables, the Ctx() construction contract, and
document_colors().

Fixture note: `font_dir` and `sample_doc` come from tests/conftest.py.
"""

from __future__ import annotations

import copy

import pytest

from display_mcp.render import (
    BUILTIN_MIXES,
    COLORS,
    FONTS,
    HEIGHT,
    INK,
    TIERS,
    WIDTH,
    Ctx,
    Ink,
    _grounds,
    check,
    colour,
    document_colors,
    mix_on,
    render,
)

from .conftest import _glyph_msgs, _hex, _spec_palette_hexes, _spec_palette_rows, _thin_mix_msgs


def test_palette_alias_chain_resolves(font_dir):
    doc = {
        "bg": "white",
        "palette": {"a": "b", "b": "c", "c": "red"},
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "a"}],
    }
    _, problems = render(doc, font_dir)
    assert problems == []


@pytest.mark.parametrize(
    "palette",
    [
        # A cycle: the walk must terminate rather than hang.
        {"a": "b", "b": "a"},
        # a->b->...->i->red: 9 hops to reach a base colour, beyond the cap,
        # so it must NOT resolve (mirrors resolve_color()'s hop cap).
        {"a": "b", "b": "c", "c": "d", "d": "e", "e": "f",
         "f": "g", "g": "h", "h": "i", "i": "red"},
    ],
    ids=["cycle-no-hang", "nine-hops-past-the-cap"],
)
def test_palette_walk_past_eight_hops_falls_back_to_black(font_dir, palette):
    doc = {
        "bg": "white",
        "palette": palette,
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "a"}],
    }
    img, problems = render(doc, font_dir)
    assert any("unknown colour" in p for p in problems)
    # Falls back to black.
    assert img.getpixel((5, 5)) == (32, 32, 32)  # INK["black"]


def test_unknown_colour_is_one_problem_no_raise(font_dir):
    doc = {"bg": "white", "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "mauve"}]}
    _, problems = render(doc, font_dir)
    assert len(problems) == 1
    assert "unknown colour" in problems[0]


def test_over_long_colour_name_warns_and_falls_back_to_black(font_dir):
    """Final safety review, B7/A1: a several-KB `c` used to cost
    resolve_ink()/resolve_solid() one unbounded allocation on the panel; the
    same firmware fix mirrored here means a 65,400-byte name (the reviewer's
    own reproduction) still renders -- warned about, never raised, and
    drawn as black, exactly today's unknown-colour fallback -- rather than
    check()/render() ever holding a 65 KB `!r` in `problems`."""
    long_name = "x" * 65_400
    doc = {
        "bg": "white",
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": long_name}],
    }
    img, problems = render(doc, font_dir)
    assert len(problems) == 1
    assert problems[0] == (
        f"ops[0] rect: colour name is {len(long_name)} bytes, more than 64; using black"
    )
    assert long_name not in problems[0]
    assert img.getpixel((5, 5)) == (32, 32, 32)  # INK["black"]

    # check() must not block a publish over this -- warnings never do
    # (CLAUDE.md's "Rules that are settled").
    assert check(doc, font_dir) == problems


def test_over_long_colour_name_caught_through_a_palette_alias_hop(font_dir):
    """The bound applies at every hop, not just the initial name -- a
    palette alias landing on an over-long target is caught before it is
    ever assigned into the walk's own candidate, mirroring
    resolve_ink()'s/resolve_solid()'s per-hop check."""
    long_name = "y" * 100
    doc = {
        "bg": "white",
        "palette": {"a": long_name},
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "a"}],
    }
    _, problems = render(doc, font_dir)
    assert len(problems) == 1
    assert "colour name is 100 bytes, more than 64; using black" in problems[0]


def test_colour_name_at_exactly_the_bound_is_not_too_long(font_dir):
    """64 bytes -- `shapes.NAME_MAX_LEN` itself -- is still an ordinary
    unknown colour, not the too-long path; the boundary is `> NAME_MAX_LEN`,
    matching the firmware's `strlen(name) > kNameMaxLen`."""
    name_64 = "z" * 64
    doc = {"bg": "white", "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": name_64}]}
    _, problems = render(doc, font_dir)
    assert len(problems) == 1
    assert problems[0] == f"ops[0] rect: unknown colour {name_64!r}"


def test_colors_tuple():
    assert set(COLORS) == {"black", "white", "yellow", "red", "blue", "green"}


def test_render_emits_only_the_six_inks(sample_doc, font_dir):
    """The panel's fonts are 1 bpp, so nothing it draws is ever a blend.

    Pillow anti-aliases text on an RGB image by default, which would put
    hundreds of impossible colours into the preview if left unguarded.
    """
    img, _ = render(sample_doc, font_dir)
    six = set(INK.values())
    px = img.load()
    strays = {px[x, y] for y in range(HEIGHT) for x in range(WIDTH)} - six
    assert not strays, f"{len(strays)} colours the panel cannot make, e.g. {list(strays)[:4]}"


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
    """A document whose palette has no mix entries renders as flat ink,
    untouched by the mixing machinery."""
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


def test_every_builtin_renders_clean(font_dir):
    """No built-in may trip check() when used as a plain fill — a named
    colour that warns on correct use would be worse than no name at all."""
    for name in sorted(BUILTIN_MIXES):
        doc = {"v": 1, "meta": {}, "bg": "white", "ops": [
            {"op": "rect", "x": 100, "y": 100, "w": 80, "h": 80, "c": name}]}
        assert check(doc, font_dir) == [], name


def _contrast_msgs(problems):
    return [p for p in problems if "below 3:1" in p]


def _mix_shift_msgs(problems):
    return [p for p in problems if "luminance gap" in p]


def test_ink_warnings_are_check_only(font_dir):
    """The ink-mixing warnings (contrast floor, an uncompiled glyph, an op
    that drew nothing) are surfaced by check(), not by a bare render()
    call — mirrors bezel_problems(), which behaves the same way. One
    document trips all three: red-on-blue text with an uncompiled arrow
    glyph, and a grey-on-grey line that draws nothing visible."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey": {"c": "black", "c2": "white"}},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "blue"},
            {"op": "text", "x": 20, "y": 20, "s": "Hi →", "f": "lg", "c": "red"},
            {"op": "rect", "x": 0, "y": 250, "w": 300, "h": 100, "c": "grey"},
            {"op": "text", "x": 20, "y": 270, "s": "Hi", "f": "lg", "c": "grey"},
        ],
    }
    _, problems = render(doc, font_dir)
    assert problems == []
    checked = check(doc, font_dir)
    assert _contrast_msgs(checked)
    assert _glyph_msgs(checked)
    assert _drew_nothing_msgs(checked)


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
    """Nothing to sample: off-canvas text and a zero-area box (an empty
    string) both leave the contrast check with no box to judge."""
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "blue"},
            {"op": "text", "x": 5000, "y": 20, "s": "Hi", "f": "lg", "c": "red"},
        ],
    }
    assert _contrast_msgs(check(doc, font_dir)) == []
    zero_area = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "blue"},
            {"op": "text", "x": 20, "y": 20, "s": "", "f": "lg", "c": "red"},
        ],
    }
    assert _contrast_msgs(check(zero_area, font_dir)) == []


def test_contrast_applies_to_fmt(font_dir):
    """The contrast floor is not specific to `text` — `fmt` and `icon` are
    judged the same way, in the same document."""
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "blue"},
            {"op": "fmt", "x": 20, "y": 20, "s": "{time24}", "f": "lg", "c": "red"},
            {"op": "icon", "x": 20, "y": 100, "n": "check", "z": "sm", "c": "red"},
        ],
    }
    msgs = _contrast_msgs(check(doc, font_dir))
    assert any("ops[1] fmt" in m for m in msgs)
    assert any("ops[2] icon" in m for m in msgs)


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


def test_mix_as_text_warns_for_a_large_chromatic_gap(font_dir):
    """Names the mix, its two inks and which one the glyph shifts toward --
    and then, per the final review's "Composer over MCP" (the warning used
    to stop at naming the problem), says what to do about it."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"mustard": {"c": "black", "c2": "yellow"}},
        "ops": [{"op": "text", "x": 200, "y": 200, "s": "Hi", "f": "lg", "c": "mustard"}],
    }
    msgs = _mix_shift_msgs(check(doc, font_dir))
    assert len(msgs) == 1
    assert "'mustard'" in msgs[0] and "black+yellow" in msgs[0]
    assert "toward yellow" in msgs[0]
    assert msgs[0].endswith(
        "for type use an ink, or a two-dark-ink mix: "
        + ", ".join(colour._DARK_TWO_INK_MIXES)
    )


def test_dark_two_ink_mixes_matches_the_tiers():
    """`_DARK_TWO_INK_MIXES` (colour.py) is derived from `TIERS`/
    `BUILTIN_MIXES`, not typed out a second time -- every "dark"-tier mix
    whose two components are both non-white, since `grey-dark` (black+white)
    is exempted from the mix-as-text warning entirely and so is not a
    sensible "use this instead" suggestion for it."""
    expected = [
        name
        for name, (c, c2, _pct) in BUILTIN_MIXES.items()
        if TIERS[name] == "dark" and "white" not in (c, c2)
    ]
    assert list(colour._DARK_TWO_INK_MIXES) == expected
    assert set(colour._DARK_TWO_INK_MIXES) == {
        name for name in TIERS if TIERS[name] == "dark"
    } - {"grey-dark"}


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


def test_mix_as_text_does_not_apply_to_a_mixed_fill(font_dir):
    """The shift is specific to glyphs, which are too few pixels to
    average — a large fill of the same mix is unaffected."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"mustard": {"c": "black", "c2": "yellow"}},
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "mustard"}],
    }
    assert _mix_shift_msgs(check(doc, font_dir)) == []


def test_thin_mix_warns_a_1px_line(font_dir):
    """Names the density, the feature and what it will actually render at --
    and then, per the final review's "Composer over MCP" (the line/outline
    warning used to stop at naming the failure mode), says what to do. The
    75% density's own parity outcome is pinned by the rect-outline test
    below."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey-25": {"c": "black", "c2": "white", "mix": 25}},
        "ops": [{"op": "line", "x": 10, "y": 10, "x2": 500, "y2": 10, "c": "grey-25", "t": 1}],
    }
    msgs = _thin_mix_msgs(check(doc, font_dir))
    assert len(msgs) == 1
    assert "ops[0] line: 25% mix on a 1px line renders at 0% or 50%" in msgs[0]
    assert msgs[0].endswith("use a 50% mix, or make the feature 2 px")


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


def test_drew_nothing_stays_quiet_for_normal_text(font_dir):
    """The common case — text against a ground it actually contrasts with —
    must never trip this, nor an off-canvas op: it draws nothing for an
    uninteresting reason, the same off-canvas skip the contrast check gets."""
    doc = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [{"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "black"}],
    }
    assert _drew_nothing_msgs(check(doc, font_dir)) == []
    off_canvas = {
        "v": 1, "meta": {}, "bg": "white", "palette": {},
        "ops": [{"op": "text", "x": 5000, "y": 20, "s": "Hi", "f": "lg", "c": "black"}],
    }
    assert _drew_nothing_msgs(check(off_canvas, font_dir)) == []


def test_drew_nothing_stays_quiet_when_the_mix_does_not_match_the_ground(font_dir):
    """Same mixed ink, different ground: the glyph is visibly dithered
    against the plain white page, so nothing should fire."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey": {"c": "black", "c2": "white"}},
        "ops": [{"op": "text", "x": 20, "y": 20, "s": "Hi", "f": "lg", "c": "grey"}],
    }
    assert _drew_nothing_msgs(check(doc, font_dir)) == []


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


def test_tiers_match_the_spec_headings():
    """TIERS == {name: tier}, parsed from docs/SPEC.md's own headings
    grouping the named-palette table — not retyped, so the two cannot
    drift apart. Dict equality here plus set equality against SPEC.md
    above is also the guard that every built-in mix has a tier and every
    tier names a real mix, so a name dropped from either side cannot
    vanish from the parametrised tests in silence."""
    assert TIERS == {name: tier for name, (*_, tier) in _spec_palette_rows().items()}


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


def test_flat_lays_down_one_colour_and_dithering_is_still_the_default(font_dir):
    """The two sides of the flag, on one document.

    Flat is the whole point of the mode: no dither to alias, so a flat fill
    is uniform. Dithered is what render() still does by default — what the
    panel does — so check(), the CLI and the firmware-parity tests get the
    real thing without asking.
    """
    flat, _ = render(_one_rect({}, "teal"), font_dir, dithered_colors=False)
    assert _share(flat, flat.load()[0, 0], 0, 0, 40, 40) == 1.0

    dithered, _ = render(_one_rect({}, "teal"), font_dir)
    assert _share(dithered, INK["green"], 0, 0, 40, 40) == 0.5
    assert _share(dithered, INK["blue"], 0, 0, 40, 40) == 0.5


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
    """The combination has no valid caller: a fused blend has no ink
    name, so allowing it would produce a garbled message like
    "white on ink is 3.0:1". Rejecting it keeps Ctx.name_of's invariant
    true rather than merely documented."""
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


def test_ctx_construction_contract(font_dir):
    """`Ctx.__init__`'s three branches, made explicit rather than left to
    `Path(None)` raising a bare TypeError."""
    # No `font_dir` is a valid colour-only context, not a TypeError.
    assert Ctx({"bg": "white"}).fonts == {}

    # Asking to load fonts with nothing to load them from is a caller
    # error, not a silent no-op.
    with pytest.raises(ValueError, match="load_fonts needs a font_dir"):
        Ctx({"bg": "white"}, load_fonts=True)

    # A `font_dir` alone still loads fonts, as it always has.
    assert set(Ctx({"bg": "white"}, font_dir).fonts) == set(FONTS)


def test_document_colors_covers_bg_op_colours_and_palette_keys():
    """Every name the document actually references shows up once: `bg`,
    every op's `c` (including a sprite's own palette and a poly's `c`), an
    `icon` op's `bgc`, and every palette key — even a palette entry
    nothing draws with."""
    doc = {
        "v": 1,
        "bg": "white",
        "palette": {
            "accent": "red",
            "flame": {"c": "red", "c2": "yellow", "mix": 50},
            "unused": "blue",
        },
        "ops": [
            {"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "accent"},
            {"op": "icon", "x": 0, "y": 0, "n": "check", "z": "sm", "bgc": "flame"},
            {"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "navy"},
            {"op": "sprite", "x": 0, "y": 0, "cell": 10,
             "palette": {"K": "black", "O": "flame"}, "rows": ["KO"]},
            {"op": "poly", "pts": [[0, 0], [10, 0], [5, 10]], "c": "teal"},
        ],
    }
    colors, problems = document_colors(doc)
    assert problems == []
    assert set(colors) == {"white", "accent", "flame", "navy", "unused", "black", "teal"}


def test_document_colors_builtin_mix_reports_its_recipe_and_the_spec_hex():
    """A built-in mix's recipe names its two base inks and density; its hex
    is exactly what docs/SPEC.md publishes for it (parsed, not retyped)."""
    doc = {"v": 1, "bg": "white", "ops": [
        {"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "navy"}]}
    c, c2, pct, want_hex = _spec_palette_hexes()["navy"]
    colors, _ = document_colors(doc)
    assert colors["navy"] == {
        "recipe": f"{c}+{c2} {pct}",
        "hex": f"#{want_hex.upper()}",
    }


def test_document_colors_document_palette_mix_reports_its_recipe():
    doc = {
        "v": 1,
        "bg": "white",
        "palette": {"flame": {"c": "red", "c2": "yellow", "mix": 50}},
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "flame"}],
    }
    colors, _ = document_colors(doc)
    got = colors["flame"]
    assert got["recipe"] == "red+yellow 50"
    assert got["hex"] == _hex(Ink(INK["red"], INK["yellow"], 50).avg)


def test_document_colors_alias_reports_what_it_resolves_to():
    doc = {
        "v": 1,
        "bg": "white",
        "palette": {"accent": "red"},
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "accent"}],
    }
    colors, _ = document_colors(doc)
    assert colors["accent"] == {"recipe": "ink", "hex": _hex(INK["red"])}


def test_document_colors_unknown_name_is_absent_and_still_a_check_warning(font_dir):
    doc = {"v": 1, "bg": "white", "ops": [
        {"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "nope"}]}
    colors, _ = document_colors(doc)
    assert "nope" not in colors
    assert any("unknown colour" in p for p in check(doc, font_dir))


def test_document_colors_skips_a_non_string_colour_value():
    """A dict in `c` (the dragon's own mistake) is skipped, not a key —
    `check()` still warns about it (D1); this just never raises resolving
    something that was never a name."""
    doc = {"v": 1, "bg": "white", "ops": [
        {"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10,
         "c": {"c": "red", "c2": "yellow", "mix": 50}}]}
    colors, _ = document_colors(doc)
    assert set(colors) == {"white"}


def test_document_colors_reads_bgc_on_an_icon_op_only():
    """`bgc` is only a field `icon` reads, so only an `icon` contributes a
    colour through it; on any other op it is an unknown field
    (`_op_field_problems` already warns) and must not."""
    icon = {"v": 1, "bg": "white", "ops": [
        {"op": "icon", "x": 0, "y": 0, "n": "check", "z": "sm", "bgc": "red"}]}
    colors, _ = document_colors(icon)
    assert "red" in colors

    text = {"v": 1, "bg": "white", "ops": [
        {"op": "text", "x": 0, "y": 0, "s": "hi", "c": "black", "bgc": "red"}]}
    colors, _ = document_colors(text)
    assert "red" not in colors


def test_document_colors_reports_a_malformed_mix_entry_nothing_draws_with():
    """A palette entry no op ever references: `check()` has no reason to
    visit it, so today this reported as a plain (black) ink with no
    warning anywhere. document_colors() now surfaces the problem itself,
    `where`d as its own palette key so it reads as a palette complaint,
    not an op's."""
    doc = {"v": 1, "bg": "white", "palette": {"broken": {"c2": "red"}}, "ops": []}
    colors, problems = document_colors(doc)
    assert colors["broken"] == {"recipe": "ink", "hex": _hex(INK["black"])}
    assert problems == ["palette 'broken': mix 'broken' has no 'c'; using black"]


def test_document_colors_reports_an_unresolvable_alias_entry():
    doc = {"v": 1, "bg": "white", "palette": {"ghost": "nope"}, "ops": []}
    colors, problems = document_colors(doc)
    assert "ghost" not in colors
    assert problems == ["palette 'ghost': unknown colour 'nope'"]


def test_check_and_document_colors_merge_does_not_duplicate(font_dir):
    """validate()'s merge (mcp_server._merge_color_problems) is a plain
    function pinned directly in tests/test_mcp.py; this is the end-to-end
    half, against the real `check()`: an op that already uses a malformed
    palette mix must earn that warning once from check(), once (under a
    different `where`) from document_colors() — and the merge collapses
    them to one."""
    from display_mcp.mcp_server import _merge_color_problems

    doc = {
        "v": 1,
        "bg": "white",
        "palette": {"broken": {"c2": "red"}},
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "c": "broken"}],
    }
    problems = check(doc, font_dir)
    assert any("mix 'broken' has no 'c'" in p for p in problems)  # check() saw it too
    _colors, color_problems = document_colors(doc)
    merged = _merge_color_problems(problems, color_problems)
    assert sum("mix 'broken' has no 'c'" in w for w in merged) == 1


@pytest.mark.parametrize(
    "doc",
    [
        None,
        "not a document",
        {},
        {"ops": "not-a-list"},
        {"bg": "white", "palette": ["not", "a", "dict"]},
        {"bg": 123, "ops": [1, None, "x", {"op": "rect"}]},
    ],
)
def test_document_colors_never_raises_on_a_malformed_document(doc):
    document_colors(doc)  # only requirement: no exception
