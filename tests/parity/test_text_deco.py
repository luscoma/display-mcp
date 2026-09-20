"""`deco`'s geometry (docs/plans/fonts-and-icons.md Decision 5, landed as
B5), differentially against the shipped header's `deco_rule_geometry()`.

The rule's *drawing* -- `get_text_bounds()`, `mix.print()`,
`clipped_filled_rectangle()` -- needs a real `BaseFont`/`Display`, which
this package's stub (see conftest.py's module docstring) doesn't have and
isn't worth building just for this: text position parity with the
firmware is eyeball, not differential, everywhere else in this file too
(Decision 5 says so explicitly -- "eyeball parity like rect, not a
differential test"). `deco_rule_geometry()` is the one part of the feature
that *is* pure arithmetic with no Display/BaseFont/JSON dependency, kept
free-standing in the header for exactly this reason, so it's what gets a
real differential diff here: the three numbers (`t`, and the two vertical
offsets) round half away from zero on both sides, and this is the test
that would catch the two sides disagreeing at an exact `.5` the way a
plain Python `round()` would (see `_round_half_away_from_zero()`'s
docstring in `display_mcp.render`).

Needs a host C++ compiler; skips cleanly without one (see conftest.py).
`font_dir` (tests/conftest.py) is also needed, to measure the real
per-face heights below -- skips cleanly without the fonts fetched either.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from display_mcp.render import FONTS, _deco_rule_geometry, load_font

from .conftest import _compile, _extract_block


# The real height every compiled face measures at -- `f.font.height`
# (Pillow's own FreeType line height), NOT `Face.cell_height`
# (B5 review fix): the firmware's font_height() returns ESPHome's compiled
# `height_`, which is FreeType's line-height metric and disagrees with
# `cell_height` (ascent + descent) by 1px on some faces (xs, sm, xl, mono)
# -- see display_mcp.render's own comment where `deco_h` is computed. Using
# `cell_height` here would silently test a number the firmware never
# produces.
#
# Plus: synthetic heights the real ladder doesn't reach at all -- `h = 14k
# + 7` puts `h/14` exactly on `k + 0.5` for `k = 0..6` (7, 21, 35, 49, 63,
# 77, 91), none of which is any compiled face's real height today (checked
# against every one of them, B5's review fix -- an earlier version of this
# comment claimed `sm` was 35, which used `cell_height` rather than the
# firmware's actual `font_height()`) -- so this sweep, not any real face,
# is what actually proves the two roundings agree at the tie. And `0`/a
# negative height, since `_round_half_away_from_zero()`'s docstring claims
# sign handling is mirrored on both sides but nothing here previously
# exercised it.
def _real_heights(font_dir) -> set[int]:
    heights = set()
    for face in FONTS.values():
        f = load_font(font_dir, face)
        if f is not None:
            heights.add(f.font.height)
    return heights


_SYNTHETIC_TIE_HEIGHTS = {7, 21, 35, 49, 63, 77, 91}
_EDGE_HEIGHTS = {0, -40}  # zero, and a negative height: sign handling, not just the common case


def _cases(font_dir):
    heights = sorted(_real_heights(font_dir) | _SYNTHETIC_TIE_HEIGHTS | _EDGE_HEIGHTS)
    return [
        (h, baseline, ly, underline)
        for h in heights
        for baseline in (2, h // 2, h - 2)
        for ly in (0, 37, -940)
        for underline in (True, False)
    ]


@pytest.fixture(scope="module")
def deco_geometry_harness(tmp_path_factory):
    """Compile `deco_rule_geometry()` -- extracted verbatim, never retyped
    -- behind a stdin/stdout loop of its own (not `_OpHarness`'s op-JSON
    protocol: this function takes four plain numbers, not an op)."""
    if shutil.which("c++") is None:
        pytest.skip("no host C++ compiler")
    parts = "#include <cmath>\n" + _extract_block(
        r"^inline void deco_rule_geometry\(", "deco_rule_geometry()"
    )
    main_src = r"""
#include <cstdio>
int main() {
  int h, baseline, ly, underline;
  while (scanf("%d %d %d %d", &h, &baseline, &ly, &underline) == 4) {
    int top = 0, t = 0;
    deco_rule_geometry(h, baseline, ly, underline != 0, &top, &t);
    std::printf("%d %d\n", top, t);
  }
  return 0;
}
"""
    return _compile(
        tmp_path_factory.mktemp("deco_geometry_parity"), "deco_geometry_harness", parts, main_src
    )


def _run(deco_geometry_harness, cases):
    stdin = "".join(
        f"{h} {baseline} {ly} {1 if underline else 0}\n" for h, baseline, ly, underline in cases
    )
    out = subprocess.run(
        [str(deco_geometry_harness)], input=stdin.encode(), capture_output=True, check=True
    ).stdout.decode()
    return [tuple(int(v) for v in line.split()) for line in out.splitlines()]


def test_deco_rule_geometry_matches_the_firmware(deco_geometry_harness, font_dir):
    cases = _cases(font_dir)
    cpp_results = _run(deco_geometry_harness, cases)
    assert len(cpp_results) == len(cases)
    diffs = []
    for (h, baseline, ly, underline), (cpp_top, cpp_t) in zip(cases, cpp_results, strict=True):
        py_top, py_t = _deco_rule_geometry(h, baseline, ly, underline)
        if (cpp_top, cpp_t) != (py_top, py_t):
            diffs.append((h, baseline, ly, underline, (cpp_top, cpp_t), (py_top, py_t)))
    assert diffs == []


def test_deco_rule_geometry_thickness_floor_is_never_1px(deco_geometry_harness, font_dir):
    """`t`'s `max(2, ...)` floor (the write-up's own reason for it: a 1px
    rule can't hold a mixed ink) holds at every case this file sweeps,
    firmware side -- the Python equivalent is
    `test_text_deco.py::test_rule_thickness_is_at_least_2px_at_every_compiled_size`."""
    cases = _cases(font_dir)
    for _top, t in _run(deco_geometry_harness, cases):
        assert t >= 2
