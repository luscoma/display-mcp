"""sprite, differentially. draw_sprite() is factored out of the op loop
precisely so it -- and utf8_prev/utf8_next/mix_on/struct Ink/MixDisplay,
which it's built on -- can be extracted verbatim, compiled against a stub
Display/ArduinoJson, and rasterised, then diffed pixel-for-pixel against
display_mcp.render.render(). JSON edge cases that never reach the pixels
(a palette key that isn't one character, a non-string row element, a bad
mirror value...) are exercised on the Python side in tests/render/; this
module only has to prove the two sides paint the same thing once an op's
fields are legal.

Needs a host C++ compiler; skips cleanly without one (see conftest.py).
"""

from __future__ import annotations

from display_mcp.render import HEIGHT, WIDTH, check, render

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
