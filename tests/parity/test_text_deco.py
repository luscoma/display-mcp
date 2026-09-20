"""`deco`'s geometry (docs/plans/fonts-and-icons.md Decision 5, landed as
B5), differentially against the shipped header's `deco_rule_geometry()`,
plus (final review, B7/F) `draw_text_deco()` itself, through conftest.py's
stub `Display`/`BaseFont` (`get_text_bounds()`, `clipped_filled_rectangle()`
and a fixed-advance font).

Text *position* parity with the firmware stays eyeball, not differential,
everywhere else in this file (Decision 5 says so explicitly -- "eyeball
parity like rect, not a differential test") -- the stub's `BaseFont` has
no relationship to any real face's metrics, so this is a bounds/coverage
test (does `draw_text_deco()` ever emit a rectangle outside the canvas, or
mis-handle a zero-width line or any of the three alignments), not a pixel
comparison. `deco_rule_geometry()` is the one part of the feature that is
pure arithmetic with no Display/BaseFont/JSON dependency, kept
free-standing in the header for exactly this reason, so it's what gets a
real differential diff for its own three numbers (`t`, and the two
vertical offsets), which round half away from zero on both sides -- this
is the test that would catch the two sides disagreeing at an exact `.5`
the way a plain Python `round()` would (see `_round_half_away_from_zero()`'s
docstring in `display_mcp.render`).

Needs a host C++ compiler; skips cleanly without one (see conftest.py).
`font_dir` (tests/conftest.py) is also needed, to measure the real
per-face heights below -- skips cleanly without the fonts fetched either.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from display_mcp.render import FONTS, _clip_span, _deco_rule_geometry, load_font

from .conftest import _compile, _extract, _extract_block


# The real height every compiled face measures at -- `f.font.height`
# (Pillow's own FreeType line height), NOT `Face.cell_height`
# (B5 review fix): the firmware's font_height() returns ESPHome's compiled
# `height_`, which is FreeType's line-height metric and disagrees with
# `cell_height` (ascent + descent) by 0-2 px depending on the face (final
# review, B7/D: measured across all 110, no pattern by slot or family) --
# see display_mcp.render's own comment where `deco_h` is computed. Using
# `cell_height` here would silently test a number the firmware never
# produces.
#
# Plus: synthetic heights that reach ties the real ladder doesn't -- `h =
# 14k + 7` puts `h/14` exactly on `k + 0.5` for `k = 0..6` (7, 21, 35, 49,
# 63, 77, 91). One of these, 63, *is* a real compiled height too
# (`karla/54`, `karla-bold/54`, `karla-italic/54`, `mono/lg` -- final
# review, B7/F, correcting an earlier version of this comment that claimed
# none of the seven coincided with a real face) -- the other six don't, so
# this sweep is what proves the two roundings agree at ties this ladder
# hasn't reached, not just the one it has (which
# `tests/renderer/test_text_deco.py::test_the_seven_ties_where_round_would_disagree`
# pins directly against the rendered rule). And `0`/a negative height,
# since `_round_half_away_from_zero()`'s docstring claims sign handling is
# mirrored on both sides but nothing here previously exercised it.
def _real_heights(font_dir) -> set[int]:
    return {load_font(font_dir, face).font.height for face in FONTS.values()}


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


# `t`'s `max(2, ...)` floor (the write-up's own reason for it: a 1px rule
# can't hold a mixed ink) has no test of its own on this side any more: the
# diff above already proves the firmware's `t` equals the Python's for every
# case in `_cases()`, and
# `tests/renderer/test_text_deco.py::test_rule_thickness_is_at_least_2px_at_every_compiled_size`
# pins the floor itself.


# --------------------------------------------------------------------------
# draw_text_deco() itself (final review, B7/F): the accepted item the first
# pass of this batch skipped as needing "ESPHome types beyond a stub" --
# it doesn't. Reading what it actually calls (Display::get_text_bounds(),
# clip_span()/clipped_filled_rectangle(), and BaseFont::measure() through
# get_text_bounds()) shows every one of them is either pure arithmetic
# already extracted above or a Display/BaseFont method conftest.py's stub
# can implement faithfully -- neither needs PollingComponent or any other
# ESPHome machinery. Driven across 64 lines (the wrap bound), a zero-width
# line (an empty string measures 0 and draw_text_deco() returns before
# drawing anything), and all three alignments.
# --------------------------------------------------------------------------

# The stub BaseFont's fixed metrics (conftest.py): a real face's numbers
# don't matter here (Decision 5's own eyeball-parity carve-out) -- only
# that get_text_bounds()'s arithmetic runs for real, with values the
# Python mirror below can reproduce exactly.
_STUB_ADVANCE = 10
_STUB_H = 40
_STUB_BASELINE = 30
_STUB_CANVAS = 200  # both width and height


def _trunc_div(a: int, b: int) -> int:
    """C++'s `/` on ints truncates toward zero; Python's `//` floors --
    they disagree for a negative dividend, which `get_text_bounds()`'s
    `(*width + x_offset) / 2` can be here (a right/center-aligned line at
    a negative `x`)."""
    q = a // b
    return q + 1 if q < 0 and q * b != a else q


def _predicted_box(
    x: int, y: int, lh: int, align: int, underline: bool, text_len: int, n: int
) -> tuple[int, int, int, int] | None:
    """The Python mirror of one `draw_text_deco()` call against the stub's
    fixed metrics -- `_deco_rect()`'s own logic (deco_rule_geometry() +
    clip_span() twice), but against `_STUB_CANVAS` instead of the real
    WIDTH/HEIGHT, and with `get_text_bounds()`'s alignment arithmetic
    (`_deco_rect()` is only ever called with `lx1`/`lw` already resolved
    for `align`, by `render()`'s own textbbox() call -- this reproduces
    that resolution too, for the stub's fixed-advance font)."""
    ly = y + n * lh
    lw = _STUB_ADVANCE * text_len
    if lw <= 0:
        return None
    if align == 0:  # left
        lx1 = x
    elif align == 1:  # center
        lx1 = x - _trunc_div(lw, 2)
    else:  # right
        lx1 = x - lw
    top, t = _deco_rule_geometry(_STUB_H, _STUB_BASELINE, ly, underline)
    x0, w = _clip_span(lx1, lw, _STUB_CANVAS)
    y0, hh = _clip_span(top, t, _STUB_CANVAS)
    if w <= 0 or hh <= 0:
        return None
    return (x0, y0, x0 + w, y0 + hh)


@pytest.fixture(scope="module")
def draw_text_deco_harness(tmp_path_factory):
    """Compile `draw_text_deco()` -- extracted verbatim, along with its own
    dependencies (`Deco`, `deco_rule_geometry()`, `clip_span()`,
    `clipped_filled_rectangle()`) -- against conftest.py's stub
    `Display`/`BaseFont` (`get_text_bounds()`, a fixed-advance font).
    Its own stdin/stdout protocol, not `_OpHarness`'s op-JSON one: each
    line is `x y lh align deco text_len`, and the harness itself runs the
    64-line loop `render()`'s own wrap path runs, printing one result line
    (`NONE`, or the painted box `x0 y0 x1 y1`) per line."""
    if shutil.which("c++") is None:
        pytest.skip("no host C++ compiler")
    parts = "\n".join([
        _extract(r"^enum class Deco \{.*\};$", "the Deco enum"),
        _extract_block(r"^inline void deco_rule_geometry\(", "deco_rule_geometry()"),
        _extract_block(r"^inline void clip_span\(", "clip_span()"),
        _extract_block(r"^inline void clipped_filled_rectangle\(", "clipped_filled_rectangle()"),
        _extract_block(r"^inline void draw_text_deco\(", "draw_text_deco()"),
    ])
    main_src = f"""
#include <cstdio>
#include <string>

int main() {{
  int x, y, lh, align_i, deco_i, text_len;
  const int cw = {_STUB_CANVAS}, ch = {_STUB_CANVAS};
  while (scanf("%d %d %d %d %d %d", &x, &y, &lh, &align_i, &deco_i, &text_len) == 6) {{
    esphome::display::BaseFont font;
    font.advance = {_STUB_ADVANCE};
    esphome::display::TextAlign align =
        align_i == 0 ? esphome::display::TextAlign::TOP_LEFT
        : align_i == 1 ? esphome::display::TextAlign::TOP_CENTER
                        : esphome::display::TextAlign::TOP_RIGHT;
    Deco deco = deco_i == 0 ? Deco::kUnderline : Deco::kStrike;
    std::string text(text_len, 'A');
    for (int n = 0; n < 64; n++) {{
      Canvas canvas(cw, ch);
      const int ly = y + n * lh;
      draw_text_deco(canvas, x, ly, text.c_str(), &font, align, deco, {_STUB_H}, {_STUB_BASELINE},
                      esphome::Color(0, 0, 0));
      int x0 = -1, y0 = -1, x1 = -1, y1 = -1;
      for (int py = 0; py < ch; py++) {{
        for (int px = 0; px < cw; px++) {{
          const auto &c = canvas.px[py * cw + px];
          if (c.r != 222 || c.g != 222 || c.b != 216) {{
            if (x0 == -1 || px < x0) x0 = px;
            if (y0 == -1 || py < y0) y0 = py;
            if (px > x1) x1 = px;
            if (py > y1) y1 = py;
          }}
        }}
      }}
      if (x0 == -1) {{
        std::printf("NONE\\n");
      }} else {{
        std::printf("%d %d %d %d\\n", x0, y0, x1 + 1, y1 + 1);
      }}
    }}
  }}
  return 0;
}}
"""
    return _compile(
        tmp_path_factory.mktemp("draw_text_deco_parity"), "draw_text_deco_harness", parts, main_src
    )


def _run_draw_text_deco(harness, cases):
    stdin = "".join(
        f"{x} {y} {lh} {align} {deco} {text_len}\n"
        for x, y, lh, align, deco, text_len in cases
    )
    out = subprocess.run(
        [str(harness)], input=stdin.encode(), capture_output=True, check=True
    ).stdout.decode()
    lines = out.splitlines()
    assert len(lines) == len(cases) * 64
    results = []
    i = 0
    for _case in cases:
        batch = []
        for _n in range(64):
            line = lines[i]
            i += 1
            batch.append(None if line == "NONE" else tuple(int(v) for v in line.split()))
        results.append(batch)
    return results


# There is no `+-kMaxCoord` extremes sweep here any more. With `x` itself at
# `+-kMaxCoord` (`4096`, against a 200px stub canvas) the horizontal clip
# never has anything to keep, so every one of its 96 cases predicted -- and
# got -- `None` at every one of the 64 lines, `lh` included: `assert cpp_box
# == py_box` was `None == None` by construction, proving nothing a clipping
# bug could have broken. The two tests below are the real coverage: boxes
# that land and match the mirror, and the zero-width early return.


def test_draw_text_deco_matches_the_python_mirror_at_ordinary_coordinates(draw_text_deco_harness):
    """Ordinary `x`/`y`/`lh` values, 64 lines, all three alignments, both
    `deco` values, and a real (non-zero-width) line -- every box lands, is
    contained in the stub canvas, and matches the Python mirror exactly.

    This is now the sole guard of `draw_text_deco()`'s geometry: it skips
    without a host C++ compiler, and nothing else in the suite drives the
    function."""
    cases = [
        (x, y, lh, align, deco, 2)
        for x in (10, 80, 150)
        for y in (10, 50)
        for lh in (20, -20)
        for align in (0, 1, 2)
        for deco in (0, 1)
    ]
    all_results = _run_draw_text_deco(draw_text_deco_harness, cases)
    checked_a_box = False
    for (x, y, lh, align, deco, text_len), batch in zip(cases, all_results, strict=True):
        for n, cpp_box in enumerate(batch):
            py_box = _predicted_box(x, y, lh, align, deco == 0, text_len, n)
            assert cpp_box == py_box, (x, y, lh, align, deco, text_len, n, cpp_box, py_box)
            if cpp_box is not None:
                checked_a_box = True
                x0, y0, x1, y1 = cpp_box
                assert 0 <= x0 < x1 <= _STUB_CANVAS
                assert 0 <= y0 < y1 <= _STUB_CANVAS
    # Sanity: this sweep must not be vacuously all-NONE, or it would prove
    # nothing beyond the extremes test above.
    assert checked_a_box


def test_draw_text_deco_zero_width_line_draws_nothing(draw_text_deco_harness):
    """`text_len=0` (an empty printed line) must never emit a rectangle,
    regardless of x/y/align/deco -- `get_text_bounds()` measures a 0px
    line and `draw_text_deco()` returns before `deco_rule_geometry()` is
    even called."""
    cases = [
        (0, 0, 40, align, deco, 0)
        for align in (0, 1, 2)
        for deco in (0, 1)
    ]
    for batch in _run_draw_text_deco(draw_text_deco_harness, cases):
        assert all(box is None for box in batch)
