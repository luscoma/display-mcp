"""Differential tests: the compiled mix_on() mask, and the built-in mix
table, against the shipped firmware header. `firmware/display_list.h` is
authoritative (docs/SPEC.md) and `display_mcp.render` mirrors it, so where
the two disagree the Python is the bug.
"""

from __future__ import annotations

import re

import pytest

from display_mcp.render import BUILTIN_MIXES, DENSITIES, INK, mix_on

from .conftest import HEADER

# The mix_on tests need a compiler (module-scoped `cpp_mix_on`); the table
# tests are pure data and always run, so a machine without a toolchain
# still catches a drifted table.


def test_mix_on_matches_the_firmware(cpp_mix_on):
    """Every cell, every density: the two implementations must agree."""
    disagreements = [
        (pct, x, y, want, mix_on(x, y, pct))
        for (pct, x, y), want in cpp_mix_on.items()
        if mix_on(x, y, pct) != want
    ]
    assert not disagreements, f"{len(disagreements)} cells differ, e.g. {disagreements[:4]}"


@pytest.mark.parametrize("pct", DENSITIES)
def test_firmware_densities_are_exact(cpp_mix_on, pct):
    """The compiled mask really does select pct% of a 16x16 field."""
    on = sum(1 for (p, _, _), v in cpp_mix_on.items() if p == pct and v)
    assert on / 256 == pct / 100


def test_firmware_50_percent_is_the_historic_checkerboard(cpp_mix_on):
    """The compatibility claim, checked against the compiled header rather
    than against the comment that asserts it: every shipped document using
    `tone` depends on the 50% mask being exactly `(x + y) % 2 == 0`."""
    assert all(
        v == ((x + y) % 2 == 0)
        for (pct, x, y), v in cpp_mix_on.items()
        if pct == 50
    )


# --------------------------------------------------------------------------
# the built-in mix table -- docs/plans/ink-mixing.md decision 10
#
# Twenty-one entries transcribed between C++ and Python is exactly where a
# typo hides and is never noticed: the wrong colour still draws, still
# validates, and only looks slightly off on a wall nobody is measuring. The
# table is a permanent contract, so it is diffed rather than trusted. This
# one needs no compiler -- it is a data table, not behaviour -- so unlike
# the mix_on tests above it always runs.
# --------------------------------------------------------------------------

_ENTRY_RE = re.compile(
    r'^\s*\{"(?P<name>[a-z-]+)",\s*"(?P<c>[a-z]+)",\s*"(?P<c2>[a-z]+)",\s*(?P<mix>\d+)\},\s*$',
    re.MULTILINE,
)


def _firmware_table() -> dict[str, tuple[str, str, int]]:
    src = HEADER.read_text()
    start = src.index("BUILTIN_MIXES[]")
    end = src.index("};", start)
    table = {
        m.group("name"): (m.group("c"), m.group("c2"), int(m.group("mix")))
        for m in _ENTRY_RE.finditer(src[start:end])
    }
    assert table, f"could not extract BUILTIN_MIXES from {HEADER.name}"
    return table


def test_builtin_table_has_no_compiler_dependency():
    """Guard the guard: if the extraction silently matched nothing, every
    comparison below would pass vacuously."""
    assert len(_firmware_table()) == len(BUILTIN_MIXES) > 0


def test_builtin_mixes_match_the_firmware():
    """The firmware's table is the same 21 names with the same recipes as
    Python's, and every recipe names two real, different inks at a legal
    density -- the SPEC-table parser test (tests/renderer/test_colour.py) is
    the stronger check that every name is documented, so this stays
    firmware-focused."""
    fw = _firmware_table()
    diff = sorted(n for n in fw.keys() & BUILTIN_MIXES.keys() if fw[n] != BUILTIN_MIXES[n])
    assert fw == BUILTIN_MIXES, (
        f"only in firmware: {sorted(set(fw) - set(BUILTIN_MIXES))}; "
        f"only in python: {sorted(set(BUILTIN_MIXES) - set(fw))}; "
        f"differing recipes: {diff}"
    )
    for name, (c, c2, mix) in BUILTIN_MIXES.items():
        assert c in INK, f"{name}: unknown base ink {c!r}"
        assert c2 in INK, f"{name}: unknown second ink {c2!r}"
        assert c != c2, f"{name}: c and c2 are the same ink, so it is not a mix"
        assert mix in DENSITIES, f"{name}: density {mix} is not one of {DENSITIES}"
