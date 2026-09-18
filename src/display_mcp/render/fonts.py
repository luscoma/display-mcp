"""The compiled type-scale table and font loading: Face, FONTS, the glyph
sets each face is compiled with, load_font()/fonts_available(), and the
uncompiled-glyph authoring warning (docs/plans/dragon-feedback.md D11).
colour.py's Ctx.font() and __init__.py's render()/bezel_problems()/
vocabulary() import from here.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from PIL import ImageFont

if TYPE_CHECKING:
    from .colour import Ctx


class Face(NamedTuple):
    """One compiled type-scale entry. A plain `NamedTuple`: read fields by
    name (`FONTS[name].size`); positional access works but is not used.

    `cell_height` is `size`'s ascent + descent as PIL's `font.getmetrics()`
    reports it for the *loaded* face (the selected weight instance, for
    Instrument Sans and JetBrains Mono alike) — measured once, by hand, and
    stored here as data rather than recomputed at import time, so a font
    swap that silently changes the metrics is a failing test
    (test_render.py) rather than a page that quietly reflows. `lh`'s own
    default stays `round(size * 1.24)` for every face including `mono` (the
    firmware has no per-face default), so `cell_height` is published
    separately in `describe().fonts[*]` instead of changing what an unset
    `lh` means.

    `ink_height` is `None` for every Instrument Sans entry and the one
    number that actually matters for stacking `mono` block art
    (docs/plans/dragon-feedback.md D11): the row count a full-height
    glyph (`│`, `█`) inks at 1bpp, measured by rendering one bilevel and
    counting rows with any ink. It is *not* `cell_height` — that's 2px more
    (33 vs 31), which is ascent+descent, not glyph extent, and leaves a 2px
    hairline seam if you stack by it. `describe().fonts.mono.ink_height` is
    the field a composer stacking block art by hand should use.
    """

    size: int
    bold: bool
    file: str
    cell_height: int
    ink_height: int | None = None
    # Code points the firmware compiles into this face beyond GF_LATIN_CORE
    # (docs/plans/dragon-feedback.md D11), as ranges, so the YAML
    # (`epaper-schedule.yaml`'s `glyphs:` string) and this table say the
    # same thing — tests/parity/test_limits_and_dispatch.py checks that they do.
    # Empty for every face but `mono`.
    extra_glyphs: tuple[range, ...] = ()
    # "raqm" (Pillow's default layout engine) for every face but `mono`,
    # which is "basic" — see load_font(). load_font()/_load_fonts() read a
    # face's own layout rather than recognising it by name.
    layout: str = "raqm"
    # Whether this face's file missing from `font_dir` is tolerated —
    # `mono`'s alone: it is the one face this repo doesn't ship pre-fetched
    # (deploy/fetch-fonts.sh's newer half), so _load_fonts() turns its
    # OSError into a plain `None` instead of letting it raise. Every other
    # face missing is still fatal, as it always was.
    optional: bool = False

    @property
    def line_height(self) -> int:
        """The wrap default every face uses when an op's `lh` is unset:
        `round(size * 1.24)`, including for `mono` — the firmware has no
        per-face default, so this stays one formula for every face, and
        `cell_height`/`ink_height` are published separately in
        `describe().fonts[*]` instead of changing what an unset `lh` means."""
        return round(self.size * 1.24)


def _load_gf_latin_core() -> frozenset[int]:
    """Parse `gf_latin_core.txt` (one hex code point per line, `#` comments
    ignored) into the set every compiled face carries."""
    path = Path(__file__).parent / "gf_latin_core.txt"
    return frozenset(
        int(line, 16)
        for line in path.read_text().splitlines()
        if line and not line.startswith("#")
    )


GF_LATIN_CORE: frozenset[int] = _load_gf_latin_core()


MONO_EXTRA_GLYPHS: range = range(0x2500, 0x25A0)


FONTS: dict[str, Face] = {
    "xl": Face(84, True, "InstrumentSans-Bold.ttf", 103),
    "lg": Face(48, True, "InstrumentSans-Bold.ttf", 59),
    "md": Face(36, False, "InstrumentSans-Regular.ttf", 44),
    "sm": Face(28, False, "InstrumentSans-Regular.ttf", 35),
    "xs": Face(22, True, "InstrumentSans-Bold.ttf", 28),
    # JetBrains Mono, 24px regular (docs/plans/dragon-feedback.md D11): the
    # one monospace face, for block art, aligned columns and code. Loaded
    # with BASIC layout and no ligatures — see load_font(). ink_height=31
    # is measured (test_render.py), not derived: a full-height glyph at
    # 1bpp inks 31 rows inside the 33px cell.
    "mono": Face(
        24, False, "JetBrainsMono-Regular.ttf", 33, 31, (MONO_EXTRA_GLYPHS,),
        layout="basic", optional=True,
    ),
}


_FACE_GLYPHS: dict[str, frozenset[int]] = {
    name: GF_LATIN_CORE | frozenset(cp for r in face.extra_glyphs for cp in r)
    for name, face in FONTS.items()
}


def _font_path(font_dir: Path, file: str) -> Path:
    return Path(font_dir) / file


def load_font(font_dir: Path, face: Face) -> ImageFont.FreeTypeFont:
    """Load one compiled face (`FONTS[name]`). `face.bold` also selects the
    variable font's "Bold" instance; `face.layout` picks Pillow's layout
    engine.

    Google Fonts ships Instrument Sans as a variable font: Pillow loads the
    default instance (Regular) unless the named instance is selected, and
    the wrong weight means text wraps in different places than the panel
    does. A static Bold face (nothing to select) is fine too.

    A `"basic"`-layout face (`mono`, the only one today) is loaded with
    `ImageFont.Layout.BASIC` instead of Pillow's default raqm layout:
    raqm turns `<>`/`->`/`!=` into single ligature glyphs and positions
    every glyph at a fractional advance (14.4px at 24px here), and at 1bpp
    that fractional advance opened a 1px gap in every box-drawing rule —
    the panel's own bitmap font does neither (docs/plans/dragon-feedback.md
    D11's second finding). Its "Regular" instance is selected the same way
    Bold is, in its own try/except — every `"basic"` face's `bold` is False,
    so a raqm face and a basic one never fight over which name to select.
    """
    path = _font_path(font_dir, face.file)
    if face.layout == "basic":
        f = ImageFont.truetype(str(path), face.size, layout_engine=ImageFont.Layout.BASIC)
        try:
            f.set_variation_by_name("Regular")
        except Exception:
            pass  # a static Regular face: nothing to select
        return f
    f = ImageFont.truetype(str(path), face.size)
    if face.bold:
        try:
            f.set_variation_by_name("Bold")
        except Exception:
            pass  # a static Bold face: nothing to select
    return f


def _load_fonts(font_dir: Path) -> dict[str, ImageFont.FreeTypeFont | None]:
    """Every compiled face, keyed by name. An `optional` face (`mono`,
    today) may come back `None`: its file is the one face this repo doesn't
    ship pre-fetched, so a font directory that hasn't run
    `deploy/fetch-fonts.sh`'s newer half must not break every other render —
    `Ctx.font()` turns a `None` here into the same "abandon the op" path an
    unknown font name gets. A non-optional face missing still raises
    `OSError` out of this function, exactly as before `mono` existed (there
    is a test pinning that)."""
    fonts: dict[str, ImageFont.FreeTypeFont | None] = {}
    for name, face in FONTS.items():
        if face.optional:
            try:
                fonts[name] = load_font(font_dir, face)
            except OSError:
                fonts[name] = None
        else:
            fonts[name] = load_font(font_dir, face)
    return fonts


def fonts_available(font_dir: Path) -> bool:
    """Every compiled face's file present in `font_dir` — including
    `mono`'s, even though `_load_fonts()` alone tolerates it missing: this
    is the /healthz and setup.sh gate, which wants to know the font
    directory is genuinely complete, not just render-safe. Deduped by
    filename (several faces share the two Instrument Sans files), so this
    stays table-driven."""
    font_dir = Path(font_dir)
    return all((font_dir / file).exists() for file in {face.file for face in FONTS.values()})


def _check_uncompiled_glyphs(ctx: Ctx, face_name: str, text: str, where: str) -> None:
    """Warning: a character `face_name` draws that the panel has not
    compiled in (docs/plans/dragon-feedback.md D11).

    The preview loads the whole TTF, so it draws any glyph the file has;
    the panel compiles only GF_LATIN_CORE (every face) plus box drawing
    and block elements (`mono` only, `Face.extra_glyphs`) — `"a → b"`
    previews fine and loses the arrow on the wall, silently, unless
    something says so. One warning per op, naming up to five distinct
    offending characters with their code points.

    `text` is what the op actually draws — after `fit_line`/`wrap_lines`
    has already trimmed it, so a character that would have been cut
    anyway is never reported — and a space or a literal `{`/`}` an
    unexpanded `fmt` field leaves behind is never counted as one, even
    though both are in GF_LATIN_CORE: a document's own template syntax
    isn't a font question. A no-op unless `ctx.warn_ink`.
    """
    if not ctx.warn_ink:
        return
    allowed = _FACE_GLYPHS.get(face_name)
    if allowed is None:
        return
    offenders: list[str] = []
    seen: set[str] = set()
    for ch in text:
        # `seen` keeps this linear: a max-size document of distinct
        # characters must not turn one op into a multi-second scan.
        if ch == " " or ch in seen:
            continue
        seen.add(ch)
        if ord(ch) not in allowed:
            offenders.append(ch)
    if not offenders:
        return
    examples = ", ".join(f"{ch} (U+{ord(ch):04X})" for ch in offenders[:5])
    ctx.problems.append(
        f"{where}: {len(offenders)} character(s) the panel has not compiled: "
        f"{examples} — GF_Latin_Core only (plus box drawing and block "
        "elements for mono)"
    )


# A one-off Face matching no compiled entry -- 22px, regular weight, chosen
# only to survive a client downscaling the grid overlay's PNG.
# `cell_height` is unused by load_font()/grid_overlay(), so 0 is a safe
# filler. Shared by mcp_server.preview's grid overlay and its own tests, so
# neither has to spell the same four-argument Face out by hand.
GRID_FACE = Face(22, False, "InstrumentSans-Regular.ttf", 0)
