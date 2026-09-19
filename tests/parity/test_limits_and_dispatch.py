"""Pure-data differential tests that need no compiler: the three
device-safety bounds, the op-loop dispatch (grepped, not compiled), and
the compiled glyph set against `epaper-schedule.yaml`.
"""

from __future__ import annotations

import re

import pytest

from display_mcp.render import (
    FONTS,
    MAX_COORD,
    POLY_MAX_PTS,
    SPRITE_MAX_CELL,
    SPRITE_MAX_COLS,
    SPRITE_MAX_PALETTE,
    SPRITE_MAX_ROWS,
    TEXT_MAX_LEN,
    TEXT_MAX_LINES,
    THICK_MAX,
)
from display_mcp.store import MAX_DOC_BYTES

from .conftest import HEADER, YAML, _branch, _firmware_const_value


def test_device_safety_limits_match_the_firmware():
    """Every device-safety bound (docs/plans/firmware-bounds.md D4/D6/D7/D8,
    docs/plans/dragon-feedback.md D9) is the same value on both sides --
    each `kFoo` sits at namespace scope in the header the same way its
    Python name does here. Pure data, no compiler needed."""
    assert _firmware_const_value("kThickMax") == THICK_MAX
    assert _firmware_const_value("kSpriteMaxCell") == SPRITE_MAX_CELL
    assert _firmware_const_value("kMaxCoord") == MAX_COORD
    assert _firmware_const_value("kTextMaxLen") == TEXT_MAX_LEN
    assert _firmware_const_value("kTextMaxLines") == TEXT_MAX_LINES
    assert _firmware_const_value("kSpriteMaxCols") == SPRITE_MAX_COLS
    assert _firmware_const_value("kSpriteMaxRows") == SPRITE_MAX_ROWS
    assert _firmware_const_value("kSpriteMaxPalette") == SPRITE_MAX_PALETTE
    assert _firmware_const_value("kPolyMaxPts") == POLY_MAX_PTS


# ESPHome's own metric prefixes (config_validation.py's METRIC_SUFFIXES) are
# decimal, not binary -- "k" is 1000, not 1024, which is exactly the bug a
# literal "64kB" in the YAML would have (64000, 1536 bytes short of 64 KiB).
# Narrowed to the prefixes this file could plausibly use, rather than
# importing esphome itself, which this package has no other reason to
# depend on.
_ESPHOME_METRIC_SUFFIXES = {"": 1, "k": 1_000, "M": 1_000_000, "G": 1_000_000_000}


def _parse_esphome_bytes(value: str) -> int:
    """A byte-count literal the way ESPHome's own `validate_bytes()` reads
    it: `<digits><optional decimal prefix><optional B/b>`."""
    m = re.match(r"^(\d+)\s*([kMG]?)B?$", value)
    assert m, f"could not parse byte literal {value!r} the way ESPHome does"
    return int(m.group(1)) * _ESPHOME_METRIC_SUFFIXES[m.group(2)]


def test_parse_esphome_bytes_matches_the_validator():
    """Pins this test file's own reimplementation against the real
    validator it stands in for, at exactly the case that motivated D9's
    fix -- skips cleanly if the `esphome` Python package (a separate CLI
    install, not a dependency of this project) isn't importable here."""
    cv = pytest.importorskip("esphome.config_validation")

    for literal in ("64kB", "65536B", "65536", "1kB", "2MB"):
        assert _parse_esphome_bytes(literal) == cv.validate_bytes(literal), literal


def test_yaml_response_buffer_matches_the_store_ceiling():
    """docs/plans/firmware-bounds.md D9: the YAML's
    `max_response_buffer_size` and `store.MAX_DOC_BYTES` are one number
    stated twice, and this is what keeps them from drifting apart -- read
    with ESPHome's own (decimal) unit rules, not a binary-KB assumption
    that a literal like "64kB" would get wrong by 1536 bytes. Parsed from
    the YAML text directly, the same way `_yaml_font_entries()` below reads
    it, rather than loading the file through a full ESPHome/YAML parse this
    package has no other reason to depend on."""
    src = YAML.read_text()
    m = re.search(r"max_response_buffer_size:\s*(\S+)", src)
    assert m, "could not find max_response_buffer_size in the YAML"
    assert _parse_esphome_bytes(m.group(1)) == MAX_DOC_BYTES


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
