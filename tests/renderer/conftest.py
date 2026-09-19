"""Shared fixtures and helpers for the renderer test package.

`sample_doc`/`sprite_sample_doc`/`vocabulary_sample_doc`/`font_dir` come from
the parent `tests/conftest.py` and apply here too. This file adds what more
than one concern-file in this package needs: the SPEC.md table parsers, a
couple of small problem-list filters, and the one document builder
(`_icon_doc`) used by both the icon and the bezel tests.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _icon_doc(sample_doc, name, z):
    doc = copy.deepcopy(sample_doc)
    doc["ops"].append({"op": "icon", "x": 10, "y": 10, "n": name, "z": z, "c": "black"})
    return doc


def _thin_mix_msgs(problems):
    return [p for p in problems if "coordinate parity" in p]


def _glyph_msgs(problems: list[str]) -> list[str]:
    return [p for p in problems if "has not compiled" in p]


_TIER_HEADINGS = (
    ("Dark backgrounds", "dark"),
    ("Light backgrounds", "light"),
    ("Mid-tone", "mid"),
)


def _spec_palette_rows():
    """The named-palette table in docs/SPEC.md, as {name: (c, c2, mix, hex, tier)}.

    Parsed rather than duplicated: the point of the tests below is that the
    published tables, their tier headings, and the renderer cannot drift
    apart, which a second copy of any of this here would defeat. `tier` is
    decided by which of the three tier headings a row's chunk of text falls
    under — the same way a reader of SPEC.md would decide it.
    """
    spec = (ROOT / "docs" / "SPEC.md").read_text()
    section = spec[spec.index("## The named palette") :]
    marks = sorted(
        (m.start(), tier)
        for heading, tier in _TIER_HEADINGS
        for m in re.finditer(re.escape(heading), section)
    )
    rows: dict[str, tuple[str, str, int, str, str]] = {}
    for i, (start, tier) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(section)
        chunk = section[start:end]
        for n, a, b, p, h in re.findall(
            r"`([a-z-]+)` \| (\w+)\+(\w+) (\d+) \| `#([0-9A-F]{6})`", chunk
        ):
            rows[n] = (a, b, int(p), h.lower(), tier)
    return rows


def _spec_palette_hexes():
    """The named-palette table in docs/SPEC.md, as {name: (c, c2, mix, hex)}."""
    return {n: v[:4] for n, v in _spec_palette_rows().items()}


def _hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*rgb)
