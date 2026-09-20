"""The compiled type-scale table and font loading: Face, FONTS, the glyph
sets each face is compiled with, load_font()/fonts_available(), and the
uncompiled-glyph authoring warning (docs/plans/dragon-feedback.md D11).
colour.py's Ctx.font() and __init__.py's render()/bezel_problems()/
vocabulary() import from here.

docs/plans/fonts-and-icons.md Decision 1-3 (B1): a face is named
`family[-style]/size` (`style` is `""`, `"bold"` or `"italic"`; `size` is a
slot -- `xs sm md lg xl` -- or a pixel count). `FAMILIES` x `SIZES` generate
every `Face` at import; `FONT_ALIASES` resolves every other accepted
spelling (a face's own px spelling, plus the five legacy bare names) to its
canonical key. `resolve_font()` is the one function every font-name lookup
in this package goes through. `cell_height`/`ink_height` are read from the
committed `font_metrics.json` (measured by `display-mcp-cli font-metrics
<font_dir>`, cli.py -- see `_write_metrics()` below), not hand-typed --
except while the environment variable `DISPLAY_MCP_FONT_METRICS_BOOTSTRAP`
is set, when a face missing from that file gets a placeholder instead of
raising (B3b re-review, item 3): `display-mcp-cli font-metrics` sets it
before its own first import of this module, precisely so that adding a
size or a family and then running that command to populate the file it's
missing a row for isn't a chicken-and-egg `RuntimeError`. A plain
`import display_mcp.render`, and every command but `font-metrics`, never
sets the flag and stays strict.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from PIL import ImageFont

if TYPE_CHECKING:
    from .colour import Ctx


# Every compiled size, and the five named slots (docs/plans/fonts-and-icons.md
# Decision 1-2). A size not in this tuple is not compiled for any family --
# `resolve_font()` returns None for it, the same as an unknown family.
SIZES: tuple[int, ...] = (22, 24, 26, 28, 32, 36, 40, 44, 48, 54, 84)

SLOTS: dict[str, int] = {"xs": 22, "sm": 28, "md": 36, "lg": 48, "xl": 84}

# The reverse of SLOTS -- a size's slot name, when it has one. Used both to
# build the canonical name (the slot spelling when a size is a slot, the
# pixel spelling otherwise) and to publish `slot` in vocabulary()'s per-face
# entries.
SIZE_TO_SLOT: dict[int, str] = {px: slot for slot, px in SLOTS.items()}


class StyleSpec(NamedTuple):
    """One style (`""`, `"bold"` or `"italic"`) of a `Family`: the file it
    loads from, the weight it draws as, the named variable-font instance
    `load_font()` selects, and whether it is slanted. `italic` is a
    separate flag rather than derived from `style == "italic"` so a family
    could in principle carry an italic under another name -- none does
    today, so this is future-proofing, not a distinction B1 exercises."""

    file: str
    weight: int
    instance: str
    italic: bool = False


class Family(NamedTuple):
    """One typeface, compiled at every size in `SIZES` for every style it
    lists. `typeface` is the human name (`describe().font_families[*]`'s
    own field) — `name` is the short key every canonical face name and
    alias is built from, and the two can differ (`"instrument"` names
    "Instrument Sans"). `layout`/`extra_glyphs`/`optional` are per-family,
    matching yesterday's per-face fields exactly -- `mono` is still the
    one `"basic"`-layout, extra-glyph, `optional` family; every
    proportional family uses the raqm-layout, no-extra-glyph, non-optional
    defaults."""

    name: str
    typeface: str
    styles: dict[str, StyleSpec]
    layout: str = "raqm"
    extra_glyphs: tuple[range, ...] = ()
    optional: bool = False


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


# The full family table (docs/plans/fonts-and-icons.md Decision 2, B3b):
# Petrona, Instrument Sans and Karla each in regular/bold/italic, plus mono
# regular-only. Petrona's regular is the file's SemiBold (600) instance, not
# its own default (Regular, 400 -- confirmed with get_variation_names()), so
# load_font() always has to select it; its bold is ExtraBold (800), one step
# heavier than the design asked for so the serif has a heavier step like the
# other two families. Petrona and Karla's italics come from their own
# `-Italic.ttf` files, the way every italic in this table does -- Google
# Fonts never puts an italic instance in the upright file. Instrument Sans
# now loads regular/bold from the single `InstrumentSans.ttf` (its Regular/
# Bold named instances) rather than the old Regular/Bold file pair -- the
# same bytes, one file instead of two -- and gains its own italic from
# `InstrumentSans-Italic.ttf`. `mono` is unchanged.
FAMILIES: dict[str, Family] = {
    "petrona": Family(
        "petrona",
        "Petrona",
        styles={
            "": StyleSpec("Petrona.ttf", 600, "SemiBold"),
            "bold": StyleSpec("Petrona.ttf", 800, "ExtraBold"),
            "italic": StyleSpec("Petrona-Italic.ttf", 500, "Medium Italic", italic=True),
        },
    ),
    "instrument": Family(
        "instrument",
        "Instrument Sans",
        styles={
            "": StyleSpec("InstrumentSans.ttf", 400, "Regular"),
            "bold": StyleSpec("InstrumentSans.ttf", 700, "Bold"),
            "italic": StyleSpec("InstrumentSans-Italic.ttf", 400, "Italic", italic=True),
        },
    ),
    "karla": Family(
        "karla",
        "Karla",
        styles={
            "": StyleSpec("Karla.ttf", 400, "Regular"),
            "bold": StyleSpec("Karla.ttf", 700, "Bold"),
            "italic": StyleSpec("Karla-Italic.ttf", 400, "Italic", italic=True),
        },
    ),
    "mono": Family(
        "mono",
        "JetBrains Mono",
        styles={"": StyleSpec("JetBrainsMono-Regular.ttf", 400, "Regular")},
        layout="basic",
        extra_glyphs=(MONO_EXTRA_GLYPHS,),
        optional=True,
    ),
}


def _family_style_key(family: str, style: str) -> str:
    """`family` for the regular style, `family-style` for any other --
    `"instrument"`, `"instrument-bold"`. Shared by canonical-name
    generation, alias generation and the which-half-is-wrong warning, so
    the three can never disagree on what a family-style is called."""
    return family if not style else f"{family}-{style}"


def _canonical_name(key: str, size: int) -> str:
    """The slot spelling when `size` is one of `SLOTS`' pixel counts, the
    pixel spelling otherwise -- Decision 1's canonical-name rule."""
    slot = SIZE_TO_SLOT.get(size)
    return f"{key}/{slot}" if slot is not None else f"{key}/{size}"


class Face(NamedTuple):
    """One compiled type-scale entry. A plain `NamedTuple`: read fields by
    name (`FONTS[name].size`); positional access works but is not used.

    `family`/`style`/`italic`/`weight`/`variation` (docs/plans/
    fonts-and-icons.md Decision 3) replace the old `bold: bool` -- `variation`
    is the named variable-font instance `load_font()` selects (`"Regular"`,
    `"Bold"`, `"SemiBold"`, `"ExtraBold"`, `"Medium Italic"`, ...), so a
    face's weight and the instance that produces it are no longer
    conflated into one flag.

    `cell_height` is `size`'s ascent + descent as PIL's `font.getmetrics()`
    reports it for the *loaded* face (the selected variation, for every
    family alike) -- measured by `display-mcp-cli font-metrics <font_dir>`
    and read from the committed `font_metrics.json` at import, so a
    font swap that silently changes the metrics fails a test
    (tests/renderer/test_text.py) rather than a page that quietly reflows.
    `lh`'s own default stays `round(size * 1.24)` for every face including
    `mono` (the firmware has no per-face default), so `cell_height` is
    published separately in `describe().fonts[*]` instead of changing what
    an unset `lh` means.

    `ink_height` is `None` for every face but `mono`'s and the one number
    that actually matters for stacking `mono` block art
    (docs/plans/dragon-feedback.md D11): the row count a full-height
    glyph (`│`, `█`) inks at 1bpp, measured by rendering one bilevel and
    counting rows with any ink. It is *not* `cell_height` — that's 2px more
    (33 vs 31 at 24px), which is ascent+descent, not glyph extent, and
    leaves a 2px hairline seam if you stack by it. `describe().fonts[*
    ].ink_height` is the field a composer stacking block art by hand
    should use.
    """

    family: str
    style: str
    size: int
    file: str
    weight: int
    variation: str
    italic: bool = False
    cell_height: int = 0
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

    @property
    def canonical_name(self) -> str:
        """This face's own `FONTS` key, recomputed from `family`/`style`/
        `size` rather than stored twice -- `_build_fonts()` derives a
        face's dict key the same way, so the two can never disagree
        (docs/plans/fonts-and-icons.md Decision 3, B2)."""
        return _canonical_name(_family_style_key(self.family, self.style), self.size)

    @property
    def yaml_id(self) -> str:
        """The firmware `font:` entry id for this face, deterministic from
        its own `canonical_name` (`"instrument-bold/xl"` ->
        `"font_instrument_bold_xl"`, `"mono/24"` -> `"font_mono_24"`) --
        letters, digits and underscores only, so it never has to be typed
        twice (docs/plans/fonts-and-icons.md Decision 3, B2)."""
        return "font_" + self.canonical_name.replace("-", "_").replace("/", "_")


# The committed metrics data (Decision 3): cell_height for every face,
# ink_height for every mono size, measured from the real font files by
# `display-mcp-cli font-metrics <font_dir>` (see _write_metrics() below)
# and read here rather than hand-typed, so adding a size or a family is one
# `SIZES`/`FAMILIES` edit and one re-run of the command, not a
# hand-maintained table that can silently drift from what the fonts
# actually measure.
_METRICS_PATH: Path = Path(__file__).parent / "font_metrics.json"

# Set by `display-mcp-cli font-metrics` (cli.py's cmd_font_metrics) before
# its own first import of this module, and nowhere else -- the bootstrap
# escape hatch for _metrics_for() below (B3b re-review, item 3).
_BOOTSTRAP_ENV_VAR = "DISPLAY_MCP_FONT_METRICS_BOOTSTRAP"


def _load_metrics() -> dict[str, dict[str, int | None]]:
    """The committed metrics file, or a loud `RuntimeError` if it's
    missing -- the same "fail at import, not with a quiet wrong number"
    rule `_load_gf_latin_core()` already holds `gf_latin_core.txt` to
    (B1 review, item 5): a font_metrics.json this table can't find is not
    a directory this repo runs without, the way a missing font *file* is
    (`_load_fonts()`'s `optional` path) -- it's a checked-in data file that
    should always be there, so its absence means something is actually
    wrong and every face's `cell_height`/`ink_height` would otherwise be
    silently unusable (0 and `None`)."""
    if not _METRICS_PATH.exists():
        # The same escape hatch `_metrics_for()` has for a stale row: with
        # the bootstrap flag set the writer can import this module with no
        # file at all and produce one (B3b re-review). Every normal import
        # stays strict.
        if os.environ.get(_BOOTSTRAP_ENV_VAR):
            return {}
        raise RuntimeError(
            f"{_METRICS_PATH} is missing -- run `display-mcp-cli font-metrics "
            "<font_dir>` to generate it"
        )
    return json.loads(_METRICS_PATH.read_text())


_METRICS: dict[str, dict[str, int | None]] = _load_metrics()


def _metrics_for(name: str) -> dict[str, int | None]:
    """`_METRICS[name]`, with its `cell_height` present -- or a loud
    `RuntimeError` naming both the file and the missing face (B1 review,
    item 5), *unless* `_BOOTSTRAP_ENV_VAR` is set (B3b re-review, item 3),
    in which case a missing/stale row gets a placeholder
    (`cell_height=0`, `ink_height=None`) instead of raising. That's the
    only way `display-mcp-cli font-metrics` -- the command that fixes a
    stale file -- can build `FONTS` at all right after `SIZES`/`FAMILIES`
    grows and before that command has run: without the escape hatch,
    building `FONTS` to run it is the very thing raising here prevents,
    a chicken-and-egg deadlock (hit for real writing this file the first
    time for B3b). `_write_metrics()` then re-measures every face from the
    real font files, so the placeholder never survives into what's
    actually written.

    Every ordinary caller -- a plain `import display_mcp.render`, and
    every CLI command but `font-metrics` -- never sets the flag, so a name
    absent from `_METRICS`, or present without `cell_height`, still means
    `font_metrics.json` is stale: a `SIZES`/`FAMILIES` edit not followed by
    a re-run of `display-mcp-cli font-metrics` — silently handing out
    `cell_height=0`/`ink_height=None` for it would let a real gap in the
    committed data pass as a face that simply has no ink to measure."""
    entry = _METRICS.get(name)
    if entry is None or "cell_height" not in entry:
        if os.environ.get(_BOOTSTRAP_ENV_VAR):
            return {"cell_height": 0, "ink_height": None}
        raise RuntimeError(
            f"{_METRICS_PATH} has no cell_height for {name!r} -- run "
            "`display-mcp-cli font-metrics <font_dir>` to regenerate it "
            f"(that command works even though this row is stale -- it "
            f"sets {_BOOTSTRAP_ENV_VAR} itself before building this table)"
        )
    return entry


def _build_fonts() -> dict[str, Face]:
    """`FAMILIES` x `SIZES`, generated rather than typed out (Decision 3):
    every family, every style it has, every compiled size, keyed by its
    canonical name. `cell_height`/`ink_height` come from `_metrics_for()`,
    which raises rather than silently defaulting when `font_metrics.json`
    is stale (B1 review, item 5) -- so an import fails loudly, at the
    point the mismatch actually happened, rather than a page quietly
    reflowing around a wrong 0."""
    fonts: dict[str, Face] = {}
    for family in FAMILIES.values():
        for style, spec in family.styles.items():
            key = _family_style_key(family.name, style)
            for size in SIZES:
                name = _canonical_name(key, size)
                metrics = _metrics_for(name)
                fonts[name] = Face(
                    family=family.name,
                    style=style,
                    size=size,
                    file=spec.file,
                    weight=spec.weight,
                    variation=spec.instance,
                    italic=spec.italic,
                    cell_height=metrics["cell_height"],
                    ink_height=metrics.get("ink_height"),
                    extra_glyphs=family.extra_glyphs,
                    layout=family.layout,
                    optional=family.optional,
                )
    return fonts


FONTS: dict[str, Face] = _build_fonts()


def _build_aliases() -> dict[str, str]:
    """Every accepted spelling that isn't already a `FONTS` key (Decision 1):
    a face's own pixel spelling when its canonical name is the slot spelling
    (`"instrument/48"` -> `"instrument/lg"`), plus the five legacy bare
    names, which stay pointed at Instrument Sans so nothing already
    published reflows. Bare `"mono"` is deliberately not one of them --
    it's the only bare name that wouldn't be a size, and nothing published
    uses it (docs/plans/fonts-and-icons.md Decision 1)."""
    aliases: dict[str, str] = {}
    for name, face in FONTS.items():
        if face.size not in SIZE_TO_SLOT:
            continue  # canonical name is already the (only) pixel spelling
        key = _family_style_key(face.family, face.style)
        aliases[f"{key}/{face.size}"] = name
    aliases.update(
        {
            "xl": "instrument-bold/xl",
            "lg": "instrument-bold/lg",
            "md": "instrument/md",
            "sm": "instrument/sm",
            "xs": "instrument-bold/xs",
        }
    )
    return aliases


FONT_ALIASES: dict[str, str] = _build_aliases()


def _build_aliases_by_target() -> dict[str, list[str]]:
    """The reverse of `FONT_ALIASES`, sorted -- what `vocabulary()` publishes
    as each face's own `aliases` list."""
    out: dict[str, list[str]] = {}
    for alias, target in FONT_ALIASES.items():
        out.setdefault(target, []).append(alias)
    for names in out.values():
        names.sort()
    return out


ALIASES_BY_TARGET: dict[str, list[str]] = _build_aliases_by_target()


def _build_font_families() -> dict[str, dict[str, Any]]:
    """The per-family-style constants that don't vary by size, keyed the
    same way a canonical face name's own family-style half is spelled
    (`"instrument"`, `"instrument-bold"`, `"mono"`) -- `describe()`
    publishes this once as `font_families` instead of repeating
    `glyphs`/`weight`/`italic` on every one of a family-style's `SIZES`
    entries (B1 review, item 6: with 33 faces, `glyphs` alone was showing
    up 33 times for two distinct strings; at 110 faces that only gets
    worse). `describe().fonts[*]` keeps `family`/`style` so a caller can
    still join back to this table."""
    out: dict[str, dict[str, Any]] = {}
    for family in FAMILIES.values():
        glyphs = "GF_Latin_Core" + (" + U+2500–U+259F" if family.extra_glyphs else "")
        for style, spec in family.styles.items():
            key = _family_style_key(family.name, style)
            out[key] = {
                "typeface": family.typeface,
                "weight": spec.weight,
                "italic": spec.italic,
                "glyphs": glyphs,
            }
    return out


FONT_FAMILIES: dict[str, dict[str, Any]] = _build_font_families()


def resolve_font(name: str) -> str | None:
    """The canonical `FONTS` key for any accepted spelling -- `name` itself
    when it already is one, `FONT_ALIASES[name]` when it's a known alias
    (a face's own px spelling, or one of the five legacy bare names),
    `None` when `name` is not a font at all. Every lookup by a document's
    font name goes through this: `Ctx.font()`, `check()`'s and
    `bezel_problems()`'s own default lookups, and swatches.py's `"sm"`/
    `"xs"` literals -- so the whole package agrees on which spellings exist
    (docs/plans/fonts-and-icons.md Decision 1)."""
    if name in FONTS:
        return name
    return FONT_ALIASES.get(name)


# Every family-style this package compiles, e.g. {"instrument",
# "instrument-bold", "mono"} in B1 -- the "is the *family* half of this name
# real" half of unknown_font_message()'s check.
_FAMILY_STYLE_KEYS: frozenset[str] = frozenset(
    _family_style_key(family.name, style) for family in FAMILIES.values() for style in family.styles
)


def _sizes_of(key: str) -> list[int]:
    """Every size some canonical `FONTS` name starting `key/` compiles at,
    sorted -- what a bad-size warning lists for a real family-style."""
    return sorted({face.size for name, face in FONTS.items() if name.split("/", 1)[0] == key})


# The five legacy bare names (`FONT_ALIASES`' only entries with no `/`),
# derived rather than typed out a second time -- if the bare-alias set
# ever changed, this and unknown_font_message()'s bad-family message
# couldn't silently disagree with FONT_ALIASES about what they are.
_BARE_ALIASES: dict[str, str] = {
    alias: target for alias, target in FONT_ALIASES.items() if "/" not in alias
}


def _families_summary() -> str:
    """"petrona (also -bold, -italic), instrument (also -bold, -italic),
    karla (also -bold, -italic) and mono" -- every compiled family, with
    its non-regular styles named, joined the way a sentence would. Grows
    on its own as `FAMILIES` grows, so a future family needs no change
    here."""
    parts = []
    for family in FAMILIES.values():
        extra_styles = [style for style in family.styles if style]
        if extra_styles:
            named = ", ".join(f"-{style}" for style in extra_styles)
            parts.append(f"{family.name} (also {named})")
        else:
            parts.append(family.name)
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def unknown_font_message(name: str) -> str:
    """"unknown font '<name>'", plus which half is wrong (docs/plans/
    fonts-and-icons.md Decision 1, B1 review item 7): a bad *size* on a
    real family-style names that family-style's own compiled sizes, plus
    the five slot names and their pixel counts (`"karla/41": karla is
    compiled at 22 24 ... 84 (slots xs=22 sm=28 md=36 lg=48 xl=84)`) --
    the size half of a bad name is as likely to be a mistyped slot as a
    mistyped pixel count, and the slot table is the thing to check either
    way. A bad *family* -- or a name with no `/` at all, like a typo'd
    bare legacy name -- lists every compiled family and its styles, plus
    the five bare legacy names themselves (they're a common thing to
    almost get right: `"xl2"`, `"XL"`, `"extra-large"`). `Ctx.font()` and
    the bezel/off-canvas default lookup are the two callers; both already
    know `name` didn't resolve."""
    key = name.rsplit("/", 1)[0] if "/" in name else name
    if key in _FAMILY_STYLE_KEYS:
        sizes = " ".join(str(size) for size in _sizes_of(key))
        slots = " ".join(f"{slot}={px}" for slot, px in SLOTS.items())
        return f"unknown font {name!r}: {key} is compiled at {sizes} (slots {slots})"
    bare = " ".join(sorted(_BARE_ALIASES, key=lambda alias: SLOTS.get(alias, 0)))
    return (
        f"unknown font {name!r}: families are {_families_summary()}; "
        f"the bare names {bare} also work (Instrument Sans)"
    )


_FACE_GLYPHS: dict[str, frozenset[int]] = {
    name: GF_LATIN_CORE | frozenset(cp for r in face.extra_glyphs for cp in r)
    for name, face in FONTS.items()
}


def _font_path(font_dir: Path, file: str) -> Path:
    return Path(font_dir) / file


def load_font(font_dir: Path, face: Face) -> ImageFont.FreeTypeFont:
    """Load one compiled face (`FONTS[name]`). `face.variation` selects the
    variable font's named instance; `face.layout` picks Pillow's layout
    engine.

    Every proportional family here ships as a variable font: Pillow loads
    the file's own default instance unless a named instance is selected,
    and the wrong weight means text wraps in different places than the
    panel does -- so a bold face still asks for its name (`"Bold"`,
    `"ExtraBold"`, ...) by name, and `mono` (the one `"basic"`-layout face)
    still asks for its own instance every time, the same as before this
    table was generated.

    A face already at its file's own default instance does not (B1 review
    amendment; B3b re-review, item 2): Pillow's `set_variation_by_name()`
    is not byte-identical to leaving a variable font at its own default
    instance, even though both land on the same weight/width axis
    coordinates -- it shifted `sm` advance widths by a fraction of a pixel
    (`getlength("mustard")`: `107.96875` -> `107.984375`), enough to move
    text 38px over a long enough line (the swatch sheet's "mustard" label
    was the tell). Asking for the instance a file is already defaulted to
    buys nothing and risks exactly this, so it's only asked for when it
    would actually change something: `face.layout == "basic"`, or
    `face.variation` names something other than *this file's own* default
    instance -- read from the freshly opened `f.getname()[1]`, not the
    literal `"Regular"`, because the three `-Italic.ttf` files default to
    `"Italic"`: comparing against a hardcoded `"Regular"` was asking
    `set_variation_by_name("Italic")` on `instrument-italic`/`karla-italic`
    for no reason, the very call this guard exists to skip, and it
    measurably moved their advances 0.016-0.0625px off the static files
    Google Fonts serves the firmware.

    A `"basic"`-layout face (`mono`, the only one today) is loaded with
    `ImageFont.Layout.BASIC` instead of Pillow's default raqm layout:
    raqm turns `<>`/`->`/`!=` into single ligature glyphs and positions
    every glyph at a fractional advance (14.4px at 24px here), and at 1bpp
    that fractional advance opened a 1px gap in every box-drawing rule —
    the panel's own bitmap font does neither (docs/plans/dragon-feedback.md
    D11's second finding).

    The `set_variation_by_name` call, when made, is wrapped in its own
    try/except: a static face (nothing to select) raises and is left at
    whatever it already is, and so, silently, does a `variation` this
    particular file doesn't have -- a wrong `variation` is otherwise
    undetectable (metrics don't depend on which instance was actually
    selected), which is what `test_face_variation_exists_in_its_own_file`
    in tests/renderer/test_text.py guards instead.
    """
    path = _font_path(font_dir, face.file)
    if face.layout == "basic":
        f = ImageFont.truetype(str(path), face.size, layout_engine=ImageFont.Layout.BASIC)
    else:
        f = ImageFont.truetype(str(path), face.size)
    if face.layout == "basic" or face.variation != f.getname()[1]:
        try:
            f.set_variation_by_name(face.variation)
        except Exception:
            pass  # a static face (nothing to select), or this file has no such instance
    return f


def _load_fonts(font_dir: Path) -> dict[str, ImageFont.FreeTypeFont | None]:
    """Every compiled face, keyed by canonical name. An `optional` face
    (`mono`'s sizes, today) may come back `None`: its file is the one this
    repo doesn't ship pre-fetched, so a font directory that hasn't run
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
    filename (every family's regular and bold share one file; only the
    seven distinct files -- three families x upright/italic, plus mono --
    actually get checked), so this stays table-driven."""
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

    `face_name` is resolved through `resolve_font()` first, the same as
    every other font-name lookup in this package, so a bare/px/slot
    spelling of the same face is always judged against its one glyph set.

    `text` is what the op actually draws — after `fit_line`/`wrap_lines`
    has already trimmed it, so a character that would have been cut
    anyway is never reported — and a space or a literal `{`/`}` an
    unexpanded `fmt` field leaves behind is never counted as one, even
    though both are in GF_LATIN_CORE: a document's own template syntax
    isn't a font question. A no-op unless `ctx.warn_ink`.
    """
    if not ctx.warn_ink:
        return
    canonical = resolve_font(face_name)
    allowed = _FACE_GLYPHS.get(canonical) if canonical is not None else None
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


# The preview grid overlay's own face -- 22px Instrument Sans regular,
# chosen only to survive a client downscaling the grid overlay's PNG.
# Expressed through the generated table (docs/plans/fonts-and-icons.md
# Decision 3) rather than a hand-built Face, so it can never drift from
# what `instrument/xs` actually is.
GRID_FACE = FONTS["instrument/xs"]


def _measure_ink_height(f: ImageFont.FreeTypeFont) -> int:
    """Rows a full-height glyph (`█`) inks at 1bpp -- the pitch mono block
    art should stack by, not `cell_height` (ascent + descent, headroom no
    glyph actually fills). Shared by `_write_metrics()` and the metrics
    round-trip test in tests/renderer/test_text.py, so the two can never
    measure it two different ways."""
    from PIL import Image, ImageDraw

    size = f.size if isinstance(f.size, int) else int(f.size)
    img = Image.new("1", (size * 3, size * 3), 0)
    dr = ImageDraw.Draw(img)
    dr.text((size, size), "█", font=f, fill=1)
    px = img.load()
    w, h = img.size
    return sum(1 for y in range(h) if any(px[x, y] for x in range(w)))


def _write_metrics(
    font_dir: Path, out_path: Path = _METRICS_PATH
) -> dict[str, dict[str, int | None]]:
    """Measure `cell_height` (every face) and `ink_height` (mono sizes
    only) from the real font files in `font_dir`, and write them to
    `out_path` as `font_metrics.json` (Decision 3, docs/plans/
    fonts-and-icons.md) -- run via `display-mcp-cli font-metrics
    <font_dir>` (cli.py) after adding a family, a style or a size. Returns
    what it wrote, so a caller (the CLI subcommand, or a test) doesn't
    have to re-read the file to see it."""
    metrics: dict[str, dict[str, int | None]] = {}
    for name, face in FONTS.items():
        f = load_font(font_dir, face)
        ascent, descent = f.getmetrics()
        ink_height = _measure_ink_height(f) if face.family == "mono" else None
        metrics[name] = {"cell_height": ascent + descent, "ink_height": ink_height}
    out_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    return metrics
