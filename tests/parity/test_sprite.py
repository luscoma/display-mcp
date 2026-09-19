"""sprite, differentially. draw_sprite() is factored out of the op loop
precisely so it -- and utf8_prev/utf8_next/mix_on/struct Ink/MixDisplay,
which it's built on -- can be extracted verbatim, compiled against a stub
Display/ArduinoJson, and rasterised, then diffed pixel-for-pixel against
display_mcp.render.render(). JSON edge cases that never reach the pixels
(a palette key that isn't one character, a non-string row element, a bad
mirror value...) are exercised on the Python side in tests/renderer/; this
module only has to prove the two sides paint the same thing once an op's
fields are legal.

Needs a host C++ compiler; skips cleanly without one (see conftest.py).
"""

from __future__ import annotations

import time

from display_mcp.render import (
    HEIGHT,
    MAX_COORD,
    SPRITE_MAX_COLS,
    SPRITE_MAX_PALETTE,
    SPRITE_MAX_ROWS,
    WIDTH,
    check,
    render,
)

from .conftest import _diff


def test_sprite_multibyte_row_matches_the_firmware(sprite_harness, font_dir):
    """`{"palette": {"█": "black", "▄": "red"}, "rows": ["█▄█"]}` draws
    three cells, not nine -- the whole point of walking by codepoint,
    on both sides."""
    diffs, problems = _diff(
        sprite_harness,
        font_dir,
        {
            "op": "sprite", "x": 0, "y": 0, "cell": 10,
            "palette": {"█": "black", "▄": "red"}, "rows": ["█▄█"],
        },
        30, 10,
    )
    assert problems == []
    assert not diffs, diffs[:5]


def test_sprite_abutting_mixed_runs_at_odd_origin_match_the_firmware(sprite_harness, font_dir):
    diffs, problems = _diff(
        sprite_harness,
        font_dir,
        {
            "op": "sprite", "x": 1, "y": 1, "cell": 6,
            "palette": {"N": "navy", "D": "grey-dark"}, "rows": ["NNDD"],
        },
        30, 10,
    )
    assert problems == []
    assert not diffs, diffs[:5]


def test_sprite_mirrored_ragged_matches_the_firmware(sprite_harness, font_dir):
    diffs, problems = _diff(
        sprite_harness,
        font_dir,
        {
            "op": "sprite", "x": 0, "y": 0, "cell": 5,
            "palette": {"K": "black", "O": "red"},
            "rows": ["KKKKK", "OK", "KOK"], "mirror": "x",
        },
        30, 20,
    )
    assert len(problems) == 1 and "ragged" in problems[0]
    assert not diffs, diffs[:5]


def test_sprite_3x3_mixed_block_matches_a_rect(sprite_harness, font_dir):
    """A uniform 3x3 grid of one mixed character is, pixel for pixel, the
    same box a single `rect` of the same colour fills -- proof that
    run-merging across several rows costs nothing at the seams, on the
    compiled side as much as the Python's own
    test_sprite_mixed_cell_dithers_identically_to_a_rect does."""
    op = {
        "op": "sprite", "x": 0, "y": 0, "cell": 10,
        "palette": {"K": "navy"}, "rows": ["KKK", "KKK", "KKK"],
    }
    drew, cpp_px, logs = sprite_harness.run(op, 30, 30)
    assert drew and not logs
    rect_doc = {
        "v": 1, "bg": "white",
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 30, "h": 30, "c": "navy"}],
    }
    img, problems = render(rect_doc, font_dir)
    assert problems == []
    px = img.load()
    diffs = [
        (x, y, cpp_px[y][x], px[x, y])
        for y in range(30)
        for x in range(30)
        if cpp_px[y][x] != px[x, y]
    ]
    assert not diffs, diffs[:5]


def test_sprite_sample_matches_the_firmware(sprite_harness, font_dir, sprite_sample_doc):
    """samples/sprite.json's own sprite op, verbatim but for x=y=0 -- only
    the relative pixels matter for a dithering-phase diff, not where the
    real document places the dragon on the panel."""
    op = dict(next(o for o in sprite_sample_doc["ops"] if o["op"] == "sprite"))
    op["x"] = op["y"] = 0
    cw = max(len(r) for r in op["rows"]) * op["cell"]
    ch = len(op["rows"]) * op["cell"]
    diffs, problems = _diff(
        sprite_harness, font_dir, op, cw, ch, palette=sprite_sample_doc.get("palette")
    )
    assert problems == []
    assert not diffs, diffs[:5]


def test_sprite_oversized_cell_is_malformed_on_both_sides(sprite_harness, font_dir):
    """The two sides have to agree on the bound, not just each avoid
    overflowing on their own terms -- including the bound itself, which the
    message states so the two tables (here and in draw_sprite()) can't
    silently drift."""
    op = {
        "op": "sprite", "x": 0, "y": 0, "cell": 99999,
        "palette": {"K": "black"}, "rows": ["K"],
    }
    drew, _px, logs = sprite_harness.run(op, 10, 10)
    assert not drew
    assert any("cell" in log for log in logs)
    problems = check({"v": 1, "bg": "white", "ops": [op]}, font_dir)
    assert any("nothing to draw, skipped" in p for p in problems)
    assert any(f"<= {max(WIDTH, HEIGHT)}" in p for p in problems)


# --------------------------------------------------------------------------
# Grid bounds (docs/plans/firmware-bounds.md D7): cols, rows and palette
# size, each malformed on both sides at the same value.
# --------------------------------------------------------------------------


def test_sprite_past_cols_bound_is_malformed_on_both_sides(sprite_harness, font_dir):
    op = {
        "op": "sprite", "x": 0, "y": 0, "cell": 1,
        "palette": {"K": "black"}, "rows": ["K" * (SPRITE_MAX_COLS + 1)],
    }
    drew, _px, logs = sprite_harness.run(op, 10, 10)
    assert not drew
    assert any("columns" in log for log in logs)
    problems = check({"v": 1, "bg": "white", "ops": [op]}, font_dir)
    assert any("columns wide" in p for p in problems)


def test_sprite_past_rows_bound_is_malformed_on_both_sides_and_fast(sprite_harness, font_dir):
    """The ragged case from the plan: one long row near the column bound
    plus thousands of empty rows past the row bound -- both sides reject
    on the row count alone, before ever measuring the widest row."""
    rows = ["K" * SPRITE_MAX_COLS] + [""] * (SPRITE_MAX_ROWS + 5000)
    op = {"op": "sprite", "x": 0, "y": 0, "cell": 1, "palette": {"K": "black"}, "rows": rows}
    t0 = time.monotonic()
    drew, _px, logs = sprite_harness.run(op, 10, 10)
    cpp_elapsed = time.monotonic() - t0
    assert cpp_elapsed < 1.0, cpp_elapsed
    assert not drew
    assert any("rows" in log for log in logs)
    t0 = time.monotonic()
    problems = check({"v": 1, "bg": "white", "ops": [op]}, font_dir)
    py_elapsed = time.monotonic() - t0
    assert py_elapsed < 1.0, py_elapsed
    assert any("rows, more than" in p for p in problems)


def test_sprite_past_palette_bound_is_malformed_on_both_sides(sprite_harness, font_dir):
    palette = {chr(ord("一") + i): "black" for i in range(SPRITE_MAX_PALETTE + 1)}
    op = {"op": "sprite", "x": 0, "y": 0, "cell": 1, "palette": palette, "rows": ["a"]}
    drew, _px, logs = sprite_harness.run(op, 10, 10)
    assert not drew
    assert any("palette" in log for log in logs)
    problems = check({"v": 1, "bg": "white", "ops": [op]}, font_dir)
    assert any("palette has" in p for p in problems)


def test_sprite_at_the_pixel_box_bound_matches_the_firmware(sprite_harness, font_dir):
    """x + cols*cell == MAX_COORD exactly is legal on both sides
    (docs/plans/firmware-bounds.md D4/D7)."""
    op = {
        "op": "sprite", "x": MAX_COORD - 10, "y": 0, "cell": 1,
        "palette": {"K": "black"}, "rows": ["K" * 10],
    }
    drew, _px, logs = sprite_harness.run(op, 10, 10)
    assert drew and not logs
    problems = check({"v": 1, "bg": "white", "ops": [op]}, font_dir)
    assert not any("pixel box" in p for p in problems)


def test_sprite_past_the_pixel_box_bound_is_malformed_on_both_sides(sprite_harness, font_dir):
    op = {
        "op": "sprite", "x": MAX_COORD - 9, "y": 0, "cell": 1,
        "palette": {"K": "black"}, "rows": ["K" * 10],
    }
    drew, _px, logs = sprite_harness.run(op, 10, 10)
    assert not drew
    assert any("pixel box" in log for log in logs)
    problems = check({"v": 1, "bg": "white", "ops": [op]}, font_dir)
    assert any("pixel box" in p for p in problems)


def test_sprite_huge_float_coordinate_is_rejected_on_both_sides(sprite_harness, font_dir):
    """docs/plans/firmware-bounds.md D4's review amendment: ArduinoJson's
    `o["x"] | 0` would silently read 0 for a float like 1e10 -- any JSON
    float fails its `is<int>()` check -- rather than being rejected.
    draw_sprite() now reads x/y as `double` and bound-checks that itself,
    since it has its own harness that calls it directly, bypassing the op
    loop's own blanket check entirely."""
    op = {"op": "sprite", "x": 1e10, "y": 0, "cell": 1, "palette": {"K": "black"}, "rows": ["K"]}
    drew, _px, logs = sprite_harness.run(op, 10, 10)
    assert not drew
    # "1e+10" -- the firmware's own %g, which the ESP_LOGW stub prefixes
    # with "W " (docs/plans/firmware-bounds.md's review amendment).
    assert logs == [f"W sprite: x=1e+10 out of range (|v| <= {MAX_COORD}); skipped"]
    problems = check({"v": 1, "bg": "white", "ops": [op]}, font_dir)
    assert problems == [f"ops[0] sprite: x=1e+10 out of range (|v| <= {MAX_COORD}); skipped"]


def test_sprite_no_palette_entry_warning_capped_matches_the_firmware(sprite_harness, font_dir):
    """docs/plans/firmware-bounds.md D7's warning cap (eight distinct
    characters plus one "...and more" line) fires identically on both
    sides -- the firmware's own stderr and the Python's `problems`."""
    n_distinct = 20
    row = "".join(chr(ord("一") + i) for i in range(n_distinct))
    op = {"op": "sprite", "x": 0, "y": 0, "cell": 1, "palette": {}, "rows": [row]}
    drew, _px, logs = sprite_harness.run(op, n_distinct + 2, 2)
    assert drew  # every cell draws black; the op itself is not abandoned
    own_lines = [log for log in logs if "no palette entry for" in log]
    overflow_lines = [log for log in logs if "...and more" in log]
    assert len(own_lines) == 8
    assert len(overflow_lines) == 1
    # Each own_line names a genuinely distinct character (the review
    # amendment this pins): the C++ `warned` set is bounded to 8 entries,
    # not just the printed lines -- a bug that only throttled logging
    # while still inserting into the set would still print 8 lines here,
    # so distinctness is what actually catches it.
    cpp_warned = {log.split("no palette entry for '")[1].split("'")[0] for log in own_lines}
    assert len(cpp_warned) == 8

    problems = check({"v": 1, "bg": "white", "ops": [op]}, font_dir)
    py_own = [p for p in problems if "no palette entry for" in p]
    py_overflow = [p for p in problems if "...and more" in p]
    assert len(py_own) == 8
    assert len(py_overflow) == 1


def test_sprite_repeated_character_after_the_cap_matches_the_firmware(sprite_harness, font_dir):
    """docs/plans/firmware-bounds.md's review amendment: exactly eight
    distinct characters (A-H), the first (A) repeated once more at the
    end -- once `warned`/`warned_chars` holds eight entries, a *repeat*
    of an already-warned character must not fall into the "...and more"
    branch on either side just because the set happens to be full by
    then. Before the fix, the firmware logged "A" a second time as the
    overflow line here; the Python mirror already got this right."""
    op = {"op": "sprite", "x": 0, "y": 0, "cell": 1, "palette": {}, "rows": ["ABCDEFGHA"]}
    drew, _px, logs = sprite_harness.run(op, 12, 2)
    assert drew
    own_lines = [log for log in logs if "no palette entry for" in log]
    overflow_lines = [log for log in logs if "...and more" in log]
    assert len(own_lines) == 8
    assert overflow_lines == []

    problems = check({"v": 1, "bg": "white", "ops": [op]}, font_dir)
    py_own = [p for p in problems if "no palette entry for" in p]
    py_overflow = [p for p in problems if "...and more" in p]
    assert len(py_own) == 8
    assert py_overflow == []
    py_warned = {p.split("no palette entry for ")[1].split(";")[0] for p in py_own}
    assert len(py_warned) == 8
