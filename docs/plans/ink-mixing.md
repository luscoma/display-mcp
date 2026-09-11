# Ink mixing: more than six colours by dithering

Status: coupon-tested on the panel 2026-09-10, nothing implemented yet. Two
coupon documents were published to the wall and judged by eye at normal
reading distance; this file records what they showed and the design that
follows from it. The renderer, firmware and spec are all unchanged so far.

## What we want

The panel has six inks and no grey. A dashboard wants a grey rule, a quiet
secondary panel, a second accent that isn't stealing red. All of those are
reachable by dithering two inks at the pixel level — the panel is ~150 DPI
and read from 1–2 m, so a 1 px checkerboard fuses.

The mechanism already exists in the vocabulary. `tone: "light"` is a 1 px
checkerboard of the background knocked out of a glyph box
(`lighten_rect()` in `firmware/display_list.h`, `_apply_tone_box()` in
`display_mcp.render`). Ink mixing is that same mask, generalised.

## The coupon

Both pages were drawn with a **brush trick** that needs no firmware change,
worth recording because it is reusable: a filled `rect` in ink A, then an
`lg` `icon` coloured A with `bgc: B` and `tone: "light"`. The knockout runs
over the icon's whole 88×88 box regardless of the glyph, and the glyph is A
drawn on a ground of A, so it never shows. One op per 88×88 tile of 50% A/B
checkerboard. Mask phase is absolute, so tiles abut seamlessly — verified at
exactly 50.0/50.0 across a tile seam.

The brush tops out at 50%. Every op carrying `tone` also draws glyphs, and
those glyphs paint over anything laid underneath, so the obvious trick for
25% (stripes, then a knockout) leaves a visible glyph patch — measured 16.4%
instead of 25%. A quarter grid needs per-pixel ops, ~1936 per swatch.

The generator is `docs/plans/ink-mixing-coupon.py`; run it with an output
directory and it writes both documents, ready for `display-mcp-cli stamp`
and `publish`.

## What the glass showed

**All fifteen pairs fuse.** No halo or bloom at ink boundaries, which was the
single biggest risk to the idea and is now closed. The darker pairs read
best overall.

Names, as judged on the wall:

| pair | reads as | | pair | reads as |
|---|---|---|---|---|
| black+white | grey | | white+green | sage |
| black+yellow | **mustard** | | yellow+red | orange |
| black+red | maroon | | yellow+blue | **olive** |
| black+blue | navy | | yellow+green | **chartreuse** |
| black+green | forest | | red+blue | plum |
| white+yellow | cream | | red+green | brown |
| white+red | pink | | blue+green | teal |
| white+blue | pale slate | | | |

**Four pairs show faint regular structure** on the panel: `black+yellow`,
`black+green`, `yellow+red`, `white+blue`. Not very noticeable, but present.
The document is a mathematically exact checkerboard — this was verified per
column across every swatch — so the structure is the panel, not the data.
Mechanism undetermined; most likely a beat between the 1 px mask and the
panel's own particle structure. All four involve yellow or white, which is a
thin sample but suggests the lighter ink is where it shows through.

**Text on a mixed ground is fine.** Black 36 px over grey, pale slate and
cream all read cleanly.

**Toned text over a mixed ground vanishes**, as predicted: the knockout is in
phase with the dither, so the glyph keeps only its base-ink pixels. Do not
put toned text on a mixed fill.

**Grey text reads well at every size, `xs` included.** `tone: light` black
text — which is `black+white` at 50% — was judged good at all five sizes,
where previously it had only ever been judged at `xs`, and it reads
specifically as a *light* grey rather than a mid grey. `black+white` is the
largest luminance gap of any pair and still the best mixed glyph on the
coupon; see decision 3 for why that is not a contradiction.

This is also the case that already ships: the footer stamp is `xs` toned
black text and has been on the wall since 2026-09-09. Any rule that
discourages mixing at small sizes would outlaw it, so there is no such rule.
Reading light at 50% is instead the argument for building 25%: a dimmer grey
is not otherwise reachable.

## Decision 1: mixes live in the palette, not on each op

```json
"palette": {
  "accent": "red",
  "mustard": {"c": "black", "c2": "yellow", "mix": 50},
  "grey":    {"c": "black", "c2": "white",  "mix": 25}
}
```

Rather than adding `c2`/`mix` to every op's field table. Reasons: restyling
stays one line, which is why `palette` exists; `meta.hash` already covers
`palette`, so change detection needs no thought; every op including `bg`
gets mixed ink for free; and `bgc` can then name a mix, which makes toned
text over a mixed ground land correctly instead of speckling — the absolute
phase means the knockout reproduces the fill underneath exactly.

### The schema, exactly

This is the contract between the firmware and the renderer. Both implement
it independently, so every case below is pinned down rather than left to
whichever is written first. Nothing here ever skips an op — the existing rule
is that a bad value warns and draws something.

A palette entry is either a **string** (an alias, as today) or an **object**:

| field | | |
|---|---|---|
| `c` | required | base ink; the one a mix degrades to |
| `c2` | required | second ink |
| `mix` | optional, default `50` | percentage of `c2`, one of 25 / 50 / 75 |

- `c` and `c2` **may be aliases**, resolved through the existing 8-hop cap
  (`{"c": "accent", "c2": "white"}` where `accent` → `red` is legal).
- `c` and `c2` **may not be mixes**. A mix of mixes is not representable in a
  2×2 mask; warn and use the referenced entry's own `c`.
- `mix` outside {25, 50, 75} warns and **rounds to the nearest** of the three.
  `mix` outside 0–100, or not a number, warns and uses 50.
- An unknown name in `c` or `c2` behaves exactly as an unknown colour does
  today: warn, fall back to black.
- `c2` missing, or equal to `c`, is not a mix — warn and draw solid `c`.
- A mix is legal anywhere a colour name is legal: `c`, `bgc`, and `bg`.
- Resolution returns `{a, b, mix}`; a plain colour is `{a, a, 100}`, so the
  solid path is the mix path with nothing to interleave and needs no branch
  at the call sites.

## Decision 2: one 2×2 Bayer mask, densities 25 / 50 / 75, absolute phase

```c
static const uint8_t B[2][2] = {{0, 2}, {3, 1}};
inline bool mix_on(int x, int y, int pct) { return B[y & 1][x & 1] < pct / 25; }
```

At `pct = 50` this is `(x + y) & 1`, **bit-identical to today's
`lighten_rect`**, so `tone: "light"` keeps drawing exactly what it draws now
and the existing footer stamp is untouched.

Absolute phase (not relative to the op's origin) so adjacent fills tile
seamlessly and a knockout lands on the mix beneath it. This is hard to
change later; it is decided.

Three densities only, not a 4×4 Bayer's seventeen — 17 steps is false
precision on a six-ink panel, and a 4×4 tile is 0.68 mm, large enough to
read as texture. Same kind of commitment as the five-size font scale.

Implementation is the proxy of decision 6, which applies the mask uniformly
to fills, shapes and glyphs alike. `bg` is the one exception and needs fill
plus an overlay pass; see decision 6.

25% and 75% were **not** reachable on the coupon (see above), so they remain
unjudged. They cost one threshold once the mask exists, so ship all three
and judge on the first real build.

## Decision 3: mixed ink is allowed on text, and the ground picks the mix

An earlier draft of this design said mixes were fill-only. That was wrong:
`tone: "light"` already *is* mixed-ink text — a red glyph half knocked out
to white is pink text — and it has shipped and been judged good since
2026-09-09.

Two effects govern a dithered glyph, and they are easy to confuse. The first
matters more.

**Coverage against the ground.** A mixed glyph only shows where its pixels
differ from what is behind it. If one of its two inks matches the ground,
half the glyph disappears into the page and the mix reads as a tint of the
other ink rather than as the blend. So a mix is a *ground-dependent* choice,
not a property of the pair:

| pink (`white+red`) on… | reads as |
|---|---|
| red | the red half vanishes → washed out, "the lightest pink" |
| white | the white half vanishes → a faint pink tint, i.e. exactly `tone: light` on red text |
| black or navy | neither half matches → full coverage, genuine pink |

The coupon could only draw a two-ink glyph by knocking ink A out to ink B,
which forces the ground to *be* B — the worst of the three cases. That is why
section 3 looked weak, and it is a property of the test, not of the
technique.

**Luminance gap** between the two inks is the second-order effect. A large
fill averages the two; a 3 px stem has too few pixels to average, so the
brighter ink dominates and the blend shifts toward it.

```
black .014   blue .056   red .092   green .125   yellow .428   white .727
```

| gap | pairs | as a glyph |
|---|---|---|
| < .08 | red+green, red+blue, black+blue, blue+green, black+red | hue holds |
| ~.11 | black+green | slight shift |
| .30–.42 | white+yellow, yellow+green, yellow+red, yellow+blue, black+yellow | shifts toward the lighter ink |
| > .60 | white+green, white+red, white+blue, black+white | shifts hard |

Confirmed on the coupon: `yellow+red` (gap .34) as a glyph read "a bit
yellowish" where the same mix as a 176 px fill read as proper orange;
`white+red` (gap .64) read as "the lightest pink".

**The gap governs hue fidelity, not legibility, and only bites on chromatic
pairs.** `white+black` has the largest gap of all fifteen (.713) and is the
best mixed glyph on the coupon. Both facts are the same mechanism: a dithered
glyph always reads lighter than its nominal density, because the brighter ink
dominates at glyph scale. When the pair carries a hue, that is a hue you
asked for and did not get. When the pair is achromatic there is no hue to
lose, so the shift is simply the tone — grey at 50% on black reads as a
*light* grey, which is a useful thing to be. So the two axes are independent:

- **contrast against the ground** decides legibility; a mix must still clear
  ~3:1 after the mix, and `white+red` on red fails here as much as on hue.
- **luminance gap** decides whether the colour's name survives, and is
  irrelevant when the mix has no hue.

So `check()` should warn when a mix whose gap exceeds ~0.2 **and whose two
inks are not both achromatic** is used as `c` on `text`, `fmt` or `icon` — a
warning, never a skip, per the existing rule that warnings do not block a
publish. The firmware resolves such a mix normally; this is a composition
warning, not a render error. `black+white` at any density is exempt.

Separately, a 50% glyph carries half the ink and **reads lighter in weight**
than solid. That is not a defect to be designed around — at `xs` it is
usually the point, and it is what the shipping footer stamp is for. It only
costs something when the weight was load-bearing: a chromatic mix at `sm` or
`xs` gives up both its hue and its weight at once, which is the combination
to avoid. Achromatic mixes carry no such penalty at any size.

On a **white** ground — the usual case — the two rules agree and pick the
same five: plum, brown, navy, maroon, forest. Both of their inks are dark, so
neither vanishes into the page (rule one) and their gaps are all under .08
(rule two). These are the prize and are **still untested as text**, for the
reason above.

But the five are not a fixed list, because rule one depends on the ground.
On a dark panel the answer inverts: pink, cream and pale slate come into
their own there, and plum on navy would be the washed-out one. Any
recommended set in `SPEC.md` has to be written as pairs *per ground*, not as
a blessed list of mixes.

## Decision 4: replace the colour folklore in SPEC.md with the contrast matrix

`docs/SPEC.md` currently asserts "yellow is a fill, never text" and "small
text is always black … blue and green turn to mud at 28 px". Both were
tested on the coupon and both are wrong as written.

Contrast ratios on the `INK` table (WCAG: 4.5 body, 3.0 large):

|  | black | white | yellow | red | blue | green |
|---|---|---|---|---|---|---|
| **black** | — | 12.06 | 7.42 | 2.20 | 1.64 | 2.71 |
| **white** | 12.06 | — | 1.63 | 5.48 | 7.34 | 4.44 |
| **yellow** | 7.42 | 1.63 | — | 3.37 | 4.52 | 2.73 |
| **red** | 2.20 | 5.48 | 3.37 | — | 1.34 | 1.23 |
| **blue** | 1.64 | 7.34 | 4.52 | 1.34 | — | 1.65 |
| **green** | 2.71 | 4.44 | 2.73 | 1.23 | 1.65 | — |

Yellow on white is 1.63:1 and genuinely unreadable — confirmed on the wall.
Yellow on black is 7.42:1, better than red on white, and reads crisply at
`lg`, `md` and `sm`. Yellow is not the problem; the ground is. Small
coloured text was judged "totally fine", and blue on white (7.34) is in fact
the strongest coloured text available, better than red (5.48).

The real prohibitions are dark-on-dark and invisible in the current prose:
red/blue 1.34, red/green 1.23, blue/green 1.65, black/blue 1.64. The matrix
states them; the folklore does not. Replace the "Designing for six inks"
bullets with the matrix plus a 3:1 floor, and have `check()` enforce that
floor as a warning wherever the ground is knowable.

## Decision 5: `tone` stays; it is not the same thing as a palette mix

They look equivalent and are not:

- `tone: "light"` mixes the glyph with **whatever is behind it** — `bgc`
  names the ground. Relative.
- A palette mix names a **specific second ink**. Absolute.

On a white page both give the same pixels. On a red panel they diverge:
black text with `tone: light, bgc: red` is a red-speckled black glyph, while
a `grey-50` mix would paint actual white pixels onto the red.

So `tone` is kept rather than retired in favour of named mixes. It ships, it
is in the sample and the footer stamp, it is bit-identical to a 50% mix, and
"a quieter version of this against whatever is behind it" is the more
convenient spelling for the common case. Define it as sugar for "mix with
`bgc`", which makes `tone: "faint"` the 25% rung for free once densities
exist.

## Decision 6: a proxy `Display` that rewrites colour in `draw_pixel_at`

Resolved 2026-09-10 by reading the generated tree at
`firmware/.esphome/build/epaper-13e6/src/esphome/`, whose `core/version.h`
says `ESPHOME_VERSION "2026.8.2"` — the exact source this panel is built
from, not an upstream guess.

`Display::print()` does alignment and then hands the font **itself**
(`display.cpp:506-510`):

```cpp
font->print(x_start, y_start, this, color, text, background);
```

and the glyph inner loop calls, per lit pixel (`font.cpp:347`):

```cpp
display->draw_pixel_at(glyph_x, glyph_y, color);
```

against `virtual void draw_pixel_at(int, int, Color) = 0;`
(`display.h:338`). So a subclass override dispatches, and passing `print()` a
proxy gives per-pixel colour control over glyphs with **no framebuffer
readback**. This is the opposite direction from `lighten_rect`, which only
proved `draw_pixel_at` as a *write* path; both are now confirmed.

Subclass `display::Display`, not `DisplayBuffer` — the latter adds a pure
`draw_absolute_pixel_internal`. Five pure virtuals to implement
(`draw_pixel_at`, `get_display_type`, `get_width_internal`,
`get_height_internal`, `update`), plus forward the virtual `get_width()` /
`get_height()`. Nothing self-registers with `App`, so a stack or static proxy
is never polled.

**Do not set clipping or rotation on the proxy.** It gets its own
`clipping_rectangle_` and `rotation_`, but since `draw_pixel_at` forwards
into the real `DisplayBuffer::draw_pixel_at`, that one still applies the
panel's clipping and rotation. Keep setting those on the real display.

Three consequences:

- **The shape primitives come free.** `line`, `rectangle`,
  `filled_rectangle`, `circle`, `filled_circle`, `triangle` and `image` are
  non-virtual members that call `this->draw_pixel_at`, so invoking them *on
  the proxy* dithers them. That collapses decision 2's separate "base fill
  plus overlay" path: one mechanism covers rect, circle, line, text and icon
  uniformly. It costs roughly 2× the per-pixel work of fill-then-overlay
  (every pixel goes through the virtual rather than half of them), which is
  still negligible against a ~20 s refresh — take the uniformity.
- **`fill()` is the exception.** `EpaperSpectra6133` overrides it with a
  framebuffer memset, so it never reaches `draw_pixel_at`. A mixed `bg` has
  to be `fill(A)` followed by an overlay pass, and `fill`/`clear` must be
  routed to the real display explicitly or the inherited base implementation
  will paint the whole panel one pixel at a time.
- **The fonts are 1 bpp**, confirmed in the generated `main.cpp`
  (`font::Font(..., 1)`), so `bpp_max == 1` and every lit pixel takes the
  exact-`color` branch. The anti-aliasing blend at `font.cpp:349` — which
  would have handed the proxy intermediate colours to quantise onto six inks
  — never fires. If a font is ever compiled at higher bpp this needs
  revisiting.

`display_list.h` already holds fonts as `display::BaseFont *`, which is what
`Display::print` takes, so the call sites need no cast and no signature
change.

### What the sketch missed: icons carry two colours

Implementing this turned up one thing the design above was too thin to
cover. `Image::draw()` takes `color_on` *and* `color_off` and can call
`draw_pixel_at` with either, so a proxy holding a single ink cannot be right
for the `icon` op. The proxy therefore keys on the incoming `Color`: each op
registers up to two (colour, `Ink`) pairs and `draw_pixel_at` substitutes by
lookup, passing anything unregistered straight through.

Two consequences worth knowing:

- The proxy is constructed **inside** the op loop, so its two slots reset
  every op. If it were ever hoisted out, it would fill after the first two
  ops and silently mis-colour everything after them.
- A collision is possible in principle: if an icon's `c` and `bgc` are
  different mixes that happen to share a base ink, both register the same
  key and the first match wins, so the off pixels would take the on pixels'
  density. It cannot happen with the icons this firmware compiles, because
  `transparency: chroma_key` means off pixels are skipped and never reach
  `draw_pixel_at` at all. It would become reachable if a future icon were
  compiled as an opaque binary image.

## Still open

- 25% and 75% — unjudged; decide on the first real build.
- Whether the palette needs a per-op density override, or whether one entry
  per density (`grey-25`, `grey-50`, `grey-75`) is acceptable. Deferred
  2026-09-10: put a mix in the palette if you want to use it, and revisit
  only if that proves annoying in practice.
- The five clean-hue pairs as text on white — the case the coupon could not
  reach and the main reason to build this.
- Mechanism for the faint structure on those four pairs. Judged acceptable
  at reading distance 2026-09-10 and deferred: a macro photograph resolves
  the weave, but at the distance the panel is actually read it does not
  intrude. No tiering of the recommended set for now; revisit only if it
  starts showing up in real documents.
- Ghosting on dithered areas. Weaker than it first looked: the driver does
  support auto-partial and the YAML sets `change_detection_mode: track`, but
  dithering does not change the *bounding box* of a text run — same glyphs,
  same positions, only different pixels inside the box — so
  `detect_changed_region` sees the same region either way, and the wake cycle
  redraws a whole new document regardless. The residual question is whether
  alternating adjacent pixels between distant ink states ghosts more than
  solid fills. Just watch for it while judging coupon 3; not a gate.

## Decision 7: the preview stops anti-aliasing text

Found while wiring mixes through the renderer, and fixed rather than carried:
the preview has always been softer than the wall.

Pillow defaults to an 8-bit glyph mask when drawing text on an RGB image, so
every piece of text the preview has ever drawn had blended edge pixels. The
panel cannot do that. Its fonts compile at **1 bpp** (`font::Font(..., 1)` in
the generated `main.cpp`), so `font.cpp`'s blending branch never runs and a
glyph pixel is either full ink or nothing.

Measured on the two documents to hand, the old preview emitted colours the
panel physically cannot produce:

| document | non-ink pixels | distinct non-ink colours |
|---|---|---|
| `samples/display.json` | 27,746 (1.4%) | 452 |
| the text coupon | 58,481 (3.0%) | 1,603 |

A six-ink panel previewed in 1,600 colours. Setting `fontmode = "1"` on every
`ImageDraw` (`draw_on()`) renders bilevel, and both documents now come back
at exactly zero non-ink pixels.

This is a deliberate break in preview output — every existing PNG changes at
glyph edges — taken because the preview's job is to look like the wall. It
also removes an inconsistency mixing would otherwise have introduced, since
mixed text goes through a 1-bit stencil and was never anti-aliased.

## Found along the way

`draw_icon()` in `display_mcp.render` paints its procedural stand-ins 2 px
outside the nominal icon box on every side, so a preview can disagree with
the panel wherever an icon sits next to other content — the firmware's
`image->draw()` blits exactly `get_width() × get_height()` and cannot spill.
Unrelated to ink mixing; tracked separately. `weather-night` additionally
appears to paint non-glyph pixels where the other stand-ins do not.
