"""Colour: the six inks, the built-in mixes, the Bayer dither mask, Ink and
Ctx (palette alias/mix resolution), document_colors(), and the four
check()-only ink-mixing authoring warnings (contrast floor, mix-as-text,
thin mix, drew-nothing) -- docs/plans/ink-mixing.md. These four live beside
Ctx/Ink/mix_on rather than in a separate checks.py because every one of
them is fundamentally about colour physics (luminance, fused ground,
mix density), not about glyphs or geometry, and they read Ctx's own state
(`ctx.warn_ink`, `ctx.problems`, `ctx.table`) directly.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, NamedTuple

from PIL import Image

from .fonts import FONTS, _load_fonts

WIDTH, HEIGHT = 1200, 1600

COLORS = ("black", "white", "yellow", "red", "blue", "green")


INK = {
    "black": (32, 32, 32),
    "white": (222, 222, 216),
    "yellow": (206, 172, 44),
    "red": (156, 46, 42),
    "blue": (46, 62, 128),
    "green": (72, 108, 66),
}


_BAYER2 = ((0, 2), (3, 1))


DENSITIES = (25, 50, 75)


BUILTIN_MIXES: dict[str, tuple[str, str, int]] = {
    "navy": ("black", "blue", 50),
    "maroon": ("black", "red", 50),
    "plum": ("red", "blue", 50),
    "forest": ("black", "green", 50),
    "teal": ("blue", "green", 50),
    "brown": ("red", "green", 50),
    "grey-dark": ("black", "white", 25),
    "cream-pale": ("yellow", "white", 75),
    "cream": ("yellow", "white", 50),
    "sage-pale": ("green", "white", 75),
    "slate-pale": ("blue", "white", 75),
    "pink-pale": ("red", "white", 75),
    "grey-light": ("black", "white", 75),
    "sage": ("green", "white", 50),
    "pink": ("red", "white", 50),
    "slate": ("blue", "white", 50),
    "chartreuse": ("yellow", "green", 50),
    "grey-mid": ("black", "white", 50),
    "mustard": ("black", "yellow", 50),
    "orange": ("yellow", "red", 50),
    "olive": ("yellow", "blue", 50),
}


TIERS: dict[str, str] = {
    "navy": "dark",
    "teal": "dark",
    "maroon": "dark",
    "plum": "dark",
    "brown": "dark",
    "forest": "dark",
    "grey-dark": "dark",
    "cream": "light",
    "cream-pale": "light",
    "sage": "light",
    "sage-pale": "light",
    "slate": "light",
    "slate-pale": "light",
    "pink": "light",
    "pink-pale": "light",
    "chartreuse": "light",
    "grey-light": "light",
    "grey-mid": "mid",
    "mustard": "mid",
    "orange": "mid",
    "olive": "mid",
}


def mix_on(x: int, y: int, pct: int) -> bool:
    """True where the *second* ink of a mix goes.

    Phase is absolute — canvas coordinates, not the op's origin — so abutting
    fills tile without a seam and a knockout lands exactly on the mix beneath
    it. At pct=50 the matrix selects cells 0 and 1, which sit at (0,0) and
    (1,1), i.e. precisely `(x + y) % 2 == 0`: the test tone's knockout has
    always used. Existing documents therefore render unchanged.
    """
    return _BAYER2[y & 1][x & 1] < pct // 25


class Ink(NamedTuple):
    """A resolved colour: two inks and the percentage of `b` among them.

    A plain colour is `Ink(c, c, 100)`, so callers never branch on whether
    something is a mix — the solid case is a mix with nothing to interleave.
    """

    a: tuple
    b: tuple
    mix: int

    @property
    def solid(self) -> bool:
        return self.a == self.b

    @property
    def avg(self) -> tuple:
        """The single colour this mix averages to over a large enough area.

        What the eye integrates a dithered fill into, and what the panel's
        glass actually shows for anything bigger than a few pixels. For a
        solid ink `mix` is 100 and `a == b`, so this returns that ink
        unchanged and needs no special case.

        This is the colour `render(dithered_colors=False)` paints, and it
        reproduces every hex in the named-palette table in docs/SPEC.md
        exactly — tests/render/test_colour.py pins that, so the table
        cannot drift away from the renderer.

        It is honest for a fill and optimistic for a glyph: a few pixels of
        stroke cannot average two inks, so text reads shifted toward the
        lighter one. That gap is what _check_mix_as_text() warns about, and
        it is why a flat preview has to carry its warnings with it.
        """
        w = self.mix / 100
        return tuple(round(self.a[i] * (1 - w) + self.b[i] * w) for i in range(3))


def _luminance(rgb: tuple) -> float:
    """WCAG relative luminance of an (r, g, b) triple, channels 0-255."""

    def lin(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast_ratio(rgb_a: tuple, rgb_b: tuple) -> float:
    """WCAG contrast ratio between two colours; always >= 1."""
    la, lb = _luminance(rgb_a), _luminance(rgb_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _clip_to_canvas(box: tuple) -> tuple | None:
    """Clip a box to the canvas as ints. None when there is no on-canvas
    area at all — an op drawn off-screen, a zero-size box (an empty
    string) — so callers skip rather than warn on those, per the
    false-positive list in the ink-mixing plan."""
    x0, y0, x1, y1 = box
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(WIDTH, int(x1)), min(HEIGHT, int(y1))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _grounds(img: Image.Image, box: tuple) -> list[tuple[tuple[float, ...], Counter]] | None:
    """The ground colour(s) under `box`, sampled at the scale the eye fuses at.

    A dither is two inks a pixel apart and fuses into one colour at reading
    distance; two regions side by side do not. So the sample is taken per
    2x2 mask tile — the mask's whole period (decision 2), 0.34 mm on the
    glass — averaging each tile into the colour it fuses to, and then taking
    the tile colour covering most of the box. Tiles align to the mask's own
    absolute phase, so a mixed fill sampled anywhere yields whole periods.

    That is `most_common` as it was always meant to work; what was wrong
    before was the scale, not the idea. Sampled per pixel, a 50% mix is two
    colours tied 50/50 and the tie-break decided whether white text on
    `grey-mid` scored 12.06:1 or 1.00:1. Sampled per tile there is no tie to
    break: every tile of that mix is the same fused grey. Sampling the
    canvas rather than reading the ink also means the density is whatever
    was really painted, parity trap (decision 2) included.

    When tile colours genuinely tie — a box sitting half on one rect and
    half on another — every tied colour comes back rather than one of them,
    so the caller can judge against the harder half instead of flipping a
    coin. Each comes with the tally of the inks behind it, because a fused
    colour is generally not an ink and the warning still has to name what is
    behind the text.

    None when the box has no on-canvas area at all — an op drawn off-screen,
    a zero-size box (an empty string) — so callers skip rather than warn on
    those, per the false-positive list in the ink-mixing plan.
    """
    clipped = _clip_to_canvas(box)
    if clipped is None:
        return None
    x0, y0, x1, y1 = clipped
    px = img.load()
    tiles: Counter = Counter()
    inks: dict[tuple, Counter] = {}
    for ty in range(y0 - (y0 % 2), y1, 2):
        for tx in range(x0 - (x0 % 2), x1, 2):
            cell = Counter(
                px[x, y]
                for y in range(max(ty, y0), min(ty + 2, y1))
                for x in range(max(tx, x0), min(tx + 2, x1))
            )
            n = sum(cell.values())
            fused = tuple(sum(c[i] * k for c, k in cell.items()) / n for i in range(3))
            tiles[fused] += n
            inks.setdefault(fused, Counter()).update(cell)
    most = max(tiles.values())
    return [(fused, inks[fused]) for fused, n in tiles.items() if n == most]


# The report's whole "mixes don't render" section, in one sentence: `c2`
# and `mix` are fields of a *palette entry*, not of an op, and a `c` that
# is an object instead of a name is the same mistake written inline. Both
# get this exact message (docs/plans/dragon-feedback.md, D1). Lives here
# rather than in __init__.py's `_op_field_problems` (which also uses it)
# because the message is Ctx.ink()/Ctx._mix()'s own, and __init__.py
# imports it from here instead of the other way round.
_MIX_HINT = (
    'mixes are palette entries — write palette: {name: {c, c2, mix}} and '
    'c: name (docs/SPEC.md "Mixes")'
)


class Ctx:
    def __init__(
        self,
        doc: dict[str, Any],
        font_dir: Path | None = None,
        warn_ink: bool = False,
        load_fonts: bool | None = None,
    ):
        # The contract, made explicit rather than left to `Path(None)`
        # raising a bare TypeError: no `font_dir` means no fonts by
        # default (`Ctx(doc)` is a valid colour-only context), but asking
        # to load fonts with nothing to load them from is a caller error,
        # not a silent no-op.
        if load_fonts is None:
            load_fonts = font_dir is not None
        elif load_fonts and font_dir is None:
            raise ValueError("load_fonts needs a font_dir")
        palette = doc.get("palette") or {}
        self.problems: list[str] = []
        if not isinstance(palette, dict):
            # Never raise from a shape the JSON allows: a palette that is
            # not an object is ignored, with a problem, and every name then
            # resolves as if the document had none.
            self.problems.append(f"palette: must be an object, not {type(palette).__name__}")
            palette = {}
        self.palette = palette
        self.table = INK
        self.table_rev = {v: k for k, v in self.table.items()}
        # `load_fonts=False` skips the (comparatively expensive) face load
        # for callers that only resolve colours — document_colors() is the
        # one today — and never touch a font. `font_dir` is then unused and
        # may be omitted.
        self.fonts = _load_fonts(Path(font_dir)) if load_fonts else {}
        # The three ink-mixing authoring warnings (contrast floor, chromatic
        # mix as text, sub-2px density) are check()-only, the same way
        # bezel_problems() is check()-only — render() on its own reports
        # only what stops a document from drawing correctly. Gated so a bare
        # render() call is unaffected.
        self.warn_ink = warn_ink

    def name_of(self, rgb: tuple) -> str:
        """Reverse-lookup a raw canvas pixel to its ink name. Every pixel a
        *dithered* render paints is one of the six table entries verbatim —
        a mix interleaves two solid inks, it never averages them on canvas —
        so this always resolves for real pixels.

        `render(dithered_colors=False)` does paint blends, which have no ink
        name. It cannot reach here: every caller is behind `warn_ink`, and
        render() rejects `warn_ink` on a flat canvas for exactly this
        reason. The `"ink"` fallback is therefore unreachable, and kept only
        so a stray colour degrades a message rather than raising."""
        return self.table_rev.get(rgb, "ink")

    def ground_name(self, counts: Counter) -> str:
        """Name a sampled ground for a warning message: a solid one by its
        ink name, a dithered one as `black+white`. Ordered by how much of
        the ground each ink covers, darker ink first on a tie, so a 50/50
        mix is always named the same way round."""
        inks = sorted(counts, key=lambda c: (-counts[c], _luminance(c)))
        return "+".join(self.name_of(c) for c in inks)

    def ink(self, name: str, where: str = "") -> Ink:
        """Resolve a colour name to an Ink, following palette aliases.

        Mirrors resolve_ink() in display_list.h. Every malformed case warns
        and still yields something drawable; nothing here skips an op.

        `name` is meant to be a string; a document that writes an inline
        `{c, c2, mix}` object where a colour *name* belongs is caught before
        the table lookup, since a dict can't be looked up in `self.table`: a
        dict gets the same palette hint `c2`/`mix`-on-an-op gets
        (docs/plans/dragon-feedback.md D1), and anything else non-string
        falls back to the ordinary "unknown colour" message. Either way this
        returns black rather than raising. Everything else is `resolve()`'s
        walk, wrapped: black in place of the `None` a name that never
        resolves gets there.
        """
        black = self.table["black"]
        if isinstance(name, dict):
            self.problems.append(f"{where}: {_MIX_HINT}")
            return Ink(black, black, 100)
        if not isinstance(name, str):
            self.problems.append(f"{where}: unknown colour {name!r}")
            return Ink(black, black, 100)
        resolved = self.resolve(name, where)
        return resolved if resolved is not None else Ink(black, black, 100)

    def resolve(self, name: str, where: str = "") -> Ink | None:
        """The alias/mix/built-in walk, `None` where `ink()` falls back to
        black: base inks -> the document's palette -> the built-in mixes,
        so the six ink names are immutable and a document can shadow a
        built-in one by declaring it. A palette entry that is itself a mix
        definition (a `dict`) is handed to `_mix()` for real — a malformed
        one still warns and still resolves to something drawable, same as
        it always has; `_base` stays separate; it walks with different
        degrade rules for a name found *inside* a mix (D9/D1), not "does
        this name resolve at all".

        `ink()` wraps this for a caller that always wants something
        drawable back. `document_colors()` and `swatch_groups()` call it
        directly (folded from the old module-level `_color_name_resolves()`)
        so a name that merely warns about something else along the way
        (a malformed mix, still resolvable) isn't confused with one that
        never resolves.

        Mirrors `resolve_ink()` in display_list.h and the alias-chasing
        limit in `_base()` (8 hops).
        """
        n = name
        for _ in range(8):
            if not isinstance(n, str):
                break  # an alias that lands on a list/number: unknown, below
            if n in self.table:
                return Ink(self.table[n], self.table[n], 100)
            entry = self.palette.get(n)
            if entry is None:
                builtin = BUILTIN_MIXES.get(n)
                if builtin is None:
                    break
                a, b, m = builtin
                return Ink(self.table[a], self.table[b], m)
            if isinstance(entry, dict):
                return self._mix(entry, n, where)
            n = entry
        self.problems.append(f"{where}: unknown colour {n!r}")
        return None

    def _mix(self, entry: dict[str, Any], name: str, where: str) -> Ink:
        black = self.table["black"]
        c, c2 = entry.get("c"), entry.get("c2")
        if not isinstance(c, str):
            self.problems.append(f"{where}: mix {name!r} has no 'c'; using black")
            return Ink(black, black, 100)
        a = self._base(c, where)
        if not isinstance(c2, str):
            self.problems.append(f"{where}: mix {name!r} has no 'c2'; drawing solid")
            return Ink(a, a, 100)
        b = self._base(c2, where)
        if a == b:
            self.problems.append(f"{where}: mix {name!r} has c2 == c; drawing solid")
            return Ink(a, a, 100)
        return Ink(a, b, self._density(entry.get("mix"), name, where))

    def _base(self, name: str, where: str) -> tuple:
        """One ink. A mix inside a mix isn't representable in a 2x2 mask, so
        a nested one warns and contributes only its own base colour."""
        n = name
        for _ in range(8):
            if not isinstance(n, str):
                break
            if n in self.table:
                return self.table[n]
            entry = self.palette.get(n)
            if entry is None:
                builtin = BUILTIN_MIXES.get(n)
                if builtin is None:
                    break
                self.problems.append(
                    f"{where}: {n!r} is a built-in mix, not a plain colour here; "
                    "using its base ink"
                )
                n = builtin[0]
                continue
            if isinstance(entry, dict):
                self.problems.append(
                    f"{where}: {n!r} is a mix and mixes cannot nest; using its 'c'"
                )
                n = entry.get("c")
                if not isinstance(n, str):
                    break
                continue
            n = entry
        self.problems.append(f"{where}: unknown colour {n!r}")
        return self.table["black"]

    def _density(self, raw: Any, name: str, where: str) -> int:
        if raw is None:
            return 50
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not 0 <= raw <= 100:
            self.problems.append(f"{where}: mix {name!r} has mix={raw!r}; using 50")
            return 50
        pct = min(DENSITIES, key=lambda v: (abs(v - raw), v))
        if pct != raw:
            self.problems.append(
                f"{where}: mix {name!r} has mix={raw}, rounded to {pct} (25/50/75 only)"
            )
        return pct

    def font(self, name: str, where: str = ""):
        """Resolve a font name, or None when it isn't compiled in or isn't
        installed here.

        Mirrors the firmware's `assets.fonts.find()` miss: `text` and `fmt`
        both `skipped++; continue` there rather than draw with a substitute
        face, so a caller returning None here must abandon the op the same
        way rather than fall back to `md` — a fallback would draw in the
        preview something the panel never puts on the wall.

        `mono` is the one face `_load_fonts` may have stored as `None` (its
        file missing rather than the font directory itself): that is a
        second, distinct kind of "no font here" from an unknown *name*, so
        it gets its own message naming the file to fetch rather than the
        generic "unknown font" one.
        """
        if name not in self.fonts:
            self.problems.append(f"{where}: unknown font {name!r}")
            return None
        f = self.fonts[name]
        if f is None:
            self.problems.append(
                f"{where}: font {name!r} is not installed here "
                f"(fonts/{FONTS[name].file}); skipped"
            )
            return None
        return f


def hex_of(rgb: tuple) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def builtin_ink(name: str) -> Ink:
    """The `Ink` a bare, document-free name resolves to: one of the six
    base inks, or one of the built-in mixes (`BUILTIN_MIXES`) — the one
    table lookup `vocabulary()` and `swatch_groups()` both need for a name
    that is never resolved against a document's own palette (that walk is
    `Ctx.ink()`'s job, for a name that might be a palette alias). Raises
    `KeyError` for anything else; both callers only ever pass a name
    straight out of `INK` or `BUILTIN_MIXES`'s own keys."""
    if name in INK:
        return Ink(INK[name], INK[name], 100)
    c, c2, mix = BUILTIN_MIXES[name]
    return Ink(INK[c], INK[c2], mix)


_INK_NAMES: dict[tuple, str] = {v: k for k, v in INK.items()}


def recipe_of(ink: Ink) -> str:
    """`"ink"` for a base ink, `"<a>+<b> <mix>"` for a mix — the one recipe
    formatter every caller that reports a resolved colour uses
    (`document_colors()`, `swatch_groups()`, `vocabulary()`), so a name's
    recipe reads the same way wherever it is shown. `_INK_NAMES` always
    resolves for a real `Ink`'s components — they come from `INK` itself,
    directly or through `Ctx.ink()`'s alias walk — so the `"ink"` fallback
    here is defensive, not a path anything today can reach."""
    if ink.solid:
        return "ink"
    return f"{_INK_NAMES.get(ink.a, 'ink')}+{_INK_NAMES.get(ink.b, 'ink')} {ink.mix}"


def document_colors(doc: dict[str, Any]) -> tuple[dict[str, dict[str, str]], list[str]]:
    """The effective colour of every name a document references, and the
    problems resolving them turned up along the way.

    `bg`, each op's `c` (and, `icon` ops only — `bgc` is a field of no
    other op, and writing it on one already earns its own "no such field"
    from `_op_field_problems`), every string value in a `sprite` op's own
    `palette` (a sprite has no `c` of its own — its colours are entirely
    there), and every document `palette` key, each mapped to
    `{"recipe": ..., "hex": ...}` — `"ink"` for a base ink, `"<a>+<b>
    <mix>"` for a mix (built-in or from the document's own palette), and an
    alias's own recipe when a name points at one. `hex` is `Ink.avg`, the
    same colour `render(dithered_colors=False)` paints, so this cannot say
    something `preview` disagrees with.

    The second element is every problem resolution raised, `where`d
    `"palette '<name>'"` — so it reads as this function's own finding, not
    an op's — including for a palette entry nothing in `ops` ever points
    at (a malformed one `check()` has no reason to visit, since it only
    resolves names an op actually references). `validate` merges these
    into its `warnings`, deduping against what `check()` already reported
    for the same name.

    Resolution never touches fonts (`Ctx(..., load_fonts=False)`), so this
    is cheap enough to call on every `validate()`. It never raises: a
    document that isn't a dict, has no `ops` list, or has a non-dict
    `palette` simply yields fewer entries — the same tolerance `Ctx`
    already has for each of those shapes. A colour value that isn't a
    string is skipped, matching what `Ctx.ink()` does for one it meets
    while rendering. A name that doesn't resolve at all is left out of
    `colors` (same as today's "unknown colour" warning from `check()`),
    but still contributes the problem that says so.
    """
    if not isinstance(doc, dict):
        return {}, []
    ctx = Ctx(doc, load_fonts=False)

    order: dict[str, None] = {}

    def add(value: Any) -> None:
        if isinstance(value, str):
            order.setdefault(value, None)

    add(doc.get("bg", "white"))
    ops = doc.get("ops")
    if isinstance(ops, list):
        for op in ops:
            if isinstance(op, dict):
                add(op.get("c"))
                if op.get("op") == "icon":
                    add(op.get("bgc"))
                if op.get("op") == "sprite" and isinstance(op.get("palette"), dict):
                    for value in op["palette"].values():
                        add(value)
    for key in ctx.palette:
        add(key)

    colors: dict[str, dict[str, str]] = {}
    for name in order:
        where = f"palette {name!r}"
        resolved = ctx.resolve(name, where)
        if resolved is None:
            continue
        colors[name] = {"recipe": recipe_of(resolved), "hex": hex_of(resolved.avg)}
    return colors, ctx.problems


def _check_contrast(img, ctx: Ctx, ink: Ink, fg_name: str, where: str, boxes: list[tuple]) -> None:
    """Warning: 3:1 contrast floor for text/fmt/icon against what is actually
    behind it (docs/plans/ink-mixing.md decision 4).

    The ground is sampled from the real canvas *before* this op draws, so a
    rect, a mixed fill or the page bg are all handled the same way. All five
    compiled font sizes are WCAG "large text", so one floor covers every
    size. `boxes` lets a wrapped text block check each line's own ground;
    the worst line is what gets reported. A no-op unless `ctx.warn_ink`
    (set by check(), not by a bare render() call -- see Ctx.__init__).

    A dithered glyph is legible if *either* of its two inks stands out from
    the ground — the contrasting pixels alone draw the letterform — so the
    effective contrast of a mixed ink is `max(contrast(a, ground),
    contrast(b, ground))`, not the contrast of their blend. Solid ink is
    unaffected: `max` over two identical colours is just that colour's
    contrast.

    The ground is measured the other way round, as the single colour it
    fuses to (`_grounds`). The two sides are asymmetric because the physics
    is: "a large fill averages the two; a 3 px stem has too few pixels to
    average" (decision 3). `max` on the ground as well would pass nearly
    anything — one lucky pairing out of four would carry the op — and in
    particular it would pass the one mixed-ground case the wall has judged,
    red/white 50 on pink, which is poor precisely because the letterform
    fuses to the colour the ground fuses to even though every pixel of it
    differs from the pixel beneath.
    """
    if not ctx.warn_ink:
        return
    worst = None
    for box in boxes:
        grounds = _grounds(img, box)
        if grounds is None:
            continue
        for bg, counts in grounds:
            ratio = max(_contrast_ratio(ink.a, bg), _contrast_ratio(ink.b, bg))
            if worst is None or ratio < worst[0]:
                worst = (ratio, counts)
    if worst is None:
        return
    ratio, counts = worst
    if ratio < 3.0:
        # Floored, not rounded, so a ratio just under the floor cannot print
        # as "3.0:1 (below 3:1)" — white on `grey-mid` is 2.95 and does.
        shown = int(ratio * 10) / 10
        ctx.problems.append(
            f"{where}: {fg_name} on {ctx.ground_name(counts)} is {shown:.1f}:1 "
            "(below 3:1) — will be hard to read"
        )


def _union_box(boxes: list[tuple]) -> tuple:
    """The smallest box containing every box in `boxes` — a wrapped text
    block's lines land at different y (and, centred/right-aligned, x)
    positions, so the op's own bounding box for the drew-nothing check is
    their union, not any single line's."""
    xs0, ys0, xs1, ys1 = zip(*boxes, strict=True)
    return min(xs0), min(ys0), max(xs1), max(ys1)


def _snapshot(img: Image.Image, box: tuple) -> tuple | None:
    """Crop `img` to `box` (clipped to the canvas) for a before/after diff.

    Returns `(clipped_box, pixel bytes)`, or None when the box has no
    on-canvas area — same skip rule as `_grounds`, and for the same
    reason: an off-screen op drawing nothing is not interesting.
    """
    clipped = _clip_to_canvas(box)
    if clipped is None:
        return None
    return clipped, img.crop(clipped).tobytes()


def _check_drew_nothing(img: Image.Image, ctx: Ctx, before: tuple | None, where: str) -> None:
    """Warning: the op changed not one pixel inside its own box
    (docs/plans/ink-mixing.md, "What the glass showed" / the contrast-check
    limitation this replaces).

    Contrast measures marginal legibility and cannot see absolute
    invisibility: text drawn over a ground that is a mix of the same two
    inks becomes pixel-identical to its background and vanishes completely,
    while still scoring a comfortable contrast ratio. Rather than model
    that, observe it — snapshot the op's box before drawing, draw, and diff.
    A no-op unless `ctx.warn_ink`, or when the op had no on-canvas area to
    begin with (`before` is None).
    """
    if not ctx.warn_ink or before is None:
        return
    clipped, before_bytes = before
    if img.crop(clipped).tobytes() == before_bytes:
        ctx.problems.append(
            f"{where}: drew nothing visible — every pixel in its box already "
            "matched what is behind it"
        )


def _check_mix_as_text(ctx: Ctx, ink: Ink, name: str, where: str) -> None:
    """Warning: a chromatic mix used as text shifts toward its lighter ink
    (docs/plans/ink-mixing.md decision 3).

    A fill has enough pixels to average two inks; a glyph does not, so the
    brighter ink dominates and the blend reads lighter than the swatch of
    the same mix. Achromatic (black+white) is exempt — there is no hue to
    lose, and the lightening is the point (it is what the shipping footer
    stamp already relies on). A no-op unless `ctx.warn_ink`.
    """
    if not ctx.warn_ink:
        return
    if ink.solid:
        return
    black, white = ctx.table["black"], ctx.table["white"]
    if {ink.a, ink.b} == {black, white}:
        return
    gap = abs(_luminance(ink.a) - _luminance(ink.b))
    if gap > 0.2:
        a_name, b_name = ctx.name_of(ink.a), ctx.name_of(ink.b)
        lighter = a_name if _luminance(ink.a) > _luminance(ink.b) else b_name
        ctx.problems.append(
            f"{where}: {name!r} mixes {a_name}+{b_name} (luminance gap "
            f"{gap:.2f}) — as text it will read shifted toward {lighter}, "
            "not the blend a fill of the same mix would show"
        )


_PARITY_OUTCOME = {25: "0% or 50%", 75: "50% or 100%"}


def _check_thin_mix(ctx: Ctx, ink: Ink, where: str, feature: str, **dims) -> None:
    """Warning: a feature thinner than 2 px cannot carry 25%/75%
    (docs/plans/ink-mixing.md decision 2).

    The mask is 2x2, so a one-pixel-wide run samples a single row or column
    of it and lands on 0/50/100% depending on which row or column that is —
    only 50% is parity-independent. `feature` is one of "line", "outline"
    (a rect drawn with fill: false) or "fill" (a filled rect too thin in one
    dimension); `dims` carries the measurements to report. A no-op unless
    `ctx.warn_ink`.
    """
    if not ctx.warn_ink:
        return
    if ink.solid or ink.mix not in _PARITY_OUTCOME:
        return
    outcome = _PARITY_OUTCOME[ink.mix]
    if feature in ("line", "outline"):
        t = dims["t"]
        if t >= 2:
            return
        noun = "line" if feature == "line" else "rect outline"
        ctx.problems.append(
            f"{where}: {ink.mix}% mix on a {t}px {noun} renders at {outcome}, "
            f"not {ink.mix}%, and which one depends on the op's coordinate "
            "parity"
        )
    else:
        w, h = dims["w"], dims["h"]
        if w >= 2 and h >= 2:
            return
        ctx.problems.append(
            f"{where}: {ink.mix}% mix on a {w}x{h} fill is too thin to carry "
            f"the density — renders at {outcome} depending on the op's "
            "coordinate parity"
        )
