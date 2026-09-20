"""Pure-data differential tests that need no compiler: the three
device-safety bounds, the op-loop dispatch (grepped, not compiled), and
the compiled glyph set against `epaper-schedule.yaml`.
"""

from __future__ import annotations

import re

import pytest

from display_mcp.render import (
    BARE_ALIASES,
    FONTS,
    ICONS,
    MAX_COORD,
    NAME_MAX_LEN,
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
    assert _firmware_const_value("kNameMaxLen") == NAME_MAX_LEN


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
    assert len(entries) == len(FONTS), (
        f"expected {len(FONTS)} font entries (one per FONTS face), found {len(entries)}"
    )
    missing = [e.splitlines()[1] for e in entries if "glyphsets: [GF_Latin_Core]" not in e]
    assert not missing, f"entries missing 'glyphsets: [GF_Latin_Core]': {missing}"


def test_mono_extra_glyph_range_matches_the_yaml():
    """Every `font_mono_*` entry's `glyphs:` string, decoded back to code
    points, must be exactly `Face("mono/*").extra_glyphs` -- not just one
    of them: with Decision 3's per-size table (docs/plans/fonts-and-icons.md,
    B2) every mono size compiles its own `font:` entry, and a size the
    generator forgot to give a `glyphs:` line would silently drop the
    box-drawing/block glyphs at that size alone while every other size (and
    this test, if it only checked the first) looked fine."""
    entries = _yaml_font_entries()
    mono_names = [name for name in FONTS if name.split("/", 1)[0] == "mono"]
    mono_entries = [e for e in entries if re.search(r"^\s*id: font_mono_", e, re.MULTILINE)]
    assert len(mono_entries) == len(mono_names), (
        f"{len(mono_entries)} font_mono_* YAML entries, {len(mono_names)} mono faces in FONTS"
    )
    (extra_range,) = FONTS["mono/24"].extra_glyphs  # the same range for every mono size
    for entry in mono_entries:
        m = re.search(r'glyphs: "(.*?)"', entry)
        assert m, f"a font_mono_* entry has no glyphs: string: {entry.splitlines()[1]}"
        yaml_codepoints = {ord(c) for c in m.group(1)}
        assert yaml_codepoints == set(extra_range), (
            f"{entry.splitlines()[1]}: yaml has {len(yaml_codepoints)} code points, "
            f"Face('mono').extra_glyphs has {len(set(extra_range))}"
        )


# --------------------------------------------------------------------------
# The font vocabulary itself (docs/plans/fonts-and-icons.md Decision 1-3,
# B2): the YAML's two generated fences (`font:`'s entries, the lambda's
# `a.fonts[...]` lines) must say exactly what FONTS/FONT_ALIASES say, so the
# firmware and the renderer can never quietly disagree about which font
# spellings exist.
# --------------------------------------------------------------------------


def _yaml_font_ids() -> list[str]:
    """Every `id:` the YAML's `font:` list defines, in order -- parsed from
    the YAML text directly, the same way `_yaml_font_entries()` does."""
    src = YAML.read_text()
    start = src.index("\nfont:\n")
    end = src.index("\n\n", start + 1)
    block = src[start:end]
    return re.findall(r"^\s*id:\s*(\w+)\s*$", block, re.MULTILINE)


def _yaml_a_fonts_entries() -> dict[str, str]:
    """Every `a.fonts["key"] = id(some_id);` line inside the display
    lambda, as `{key: id}` -- parsed from the YAML text directly."""
    from display_mcp.render.firmware_yaml import FONT_LAMBDA_END, FONT_LAMBDA_START

    # Only the fenced lines count: a commented-out `a.fonts[...]` left as
    # documentation elsewhere in the YAML must not read as a spelling the
    # firmware accepts (B2 review, N3).
    src = YAML.read_text()
    start = src.index(FONT_LAMBDA_START)
    end = src.index(FONT_LAMBDA_END, start)
    fence = src[start:end]
    entries = re.findall(r'a\.fonts\["([^"]+)"\]\s*=\s*id\((\w+)\);', fence)
    # One line per spelling, no repeats (N4): a set comparison alone would
    # pass a self-consistent duplicate. B4b: only the five bare aliases are
    # carried as their own entry any more (110 + 5 = 115), not all 55
    # (B2's count) -- the fifty pixel-count aliases are normalised by the
    # firmware itself instead (docs/plans/fonts-and-icons.md Decision 4).
    assert len(entries) == len(FONTS) + len(BARE_ALIASES), len(entries)
    return dict(entries)


def test_yaml_font_and_icon_fences_match_the_generated_tables():
    """The YAML's four font/icon fences are exactly what
    `firmware_yaml.generate_firmware_yaml()` emits from today's
    `FONTS`/`FONT_ALIASES`/`ICONS`/`ICON_SIZES` -- the font/icon analogue of
    the glyph-set parity test above. Run on a copy of the YAML text (never
    written back), so a stale committed file fails this test instead of
    being silently accepted."""
    from display_mcp.render.firmware_yaml import generate_firmware_yaml

    src = YAML.read_text()
    assert generate_firmware_yaml(src) == src, (
        "epaper-schedule.yaml's font/icon fences are stale -- run "
        "`display-mcp-cli firmware-vocabulary` to regenerate them"
    )


def test_a_fonts_keys_are_exactly_fonts_and_bare_aliases():
    keys = set(_yaml_a_fonts_entries())
    expected = set(FONTS) | set(BARE_ALIASES)
    assert keys == expected, (
        f"only in the YAML: {sorted(keys - expected)}; "
        f"only in FONTS + the five bare aliases: {sorted(expected - keys)}"
    )


def test_every_a_fonts_id_is_defined_in_the_font_block():
    used = set(_yaml_a_fonts_entries().values())
    defined = set(_yaml_font_ids())
    missing = used - defined
    assert not missing, f"a.fonts[...] references undefined font id(s): {sorted(missing)}"


def test_no_duplicate_font_ids():
    ids = _yaml_font_ids()
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"duplicate id(s) in the YAML's font: block: {sorted(dupes)}"


# --------------------------------------------------------------------------
# The icon vocabulary (docs/plans/fonts-and-icons.md Decision 4, B4b): the
# YAML's `image:`/`a.icons[...]` fences must say exactly what ICONS/
# ICON_SIZES say -- unlike fonts, every key is canonical (`name/slot`); there
# is no bare or pixel-count alias to carry as its own map entry, since
# `display_list.h`'s `normalize_size_alias()` handles a pixel-count `z` the
# same way it handles a pixel-count font size.
# --------------------------------------------------------------------------

_ALL_ICON_KEYS: set[str] = {f"{name}/{slot}" for name, slots in ICONS.items() for slot in slots}


def _yaml_icon_ids() -> list[str]:
    """Every `id:` the YAML's `image:` list defines, in order."""
    from display_mcp.render.firmware_yaml import ICON_YAML_END, ICON_YAML_START

    src = YAML.read_text()
    start = src.index(ICON_YAML_START)
    end = src.index(ICON_YAML_END, start)
    fence = src[start:end]
    return re.findall(r"id:\s*(\w+)\s*,", fence)


def _yaml_a_icons_entries() -> dict[str, str]:
    """Every `a.icons["key"] = id(some_id);` line inside the display
    lambda, as `{key: id}` -- parsed from the fenced text directly."""
    from display_mcp.render.firmware_yaml import ICON_LAMBDA_END, ICON_LAMBDA_START

    src = YAML.read_text()
    start = src.index(ICON_LAMBDA_START)
    end = src.index(ICON_LAMBDA_END, start)
    fence = src[start:end]
    entries = re.findall(r'a\.icons\["([^"]+)"\]\s*=\s*id\((\w+)\);', fence)
    assert len(entries) == len(_ALL_ICON_KEYS), len(entries)
    return dict(entries)


def test_a_icons_keys_are_exactly_icons_and_slots():
    keys = set(_yaml_a_icons_entries())
    assert keys == _ALL_ICON_KEYS, (
        f"only in the YAML: {sorted(keys - _ALL_ICON_KEYS)}; "
        f"only in ICONS: {sorted(_ALL_ICON_KEYS - keys)}"
    )


def test_every_a_icons_id_is_defined_in_the_image_block():
    used = set(_yaml_a_icons_entries().values())
    defined = set(_yaml_icon_ids())
    missing = used - defined
    assert not missing, f"a.icons[...] references undefined image id(s): {sorted(missing)}"


def test_no_duplicate_icon_ids():
    ids = _yaml_icon_ids()
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"duplicate id(s) in the YAML's image: block: {sorted(dupes)}"


def test_image_block_entry_count_matches_icons():
    assert len(_yaml_icon_ids()) == len(_ALL_ICON_KEYS) == 95


# --------------------------------------------------------------------------
# The fence-rewriting mechanism itself (firmware_yaml.rewrite_fenced_region),
# tested against synthetic text -- no YAML file needed.
# --------------------------------------------------------------------------


def test_rewrite_fenced_region_leaves_outside_text_untouched():
    from display_mcp.render.firmware_yaml import rewrite_fenced_region

    text = "before\nSTART\nold body\nEND\nafter\n"
    out = rewrite_fenced_region(text, "START", "END", "new body")
    assert out == "before\nSTART\nnew body\nEND\nafter\n"


# Idempotence has no synthetic test of its own: applying
# `rewrite_fenced_region()` a second time with the same body to the exact
# output the test above pins is the same call re-derived by the same code,
# and the idempotence that matters -- on the real YAML, from the real tables
# -- is `test_yaml_font_and_icon_fences_match_the_generated_tables`'s
# `generate_firmware_yaml(src) == src`.


@pytest.mark.parametrize(
    ("text", "match"),
    [
        # no marker at all -- names the marker it could not find
        pytest.param("no markers here", "START", id="missing-start"),
        # a marker twice: which start/end pair would it be?
        pytest.param("STARTfirst\nSTART\nbody\nEND\nafter\n", r"appears 2 times", id="duplicate"),
        # a start with no end
        pytest.param("START\nbody\nno end\n", "END", id="missing-end"),
        # both present but in the wrong order (the `end < start` guard)
        pytest.param("END\nbody\nSTART\n", r"appears before its start marker", id="reversed"),
    ],
)
def test_rewrite_fenced_region_broken_fence_raises_clearly(text, match):
    """Each of the four ways the fence can be broken raises `RuntimeError`
    naming which marker and why, rather than silently rewriting the wrong
    span of a file the generator owns. One case per branch of
    `rewrite_fenced_region()`'s own guard block."""
    from display_mcp.render.firmware_yaml import rewrite_fenced_region

    with pytest.raises(RuntimeError, match=match):
        rewrite_fenced_region(text, "START", "END", "body")
