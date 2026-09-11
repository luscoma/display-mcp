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

from display_mcp.render import DENSITIES, mix_on

HEADER = Path(__file__).resolve().parents[1] / "firmware" / "display_list.h"

pytestmark = pytest.mark.skipif(
    shutil.which("c++") is None, reason="no host C++ compiler"
)


def _extract(pattern: str, what: str) -> str:
    src = HEADER.read_text()
    m = re.search(pattern, src, re.MULTILINE)
    assert m, f"could not find {what} in {HEADER.name} — has it been renamed?"
    return m.group(0)


@pytest.fixture(scope="module")
def cpp_mix_on(tmp_path_factory):
    """Compile the header's own mix_on and return a callable front end."""
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
