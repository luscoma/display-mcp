"""`sprite`: pixel art as rows of characters, one `cell`x`cell` square per
character, coloured by `palette` (docs/plans/dragon-feedback.md D9/B1).
The fill is pixel-diffed against the firmware in
tests/parity/test_sprite.py; these pin the Python side's own behaviour.

Fixture note: `font_dir` comes from tests/conftest.py.
"""

from __future__ import annotations

import time

import pytest

from display_mcp.render import (
    INK,
    MAX_COORD,
    SPRITE_MAX_COLS,
    SPRITE_MAX_PALETTE,
    SPRITE_MAX_ROWS,
    check,
    render,
)


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


def test_sprite_over_long_palette_key_warns_with_length_not_content(font_dir):
    """Final review, B7/F: past NAME_MAX_LEN characters, the warning names
    the length, not the key itself -- a `!r` of an unbounded
    document-supplied key is exactly the class of warning kNameMaxLen
    exists to keep out of `problems` (the reviewer's reproduction turned
    this exact line into a 65,486-character warning)."""
    from display_mcp.render import NAME_MAX_LEN

    long_key = "K" * (NAME_MAX_LEN + 1)
    doc = _sprite_doc(palette={long_key: "red"}, rows=["K"])
    img, problems = render(doc, font_dir)
    assert problems == [
        f"ops[0] sprite: sprite palette key is {len(long_key)} bytes, "
        f"more than {NAME_MAX_LEN}; ignored",
        "ops[0] sprite: no palette entry for 'K'; drawing black",
    ]
    assert long_key not in problems[0]
    assert img.getpixel((105, 105)) == INK["black"]
    # Bytes, not characters, so the renderer and the firmware's strlen()
    # take the same branch: 30 four-byte code points is 120 bytes.
    wide_key = "\U0001F600" * 30
    _, wide_problems = render(_sprite_doc(palette={wide_key: "red"}, rows=["K"]), font_dir)
    assert wide_problems[0] == (
        f"ops[0] sprite: sprite palette key is 120 bytes, more than {NAME_MAX_LEN}; ignored"
    )


def test_sprite_palette_key_at_exactly_name_max_len_uses_the_content_message(font_dir):
    """NAME_MAX_LEN itself is still short enough to name in the ordinary
    message -- the boundary is `> NAME_MAX_LEN`, matching the firmware's
    `strlen(key) > kNameMaxLen`."""
    from display_mcp.render import NAME_MAX_LEN

    key_64 = "K" * NAME_MAX_LEN
    doc = _sprite_doc(palette={key_64: "red"}, rows=["K"])
    _, problems = render(doc, font_dir)
    assert problems[0] == f"ops[0] sprite: palette key {key_64!r} is not one character; ignored"


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


# --------------------------------------------------------------------------
# Grid bounds (docs/plans/firmware-bounds.md D7): cols, rows, palette size,
# each independent of `cell` and each its own warn-and-skip.
# --------------------------------------------------------------------------


def test_sprite_at_the_cols_bound_is_accepted(font_dir):
    doc = _sprite_doc(cell=1, rows=["K" * SPRITE_MAX_COLS], palette={"K": "black"})
    problems = check(doc, font_dir)
    assert not any("columns wide" in p for p in problems)


def test_sprite_past_the_cols_bound_is_rejected_and_fast(font_dir):
    doc = _sprite_doc(cell=1, rows=["K" * (SPRITE_MAX_COLS + 1)], palette={"K": "black"})
    t0 = time.monotonic()
    problems = check(doc, font_dir)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, elapsed
    assert problems == [
        f"ops[0] sprite: sprite is {SPRITE_MAX_COLS + 1} columns wide, more than "
        f"{SPRITE_MAX_COLS}; skipped"
    ]


def test_sprite_at_the_rows_bound_is_accepted(font_dir):
    doc = _sprite_doc(cell=1, rows=["K"] * SPRITE_MAX_ROWS, palette={"K": "black"})
    problems = check(doc, font_dir)
    assert not any("rows, more than" in p for p in problems)


def test_sprite_past_the_rows_bound_is_rejected_and_fast(font_dir):
    """The ragged case from the plan: one long row near the column bound
    plus thousands of empty rows past the row bound -- the row-count check
    must run before the widest-row scan, so this rejects fast rather than
    walking every one of those rows first."""
    rows = ["K" * SPRITE_MAX_COLS] + [""] * (SPRITE_MAX_ROWS + 5000)
    doc = _sprite_doc(cell=1, rows=rows, palette={"K": "black"})
    t0 = time.monotonic()
    problems = check(doc, font_dir)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, elapsed
    n_rows = len(rows)
    assert problems == [
        f"ops[0] sprite: sprite has {n_rows} rows, more than {SPRITE_MAX_ROWS}; skipped"
    ]


def test_sprite_at_the_palette_bound_is_accepted(font_dir):
    palette = {chr(ord("a") + i): "black" for i in range(SPRITE_MAX_PALETTE)}
    doc = _sprite_doc(cell=1, rows=["a"], palette=palette)
    problems = check(doc, font_dir)
    assert not any("palette has" in p for p in problems)


def test_sprite_past_the_palette_bound_is_rejected(font_dir):
    palette = {chr(ord("一") + i): "black" for i in range(SPRITE_MAX_PALETTE + 1)}
    doc = _sprite_doc(cell=1, rows=["a"], palette=palette)
    problems = check(doc, font_dir)
    n_entries = SPRITE_MAX_PALETTE + 1
    assert problems == [
        f"ops[0] sprite: sprite palette has {n_entries} entries, more than "
        f"{SPRITE_MAX_PALETTE}; skipped"
    ]


def test_sprite_at_the_pixel_box_bound_is_accepted(font_dir):
    """x + cols*cell == MAX_COORD exactly is legal (docs/plans/
    firmware-bounds.md D4/D7): x itself is well within MAX_COORD, but the
    box's far edge lands exactly on the bound."""
    doc = _sprite_doc(x=MAX_COORD - 10, y=0, cell=1, rows=["K" * 10], palette={"K": "black"})
    problems = check(doc, font_dir)
    assert not any("pixel box" in p for p in problems)


def test_sprite_past_the_pixel_box_bound_is_rejected(font_dir):
    doc = _sprite_doc(x=MAX_COORD - 9, y=0, cell=1, rows=["K" * 10], palette={"K": "black"})
    problems = check(doc, font_dir)
    assert problems == [
        f"ops[0] sprite: sprite pixel box out of range (|v| <= {MAX_COORD}); skipped"
    ]


def test_sprite_no_palette_entry_warning_is_capped(font_dir):
    """docs/plans/firmware-bounds.md D7: eight distinct offending
    characters, each its own line, plus one "...and more" line -- not one
    line per distinct character, however many there are. Also proof the
    *set* tracking which characters have already been warned about stays
    at 8 (the review amendment this pins), not just the printed lines:
    each of the 8 own_lines names a genuinely distinct character -- if the
    cap only throttled logging while still inserting into the set, this
    would still pass, but a repeat of an already-seen character past the
    cap would not silently re-check membership against an ever-growing
    set (exercised by using more than twice the cap's worth of distinct
    input characters, all of which must still route to the single
    overflow line rather than any of them getting their own)."""
    n_distinct = 20
    row = "".join(chr(ord("一") + i) for i in range(n_distinct))
    doc = _sprite_doc(cell=1, rows=[row], palette={})
    problems = check(doc, font_dir)
    own_lines = [p for p in problems if "no palette entry for" in p]
    overflow_lines = [p for p in problems if "...and more" in p]
    assert len(own_lines) == 8
    assert len(overflow_lines) == 1
    # Each individual line names a distinct character -- the cap didn't
    # just stop printing while quietly re-warning the same one repeatedly.
    warned_reprs = {p.split("no palette entry for ")[1].split(";")[0] for p in own_lines}
    assert len(warned_reprs) == 8


# docs/plans/firmware-bounds.md's review amendment -- exactly eight distinct
# characters (A-H) with the first repeated at the end, where a *repeat* of an
# already-warned character must not fall into the "...and more" branch just
# because the set happens to be full by then -- is asserted on this same
# `check()` call, for this same `rows=["ABCDEFGHA"]` / `palette={}` op, by
# tests/parity/test_sprite.py::test_sprite_repeated_character_after_the_cap_matches_the_firmware,
# which adds the firmware side and the distinctness of the eight warned
# characters on top.
