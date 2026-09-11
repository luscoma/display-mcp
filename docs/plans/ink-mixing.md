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

**Coupon 3 (2026-09-10), on the new firmware.** 25% and 75% both work and
the grey ladder reads as three clear steps. A `grey-25` rule at 2 px+ is
fine at rule thickness. The five clean-hue pairs hold as text on white at
`lg`, `md` and `sm` — `brown` (red+green) reads "a bit mustardy" but still
as brown. The one miss was the secondary panel, which used the wrong grey;
see decision 8.

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
  "accent":     "red",
  "mustard":    {"c": "black", "c2": "yellow", "mix": 50},
  "grey-light": {"c": "black", "c2": "white",  "mix": 75}
}
```

**`mix` is the share of `c2`, not of the ink.** With `c: black, c2: white`,
a higher `mix` means more white and therefore a *lighter* grey. This reads
backwards to anyone carrying print habits, where "25% black" means a light
tint, and it is a live trap: see decision 8.

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

25% and 75% were **not** reachable on the coupons 1 and 2 (see above), so
they were unjudged until coupon 3.

### A feature thinner than 2 px cannot carry 25% or 75%

Found building coupon 3. The mask is 2x2, so a one-pixel-wide run samples a
single row or column of it and cannot express a quarter:

| density | a 1 px run actually renders at |
|---|---|
| 25% | **0% or 50%**, by parity |
| 50% | exactly 50%, always |
| 75% | **50% or 100%**, by parity |

50% is parity-independent and safe at any thickness — which is why `tone`
has never had this problem. 25% and 75% need **2 px in both axes** to land on
their nominal density.

The trap is not just that a 1 px rule is wrong, it is that it is wrong
*by position*: nudging a `grey-25` rule down one pixel flips it between
invisible and half strength, with nothing in the document to explain why. So
`check()` should warn when a 25% or 75% mix is used on a `line` with `t < 2`,
on a `rect` outline with `t < 2`, or on a fill less than 2 px in either
dimension. That warning is worth more than most of the others, because the
failure is silent and looks like a rendering bug rather than an authoring
one.

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

Two errors in `src/display_mcp/prompts/compose.md` go in the same pass: it
repeats "Yellow is a fill, never text", and it claims an unknown *colour*
skips the op. It does not — `resolve_ink` falls back to black with a warning
and the op still draws. Only an unknown op, font or icon is skipped.

### How the named set is stated

The named colours (decision 9) get the same treatment, because the failure
mode that produced "yellow is a fill, never text" was not a wrong
observation — yellow on white really is unreadable — but a narrow one
written as law. A blessed list of colours would repeat that shape exactly.

So the set is presented as **combinations that have been tested, with what
each turned out to be good for**, never as a whitelist. Every pair of the
six inks and all three densities stay available; a caller can write a mix
inline without asking. And the reader gets the method rather than only the
permission: contrast is the check, ~4.5:1 for body text and 3:1 for large,
which is what sorted these colours into tiers in the first place. Someone
evaluating a combination we never tried should be able to do it the same way
we did.

The measurements are also stated as best-case. They come from the renderer's
ink approximations and one panel judged in one room. E-paper is reflective,
so appearance tracks the ambient light in a way an emissive screen does not,
and it shifts with viewing angle, temperature, refresh history and unit
variation. The numbers are a good starting point; the reader's own wall
wins where the two disagree.

## Decision 5 (superseded): `tone` is removed

**Reversed 2026-09-11.** `tone` is gone from the firmware, the renderer and
the documentation. The argument below was that it differs from a palette mix
because it resolves against `bgc` rather than naming a second ink outright.
That is true and turns out not to matter, because the difference is only ever
visible when it is a bug.

Rendered both ways and diffed, on the page background and on a filled rect
with `bgc` naming it correctly, `tone: "light"` is **pixel-identical** to
drawing the same glyph in a 50% mix of its ink and `bgc`. The only case where
the two differ is when `bgc` does *not* match what is underneath — and there
`tone` speckles the background into the fill, which is the footgun the spec
already warned about. A mix cannot do it, because a mix only ever touches
glyph pixels while `tone` repaints the whole glyph box.

So it was redundant when used correctly and uniquely dangerous when not. The
adaptivity that justified it — `bgc` defaulting to the document `bg`, so
toned text follows a changed background — is the same mechanism that causes
the speckle, and is not worth a second concept in the vocabulary.

Removed outright rather than deprecated: a parser that keeps a removed
feature alive is just a slower removal, and a deprecation note in `SPEC.md`
preserves exactly the confusion that prompted this.

The document version stays at **1**. Removing an op attribute is a breaking
change and the agreed mechanism for one is a version bump, but this panel has
a single user and no third-party documents in circulation, so bumping it
would fire a warning on every document that exists in order to report
something already known. The unknown-version machinery stays in the firmware
for a future break that earns it. (Decided 2026-09-11.)

The original reasoning follows, for the record.

### Original: `tone` stays; it is not the same thing as a palette mix

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

## Decision 8: palette names describe the colour, never the recipe

`mix` is the percentage of `c2`. With `c: black, c2: white` that makes a
*higher* number *lighter* — the opposite of the print convention, where "25%
black" is a pale tint. Naming an entry `grey-25` therefore tells the author
the wrong thing at exactly the moment they are choosing a colour.

This is not hypothetical. Coupon 3 filled its "quiet secondary panel" with
`grey-25` to sit behind black body text. `grey-25` is 75% black:

| entry | white | vs black text | |
|---|---|---|---|
| `grey-25` | 25% | **3.8:1** | large text only |
| `grey-50` | 50% | 6.5:1 | body text ok |
| `grey-75` | 75% | **9.3:1** | body text ok |

Judged on the wall: "okay close up though blends together into a dark grey
further away" — which is 3.8:1 described in words. The panel wanted
`grey-75`. The convention produced the mistake within hours of being
invented, and it fooled the author, the reviewer and the coupon.

So palette entries are named for **how they look**, not for their density:
`grey-light`, `grey-mid`, `grey-dark`. The rest of the palette already works
this way — `mustard`, `plum`, `navy`, `forest` are names, not recipes — and
the density belongs inside the entry where the author does not have to
reason about it. `check()` cannot catch this; only naming can.

## Decision 10: the named set is compiled in, and the palette can override it

A document writes `"c": "navy"` and it works, with no palette at all.

This was first decided the other way, on the grounds that only fonts, icons
and ops are compiled vocabulary and adding colours would make a rename a
reflash. That argument does not survive contact with the reason the set
exists. Fonts and icons *are* compiled vocabulary and the six inks are
already listed as such; named mixes are the same kind of thing, and "adding
one is a rebuild" is a cost this project already pays for icons.

The point of the named set is to remove a class of error from the caller. A
library the caller has to paste recipes from still lets them write `25`
where they meant `75` and get a silently wrong colour — the exact failure
decision 8 is about, and the one four coupons went to the wall to eliminate.
Making the names first-class removes it; documenting them does not.

Resolution order is **base inks → document `palette` → built-in mixes**. So
the six ink names stay immutable, a document can redefine `navy` or add
colours the firmware has never heard of, and everything else resolves to the
tested set for free. The escape hatch that made palette-only attractive is
preserved without the boilerplate.

Two consequences to hold:

- **The definition no longer travels in `meta.hash`.** A firmware that
  changed `navy`'s recipe would draw a document differently under an
  unchanged hash, and a device that had already shown it would 304 and stay
  stale. This is exactly as true of fonts and icons today, and is the
  accepted price of compiled vocabulary. The table is therefore a
  **permanent contract**: these twenty-one names mean these twenty-one
  recipes, and the way to break one later is to bump the document's `v`
  rather than to redefine a name in place. (Decided 2026-09-11.)

  That only works if something reads `v`, and as of today nothing does —
  `store.py` has a lone `setdefault("v", 1)` and neither the firmware nor
  the renderer looks at it. So the firmware now logs a warning when it meets
  a version it does not implement, and draws anyway: a wall rendered by a
  slightly wrong interpreter beats a blank one, and the warning is what
  makes the mismatch diagnosable instead of baffling.
- **The table exists twice**, in `display_list.h` and in
  `display_mcp.render`, and twenty-one entries transcribed between two
  languages is precisely where a typo hides and never gets noticed. It goes
  into the differential test alongside `mix_on`: extract the table from the
  shipped header, compare every name, recipe and density against the Python.

## Decision 11: a dithered glyph is judged by its better ink, not its blend

`check()`'s 3:1 contrast warning first used the **blend** of a mixed ink —
the colour the dither averages to. That is right for a fill and wrong for a
glyph, and the measurements say so.

A dithered glyph is drawn in two colours, one on some pixels and one on the
rest. It is discernible if **either** stands out from the ground, because the
contrasting pixels alone draw the letterform. So:

    contrast = max(ratio(ink.a, ground), ratio(ink.b, ground))

Against every case the panel has actually answered:

| case | blend | **max** | the wall |
|---|---|---|---|
| black/white 50 on white (the footer stamp) | 3.0 | **12.1** | legible |
| black/white 50 on black | 4.1 | **12.1** | legible |
| white/black 50 on black | 4.1 | **12.1** | legible |
| red/white 50 on pink | 1.0 | **2.4** | poor |
| yellow/white 50 on white | 1.3 | **1.6** | poor |
| | 4/5 | **5/5** | |

The blend model warns on the project's own shipping footer at 2.98:1 — true
about the arithmetic, wrong about the panel, because a 50% glyph keeps its
stroke structure and is not averaged the way a large fill is. Solid inks are
unaffected: `max` over two identical colours is that colour.

### The ground gets the opposite treatment, for the same reason

Added 2026-09-11, finishing the model. `max` is right for the glyph and
wrong for the ground, and the asymmetry is not a fudge — it is the sentence
from decision 3: *a large fill averages the two; a 3 px stem has too few
pixels to average.* A ground is a fill. It fuses. So a mixed ground is
judged as the one colour it fuses to, and only the glyph gets to pick its
better ink.

The implementation first sampled the ground as the **most common pixel**
under the op's box, which on a 50% mix is a coin toss: the two inks are
tied 50/50 and the tie-break alone decided the answer. White `lg` text on
`grey-mid` scored **12.06:1 (silent)** or **1.00:1 (warns)** depending on
which way the tie fell — it happened to fall on black, so `check()` said
nothing. Neither number is the truth. Fused, the ground is `#7F7F7C` and
the ratio is **2.95:1**, which is what SPEC.md's mid-tone tier has been
publishing for that colour all along; the check simply could not reproduce
its own spec.

`max` on the ground as well was the tempting symmetry and it is wrong. It
takes the best of four pairings, so almost nothing would warn — and it
passes the one mixed-ground case the wall has judged. **red/white 50 on
pink** (the table above, "poor") is the proof: paint it and every pixel of
the glyph differs from the pixel beneath it, because the mask has absolute
phase and the two mixes land in counter-phase. No per-pixel rule, however
careful, can fault it. It is poor because the letterform fuses to the same
colour the ground fuses to. Fusing the ground scores it 2.4:1 and warns.

What "fuses" means is a matter of scale, and getting that wrong costs a
false positive: averaging the whole box would fuse two *regions* the eye
resolves perfectly well. `samples/display.json` ops[43] is a white `check`
icon that sits on a green rect and overlaps the white page at one edge —
box-averaged it warns at 2.8:1 against a mid colour that is nowhere on the
canvas. So the sample is per **2x2 mask tile**, the mask's whole period
(decision 2) and 0.34 mm on the glass, aligned to the mask's own absolute
phase; tiles are fused, and then the tile colour covering most of the box
wins. Most-common was never the wrong idea, only the wrong scale. Where
tile colours genuinely tie — a box sitting half on one rect, half on
another — the harder half is the answer rather than either coin face, the
same rule a wrapped text block already follows across its lines.

### And a second check, because contrast cannot see everything

Contrast measures *marginal* legibility. It cannot detect *absolute*
invisibility, and there is a real instance: a glyph drawn over a ground that
is a mix of its own two inks lands in phase with it and becomes pixel-
identical to its background. Every contrast model scores that a comfortable
4.1:1 and passes it, correctly — contrast is not what is wrong.

So rather than model mask phase, observe the result: snapshot the op's box,
draw, compare, and warn if not one pixel changed. That is more reliable than
reasoning about phase and it generalises to anything else that draws nothing
— text in its ground's own colour, an icon that never appears.

The two divide cleanly. **Contrast catches marginal, drew-nothing catches
absolute.**

## Still open

- A closing coupon that names the officially supported set. The user's idea,
  and the right last step: one page showing every mix that survives, each
  labelled with the name it will carry in `SPEC.md`, judged on the wall so
  the names come from the glass rather than from an ink table. `brown`
  (red+green) is the open case — judged "a bit mustardy but I'd still
  consider it brown", so it either keeps the name or takes a better one.
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
