"""`sprite`: pixel art as rows of characters, one `cell`x`cell` square per
character, coloured by `palette` (docs/plans/dragon-feedback.md D9/B1).
The fill is pixel-diffed against the firmware in
tests/parity/test_sprite.py; these pin the Python side's own behaviour.

Fixture note: `font_dir` comes from tests/conftest.py.
"""

from __future__ import annotations

import pytest

from display_mcp.render import INK, check, render


def _sprite_doc(**op_extra):
    op = {
        "op": "sprite", "x": 100, "y": 100, "cell": 10,
        "palette": {"K": "black", "O": "yellow"},
        "rows": ["KKOO..KK"],
    }
    op.update(op_extra)
    return {"bg": "white", "ops": [op]}


def test_sprite_row_draws_expected_rects_and_leaves_transparent_alone(font_dir):
    img, problems = render(_sprite_doc(), font_dir)
    assert problems == []
    px = img.load()
    # 'K' run at cols 0-1: centres x=105,115, y=105
    assert px[105, 105] == INK["black"]
    assert px[115, 105] == INK["black"]
    # 'O' run at cols 2-3: centres x=125,135
    assert px[125, 105] == INK["yellow"]
    assert px[135, 105] == INK["yellow"]
    # '.' run at cols 4-5: transparent, the white ground shows through
    assert px[145, 105] == INK["white"]
    assert px[155, 105] == INK["white"]
    # 'K' run at cols 6-7
    assert px[165, 105] == INK["black"]
    assert px[175, 105] == INK["black"]


def test_sprite_mirror_x_flips_the_row(font_dir):
    plain, _ = render(_sprite_doc(), font_dir)
    mirrored, problems = render(_sprite_doc(mirror="x"), font_dir)
    assert problems == []
    px_plain, px_mirror = plain.load(), mirrored.load()
    # The row is "KKOO..KK": mirrored it's "KK..OOKK", so the run that was
    # 'O' (cols 2-3) is now transparent (white), and cols 4-5 (was
    # transparent) are now 'O'.
    assert px_plain[125, 105] == INK["yellow"]
    assert px_mirror[125, 105] == INK["white"]
    assert px_plain[145, 105] == INK["white"]
    assert px_mirror[145, 105] == INK["yellow"]


def test_sprite_unknown_character_warns_once_and_draws_black(font_dir):
    doc = _sprite_doc(rows=["KQQ.Q"])
    img, problems = render(doc, font_dir)
    assert problems == ["ops[0] sprite: no palette entry for 'Q'; drawing black"]
    px = img.load()
    assert px[115, 105] == INK["black"]  # the 'Q' run drew black


def test_sprite_palette_entry_that_is_an_object_warns_with_the_mix_hint(font_dir):
    doc = _sprite_doc(palette={"K": {"c": "red", "c2": "yellow", "mix": 50}}, rows=["K"])
    img, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] sprite: mixes are palette entries — put the mix in palette and name "
        "it in c (palette: {name: {c, c2, mix}}, c: name)"
    ]
    assert img.getpixel((105, 105)) == INK["black"]


def test_sprite_ragged_rows_warn_once_and_pad_transparent(font_dir):
    doc = _sprite_doc(rows=["KKK", "K"])
    img, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] sprite: rows are ragged (widths 1..3); short rows padded transparent"
    ]
    px = img.load()
    # Row 1 (short, "K") is padded transparent past its own single 'K'.
    assert px[105, 115] == INK["black"]
    assert px[115, 115] == INK["white"]


def test_sprite_dot_and_space_are_transparent_even_if_palette_defines_them(font_dir):
    doc = _sprite_doc(palette={"K": "black", ".": "red", " ": "blue"}, rows=["K. K"])
    img, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] sprite: sprite palette cannot redefine '.'; it stays transparent",
        "ops[0] sprite: sprite palette cannot redefine ' '; it stays transparent",
    ]
    px = img.load()
    assert px[105, 105] == INK["black"]
    assert px[115, 105] == INK["white"]  # '.' stayed transparent, not red
    assert px[125, 105] == INK["white"]  # ' ' stayed transparent, not blue
    assert px[135, 105] == INK["black"]


@pytest.mark.parametrize(("field", "value"), [("cell", 0), ("cell", 1.5), ("rows", [1, 2])])
def test_sprite_malformed_required_field_warns_once_and_draws_nothing(font_dir, field, value):
    """A `cell`/`rows`/`palette` that is the right JSON *type* but still
    unusable (a non-integer or out-of-range `cell`, a `rows` of non-strings)
    reaches sprite's own, more specific required-field check."""
    doc = _sprite_doc(**{field: value})
    img, problems = render(doc, font_dir)
    assert len(problems) == 1
    assert "nothing to draw, skipped" in problems[0]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


@pytest.mark.parametrize(("field", "value"), [("cell", True), ("rows", "KK"), ("palette", ["K"])])
def test_sprite_wrong_type_field_gets_the_generic_required_field_message(font_dir, field, value):
    """A `cell`/`rows`/`palette` of the wrong JSON type entirely (a bool
    where a number belongs, a string where a list belongs, a list where an
    object belongs) is caught by the generic required-field check
    (docs/plans/dragon-feedback.md D1 follow-up) before sprite's own check
    ever runs -- one warning, not two."""
    doc = _sprite_doc(**{field: value})
    img, problems = render(doc, font_dir)
    assert len(problems) == 1
    assert "skipped" in problems[0]
    assert "sprite needs x, y, cell, rows, palette" in problems[0]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_sprite_off_canvas_on_the_far_edge_warns(font_dir):
    doc = _sprite_doc(x=1195, cell=40, rows=["KKK"])
    _, problems = render(doc, font_dir)
    assert any("x+cols*cell" in p and "off-canvas" in p for p in problems)


def test_sprite_mixed_cell_dithers_identically_to_a_rect(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"navymix": {"c": "black", "c2": "blue", "mix": 50}},
        "ops": [{"op": "sprite", "x": 40, "y": 40, "cell": 40,
                  "palette": {"K": "navymix"}, "rows": ["K"]}],
    }
    sprite_img, problems = render(doc, font_dir)
    rect_doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"navymix": {"c": "black", "c2": "blue", "mix": 50}},
        "ops": [{"op": "rect", "x": 40, "y": 40, "w": 40, "h": 40, "c": "navymix"}],
    }
    rect_img, _ = render(rect_doc, font_dir)
    assert problems == []
    assert sprite_img.tobytes() == rect_img.tobytes()


def test_sprite_25_percent_mix_on_1px_cell_gets_the_thin_mix_warning(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "palette": {"grey25": {"c": "black", "c2": "white", "mix": 25}},
        "ops": [{"op": "sprite", "x": 0, "y": 0, "cell": 1,
                  "palette": {"K": "grey25"}, "rows": ["K"]}],
    }
    problems = check(doc, font_dir)
    assert any(
        "25% mix on a 1x1 fill is too thin to carry the density" in p for p in problems
    )


def test_sprite_c_field_is_no_such_field(font_dir):
    doc = _sprite_doc(c="red")
    _, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] sprite: no such field 'c' (sprite takes x, y, cell, rows, palette, mirror)"
    ]


def test_sprite_two_character_palette_key_warns_and_is_ignored(font_dir):
    """A palette key that isn't exactly one character can't identify a
    cell, so it's dropped with a warning; a row that uses it then hits the
    ordinary unknown-character path."""
    doc = _sprite_doc(palette={"KK": "red"}, rows=["K"])
    img, problems = render(doc, font_dir)
    assert problems == [
        "ops[0] sprite: palette key 'KK' is not one character; ignored",
        "ops[0] sprite: no palette entry for 'K'; drawing black",
    ]
    assert img.getpixel((105, 105)) == INK["black"]


def test_sprite_mixed_rows_type_skips_whole_op(font_dir):
    """Any non-string element in `rows` skips the whole op, same as
    `rows` not being a list of strings at all."""
    doc = _sprite_doc(rows=["KK", 5])
    img, problems = render(doc, font_dir)
    assert len(problems) == 1
    assert "nothing to draw, skipped" in problems[0]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_sprite_mirror_other_than_x_warns_and_is_not_mirrored(font_dir):
    """`"x"` is the only legal `mirror` value; anything else warns and
    draws exactly as if `mirror` had been omitted."""
    plain, _ = render(_sprite_doc(), font_dir)
    warned, problems = render(_sprite_doc(mirror="y"), font_dir)
    assert problems == [
        "ops[0] sprite: mirror must be \"x\"; got 'y', not mirrored"
    ]
    assert warned.tobytes() == plain.tobytes()


def test_sprite_drew_nothing_warns_when_the_grid_matches_its_ground(font_dir):
    """Like text/fmt/icon, a sprite that paints nothing visibly
    different from what's already there is a warning, not silence —
    white-on-white here rather than a fully transparent grid, so the
    check has a box to snapshot at all."""
    doc = {
        "bg": "white",
        "ops": [{"op": "sprite", "x": 100, "y": 100, "cell": 10,
                  "palette": {"K": "white"}, "rows": ["K"]}],
    }
    problems = check(doc, font_dir)
    assert any("drew nothing visible" in p for p in problems)


def test_sprite_thin_mix_check_only_fires_for_characters_a_row_actually_uses(font_dir):
    """An unused palette entry has no cell on the grid to be thin, so
    it must not earn the sub-2px density warning that a used one would."""
    doc = {
        "bg": "white",
        "palette": {"grey25": {"c": "black", "c2": "white", "mix": 25}},
        "ops": [{"op": "sprite", "x": 0, "y": 0, "cell": 1,
                  "palette": {"K": "black", "U": "grey25"}, "rows": ["K"]}],
    }
    problems = check(doc, font_dir)
    assert not any("too thin to carry the density" in p for p in problems)
