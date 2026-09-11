"""Generate ink-mix coupon 3: density, clean-hue text, the grey rule, and
tone vs. a named mix — the four questions coupons 1 and 2 could not answer.

Coupons 1 and 2 drew every mix with a brush trick (a filled rect plus an `lg`
icon knocked out with `tone: "light"`) because the renderer did not resolve
mixes on its own and the brush topped out at 50% anyway. Both limits are
gone: `Ctx.ink()` now resolves a palette entry with `c`/`c2`/`mix` straight
into an `Ink(a, b, pct)`, and `paint()` interleaves it at any of 25/50/75 on
whatever primitive asks for it (decision 1 and 2, docs/plans/ink-mixing.md).
So this coupon draws mixes the ordinary way: give a palette entry a `mix`,
then use its name as `c` on a `rect`, `text` or `line` like any other colour.
No brush, no per-tile op count — a 176x176 swatch is one `rect`.

Reuses ink-mixing-coupon.py's `Page` class (header, footer, doc()) so this
reads as a third page in the same family, not a stranger.
"""
import json
import sys


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

    def line(self, x, y, x2, y2, c, **kw):
        self.ops.append({"op": "line", "x": x, "y": y, "x2": x2, "y2": y2, "c": c, **kw})

    def doc(self, title, palette):
        self.text(48, 1552, title, tone="light")
        self.ops.append({"op": "fmt", "x": 1152, "y": 1552, "s": "{hash}@{time24}",
                         "f": "xs", "a": "right", "tone": "light"})
        return {"v": 1, "meta": {"ttl": 3600, "title": title}, "bg": "white",
                "palette": palette, "ops": self.ops}


# The plan's table names the 50% mixes without a suffix (grey, plum, brown,
# navy, maroon, forest); the two off-density grey/plum entries needed for
# question 1 get an explicit suffix since they are the same pair at a
# different density, not a different name.
PALETTE = {
    "grey":     {"c": "black", "c2": "white"},          # mix defaults to 50
    "grey-25":  {"c": "black", "c2": "white", "mix": 25},
    "grey-75":  {"c": "black", "c2": "white", "mix": 75},
    "plum":     {"c": "red",   "c2": "blue"},
    "plum-25":  {"c": "red",   "c2": "blue",  "mix": 25},
    "plum-75":  {"c": "red",   "c2": "blue",  "mix": 75},
    "brown":    {"c": "red",   "c2": "green"},
    "navy":     {"c": "black", "c2": "blue"},
    "maroon":   {"c": "black", "c2": "red"},
    "forest":   {"c": "black", "c2": "green"},
}

p = Page(
    "Ink mix coupon 3 — density, hue text, the grey rule",
    "25% and 75% densities, five clean-hue pairs as text, a grey rule and "
    "panel, and tone: light next to a named mix. Judge each from 1–2 m, the "
    "way the panel is read.",
)

p.text(48, 162, "Ghosting check: watch the dithered areas below as you judge "
                "— the plan's last open question.", w=1104)

# ============================================================ 1. density
# Headline question: does 25%/75% work, and does more density read as more
# of the hue or just muddier? black+white (achromatic, gap .713 per decision
# 3) next to plum/red+blue (the smallest chromatic gap, .092 — hue should
# hold at every density if any pair's will) makes the two readings easy to
# tell apart.
p.text(48, 204, "1 · Density — 25% and 75% at last, and does density read "
                "as more hue or just mud?", f="sm")
p.text(48, 244, "grey is black+white (the largest luminance gap of any "
                "pair); plum is red+blue (the smallest). Same three "
                "densities, side by side.", w=1104, wrap=True, lines=2)

p.text(48, 302, "grey — black + white")
p.text(612, 302, "plum — red + blue")

SWATCH = 150
GAP = 24
COLS = [48 + i * (SWATCH + GAP) for i in range(6)]  # 48 236 424 612 800 988
# grey-50/plum-50 have no suffix (the plan table's default-density name).
DENSITY_KEYS = ["grey-25", "grey", "grey-75", "plum-25", "plum", "plum-75"]
DENSITY_LABELS = ["25%", "50%", "75%", "25%", "50%", "75%"]
for x, key, label in zip(COLS, DENSITY_KEYS, DENSITY_LABELS):
    p.rect(x, 332, SWATCH, SWATCH, key)
    p.text(x, 488, label, w=SWATCH)

p.text(48, 518, "grey-50 (middle of the left block) is bit-identical to "
                "tone: light — the same grey the footer stamp already uses.")

# ============================================================ 2. clean-hue text
# The case coupons 1 and 2 structurally could not draw: a two-ink glyph on a
# *third* ground (white), rather than knocked out onto one of its own inks.
# The pair name is drawn as the sample text itself, in its own mix — content
# and label in one, so nothing needs a caption per swatch.
p.text(48, 562, "2 · Do the five clean-hue pairs hold as text on white?", f="sm")
p.text(48, 602, "The five pairs decision 3 says should hold: both inks dark "
                "enough not to vanish into a white page, luminance gap under "
                ".08. If these fail as text, mixed text shrinks to fills-only.",
       w=1104, wrap=True, lines=2)
p.text(48, 660, "plum = red+blue · brown = red+green · navy = black+blue · "
                "maroon = black+red · forest = black+green", w=1104)

PAIR_NAMES = ["plum", "brown", "navy", "maroon", "forest"]
PAIR_X = [248, 408, 595, 748, 965]  # measured so "Maroon" never overlaps "Forest"
for f, y, label_y in [("lg", 694, 710), ("md", 770, 779), ("sm", 831, 835)]:
    p.text(48, label_y, f"{f} {dict(lg=48, md=36, sm=28)[f]}px")
    for x, name in zip(PAIR_X, PAIR_NAMES):
        p.text(x, y, name.capitalize(), f=f, c=name)

# ============================================================ 3. grey rule / panel
# The practical motivation for the whole feature: the panel has no grey and
# a dashboard wants one for rules and secondary panels.
p.text(48, 884, "3 · A 25% grey rule and panel — the practical case this "
                "was built for", f="sm")
p.text(48, 924, "The panel has no grey; a dashboard wants one for rules and "
                "quiet secondary panels. Judge whether 25% is too faint at "
                "rule thickness, and legible enough as a panel fill.",
       w=1104, wrap=True, lines=2)

for t, y, label in [(1, 994, "1 px"), (2, 1034, "2 px"), (4, 1074, "4 px")]:
    p.line(48, y, 700, y, "grey-25", t=t)
    p.text(730, y - 10, f"grey-25 rule, {label}")
# A 1px horizontal rule samples only one row of the 2x2 mask, so it lands on
# either 0%, 50% or 100% ink depending on which row that is — never the true
# 25% — measured on this very render. 2px+ spans both rows and hits 25% on
# the nose. Worth knowing before shipping a hairline rule at low density.
p.text(48, 1092, "1 px note: a single-pixel rule hits only one mask row — "
                 "0/50/100%, never a true 25%. 2 px+ is exact.", w=1104)

p.rect(48, 1126, 350, 110, "grey-25")
p.text(64, 1166, "Panel text at 25%", f="sm")
p.text(420, 1126, "A 350×110 panel filled grey-25, sm black text on top. "
                  "Enough contrast to read as a quiet secondary panel, or "
                  "too close to white to bother with?", w=684, wrap=True, lines=3)

# ============================================================ 4. tone vs named mix
# Decision 5's claim: tone mixes with whatever bgc names (relative), a named
# mix always uses its own second ink (absolute). Identical on white; the red
# frame is where they should visibly diverge — grey-50 puts real white
# pixels on the red, tone:light speckles black into the red itself.
p.text(48, 1258, "4 · tone: light next to a grey mix — same pixels only "
                 "where they happen to coincide", f="sm")
p.text(48, 1298, "Top line each frame is tone: light; bottom is the named "
                 "grey mix. Same on white below; watch them split apart on "
                 "the red ground.", w=1104, wrap=True, lines=2)

p.text(48, 1356, "white ground (page bg)")
p.text(620, 1356, "red ground")

FRAME_Y, FRAME_H = 1386, 130
p.rect(48, FRAME_Y, 532, FRAME_H, "black", fill=False, t=1)
p.rect(620, FRAME_Y, 532, FRAME_H, "red")

for x, bgc in [(48, "white"), (620, "red")]:
    p.text(x + 16, FRAME_Y + 12, "Agenda 9:41", f="md", c="black", tone="light", bgc=bgc)
    p.text(x + 16, FRAME_Y + 62, "Agenda 9:41", f="md", c="grey")

doc = p.doc("Ink mix coupon 3 — density, hue text, grey rule", PALETTE)

base = sys.argv[1]
with open(f"{base}/coupon-density.json", "w") as fh:
    json.dump(doc, fh, indent=2)
    fh.write("\n")
print("coupon-density", len(doc["ops"]), "ops")
