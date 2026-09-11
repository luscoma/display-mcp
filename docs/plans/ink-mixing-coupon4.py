"""Generate ink-mix coupon 4: the reference card.

Coupons 1-3 asked "does dithering work" (fusion, density, hue-as-text,
ghosting). That question is settled. This one asks a different question:
**are these the right colours, are these the right names, and is each one
usable for what we claim?** It is meant to be kept and re-photographed, so
it shows every candidate mix, grouped into the three tiers that are the
useful fact about each one (dark grounds for white text, light grounds for
black text, fills-only), each carrying a sample of the text its tier claims
works on it — including the fills-only tier, shown with black text on
purpose so the reader can see for themselves why it is disqualified.

The named set is a record of what was tested, not a whitelist: every ink
pair and density stays available to any caller inline. The card says so,
alongside the contrast test that put each colour in its tier — the same
test a caller can run on anything not shown here — and a plain caveat that
the hex values and tier calls are one panel, one room's light, one moment:
e-paper is reflective and drifts with angle, temperature, refresh history
and panel-to-panel variance, so the wall is the final judge, not the card.

Reuses ink-mixing-coupon3.py's `Page` class (header, footer, doc()), copied
rather than imported for the same reason coupon3 copied it from coupon.py:
that module writes files as a side effect of being imported.

Hex values are never hardcoded: they are blended in code from
`display_mcp.render.INK`, the same table the renderer and preview use, so a
transcription error here cannot happen and a change to INK re-derives the
labels for free. Caption line counts are measured with the real font
(`wrap_lines`) rather than guessed, so the fixed layout below is exact
rather than hopeful.

The six solid inks were dropped, per the brief's own fallback: the three
mandatory caveat paragraphs (measurement conditions, "not a whitelist",
rename invitation) plus 21 tiered swatches at a legible size already fill
the canvas to y=1532 of the ~1540 safe budget above the footer. A fourth
row of solid-ink reference swatches would either collide with the footer
or force every swatch below xs-adjacent cramping this card is trying to
avoid. The six inks are already visible as the `c`/`c2` half of every
recipe label, which is most of what a reference swatch would add.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from display_mcp.render import FONTS, INK, load_font, wrap_lines  # noqa: E402

FONT_DIR = os.environ.get("DISPLAY_MCP_FONT_DIR", "./fonts")


def blend_hex(c: str, c2: str, mix: int) -> str:
    """The dither's viewing-distance average of `c`/`c2` at `mix`% c2."""
    a, b = INK[c], INK[c2]
    p = mix / 100.0
    r, g, bl = (round(a[i] * (1 - p) + b[i] * p) for i in range(3))
    return f"#{r:02X}{g:02X}{bl:02X}"


def wrapped_height(s: str, f: str, w: int, max_lines: int) -> tuple[int, int]:
    """(number of lines actually used, total px height) for a wrap:true text
    op, measured with the real font so the layout below is exact rather than
    a guess at how many lines a paragraph needs."""
    size, bold = FONTS[f]
    font = load_font(FONT_DIR, size, bold)
    lines = wrap_lines(font, s, w, max_lines)
    lh = round(size * 1.24)
    return len(lines), (len(lines) - 1) * lh + size if lines else 0


class Page:
    """Copied from ink-mixing-coupon.py rather than imported: that module
    writes its two files as a side effect of being loaded."""

    def __init__(self, title, subtitle):
        self.ops = []
        self.text(48, 36, title, f="lg")
        self.text(48, 100, subtitle, w=1104, wrap=True, lines=2)

    def text(self, x, y, s, f="xs", c="black", **kw):
        self.ops.append({"op": "text", "x": x, "y": y, "s": s, "f": f, "c": c, **kw})

    def rect(self, x, y, w, h, c, **kw):
        self.ops.append({"op": "rect", "x": x, "y": y, "w": w, "h": h, "c": c, **kw})

    def caption(self, x, y, s, w=1104, max_lines=4, f="xs"):
        """A wrap:true paragraph; returns the y just below it, measured with
        the real font rather than assumed."""
        self.ops.append({"op": "text", "x": x, "y": y, "s": s, "f": f, "c": "black",
                          "w": w, "wrap": True, "lines": max_lines})
        _, h = wrapped_height(s, f, w, max_lines)
        return y + h

    def doc(self, title, palette):
        self.text(48, 1552, title, tone="light")
        self.ops.append({"op": "fmt", "x": 1152, "y": 1552, "s": "{hash}@{time24}",
                         "f": "xs", "a": "right", "tone": "light"})
        return {"v": 1, "meta": {"ttl": 3600, "title": title}, "bg": "white",
                "palette": palette, "ops": self.ops}


# ===================================================================
# The 21 candidates, grouped into the three tiers that are the useful
# fact about each one. (name, c, c2, mix) — mix is the share of c2
# (decision 8: a higher number is LIGHTER when c2 is the lighter ink).
TIER1 = [  # dark grounds — white text reads on these
    ("navy", "black", "blue", 50),
    ("maroon", "black", "red", 50),
    ("plum", "red", "blue", 50),
    ("forest", "black", "green", 50),
    ("teal", "blue", "green", 50),
    ("brown", "red", "green", 50),
    ("grey-dark", "black", "white", 25),
]
TIER2 = [  # light grounds — black text reads on these
    ("cream-pale", "yellow", "white", 75),
    ("cream", "yellow", "white", 50),
    ("sage-pale", "green", "white", 75),
    ("slate-pale", "blue", "white", 75),
    ("pink-pale", "red", "white", 75),
    ("grey-light", "black", "white", 75),
    ("sage", "green", "white", 50),
    ("pink", "red", "white", 50),
    ("slate", "blue", "white", 50),
    ("chartreuse", "yellow", "green", 50),
]
TIER3 = [  # fills only — neither black nor white text reads well
    ("grey-mid", "black", "white", 50),
    ("mustard", "black", "yellow", 50),
    ("orange", "yellow", "red", 50),
    ("olive", "yellow", "blue", 50),
]

PALETTE = {name: {"c": c, "c2": c2, "mix": mix} for name, c, c2, mix in TIER1 + TIER2 + TIER3}

SAMPLE = "Agenda 9:41"

SWATCH_W, SWATCH_H = 252, 78
COLS = [48, 332, 616, 900]  # 4 x 252 + 3 x 32 = 1104, margins 48
HEADER_H = 30
ROW_H = 166
TIER_GAP = 10

# "black+white 75 · #AEAEAA" all on one line is 260-290px wide at xs
# (measured with the real font) — wider than a 252px column, so it would
# overlap the next swatch. Recipe and hex get their own lines instead;
# each alone measures well under the column width for every entry here.


def cell(p, x, y, name, c, c2, mix, text_color):
    p.rect(x, y, SWATCH_W, SWATCH_H, name)
    p.ops.append({"op": "text", "x": x + 16, "y": y + SWATCH_H // 2 - 14, "s": SAMPLE,
                  "f": "sm", "c": text_color, "w": SWATCH_W - 32})
    p.text(x, y + SWATCH_H + 8, name, f="sm")
    p.text(x, y + SWATCH_H + 8 + 26, f"{c}+{c2} {mix}", f="xs")
    hexv = blend_hex(c, c2, mix)
    p.text(x, y + SWATCH_H + 8 + 26 + 24, hexv, f="xs")


def tier(p, y, title, entries, text_color):
    p.text(48, y, title, f="sm")
    row_y = y + HEADER_H
    for i, (name, c, c2, mix) in enumerate(entries):
        col = i % 4
        if col == 0 and i:
            row_y += ROW_H
        cell(p, COLS[col], row_y, name, c, c2, mix, text_color)
    rows = (len(entries) - 1) // 4 + 1
    return y + HEADER_H + rows * ROW_H


p = Page(
    "Ink mix coupon 4 — the reference card",
    "Every candidate for the official palette, grouped by what it turned "
    "out to be good for. Each swatch carries a sample of the text its tier "
    "claims works on it — judge colour and claim together, from 1–2 m.",
)

y = 170
y = p.caption(
    48, y,
    "Hex (from display_mcp.render.INK) is this panel's dither average at "
    "viewing distance, in this room's light — not a single-pixel colour, "
    "and not a promise. E-paper is reflective and shifts with ambient "
    "light, viewing angle, temperature, refresh history and panel-to-panel "
    "variance. If your wall disagrees with this card, trust the wall.",
    max_lines=4,
) + 6
y = p.caption(
    48, y,
    "Not a whitelist: every ink pair and every density (25/50/75) is "
    "available inline, no permission needed — these are what each turned "
    "out to be good for, not rules about what's allowed. Judge anything "
    "else the way these were judged: contrast against what's under it, "
    "roughly 4.5:1 for body text, 3:1 for large.",
    max_lines=4,
) + 6
y = p.caption(
    48, y,
    "Names are proposals too — rename anything that reads wrong. brown "
    "(red+green) is already in question, judged “a bit mustardy but I'd "
    "still consider it brown.”",
    max_lines=3,
) + 16

y = tier(p, y, "Dark grounds — white text reads on these", TIER1, "white")
y += TIER_GAP
y = tier(p, y, "Light grounds — black text reads on these", TIER2, "black")
y += TIER_GAP
y = tier(p, y, "Fills only — ~3–4:1 contrast; blocks and bars, never text", TIER3, "black")

print("content ends at y =", y, "(bezel-safe bottom is 1576, footer sits at 1552)")

doc = p.doc("Ink mix coupon 4 — the reference card", PALETTE)

base = sys.argv[1]
with open(f"{base}/coupon-palette.json", "w") as fh:
    json.dump(doc, fh, indent=2)
    fh.write("\n")
print("coupon-palette", len(doc["ops"]), "ops")
