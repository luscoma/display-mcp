"""Generate the two ink-mix coupon pages, using only the vocabulary that
ships today — no firmware change needed to get these onto the wall.

The dither brush: a filled rect in ink A, then an `lg` icon coloured A with
bgc=B and tone:"light". lighten_rect() / _apply_tone_box() clear every
(x+y)-even pixel of the icon's whole 88x88 box to B, independent of the
glyph — and the glyph is A drawn on a ground of A, so it never shows. One op
per 88x88 tile of 50% A/B checkerboard. The mask phase is absolute, so tiles
abut seamlessly and a 2x2 block reads as one unbroken swatch.

The brush tops out at 50%. Every op that carries `tone` also draws glyphs,
and those glyphs paint over anything laid underneath, so the obvious trick
for 25% (stripes, then a knockout) leaves a visible glyph patch. A quarter
grid needs per-pixel ops — ~1936 per swatch. 25%/75% wait for the real mask.
"""
import json
import sys

TILE = 88
BRUSH = "weather-sunny"       # any lg icon; its glyph is invisible


class Page:
    def __init__(self, title, subtitle):
        self.ops = []
        self.text(48, 36, title, f="lg")
        self.text(48, 100, subtitle, w=1104, wrap=True, lines=2)

    def text(self, x, y, s, f="xs", c="black", **kw):
        self.ops.append({"op": "text", "x": x, "y": y, "s": s, "f": f, "c": c, **kw})

    def rect(self, x, y, w, h, c, **kw):
        self.ops.append({"op": "rect", "x": x, "y": y, "w": w, "h": h, "c": c, **kw})

    def mix(self, x, y, w, h, a, b):
        """w*h of 50% a/b; w and h must be multiples of TILE."""
        self.rect(x, y, w, h, a)
        for ty in range(y, y + h, TILE):
            for tx in range(x, x + w, TILE):
                self.ops.append({"op": "icon", "x": tx, "y": ty, "n": BRUSH,
                                 "z": "lg", "c": a, "bgc": b, "tone": "light"})

    def doc(self, title):
        self.text(48, 1552, title, tone="light")
        self.ops.append({"op": "fmt", "x": 1152, "y": 1552, "s": "{hash}@{time24}",
                         "f": "xs", "a": "right", "tone": "light"})
        return {"v": 1, "meta": {"ttl": 3600, "title": title}, "bg": "white",
                "palette": {}, "ops": self.ops}


# ======================================================= page 1: fills
p = Page("Ink mix coupon — fills",
         "1 px checkerboard at 50%. Does a pair of inks fuse into a colour, or "
         "bloom and muddy? Judge it from 1–2 m, the way the panel is actually read.")

p.text(48, 140, "The six inks, undithered — the reference for every pair below")
for i, ink in enumerate(["black", "white", "yellow", "red", "blue", "green"]):
    x = 48 + i * 176
    p.rect(x, 166, TILE, TILE, ink)
    if ink == "white":
        p.rect(x, 166, TILE, TILE, "black", fill=False, t=1)
    p.text(x, 260, ink, w=TILE)

PAIRS = [
    ("black", "white", "grey"),       ("black", "yellow", "mustard"),
    ("black", "red", "maroon"),       ("black", "blue", "navy"),
    ("black", "green", "forest"),     ("white", "yellow", "cream"),
    ("white", "red", "pink"),         ("white", "blue", "pale slate"),
    ("white", "green", "sage"),       ("yellow", "red", "orange"),
    ("yellow", "blue", "olive"),      ("yellow", "green", "chartreuse"),
    ("red", "blue", "plum"),          ("red", "green", "brown"),
    ("blue", "green", "teal"),
]
p.text(48, 298, "Every pair at 176 × 176 — a 2 × 2 block of brush tiles, so the seam "
                "between tiles is under test too")
for i, (a, b, name) in enumerate(PAIRS):
    x, y = [48, 280, 512, 744, 976][i % 5], [328, 568, 808][i // 5]
    p.mix(x, y, 176, 176, a, b)
    p.text(x, y + 182, f"{a}+{b}", w=176)
    p.text(x, y + 208, name, w=176, tone="light")

p.text(48, 1038, "Text on a mixed ground", f="sm")
BANDS = [
    ("black", "white", None, "Black on grey",
     "Black 36 px on 50% black+white. The legibility question for any mixed panel."),
    ("blue", "white", None, "Black on pale slate",
     "A coloured panel light enough to still carry black body text."),
    ("yellow", "white", None, "Black on cream",
     "Same job as the flat yellow `now` row, less shouting."),
    ("black", "white", "white", "Toned on grey",
     "tone:light over a mixed ground. The knockout is in phase with the dither, "
     "so the glyph keeps only its base-ink pixels — expect it to nearly vanish."),
]
for i, (a, b, bgc, s, caption) in enumerate(BANDS):
    y = 1078 + i * 108
    p.mix(48, y, 8 * TILE, TILE, a, b)
    op = {"op": "text", "x": 64, "y": y + 24, "s": s, "f": "md", "c": "black", "w": 672}
    if bgc:
        op.update(tone="light", bgc=bgc)
    p.ops.append(op)
    p.text(768, y + 4, caption, w=384, wrap=True, lines=4)

page1 = p.doc("Ink mix coupon 1/2 — fills")

# ======================================================= page 2: text
p = Page("Ink mix coupon — text",
         "Two questions, and they are not the same one: does dithering cost a glyph "
         "too much ink, and does a two-ink glyph read as a single hue?")

p.text(48, 172, "1 · Coverage. Full ink against tone:light — half the ink knocked out "
                "to the ground. This already ships, but it was only ever judged at xs.",
       w=1104, wrap=True, lines=2)
p.text(120, 240, "full ink", tone="light")
p.text(644, 240, "tone: light", tone="light")
for f, size, y in [("xl", 84, 272), ("lg", 48, 368), ("md", 36, 428),
                   ("sm", 28, 476), ("xs", 22, 516)]:
    p.text(48, y + (size - 22) // 2, f, tone="light", w=56)
    p.text(120, y, "Agenda 9:41", f=f, w=500)
    p.text(644, y, "Agenda 9:41", f=f, w=500, tone="light")

p.text(48, 560, "2 · Yellow. On the ink table yellow-on-white is 1.63:1 and "
                "yellow-on-black is 7.42:1 — better than red-on-white at 5.48:1. The "
                "spec bans yellow text outright; the numbers blame the ground instead.",
       w=1104, wrap=True, lines=2)
p.rect(624, 632, 528, 176, "black")
for f, y in [("lg", 638), ("md", 700), ("sm", 754)]:
    p.text(48, y, "Yellow on white", f=f, c="yellow", w=540)
    p.text(640, y, "Yellow on black", f=f, c="yellow", w=496)

p.text(48, 828, "…and the same for small coloured text, which the spec also rules "
                "out: blue-on-white is 7.34:1, better than red-on-white.",
       w=1104, wrap=True, lines=2)
for c, x in [("black", 48), ("blue", 324), ("green", 600), ("red", 876)]:
    p.text(x, 896, f"{c} 28 px body", f="sm", c=c, w=264)

p.text(48, 946, "3 · A two-ink glyph, drawn as ink A knocked out to ink B — so the "
                "ground has to be B, and the contrast you see is half of A-against-B. "
                "A two-ink glyph on a *third* ground is the one thing this coupon "
                "cannot reach. red+blue is left out: at 1.34:1 it shows nothing here.",
       w=1104, wrap=True, lines=3)
for i, (a, b, label) in enumerate([
        ("yellow", "red", "Orange on red"),    ("white", "red", "Pink on red"),
        ("yellow", "blue", "Olive on blue"),   ("white", "blue", "Slate on blue"),
        ("black", "yellow", "Olive-drab on yellow"), ("white", "black", "Grey on black")]):
    x = 48 if i % 2 == 0 else 624
    y = 1046 + (i // 2) * 104
    p.rect(x, y, 528, 88, b)
    p.ops.append({"op": "text", "x": x + 16, "y": y + 20, "s": label, "f": "lg",
                  "c": a, "w": 496, "tone": "light", "bgc": b})

page2 = p.doc("Ink mix coupon 2/2 — text")

base = sys.argv[1]
for name, d in (("coupon-fills", page1), ("coupon-text", page2)):
    with open(f"{base}/{name}.json", "w") as fh:
        json.dump(d, fh, indent=2)
        fh.write("\n")
    print(name, len(d["ops"]), "ops")
