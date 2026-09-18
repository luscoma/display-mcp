"""swatch_document() / swatch_groups() -- docs/plans/ink-mixing.md's
closing coupon: every named colour as a chip, and the sheet is itself a
valid document.

Fixture note: `font_dir` comes from tests/conftest.py.
"""

from __future__ import annotations

import re

import pytest

from display_mcp.render import (
    BEZEL_MARGIN,
    BUILTIN_MIXES,
    COLORS,
    FONTS,
    HEIGHT,
    INK,
    check,
    render,
    swatch_document,
    swatch_groups,
)

from .conftest import _hex, _spec_palette_hexes


def test_swatch_document_validates_clean(font_dir):
    """The whole point of building it as an ordinary document: it has to
    pass the same bezel/contrast/off-canvas checks any other one does."""
    assert check(swatch_document(), font_dir) == []


def test_swatch_groups_covers_every_ink_and_builtin_exactly_once():
    groups = swatch_groups()
    labels = [label for _title, entries in groups for label, *_ in entries]
    assert sorted(labels) == sorted(set(COLORS) | set(BUILTIN_MIXES))
    assert len(labels) == len(COLORS) + len(BUILTIN_MIXES)  # no duplicate
    assert [title for title, _ in groups] == ["inks", "dark", "light", "mid"]


def test_every_builtin_flat_chip_matches_its_spec_hex(font_dir):
    """Renders swatch_document() flat once (dithered_colors=False, as the
    MCP tool renders it) and, for every built-in, checks BUILTIN_MIXES'
    recipe against docs/SPEC.md and the chip-centre pixel against the
    documented hex -- one render for the whole sheet rather than one per
    name. Also covers that every ink and builtin gets exactly one chip."""
    doc = swatch_document()
    rect_colors = {op["c"] for op in doc["ops"] if op["op"] == "rect"}
    assert rect_colors == set(COLORS) | {f"sw:{name}" for name in BUILTIN_MIXES}
    assert check(doc, font_dir) == []
    img, problems = render(doc, font_dir, dithered_colors=False)
    assert problems == []
    px = img.load()
    hexes = _spec_palette_hexes()
    for name in sorted(BUILTIN_MIXES):
        c, c2, pct, want = hexes[name]
        assert BUILTIN_MIXES[name] == (c, c2, pct), name
        chip = next(op for op in doc["ops"] if op["op"] == "rect" and op["c"] == f"sw:{name}")
        cx, cy = chip["x"] + chip["w"] // 2, chip["y"] + chip["h"] // 2
        assert _hex(px[cx, cy]).lower() == f"#{want}", name


def test_swatch_document_appends_a_documents_own_palette(font_dir):
    palette = {"flame": {"c": "red", "c2": "yellow", "mix": 50}}
    doc = swatch_document(palette=palette)
    assert check(doc, font_dir) == []
    labels = [op["s"] for op in doc["ops"] if op.get("f") == "sm"]
    assert "flame" in labels
    chip = next(op for op in doc["ops"] if op["op"] == "rect" and op["c"] == "flame")
    img, problems = render(doc, font_dir, dithered_colors=False)
    assert problems == []
    cx, cy = chip["x"] + chip["w"] // 2, chip["y"] + chip["h"] // 2
    assert _hex(img.load()[cx, cy]) == "#B56D2B"  # red+yellow 50, docs/SPEC.md "orange"'s recipe


def test_swatch_document_skips_an_unresolvable_palette_entry():
    groups = swatch_groups(palette={"flame": "red", "ghost": "nope"})
    title, entries = groups[-1]
    assert title == "document palette"
    assert [label for label, *_ in entries] == ["flame"]


def test_swatch_document_with_only_unresolvable_palette_entries_adds_no_group():
    groups = swatch_groups(palette={"ghost": "nope"})
    assert [title for title, _ in groups] == ["inks", "dark", "light", "mid"]


def test_swatch_document_a_shadowed_builtin_name_still_shows_canonically(font_dir):
    """SPEC.md: a document's own `navy` shadows the built-in one. The
    "document palette" group should show the document's own colour under
    that name; the canonical `navy` chip earlier on the sheet must not."""
    palette = {"navy": {"c": "red", "c2": "yellow", "mix": 50}}
    doc = swatch_document(palette=palette)
    assert check(doc, font_dir) == []
    canonical = next(op for op in doc["ops"] if op["op"] == "rect" and op["c"] == "sw:navy")
    shadowed = next(op for op in doc["ops"] if op["op"] == "rect" and op["c"] == "navy")
    img, problems = render(doc, font_dir, dithered_colors=False)
    assert problems == []
    px = img.load()
    c, cy = canonical["x"] + canonical["w"] // 2, canonical["y"] + canonical["h"] // 2
    sx, sy = shadowed["x"] + shadowed["w"] // 2, shadowed["y"] + shadowed["h"] // 2
    assert _hex(px[c, cy]) == "#272F50"  # docs/SPEC.md navy: black+blue 50
    assert _hex(px[sx, sy]) == "#B56D2B"  # the document's own red+yellow 50


def test_swatch_document_six_palette_entries_fit_with_no_more_line(font_dir):
    """A group small enough to fit in one row (the built-in groups'
    own size) needs no truncation."""
    palette = {f"c{i}": {"c": "red", "c2": "yellow", "mix": 50} for i in range(6)}
    doc = swatch_document(palette=palette)
    assert check(doc, font_dir) == []
    assert not any(
        op["op"] == "text" and "more not shown" in op["s"] for op in doc["ops"]
    )


@pytest.mark.parametrize("n", [12, 30])
def test_swatch_document_document_palette_overflow_fits_the_page(font_dir, n):
    """The appended "document palette" group is the one group whose
    size isn't fixed — 12 or 30 entries must still lay out only what fits
    `HEIGHT - BEZEL_MARGIN` and summarise the rest, rather than trip a
    bezel warning per row."""
    palette = {f"c{i}": {"c": "red", "c2": "yellow", "mix": 50} for i in range(n)}
    doc = swatch_document(palette=palette)
    assert check(doc, font_dir) == []

    more_ops = [
        op for op in doc["ops"] if op["op"] == "text" and op["s"].endswith("more not shown")
    ]
    assert len(more_ops) == 1
    match = re.match(r"\+(\d+) more not shown$", more_ops[0]["s"])
    assert match is not None
    hidden = int(match.group(1))
    assert hidden > 0

    shown_chips = [
        op
        for op in doc["ops"]
        if op["op"] == "rect" and op.get("fill", True) is not False and op["c"] in palette
    ]
    assert len(shown_chips) + hidden == n

    for op in doc["ops"]:
        if op["op"] == "rect":
            assert op["y"] + op["h"] <= HEIGHT
        else:
            size = FONTS[op.get("f", "xs")].size
            assert op["y"] + size <= HEIGHT


def test_swatch_chip_has_a_black_outline_and_still_validates_clean(font_dir):
    """Every chip — including `white`, otherwise invisible on the white
    page — gets a 1px black rule drawn just outside it, and that outline
    never trips check()'s contrast or bezel checks."""
    doc = swatch_document()
    chips = [
        op for op in doc["ops"] if op["op"] == "rect" and op.get("fill", True) is not False
    ]
    outlines = {
        (op["x"], op["y"]): op
        for op in doc["ops"]
        if op["op"] == "rect" and op.get("fill") is False
    }
    assert len(outlines) == len(chips)
    for chip in chips:
        outline = outlines[(chip["x"] - 1, chip["y"] - 1)]
        assert outline["w"] == chip["w"] + 2
        assert outline["h"] == chip["h"] + 2
        assert outline["c"] == "black"
        assert outline["t"] == 1
        assert outline["x"] > BEZEL_MARGIN  # x-1 stays outside the bezel margin
    assert check(doc, font_dir) == []

    img, problems = render(doc, font_dir, dithered_colors=False)
    assert problems == []
    white_chip = next(op for op in doc["ops"] if op["op"] == "rect" and op["c"] == "white")
    outline = outlines[(white_chip["x"] - 1, white_chip["y"] - 1)]
    assert _hex(img.load()[outline["x"], outline["y"]]) == _hex(INK["black"])


def test_swatch_document_reserved_sw_key_collision_favours_the_canonical_chip(font_dir):
    """A document palette entry literally named `sw:navy` must not
    shadow the reserved key `swatch_document()` uses for navy's own chip —
    the reserved key always wins."""
    palette = {"sw:navy": {"c": "red", "c2": "yellow", "mix": 50}}
    doc = swatch_document(palette=palette)
    assert check(doc, font_dir) == []
    assert doc["palette"]["sw:navy"] == {"c": "black", "c2": "blue", "mix": 50}

    groups = swatch_groups(palette=palette)
    # The one entry the caller passed collided with a reserved key and is
    # skipped rather than misrepresented, so there is nothing left to put
    # in a "document palette" group.
    assert [title for title, _ in groups] == ["inks", "dark", "light", "mid"]

    canonical = next(op for op in doc["ops"] if op["op"] == "rect" and op["c"] == "sw:navy")
    img, problems = render(doc, font_dir, dithered_colors=False)
    assert problems == []
    cx, cy = canonical["x"] + canonical["w"] // 2, canonical["y"] + canonical["h"] // 2
    assert _hex(img.load()[cx, cy]) == "#272F50"  # docs/SPEC.md navy, not the collision's recipe
