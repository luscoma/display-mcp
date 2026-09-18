"""Pure-data differential tests that need no compiler: the three
device-safety bounds, the op-loop dispatch (grepped, not compiled), and
the compiled glyph set against `epaper-schedule.yaml`.
"""

from __future__ import annotations

import re

from display_mcp.render import FONTS, POLY_MAX_COORD, SPRITE_MAX_CELL, THICK_MAX

from .conftest import HEADER, YAML, _branch, _firmware_const_value


def test_device_safety_limits_match_the_firmware():
    """THICK_MAX/SPRITE_MAX_CELL/POLY_MAX_COORD (docs/plans/dragon-feedback.md
    D9/D12) are the same bound on both sides -- kThickMax, kSpriteMaxCell and
    kPolyMaxCoord sit together at namespace scope in the header the same way
    these three do here. Pure data, no compiler needed."""
    assert _firmware_const_value("kThickMax") == THICK_MAX
    assert _firmware_const_value("kSpriteMaxCell") == SPRITE_MAX_CELL
    assert _firmware_const_value("kPolyMaxCoord") == POLY_MAX_COORD


# --------------------------------------------------------------------------
# sprite/poly/rect (docs/plans/dragon-feedback.md B1, D10, B2) -- the op
# loop must actually dispatch on each, so the two sides cannot silently
# diverge on whether it exists at all.
# --------------------------------------------------------------------------


def test_op_loop_dispatches_every_compiled_op():
    """The op loop must actually dispatch on sprite and poly, so the two
    sides cannot silently diverge on whether either op exists at all; and
    the rect/circle branches must read the field the plan says (D10, B2)
    and hand off to the right helper, not just contain the field name
    somewhere in the file. These harnesses test the functions the branches
    call, not the dispatch itself -- this is the one test of the dispatch."""
    src = HEADER.read_text()
    assert 'strcmp(kind, "sprite")' in src
    assert 'strcmp(kind, "poly")' in src

    rect_block = _branch(src, 'strcmp(kind, "rect")', 'strcmp(kind, "line")')
    assert 'o["r"]' in rect_block
    assert "draw_rounded_rect(" in rect_block

    circle_block = _branch(src, 'strcmp(kind, "circle")', 'strcmp(kind, "text")')
    assert 'o["t"]' in circle_block
    assert "draw_circle_ring(" in circle_block


# --------------------------------------------------------------------------
# Compiled glyph set (docs/plans/dragon-feedback.md D11): epaper-schedule.yaml
# is what actually tells the ESPHome build which code points to compile in,
# so it -- not display_list.h -- is the oracle here. No compiler needed:
# this is a data comparison, like the BUILTIN_MIXES table.
# --------------------------------------------------------------------------


def _yaml_font_entries() -> list[str]:
    """One block of text per `font:` list entry, id to id, so each font's
    own `glyphsets:`/`glyphs:` lines can be checked in isolation."""
    src = YAML.read_text()
    start = src.index("\nfont:\n")
    end = src.index("\n\n", start + 1)
    block = src[start:end]
    ids = [m.start() for m in re.finditer(r"^\s*- file:", block, re.MULTILINE)]
    ids.append(len(block))
    return [block[a:b] for a, b in zip(ids, ids[1:], strict=False)]


def test_every_font_entry_lists_gf_latin_core():
    entries = _yaml_font_entries()
    assert len(entries) == 6, f"expected six font entries, found {len(entries)}"
    missing = [e.splitlines()[1] for e in entries if "glyphsets: [GF_Latin_Core]" not in e]
    assert not missing, f"entries missing 'glyphsets: [GF_Latin_Core]': {missing}"


def test_mono_extra_glyph_range_matches_the_yaml():
    """`font_mono`'s `glyphs:` string, decoded back to code points, must be
    exactly `Face("mono").extra_glyphs` -- the YAML and the Python table
    are two independent statements of the same range, and either one
    drifting silently un-compiles or over-promises glyphs."""
    entries = _yaml_font_entries()
    mono_entry = next(e for e in entries if "font_mono" in e)
    m = re.search(r'glyphs: "(.*?)"', mono_entry)
    assert m, "font_mono entry has no glyphs: string"
    yaml_codepoints = {ord(c) for c in m.group(1)}

    (extra_range,) = FONTS["mono"].extra_glyphs
    assert yaml_codepoints == set(extra_range), (
        f"yaml has {len(yaml_codepoints)} code points, "
        f"Face('mono').extra_glyphs has {len(set(extra_range))}"
    )
