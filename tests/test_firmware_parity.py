"""Differential tests: the shipped firmware header against the Python renderer.

`firmware/display_list.h` is authoritative (docs/SPEC.md) and
`display_mcp.render` mirrors it, so where the two disagree the Python is the
bug. The wrap/truncate pair has been diffed this way since the port; this
module does the same for the ink-mixing mask.

The C++ is **extracted from the shipped header**, never retyped here — a copy
would only prove that two copies agree. If the header's shape changes enough
that the extraction fails, that is a test failure and not a silent skip.

Needs a host C++ compiler; skips cleanly without one.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from display_mcp.render import BUILTIN_MIXES, DENSITIES, INK, mix_on

HEADER = Path(__file__).resolve().parents[1] / "firmware" / "display_list.h"

# Only the mix_on tests need a compiler; the table tests are pure data and
# always run, so a machine without a toolchain still catches a drifted table.


def _extract(pattern: str, what: str) -> str:
    src = HEADER.read_text()
    m = re.search(pattern, src, re.MULTILINE)
    assert m, f"could not find {what} in {HEADER.name} — has it been renamed?"
    return m.group(0)


@pytest.fixture(scope="module")
def cpp_mix_on(tmp_path_factory):
    """Compile the header's own mix_on and return a callable front end."""
    if shutil.which("c++") is None:
        pytest.skip("no host C++ compiler")
    matrix = _extract(r"^static const uint8_t B\[2\]\[2\].*;$", "the Bayer matrix")
    fn = _extract(r"^inline bool mix_on\(.*$", "mix_on()")

    d = tmp_path_factory.mktemp("parity")
    src = d / "mix_on.cpp"
    src.write_text(
        textwrap.dedent(
            """\
            #include <cstdint>
            #include <cstdio>
            %s
            %s
            int main() {
              // Every percentage, not just the three legal densities: within
              // {25,50,75,100} a `/ 20` divisor is indistinguishable from
              // `/ 25`, so sweeping the whole range is what actually pins the
              // arithmetic down.
              for (int pct = 0; pct <= 100; pct++)
                for (int y = 0; y < 16; y++)
                  for (int x = 0; x < 16; x++)
                    printf("%%d %%d %%d %%d\\n", pct, x, y,
                           mix_on(x, y, pct) ? 1 : 0);
              return 0;
            }
            """
        )
        % (matrix, fn)
    )
    exe = d / "mix_on"
    subprocess.run(
        ["c++", "-std=c++17", "-O0", "-o", str(exe), str(src)], check=True
    )
    out = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout
    table = {}
    for line in out.splitlines():
        pct, x, y, on = (int(v) for v in line.split())
        table[(pct, x, y)] = bool(on)
    return table


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
# the built-in mix table — docs/plans/ink-mixing.md decision 10
#
# Twenty-one entries transcribed between C++ and Python is exactly where a
# typo hides and is never noticed: the wrong colour still draws, still
# validates, and only looks slightly off on a wall nobody is measuring. The
# table is a permanent contract, so it is diffed rather than trusted.
#
# This one needs no compiler — it is a data table, not behaviour — so unlike
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


def test_builtin_names_match_the_firmware():
    fw = _firmware_table()
    assert set(fw) == set(BUILTIN_MIXES), (
        f"only in firmware: {sorted(set(fw) - set(BUILTIN_MIXES))}; "
        f"only in python: {sorted(set(BUILTIN_MIXES) - set(fw))}"
    )


@pytest.mark.parametrize("name", sorted(BUILTIN_MIXES))
def test_builtin_recipe_matches_the_firmware(name):
    fw = _firmware_table()
    assert fw[name] == BUILTIN_MIXES[name], (
        f"{name}: firmware says {fw[name]}, python says {BUILTIN_MIXES[name]}"
    )


@pytest.mark.parametrize("name,recipe", sorted(BUILTIN_MIXES.items()))
def test_builtin_recipes_are_well_formed(name, recipe):
    """Every entry names two real, different inks at a legal density."""
    c, c2, mix = recipe
    assert c in INK, f"{name}: unknown base ink {c!r}"
    assert c2 in INK, f"{name}: unknown second ink {c2!r}"
    assert c != c2, f"{name}: c and c2 are the same ink, so it is not a mix"
    assert mix in DENSITIES, f"{name}: density {mix} is not one of {DENSITIES}"


def test_builtin_names_are_documented_in_the_spec():
    """A name the spec does not carry is a name no caller can discover."""
    spec = (HEADER.parent.parent / "docs" / "SPEC.md").read_text()
    missing = [n for n in BUILTIN_MIXES if f"`{n}`" not in spec]
    assert not missing, f"not in docs/SPEC.md: {missing}"
