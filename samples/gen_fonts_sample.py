"""Generate samples/fonts.json -- the type specimen: every family-style at
`md`, Petrona at every compiled size, the five bare legacy names, mono, the
two decorations, and the five slots in Karla. Run from the repo root with
`DISPLAY_MCP_FONT_DIR=./fonts .venv/bin/python samples/gen_fonts_sample.py`
and then `display-mcp-cli stamp samples/fonts.json` whenever the vocabulary
changes; the scaffold test checks the sample still names every family-style
and every size."""

import json

from display_mcp.render import FONTS, SIZES, resolve_font
from display_mcp.render.fonts import FAMILIES

ops = []


def text(x, y, s, f, **kw):
    ops.append({"op": "text", "x": x, "y": y, "s": s, "f": f, **kw})


# header
ops.append({"op": "rect", "x": 0, "y": 0, "w": 1200, "h": 196, "c": "navy"})
text(48, 36, "Type specimen", "petrona-bold/xl", c="white")
text(52, 140, "Every family and style the panel compiles", "petrona-italic/40", c="white")

# left column: ten family-styles, one specimen each at md
y = 228
family_styles = [(fam, style) for fam, family in FAMILIES.items() for style in family.styles]
for fam, style in family_styles:
    key = fam if not style else f"{fam}-{style}"
    face = FONTS[resolve_font(f"{key}/md")] if key != "mono" else FONTS["mono/24"]
    label = f"{key}/md · {face.weight}" if key != "mono" else "mono/24 · 400"
    text(48, y, label, "karla-bold/xs", c="grey-mid")
    if key == "mono":
        text(48, y + 30, "Hamburgefonstiv 0123", "mono/24", w=580)
        text(48, y + 62, "┌──┬──┐ █▓▒░ <> -> ligature-free", "mono/24", w=580)
    else:
        text(48, y + 30, "Hamburgefonstiv 0123 — Ág", f"{key}/md", w=580)
    y += 96

# right column: the size ladder in petrona
X = 690
text(X, 228, "size ladder · petrona at every compiled size", "karla-bold/xs", c="grey-mid")
y = 258
for px in SIZES[:-1]:  # 22..54; 84 is the day-name size, shown in the header
    text(X, y, f"Aa {px} px", f"petrona/{px}", w=460)
    y += round(px * 1.24)
# bare legacy names
y += 24
text(X, y, "bare names · Instrument Sans, unchanged", "karla-bold/xs", c="grey-mid", w=460)
y += 30
for bare, px in (("xl", 84), ("lg", 48), ("md", 36), ("sm", 28), ("xs", 22)):
    text(X, y, bare, bare)
    text(
        X + 120,
        y + max(0, (px - 28) // 2),
        f"= {resolve_font(bare)}",
        "karla/sm",
        c="grey-mid",
        w=340,
    )
    y += round(px * 1.24)
# decorations and a mixed ink
y += 30
text(X, y, "deco · text only", "karla-bold/xs", c="grey-mid")
y += 30
text(X, y, "underline a phrase", "karla/md", deco="underline")
y += 50
text(X, y, "strike a done to-do", "karla/md", deco="strike", c="grey-mid")
y += 50
text(X, y, "navy holds as type", "petrona-italic/sm", c="navy", w=460)
right_end = y + 35

# the five slots, bottom-left, in karla (xl is the header's size)
y = 1224
text(
    48,
    y,
    "the five slots · karla; a pixel count spells the same face",
    "karla-bold/xs",
    c="grey-mid",
    w=580,
)
y += 30
for slot, px in (("xs", 22), ("sm", 28), ("md", 36), ("lg", 48)):
    text(48, y, f"karla/{slot} is karla/{px}", f"karla/{slot}", w=580)
    y += round(px * 1.24)
text(48, y, "xl is 84 px: the day name in the header", "karla/sm", c="grey-mid", w=580)

# footer, as the other samples
ops.append({"op": "line", "x": 48, "y": 1528, "x2": 1152, "y2": 1528, "c": "grey-light", "t": 2})
text(48, 1546, "samples/fonts.json", "karla/xs", c="grey-mid")
ops.append(
    {
        "op": "fmt",
        "x": 1045,
        "y": 1546,
        "s": "{hash}@{time24}",
        "f": "xs",
        "a": "right",
        "c": "grey-mid",
    }
)
ops.append({"op": "icon", "x": 1062, "y": 1546, "n": "battery", "z": "sm", "c": "grey-mid"})
ops.append({"op": "fmt", "x": 1100, "y": 1546, "s": "{battery}", "f": "xs", "c": "grey-mid"})

doc = {"v": 1, "meta": {}, "bg": "white", "palette": {}, "ops": ops}
json.dump(doc, open("samples/fonts.json", "w"), indent=2, ensure_ascii=False)
open("samples/fonts.json", "a").write("\n")
print("ops", len(ops), "left end", 228 + 96 * len(family_styles), "right end", right_end)
