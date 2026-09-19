"""swatch_document() / swatch_groups() -- docs/plans/ink-mixing.md's
closing coupon: every named colour as a chip, and the sheet is itself a
valid document.
"""

from __future__ import annotations

from typing import Any

from .canvas import BEZEL_MARGIN, HEIGHT
from .colour import BUILTIN_MIXES, COLORS, TIERS, Ctx, builtin_ink, hex_of, recipe_of
from .fonts import FONTS

_SWATCH_CHIP_W = 182  # px; fits the widest recipe string ("yellow+green 50")


_SWATCH_COLS = 6


def swatch_groups(
    palette: dict[str, Any] | None = None,
) -> list[tuple[str, list[tuple[str, str, str, str]]]]:
    """The chips `swatch_document()` lays out and `swatches` (the MCP tool)
    lists as text — one source for both, so the picture and its caption
    cannot disagree.

    Returns `[(group_title, [(label, c_field, recipe, hex), ...]), ...]`
    in the order docs/SPEC.md's "The named palette" groups them: `"inks"`,
    then the `dark`/`light`/`mid` tiers (`TIERS`). `c_field` is what an
    op's `c` must say to draw that chip's colour in `swatch_document()`'s
    own palette — a plain ink or built-in name for the first four groups,
    always the reserved `"sw:<name>"` form for a built-in mix so a
    document's own `palette` can never shadow it (SPEC.md: a document
    redefining a built-in "shadows" it).

    With `palette` (a document's own `palette` field), a final
    `"document palette"` group is appended: each entry's recipe and hex are
    resolved exactly the way `document_colors()` resolves them (`recipe_of`,
    the same `Ctx.resolve()` walk), `c_field` is the entry's own name, and
    an entry that doesn't resolve to anything drawable is left off rather
    than guessed at. Omitted (or empty), there is no fifth group. A palette
    key that is itself one of the reserved `"sw:<name>"` forms is also left
    off: `swatch_document()`'s `out_palette` always resolves that key to
    the built-in's own canonical mix (a collision, not a real entry), so
    listing whatever the document's *own* palette says at that name would
    show a recipe the sheet doesn't actually draw there.
    """
    groups: list[tuple[str, list[tuple[str, str, str, str]]]] = []

    groups.append(
        ("inks", [
            (name, name, recipe_of(builtin_ink(name)), hex_of(builtin_ink(name).avg))
            for name in COLORS
        ])
    )

    by_tier: dict[str, list[str]] = {"dark": [], "light": [], "mid": []}
    for name in BUILTIN_MIXES:
        by_tier[TIERS[name]].append(name)
    for tier in ("dark", "light", "mid"):
        entries = [
            (name, f"sw:{name}", recipe_of(builtin_ink(name)), hex_of(builtin_ink(name).avg))
            for name in by_tier[tier]
        ]
        groups.append((tier, entries))

    if palette:
        ctx = Ctx({"palette": palette}, load_fonts=False)
        entries = []
        for name in palette:
            if isinstance(name, str) and name.startswith("sw:"):
                continue
            resolved = ctx.resolve(name)
            if resolved is None:
                continue
            entries.append((name, name, recipe_of(resolved), hex_of(resolved.avg)))
        if entries:
            groups.append(("document palette", entries))

    return groups


def swatch_document(palette: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every ink and every built-in mix as a labelled chip, as an ordinary
    display-list document — publish it with `set_display` and every named
    colour this renderer knows sits on the wall with its name under it
    (docs/plans/ink-mixing.md, "Still open"'s closing-coupon bullet).

    Chips come from `swatch_groups(palette)`, `_SWATCH_COLS` (6) to a row.
    A chip is a filled rect outlined by a 1px black rule drawn just outside
    it (`x-1, y-1, w+2, h+2`), so the `white` chip reads against the white
    page and every chip reads the same uniform way; the outline is a plain
    `black` stroke, never contrast- or bezel-checked the way a chip's own
    fill is. Its name, recipe and hex sit in three lines of `sm`/`xs` text
    on the white page underneath — never on the chip itself, where a light
    or mid-tone fill would trip the contrast floor `check()` enforces for
    every chip's own tier. Each line is its own plain `text` op with an
    explicit `y`, not a wrapped one: the firmware computes line height from
    the font it actually loaded, not the `round(px * 1.24)` estimate a
    wrapped op's default `lh` uses, so two lines stacked by hand here can
    never disagree with what the panel measures.

    The four built-in groups (`"inks"`, `"dark"`, `"light"`, `"mid"`) are
    fixed in size and always fit inside `HEIGHT - BEZEL_MARGIN`. A caller's
    own `palette` is not: the appended `"document palette"` group lays out
    only as many rows as still fit, and if any entries are left over, one
    final `xs` line reads `"+N more not shown"` at the row position the
    next row would have used — itself checked to fit before it is emitted.

    `out_palette` gives every reserved `"sw:<name>"` key priority over a
    same-named entry in `palette`, so a document whose own palette happens
    to define e.g. `"sw:navy"` still gets navy's canonical chip rather than
    having it silently redrawn as whatever that entry says (`swatch_groups`
    leaves that colliding entry out of the "document palette" listing for
    the same reason). Passing this document to `validate` will list those
    reserved `sw:<name>` keys in its `colors` — expected, since they are
    ordinary palette entries once this document leaves this function.
    """
    margin = 26
    chip_w, chip_h = _SWATCH_CHIP_W, 80
    gap_x = 10
    chip_gap, line_gap = 6, 2
    name_lh = FONTS["sm"].line_height
    xs_lh = FONTS["xs"].line_height
    row_gap = 8
    heading_lh, heading_gap = FONTS["xs"].line_height, 6
    # Roughly doubles the gap before a heading (row_gap, already left after
    # the previous group's last row) so it reads as belonging to the chips
    # below it rather than the group above.
    heading_extra_gap = row_gap
    row_height = chip_h + chip_gap + name_lh + line_gap + xs_lh + line_gap + xs_lh + row_gap
    col_x = [margin + i * (chip_w + gap_x) for i in range(_SWATCH_COLS)]

    groups = swatch_groups(palette)

    reserved = {
        f"sw:{name}": {"c": c, "c2": c2, "mix": m} for name, (c, c2, m) in BUILTIN_MIXES.items()
    }
    out_palette: dict[str, Any] = {**(palette or {}), **reserved}

    ops: list[dict[str, Any]] = []
    y = margin

    def emit_row(row: list[tuple[str, str, str, str]], top: int) -> None:
        for (label, c_field, recipe, hexs), x in zip(row, col_x, strict=False):
            ops.append({"op": "rect", "x": x, "y": top, "w": chip_w, "h": chip_h, "c": c_field})
            ops.append(
                {
                    "op": "rect",
                    "x": x - 1,
                    "y": top - 1,
                    "w": chip_w + 2,
                    "h": chip_h + 2,
                    "c": "black",
                    "fill": False,
                    "t": 1,
                }
            )
            name_y = top + chip_h + chip_gap
            ops.append(
                {"op": "text", "x": x, "y": name_y, "s": label, "f": "sm", "c": "black",
                 "w": chip_w - 4}
            )
            recipe_y = name_y + name_lh + line_gap
            ops.append(
                {"op": "text", "x": x, "y": recipe_y, "s": recipe, "f": "xs", "c": "black",
                 "w": chip_w - 4}
            )
            hex_y = recipe_y + xs_lh + line_gap
            ops.append(
                {"op": "text", "x": x, "y": hex_y, "s": hexs, "f": "xs", "c": "black",
                 "w": chip_w - 4}
            )

    for gi, (title, entries) in enumerate(groups):
        if gi > 0:
            y += heading_extra_gap
        ops.append({"op": "text", "x": margin, "y": y, "s": title, "f": "xs", "c": "black"})
        y += heading_lh + heading_gap

        if title == "document palette":
            # The only group whose size isn't fixed: lay out only the
            # rows that fit, reserving room for the "+N more" line itself
            # so it's never the thing that ends up off-canvas.
            avail = HEIGHT - BEZEL_MARGIN - y
            rows_needed = -(-len(entries) // _SWATCH_COLS)  # ceil
            if rows_needed * row_height <= avail:
                rows_fit = rows_needed
            else:
                rows_fit = max(0, (avail - xs_lh) // row_height)
            shown = entries[: rows_fit * _SWATCH_COLS]
            hidden = len(entries) - len(shown)
        else:
            shown, hidden = entries, 0

        for row_start in range(0, len(shown), _SWATCH_COLS):
            emit_row(shown[row_start : row_start + _SWATCH_COLS], y)
            y += row_height

        if hidden:
            ops.append(
                {"op": "text", "x": margin, "y": y, "s": f"+{hidden} more not shown", "f": "xs",
                 "c": "black"}
            )

    return {"v": 1, "bg": "white", "palette": out_palette, "ops": ops}
