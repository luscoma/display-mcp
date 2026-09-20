"""Text: fit/wrap, the `text`/`fmt` ops, the compiled font table, the
JetBrains Mono face (docs/plans/dragon-feedback.md D11/B3), and the
uncompiled-glyph warning.

Fixture note: `font_dir` and `sample_doc` come from tests/conftest.py. Any
test that renders real text needs `font_dir` and will skip cleanly (via
that fixture) if fonts/ hasn't been populated with the seven compiled
font files.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest
from PIL import ImageFont

from display_mcp.render import (
    FONT_ALIASES,
    FONTS,
    INK,
    MAX_COORD,
    NAME_MAX_LEN,
    SIZES,
    SLOTS,
    TEXT_MAX_LEN,
    TEXT_MAX_LINES,
    check,
    fit_line,
    fonts_available,
    load_font,
    render,
    render_hash,
    resolve_font,
    unknown_font_message,
    wrap_lines,
)
from display_mcp.render.fonts import _METRICS, _measure_ink_height

from .conftest import _glyph_msgs

FIT_CASES = [
    # (id, text, max_w, expected) -- max_w "exact"/"third" is computed per
    # case from the text's own measured width, once the font is loaded.
    ("plain_fits", "Team standup", 800, "Team standup"),
    ("empty_string", "", 100, ""),
    ("multibyte_near_cut", "Design review — display list — 12° today", 40, None),
    ("single_word_longer_than_box", "Supercalifragilisticexpialidocious", 60, None),
    ("exact_fit_is_unchanged", "Team standup", "exact", "Team standup"),
    (
        "multibyte_truncation_keeps_valid_utf8",
        "Design review — the 72° display list for today's schedule",
        "third",
        None,
    ),
    (
        "none_max_w_is_unchanged",
        "Supercalifragilisticexpialidocious, quite unchanged",
        None,
        "Supercalifragilisticexpialidocious, quite unchanged",
    ),
]


@pytest.mark.parametrize("case_id,text,max_w,expected", FIT_CASES)
def test_fit_line_cases(font_dir, case_id, text, max_w, expected):
    """Every case pins the same invariants: valid UTF-8, text_width(result)
    <= max_w, a result shorter than the input ends with an ellipsis, and
    max_w=None never truncates."""
    from display_mcp.render import load_font, text_width

    font = load_font(font_dir, FONTS["instrument/sm"])
    if max_w == "exact":
        resolved_max_w = text_width(font, text)
    elif max_w == "third":
        resolved_max_w = text_width(font, text) // 3
    else:
        resolved_max_w = max_w
    result = fit_line(font, text, resolved_max_w)
    if expected is not None:
        assert result == expected
    result.encode("utf-8")  # would raise on a bad surrogate half
    if resolved_max_w is None:
        assert result == text
    else:
        assert text_width(font, result) <= resolved_max_w or result == "…"
    if len(result) < len(text):
        assert result.endswith("…")


def test_wrap_two_lines_with_overflow_ellipsis(font_dir):
    from display_mcp.render import load_font, text_width

    font = load_font(font_dir, FONTS["instrument/md"])
    s = "Order printer filament and a spare 0.4 nozzle for the workshop bench today"
    max_w = 300
    lines = wrap_lines(font, s, max_w, 2)
    assert len(lines) == 2
    for line in lines:
        assert text_width(font, line) <= max_w
    assert lines[-1].endswith("…")


def test_wrap_last_word_just_fits(font_dir):
    from display_mcp.render import load_font, text_width

    font = load_font(font_dir, FONTS["instrument/md"])
    words = ["Book", "the", "dentist"]
    s = " ".join(words)
    max_w = text_width(font, s)  # exactly enough for every word on one line
    lines = wrap_lines(font, s, max_w, 2)
    assert lines == [s]


def test_wrap_lines_equals_one(font_dir):
    from display_mcp.render import load_font, text_width

    font = load_font(font_dir, FONTS["instrument/md"])
    s = "Measure the driver board for the frame and order new screws"
    max_w = 250
    lines = wrap_lines(font, s, max_w, 1)
    assert len(lines) == 1
    assert text_width(font, lines[0]) <= max_w


def _text_op(**overrides):
    op = {"op": "text", "x": 10, "y": 10, "s": "hello there wide world of text",
          "f": "sm", "wrap": True, "w": 140, "lines": 3}
    op.update(overrides)
    return op


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("lh", None, id="lh_null"),
        pytest.param("w", None, id="w_null_with_wrap"),
        # `wrap: true` stays set, but a `w` that isn't a number can't
        # satisfy the firmware's `wrap && max_w > 0`, so this draws a
        # single unwrapped line -- same as the op with `w` left out
        # entirely.
        pytest.param("w", "wide", id="w_non_numeric"),
        pytest.param("lines", None, id="lines_null"),
    ],
)
def test_text_optional_field_null_or_unusable_matches_it_omitted(font_dir, field, value):
    """docs/plans/fonts-and-icons.md B4b follow-up: an explicit `null` is
    absent on both sides. Each of `text`'s optional layout fields, set to
    `null` (or to a value the firmware can't use), must render
    byte-for-byte identically to the same op with the field left out
    entirely -- and must not raise."""
    doc_set = {"bg": "white", "ops": [_text_op(**{field: value})]}
    doc_omitted = {
        "bg": "white",
        "ops": [{k: v for k, v in _text_op().items() if k != field}],
    }
    img_set, problems = render(doc_set, font_dir)  # must not raise
    img_omitted, _ = render(doc_omitted, font_dir)
    assert problems == []
    assert img_set.tobytes() == img_omitted.tobytes()


def test_unknown_alignment_on_text_warns_and_falls_back_to_left(font_dir):
    doc_bad = {"bg": "white", "ops": [
        {"op": "text", "x": 10, "y": 10, "s": "hi", "f": "sm", "a": "top"}]}
    doc_left = {"bg": "white", "ops": [
        {"op": "text", "x": 10, "y": 10, "s": "hi", "f": "sm", "a": "left"}]}
    img_bad, problems = render(doc_bad, font_dir)
    img_left, _ = render(doc_left, font_dir)
    assert problems == ["ops[0] text: unknown alignment 'top', using left"]
    assert img_bad.tobytes() == img_left.tobytes()


def test_unknown_alignment_on_fmt_warns_too(font_dir):
    doc = {"bg": "white", "ops": [
        {"op": "fmt", "x": 10, "y": 10, "s": "{time}", "f": "xs", "a": "middle"}]}
    _, problems = render(doc, font_dir)
    assert problems == ["ops[0] fmt: unknown alignment 'middle', using left"]


def test_known_alignment_never_warns(font_dir):
    for a in ("left", "center", "right"):
        doc = {"bg": "white", "ops": [
            {"op": "text", "x": 10, "y": 10, "s": "hi", "f": "sm", "a": a}]}
        _, problems = render(doc, font_dir)
        assert problems == []


def test_unknown_font_skips_the_op_nothing_drawn(font_dir):
    """The firmware's `text`/`fmt` branches `skipped++; continue` on an
    unknown font — nothing is drawn on the panel. The renderer must abandon
    the op the same way, not warn and still draw with the `md` fallback,
    which would show text on the preview the wall never draws: the warning
    stays, but the canvas is untouched."""
    doc = {
        "bg": "white",
        "ops": [{"op": "text", "x": 100, "y": 100, "s": "hi", "f": "huge"}],
    }
    img, problems = render(doc, font_dir)
    assert len(problems) == 1
    assert "unknown font" in problems[0]
    # Nothing drawn: pixel-identical to the same doc with no ops at all.
    blank_img, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank_img.tobytes()

    fmt_doc = {
        "bg": "white",
        "ops": [{"op": "fmt", "x": 100, "y": 100, "s": "{time}", "f": "huge"}],
    }
    fmt_img, fmt_problems = render(fmt_doc, font_dir)
    assert len(fmt_problems) == 1
    assert "unknown font" in fmt_problems[0]
    assert fmt_img.tobytes() == blank_img.tobytes()


def test_fonts_keys():
    """B3b (docs/plans/fonts-and-icons.md Decision 2): 110 faces, ten
    family-styles (petrona, petrona-bold, petrona-italic, instrument,
    instrument-bold, instrument-italic, karla, karla-bold, karla-italic,
    mono) x `SIZES` (11) -- generated, not a fixed literal set of names the
    way the six legacy slots were."""
    assert len(FONTS) == 110
    family_styles = {(face.family, face.style) for face in FONTS.values()}
    assert family_styles == {
        ("petrona", ""), ("petrona", "bold"), ("petrona", "italic"),
        ("instrument", ""), ("instrument", "bold"), ("instrument", "italic"),
        ("karla", ""), ("karla", "bold"), ("karla", "italic"),
        ("mono", ""),
    }
    assert {face.size for face in FONTS.values()} == set(SIZES)
    # Every (family-style, size) combination compiled exactly once.
    assert len(FONTS) == len(family_styles) * len(SIZES)


def test_canonical_name_is_the_slot_spelling_when_the_size_is_a_slot():
    """Decision 1's canonical-name rule: the slot spelling when `size` is
    one of the five slots, the pixel spelling otherwise -- never both."""
    for name, face in FONTS.items():
        key, _, size_part = name.rpartition("/")
        if face.size in SLOTS.values():
            assert size_part in SLOTS and SLOTS[size_part] == face.size, name
        else:
            assert size_part == str(face.size), name
        assert key == (face.family if not face.style else f"{face.family}-{face.style}")


def test_resolve_font_slot_px_and_bare_aliases_agree():
    """Every accepted spelling of the same face resolves to one canonical
    name: a face's own slot and px spellings, and (for the five legacy
    names) the bare spelling too."""
    assert resolve_font("instrument/lg") == "instrument/lg"
    assert resolve_font("instrument/48") == "instrument/lg"
    assert resolve_font("instrument-bold/xl") == "instrument-bold/xl"
    assert resolve_font("instrument-bold/84") == "instrument-bold/xl"
    assert resolve_font("mono/24") == "mono/24"
    assert resolve_font("mono/sm") == "mono/sm"
    assert resolve_font("xl") == "instrument-bold/xl"
    assert resolve_font("lg") == "instrument-bold/lg"
    assert resolve_font("md") == "instrument/md"
    assert resolve_font("sm") == "instrument/sm"
    assert resolve_font("xs") == "instrument-bold/xs"
    # A ladder size that isn't a slot has only its one, px, spelling --
    # there's no separate slot name for 40 to alias.
    assert resolve_font("instrument/40") == "instrument/40"
    assert "instrument/40" not in FONT_ALIASES.values()


def test_bare_mono_has_no_alias():
    """Decision 1: bare `mono` is dropped -- nothing published uses it, and
    it's the only bare name that wouldn't be a size."""
    assert "mono" not in FONTS
    assert "mono" not in FONT_ALIASES
    assert resolve_font("mono") is None


def test_resolve_font_rejects_an_off_ladder_size():
    """A pixel count that isn't one of `SIZES` is not compiled for any
    family, slot or bare alias alike."""
    assert resolve_font("instrument/41") is None
    assert resolve_font("karla/41") is None
    assert resolve_font("petrona/41") is None


def test_unknown_font_message_names_the_wrong_half():
    """Decision 1 (B1 review, item 7): a bad *size* on a real family-style
    names that family-style's own compiled sizes, plus the slot table
    (a mistyped slot is as likely a mistake as a mistyped pixel count); a
    bad *family* (or a name with no size at all) lists every compiled
    family and its styles, plus the five bare legacy names. B3b (Decision
    2) grows the family list to petrona, instrument and karla (each also
    -bold and -italic) and mono."""
    msg = unknown_font_message("instrument/99")
    assert msg == (
        "unknown font 'instrument/99': instrument is compiled at "
        "22 24 26 28 32 36 40 44 48 54 84 (slots xs=22 sm=28 md=36 lg=48 xl=84)"
    )
    msg = unknown_font_message("mono/99")
    assert msg == (
        "unknown font 'mono/99': mono is compiled at 22 24 26 28 32 36 40 44 48 54 84 "
        "(slots xs=22 sm=28 md=36 lg=48 xl=84)"
    )
    msg = unknown_font_message("petrona/99")
    assert msg == (
        "unknown font 'petrona/99': petrona is compiled at "
        "22 24 26 28 32 36 40 44 48 54 84 (slots xs=22 sm=28 md=36 lg=48 xl=84)"
    )
    msg = unknown_font_message("karla/99")
    assert msg == (
        "unknown font 'karla/99': karla is compiled at "
        "22 24 26 28 32 36 40 44 48 54 84 (slots xs=22 sm=28 md=36 lg=48 xl=84)"
    )
    families = (
        "petrona (also -bold, -italic), instrument (also -bold, -italic), "
        "karla (also -bold, -italic) and mono"
    )
    msg = unknown_font_message("dragon/40")
    assert msg == (
        f"unknown font 'dragon/40': families are {families}; "
        "the bare names xs sm md lg xl also work (Instrument Sans)"
    )
    msg = unknown_font_message("huge")
    assert msg == (
        f"unknown font 'huge': families are {families}; "
        "the bare names xs sm md lg xl also work (Instrument Sans)"
    )


def test_unknown_font_message_bare_mono_says_there_is_no_bare_mono():
    """Final review, "Composer over MCP": a bare `mono` used to fall into
    the generic bad-family message, which never says outright that `mono`
    on its own was never a size (Decision 1) -- unlike the five legacy bare
    names it aliases nothing."""
    assert unknown_font_message("mono") == (
        "unknown font 'mono': there is no bare mono -- write mono/24 "
        "(or another compiled size)"
    )


def test_unknown_font_message_italic_bold_serif_as_family_gets_a_hint():
    """A composer who has seen `-italic`/`-bold` suffixes but not yet read
    Decision 1 might guess `italic`/`bold` (or the write-up's earlier
    `serif` role name) is itself a family -- the bad-family message now
    says plainly that an italic or bold always names its own family."""
    for guess in ("italic/40", "bold/40", "serif/40"):
        msg = unknown_font_message(guess)
        assert msg.endswith(
            "an italic or bold always names its family, e.g. petrona-italic/40"
        )
    # An ordinary bad family (no such reserved-word confusion) does not.
    assert not unknown_font_message("dragon/40").endswith("petrona-italic/40")


def test_font_metrics_file_matches_a_fresh_measurement(font_dir):
    """`font_metrics.json` is committed data, generated by
    `display-mcp-cli font-metrics <font_dir>`, not hand-typed
    (Decision 3, docs/plans/fonts-and-icons.md) -- re-measure every face
    from the real font files and diff against what `FONTS` actually loaded
    from the committed file, so a stale commit (a font swap, or a
    `SIZES`/`FAMILIES` edit not followed by a re-run of the script) fails
    here instead of silently reflowing a document. The key sets must match
    exactly, too: a row for a face that no longer exists (a size dropped
    from `SIZES`, a family-style renamed) is a hand-edit the file's whole
    reason for being generated is to make unnecessary (B1 re-review,
    finding B)."""
    assert set(_METRICS) == set(FONTS), sorted(set(_METRICS) ^ set(FONTS))
    for name, face in FONTS.items():
        f = load_font(font_dir, face)
        ascent, descent = f.getmetrics()
        assert face.cell_height == ascent + descent, name
        if face.family == "mono":
            assert face.ink_height == _measure_ink_height(f), name
        else:
            assert face.ink_height is None, name


def test_face_variation_exists_in_its_own_file(font_dir):
    """A wrong `variation` is otherwise undetectable (docs/plans/
    fonts-and-icons.md B1 review, item 4): `load_font()`'s
    `set_variation_by_name` swallows any exception -- including "no such
    named instance" -- and silently falls back to the file's own default
    instance, and `cell_height`/`ink_height` don't depend on which
    instance actually got selected, so a stale `font_metrics.json` can't
    catch a typo'd `variation` either. Assert every distinct (file,
    variation) pair this table asks for is really in that file's own
    variation list -- deduped, since every size of a family-style shares
    one file's variations. `get_variation_names()` returns `bytes`;
    compared as `str` on both sides so a mismatch reads plainly."""
    checked: set[tuple[str, str]] = set()
    for face in FONTS.values():
        key = (face.file, face.variation)
        if key in checked:
            continue
        checked.add(key)
        f = ImageFont.truetype(str(font_dir / face.file), face.size)
        names = {n.decode() if isinstance(n, bytes) else n for n in f.get_variation_names()}
        assert face.variation in names, (face.file, face.variation, sorted(names))


def _variation_axis_values(f: ImageFont.FreeTypeFont, weight: int) -> list[int]:
    """The axis-value list `set_variation_by_axes()` wants: `weight` on
    the font's own `Weight` axis, every other axis (Instrument Sans's
    `wdth`) left at its own default -- never a hardcoded `[weight]`, which
    would silently mis-set a multi-axis font's other axes to 0."""
    values = []
    for axis in f.get_variation_axes():
        name = axis["name"]
        name = name.decode() if isinstance(name, bytes) else name
        values.append(weight if name == "Weight" else axis["default"])
    return values


def test_load_font_selects_the_intended_weight_for_every_face_at_lg(font_dir):
    """B1 re-review, item deferred to B3b, redone per the B3b re-review
    (item 1): the previous version of this test only checked that a
    family's styles measured *distinct* advances from each other, so
    mutating Petrona's `SemiBold`/`ExtraBold`/`Medium Italic` instances to
    `"Regular"` (load_font() then silently draws weight 400 for all three)
    still passed -- Petrona's three styles are still distinct from each
    other at 400. This is the direct check instead: for every family-style
    at `lg` (48px, skipping mono's file if it's absent -- the one
    `optional` face), `load_font()`'s `getlength("Handgloves")` must equal,
    within 0.05px, the same file loaded fresh and moved to `face.weight`
    on its own weight axis directly (`set_variation_by_axes()`, never by
    name) -- proof `load_font()` actually landed on the intended weight,
    not merely on *a* weight distinct from its siblings. The reviewer
    measured the correct code within 0.03px of this and every
    wrong-instance mutation 3.7-20.8px off."""
    checked = []
    for name, face in FONTS.items():
        if face.size != 48:
            continue
        path = font_dir / face.file
        got = load_font(font_dir, face).getlength("Handgloves")
        if face.layout == "basic":
            want_font = ImageFont.truetype(str(path), 48, layout_engine=ImageFont.Layout.BASIC)
        else:
            want_font = ImageFont.truetype(str(path), 48)
        want_font.set_variation_by_axes(_variation_axis_values(want_font, face.weight))
        want = want_font.getlength("Handgloves")
        assert abs(got - want) < 0.05, (name, got, want)
        checked.append(name)
    # Every family-style's `lg` face -- ten, one per family-style -- proof
    # the loop above didn't silently skip anything. `font_dir` always has
    # all seven files fetched (deploy/fetch-fonts.sh), mono included, so
    # there is no "mono's file might be missing" case to skip here (C8,
    # final review).
    assert len(checked) == 10, checked


def test_stale_metrics_entry_raises_clearly(monkeypatch):
    """A `SIZES`/`FAMILIES` edit not followed by a re-run of
    `display-mcp-cli font-metrics` must fail loudly at build time, not
    hand out `cell_height=0`/`ink_height=None` for the face it dropped
    (docs/plans/fonts-and-icons.md B1 review, item 5). A temporary,
    monkeypatched copy of `_METRICS` stands in for a stale
    `font_metrics.json` so this doesn't touch the committed file."""
    from display_mcp.render import fonts as fonts_module

    stale = {name: dict(entry) for name, entry in fonts_module._METRICS.items()}
    del stale["instrument/md"]
    monkeypatch.setattr(fonts_module, "_METRICS", stale)
    with pytest.raises(RuntimeError, match="instrument/md"):
        fonts_module._build_fonts()


def test_bootstrap_env_var_lets_the_same_stale_table_build_a_placeholder(monkeypatch):
    """`DISPLAY_MCP_FONT_METRICS_BOOTSTRAP` (B3b re-review, item 3) is the
    escape hatch `display-mcp-cli font-metrics` sets before its own first
    import of this module: the exact stale table
    `test_stale_metrics_entry_raises_clearly` pins as a hard failure above
    must instead build, with a placeholder (`cell_height=0`,
    `ink_height=None`) for the row that's missing -- that placeholder is
    what lets `FONTS` exist at all so the command that's supposed to fix
    the stale file can run in the first place. Nothing here writes
    anything; `_write_metrics()` re-measuring the placeholder away for
    real is test_font_metrics_cli_repairs_a_missing_row_in_a_fresh_process
    below."""
    from display_mcp.render import fonts as fonts_module

    stale = {name: dict(entry) for name, entry in fonts_module._METRICS.items()}
    del stale["instrument/md"]
    monkeypatch.setattr(fonts_module, "_METRICS", stale)
    monkeypatch.setenv(fonts_module._BOOTSTRAP_ENV_VAR, "1")

    built = fonts_module._build_fonts()  # must not raise now
    assert built["instrument/md"].cell_height == 0
    assert built["instrument/md"].ink_height is None
    # Every other face is untouched -- only the one dropped from `stale`
    # got the placeholder.
    assert built["instrument/lg"].cell_height == fonts_module.FONTS["instrument/lg"].cell_height


def test_font_metrics_cli_repairs_a_missing_row_in_a_fresh_process(font_dir, tmp_path):
    """The actual deadlock this closes (B3b re-review, item 3): adding a
    size or a family leaves `font_metrics.json` missing a row for it, and
    `display-mcp-cli font-metrics` -- the command that's supposed to add
    that row -- can't import `display_mcp.render` at all to do so, since
    building `FONTS` is exactly what raises on the missing row. Reproduced
    with a fresh subprocess against a *copy* of the package (this test's
    own process has already built `FONTS` successfully by the time it
    runs, so monkeypatching `_METRICS` in-process, as the two tests above
    do, can't reproduce a failure that only happens on a from-scratch
    import) -- the real `src/display_mcp/render/font_metrics.json` is
    never touched.

    Without the flag, a plain import of the mutated copy fails loudly,
    naming the missing face; `display-mcp-cli font-metrics` run against
    that same copy repairs it, and the repaired row is a real measurement
    (not the placeholder) equal to what the committed file already has
    for that face -- Petrona and Karla didn't change, so re-measuring one
    row from the real font files must land back on the same numbers this
    batch already committed."""
    from display_mcp.render.fonts import _METRICS_PATH

    before = _METRICS_PATH.read_bytes()
    import shutil
    import subprocess
    import sys

    from display_mcp.render.fonts import _METRICS_PATH

    real_value = json.loads(_METRICS_PATH.read_text())["petrona/xs"]

    tmp_src = tmp_path / "src"
    shutil.copytree(Path(__file__).resolve().parents[2] / "src", tmp_src)
    copied_metrics = tmp_src / "display_mcp" / "render" / "font_metrics.json"
    data = json.loads(copied_metrics.read_text())
    del data["petrona/xs"]
    copied_metrics.write_text(json.dumps(data))

    env = {**os.environ, "PYTHONPATH": str(tmp_src) + os.pathsep + os.environ.get("PYTHONPATH", "")}

    without_flag = subprocess.run(
        [sys.executable, "-c", "import display_mcp.render"],
        capture_output=True, text=True, timeout=30, env=env,
    )
    assert without_flag.returncode != 0
    assert "petrona/xs" in without_flag.stderr

    repaired = subprocess.run(
        [sys.executable, "-m", "display_mcp.cli", "font-metrics", str(font_dir)],
        capture_output=True, text=True, timeout=60, env=env,
    )
    assert repaired.returncode == 0, repaired.stdout + repaired.stderr
    assert json.loads(copied_metrics.read_text())["petrona/xs"] == real_value
    # The subprocess must have written its *copy*, never the committed file
    # (a PYTHONPATH-precedence change would otherwise rewrite committed data
    # silently -- B3b re-review nit).
    assert _METRICS_PATH.read_bytes() == before



def test_fonts_available_requires_mono_too(tmp_path):
    for name in (
        "Petrona.ttf", "Petrona-Italic.ttf",
        "InstrumentSans.ttf", "InstrumentSans-Italic.ttf",
        "Karla.ttf", "Karla-Italic.ttf",
    ):
        (tmp_path / name).write_bytes(b"x")
    assert fonts_available(tmp_path) is False


def test_mono_ink_height_matches_a_measured_block_glyph(font_dir):
    """`ink_height` is measured, not derived from `cell_height` — render
    a full-height glyph (`█`) bilevel, the same target FreeType's mono
    rasterising uses on the panel, and count the rows with any ink at all.
    31, not `cell_height`'s 33 (ascent + descent, which is headroom no
    glyph actually inks) — the gap between them is a 2px hairline seam
    that stacking by `cell_height` would leave, unlike the pitch
    `test_mono_stacked_bars_meet_seamlessly_at_ink_height` pins below."""
    from PIL import Image, ImageDraw

    f = load_font(font_dir, FONTS["mono/24"])
    img = Image.new("1", (60, 80), 0)
    dr = ImageDraw.Draw(img)
    dr.text((10, 10), "█", font=f, fill=1)
    px = img.load()
    inked_rows = [y for y in range(80) if any(px[x, y] for x in range(60))]
    # 31 is pinned as data (C10, final review): a real measurement of the
    # committed JetBrains Mono file at 24px, not derived from anything else
    # here -- a font swap that moves it fails this assertion directly.
    assert len(inked_rows) == FONTS["mono/24"].ink_height == 31


def test_mono_glyph_advance_is_a_constant_integer(font_dir):
    """The whole point of BASIC layout (D11's second finding): every glyph
    advances by the same integer width, `M`/`i`/a block character alike —
    not the fractional 14.4px raqm would use."""
    f = load_font(font_dir, FONTS["mono/24"])
    advances = {f.getlength(ch) for ch in ("M", "i", "█")}
    assert len(advances) == 1
    (advance,) = advances
    assert advance == int(advance)


def test_mono_angle_brackets_render_as_two_glyphs_not_a_ligature(font_dir):
    """Raqm's default layout turns `<>` into one ligature glyph; BASIC keeps
    it two, so its width equals `<` + `>` measured separately."""
    f = load_font(font_dir, FONTS["mono/24"])
    assert f.getlength("<>") == f.getlength("<") + f.getlength(">")


def test_mono_box_drawing_run_has_no_gap(font_dir):
    """`┌─┐` as one `text` op: the rule's row has one contiguous run of ink
    with no interior blank column — a fractional advance would have opened
    a 1px gap at the seam between glyphs (D11's second finding)."""
    doc = {
        "v": 1,
        "meta": {},
        "bg": "white",
        "palette": {},
        "ops": [{"op": "text", "x": 40, "y": 40, "s": "┌─┐", "f": "mono/24"}],
    }
    img, problems = render(doc, font_dir)
    assert problems == []
    px = img.load()
    box = img.getbbox()  # whole canvas is white except the glyphs
    x0, y0, x1, y1 = box
    # the row with the most ink is the horizontal rule's row
    best_y, best_n = None, -1
    for y in range(y0, y1):
        n = sum(px[x, y] != INK["white"] for x in range(x0, x1))
        if n > best_n:
            best_y, best_n = y, n
    inked = [x for x in range(x0, x1) if px[x, best_y] != INK["white"]]
    assert inked == list(range(inked[0], inked[-1] + 1))


def _ink_runs(ys: list[int]) -> list[tuple[int, int]]:
    """Contiguous runs of consecutive integers in sorted `ys`, as
    `[(start, end), ...]` — the "is this ink one connected run or several"
    helper the mono stacking tests share."""
    if not ys:
        return []
    runs = []
    start = prev = ys[0]
    for y in ys[1:]:
        if y != prev + 1:
            runs.append((start, prev))
            start = y
        prev = y
    runs.append((start, prev))
    return runs


def test_mono_stacked_bars_meet_seamlessly_at_ink_height(font_dir):
    """Stacking by `ink_height` (31), not `cell_height` (33), is the pitch
    that makes consecutive block-art rows meet exactly — the two bars' ink
    merges into a single contiguous run, touching with no gap and no
    overlap."""
    ink_height = FONTS["mono/24"].ink_height
    doc = {
        "v": 1,
        "meta": {},
        "bg": "white",
        "palette": {},
        "ops": [
            {"op": "text", "x": 40, "y": 100, "s": "│", "f": "mono/24"},
            {"op": "text", "x": 40, "y": 100 + ink_height, "s": "│", "f": "mono/24"},
        ],
    }
    img, problems = render(doc, font_dir)
    assert problems == []
    px = img.load()
    scan_y = range(90, 100 + ink_height + 40)
    col = max(range(40, 54), key=lambda x: sum(px[x, y] != INK["white"] for y in scan_y))
    ys = [y for y in scan_y if px[col, y] != INK["white"]]
    runs = _ink_runs(ys)
    assert len(runs) == 1, "expected the two bars to meet as a single run, not leave a seam"


def test_mono_missing_face_warns_and_draws_nothing(tmp_path, font_dir):
    """A font directory with every non-optional family but no JetBrains
    Mono file still renders — `mono` ops are abandoned like an unknown
    font name, the same way the firmware skips an uncompiled one."""
    for name in (
        "Petrona.ttf", "Petrona-Italic.ttf",
        "InstrumentSans.ttf", "InstrumentSans-Italic.ttf",
        "Karla.ttf", "Karla-Italic.ttf",
    ):
        shutil.copy(font_dir / name, tmp_path / name)
    doc = {
        "v": 1,
        "meta": {},
        "bg": "white",
        "palette": {},
        "ops": [{"op": "text", "x": 40, "y": 40, "s": "hi", "f": "mono/24"}],
    }
    img, problems = render(doc, tmp_path)
    assert problems == [
        "ops[0] text: font 'mono/24' is not installed here "
        "(fonts/JetBrainsMono-Regular.ttf); skipped"
    ]
    blank, _ = render({"v": 1, "meta": {}, "bg": "white", "ops": []}, tmp_path)
    assert img.tobytes() == blank.tobytes()  # nothing drawn on the white canvas


def test_instrument_sans_missing_still_raises(tmp_path, font_dir):
    """Unlike `mono`, a missing Instrument Sans file is a hard failure at
    load time (there is nothing to abandon-and-skip a whole render for)."""
    shutil.copy(
        font_dir / "JetBrainsMono-Regular.ttf", tmp_path / "JetBrainsMono-Regular.ttf"
    )
    with pytest.raises(OSError):
        render({"v": 1, "meta": {}, "bg": "white", "ops": []}, tmp_path)


def _footer_ink(img, x0, y0, x1, y1):
    """Count non-background pixels in a box; the sample bg is ink white."""
    bg = img.getpixel((5, 1590))
    return sum(1 for x in range(x0, x1) for y in range(y0, y1) if img.getpixel((x, y)) != bg)


def test_fmt_op_substitutes_fields(font_dir):
    from datetime import datetime

    from display_mcp.render import expand_fields, system_fields

    doc = {"bg": "white", "ops": [{"op": "fmt", "x": 20, "y": 1550, "s": "{hash}@{time24} {time}"}]}
    fields = system_fields(doc, now=datetime(2026, 9, 9, 13, 43))
    assert fields["hash"] == render_hash(doc)[-5:]
    assert fields["battery"].endswith("%") and fields["battv"].endswith("V")
    assert fields["hash16"] == render_hash(doc)
    assert fields["time"] == "1:43 PM"
    assert fields["time24"] == "13:43"
    assert system_fields(doc, now=datetime(2026, 9, 9, 0, 5))["time"] == "12:05 AM"
    text, unknown = expand_fields("a {hash} b {nope} c", fields)
    assert text == f"a {fields['hash']} b {{nope}} c"
    assert unknown == ["nope"]
    img, problems = render(doc, font_dir, now=datetime(2026, 9, 9, 13, 43))
    assert problems == []
    assert _footer_ink(img, 20, 1550, 400, 1580) > 50
    # The values are not part of the hash: moving the op changes it, its text never can.
    moved = {"bg": "white", "ops": [{"op": "fmt", "x": 21, "y": 1550, "s": "{hash}"}]}
    assert render_hash(doc) != render_hash(moved)


def test_fmt_unknown_field_is_a_warning(font_dir):
    doc = {"bg": "white", "ops": [{"op": "fmt", "x": 20, "y": 1550, "s": "{nope}"}]}
    _, problems = render(doc, font_dir)
    assert any("unknown field {nope}" in p for p in problems)


def test_fmt_unknown_font_skips_before_field_expansion(font_dir):
    """The firmware checks the font first and never reaches expand_fmt()
    when it's bad, so a `fmt` op with both an unknown font and an unknown
    field warns about the font only — the same op-abandonment as `text`."""
    doc = {"bg": "white", "ops": [{"op": "fmt", "x": 20, "y": 1550, "s": "{nope}", "f": "huge"}]}
    _, problems = render(doc, font_dir)
    assert problems == [f"ops[0] fmt: {unknown_font_message('huge')}"]


# --------------------------------------------------------------------------
# Length and line-count bounds (docs/plans/firmware-bounds.md D6).
# --------------------------------------------------------------------------


def test_text_at_the_length_bound_is_accepted(font_dir):
    s = "a" * TEXT_MAX_LEN
    doc = {"bg": "white", "ops": [{"op": "text", "x": 10, "y": 10, "s": s, "f": "sm", "w": 100}]}
    _, problems = render(doc, font_dir)
    assert not any("bytes" in p and "skipped" in p for p in problems)


def test_text_past_the_length_bound_is_skipped_and_fast(font_dir):
    """A 200 KB `s`, the kind that would make fit_line()'s quadratic cost
    actually hurt, is skipped in well under a second."""
    s = "a" * (200 * 1024)
    doc = {"bg": "white", "ops": [{"op": "text", "x": 10, "y": 10, "s": s, "f": "sm", "w": 100}]}
    t0 = time.monotonic()
    img, problems = render(doc, font_dir)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, elapsed
    assert problems == [f"ops[0] text: s is {len(s)} bytes, more than {TEXT_MAX_LEN}; skipped"]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_fmt_past_the_length_bound_is_skipped(font_dir):
    """Measured on the template itself, before expansion -- {time} et al.
    are always short, so this is about the literal text an author wrote,
    not what it might expand to."""
    s = "{time}" + ("x" * (TEXT_MAX_LEN + 10))
    doc = {"bg": "white", "ops": [{"op": "fmt", "x": 10, "y": 10, "s": s, "f": "xs"}]}
    _, problems = render(doc, font_dir)
    assert problems == [f"ops[0] fmt: s is {len(s)} bytes, more than {TEXT_MAX_LEN}; skipped"]


# docs/plans/fonts-and-icons.md B4b review item 2: `text`/`fmt`'s own `f`,
# bounded by NAME_MAX_LEN the same way `s` is bounded by TEXT_MAX_LEN --
# mirrors firmware/display_list.h's kNameMaxLen, which exists because
# normalize_font_key() builds a std::string from `f` and a legal multi-KB
# `f` would have made that peak at several times its own length of
# transient heap.


def test_text_f_at_the_length_bound_is_accepted(font_dir):
    f = "a" * NAME_MAX_LEN
    doc = {"bg": "white", "ops": [{"op": "text", "x": 10, "y": 10, "s": "hi", "f": f}]}
    _, problems = render(doc, font_dir)
    assert not any("f is" in p and "skipped" in p for p in problems)


def test_text_f_past_the_length_bound_is_skipped(font_dir):
    f = "a" * (NAME_MAX_LEN + 1)
    doc = {"bg": "white", "ops": [{"op": "text", "x": 10, "y": 10, "s": "hi", "f": f}]}
    img, problems = render(doc, font_dir)
    assert problems == [f"ops[0] text: f is {len(f)} bytes, more than {NAME_MAX_LEN}; skipped"]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_fmt_f_past_the_length_bound_is_skipped(font_dir):
    f = "a" * (NAME_MAX_LEN + 1)
    doc = {"bg": "white", "ops": [{"op": "fmt", "x": 10, "y": 10, "s": "{time}", "f": f}]}
    _, problems = render(doc, font_dir)
    assert problems == [f"ops[0] fmt: f is {len(f)} bytes, more than {NAME_MAX_LEN}; skipped"]


def test_text_wrap_lines_past_the_bound_is_clamped_not_skipped(font_dir):
    """`lines` past `TEXT_MAX_LINES` is bounded the way `t` is bounded by
    `THICK_MAX` -- clamped with a warning, the op still draws."""
    doc_over = {"bg": "white", "ops": [
        {"op": "text", "x": 10, "y": 10, "s": "word " * 50, "f": "sm",
         "wrap": True, "w": 100, "lines": TEXT_MAX_LINES + 10}]}
    doc_clamped = {"bg": "white", "ops": [
        {"op": "text", "x": 10, "y": 10, "s": "word " * 50, "f": "sm",
         "wrap": True, "w": 100, "lines": TEXT_MAX_LINES}]}
    img_over, problems = render(doc_over, font_dir)
    img_clamped, _ = render(doc_clamped, font_dir)
    assert any(f"clamped to {TEXT_MAX_LINES}" in p for p in problems)
    assert img_over.tobytes() == img_clamped.tobytes()


def test_text_wrap_huge_lh_is_rejected(font_dir):
    """docs/plans/firmware-bounds.md's review amendment: `lh` joins the
    coordinate bound too -- with `lines` up to TEXT_MAX_LINES, `y + n * lh`
    is exactly the size-field arithmetic D4 already covers for every other
    op, and a `lh` like 2e9 would overflow that multiply in the firmware
    long before any print() call saw it."""
    doc = {"bg": "white", "ops": [
        {"op": "text", "x": 10, "y": 10, "s": "word " * 5, "f": "sm",
         "wrap": True, "w": 100, "lines": TEXT_MAX_LINES, "lh": 2e9}]}
    img, problems = render(doc, font_dir)
    # "2e+09", matching the firmware's own %g -- not repr()'s
    # "2000000000.0" (docs/plans/firmware-bounds.md's review amendment).
    assert problems == [f"ops[0] text: lh=2e+09 out of range (|v| <= {MAX_COORD}); skipped"]
    blank, _ = render({"bg": "white", "ops": []}, font_dir)
    assert img.tobytes() == blank.tobytes()


def test_uncompiled_glyphs_warn_on_a_proportional_face(font_dir):
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "ops": [{"op": "text", "x": 100, "y": 300, "s": "a → ☃ █ b", "f": "sm"}],
    }
    msgs = _glyph_msgs(check(doc, font_dir))
    assert len(msgs) == 1
    assert "3 character(s)" in msgs[0]
    assert "→ (U+2192)" in msgs[0]
    assert "☃ (U+2603)" in msgs[0]
    assert "█ (U+2588)" in msgs[0]
    assert "GF_Latin_Core only" in msgs[0]


def test_uncompiled_glyphs_silent_for_mono_block_element(font_dir):
    """`mono` compiles U+2500-U+259F on top of GF_Latin_Core, so the same
    block character that warns on `sm` above is silent here."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "ops": [{"op": "text", "x": 100, "y": 300, "s": "█", "f": "mono/24"}],
    }
    assert _glyph_msgs(check(doc, font_dir)) == []


def test_uncompiled_glyphs_silent_on_both_samples(sample_doc, sprite_sample_doc, font_dir):
    assert _glyph_msgs(check(sample_doc, font_dir)) == []
    assert _glyph_msgs(check(sprite_sample_doc, font_dir)) == []


def test_uncompiled_glyphs_ignore_fmt_braces_and_space(font_dir):
    """An unexpanded `fmt` field leaves its `{`/`}` literal — not a font
    question — and a space is never counted either, even though both are
    in GF_Latin_Core anyway."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "ops": [{"op": "fmt", "x": 100, "y": 300, "s": "{nope} value", "f": "xs"}],
    }
    assert _glyph_msgs(check(doc, font_dir)) == []


def test_uncompiled_glyphs_ignore_what_fit_line_would_drop(font_dir):
    """The check runs on the text actually drawn, after `fit_line` has
    already truncated it -- a character past the cut point never gets a
    chance to be counted."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "ops": [{"op": "text", "x": 1000, "y": 300, "s": "ok→", "f": "sm", "w": 20}],
    }
    assert _glyph_msgs(check(doc, font_dir)) == []


def _ink_pixel_count(font_dir, font_name: str) -> int:
    """A `text` op in one face through the real op pipeline (`render()`,
    not `load_font()` in isolation) -- the non-background pixel count, a
    coarse black-box weight signal independent of the advance-width check
    `test_load_font_selects_the_intended_weight_for_every_face_at_lg`
    above already makes."""
    doc = {
        "v": 1, "meta": {}, "bg": "white",
        "ops": [{"op": "text", "x": 40, "y": 40, "s": "Handgloves", "f": font_name}],
    }
    img, problems = render(doc, font_dir)
    assert problems == [], (font_name, problems)
    px = img.load()
    w, h = img.size
    return sum(1 for y in range(h) for x in range(w) if px[x, y] != INK["white"])


def test_every_new_family_style_renders_clean_at_md(font_dir):
    """B3b re-review, item 8: one document per new family-style
    (docs/plans/fonts-and-icons.md Decision 2) through the real op
    pipeline -- `render()`, not `load_font()` in isolation -- so a face
    that loads fine standalone but breaks somewhere in `check()`/`Ctx.font()`
    doesn't slip past every other test naming it individually. `-bold`
    inks more pixels than its family's `regular` at the same size, for
    both families new in this batch (`instrument-bold` isn't -- only
    `instrument-italic` is new for Instrument Sans, so it's checked for a
    clean render but not for a weight comparison it isn't part of)."""
    new_family_styles = (
        "petrona/md", "petrona-bold/md", "petrona-italic/md",
        "karla/md", "karla-bold/md", "karla-italic/md",
        "instrument-italic/md",
    )
    ink = {name: _ink_pixel_count(font_dir, name) for name in new_family_styles}
    assert all(count > 0 for count in ink.values()), ink

    for family in ("petrona", "karla"):
        assert ink[f"{family}-bold/md"] > ink[f"{family}/md"], (family, ink)


def test_default_instance_faces_load_exactly_as_the_file_default(font_dir):
    """Pins `load_font()`'s guard (B3b re-review): a face whose `variation`
    is its file's own default subfamily must be loaded with *no* named
    instance selected, because Pillow's named-instance selection is not
    byte-identical to the default even at the same axis coordinates -- the
    B1 blocker, and the 0.06 px `instrument-italic` drift the B3b review
    measured against the static TTFs the firmware compiles. The 48 px
    weight test cannot see it (the divergence is zero at `lg`), so this
    runs every size."""
    from PIL import ImageFont

    checked = 0
    for name, face in FONTS.items():
        if face.layout == "basic":
            continue
        path = font_dir / face.file
        plain = ImageFont.truetype(str(path), face.size)
        if face.variation != plain.getname()[1]:
            continue
        loaded = load_font(font_dir, face)
        assert loaded.getlength("Handgloves") == plain.getlength("Handgloves"), name
        assert loaded.getmetrics() == plain.getmetrics(), name
        checked += 1
    assert checked >= 40, checked  # instrument, instrument-italic, karla, karla-italic x 11
