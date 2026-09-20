# Display list — spec

A few KB of JSON describing what to draw. The firmware is a renderer, not a
design: layout lives entirely in the document, so changing the dashboard is a
file edit. Only the **vocabulary** — six font sizes, eleven icons, eight ops —
is compiled in, and changing that is a rebuild.

Two implementations must agree:

| | |
|---|---|
| `display_list.h` | runs on the panel. **Authoritative.** |
| `display_mcp.render` (`display-mcp-cli`) | renders a PNG so you can look before flashing |

The wrap and truncate logic, and `poly`'s fill and outline (the "poly"
section below), are differentially tested between them. Everything else
is eyeball parity.

## Document

```json
{
  "v": 1,
  "meta": { "generated": "...", "hash": "1c772cd7a6ebc2c7" },
  "bg": "white",
  "palette": { "accent": "red", "work": "blue" },
  "ops": [ ... ]
}
```

`meta.hash` is the identity of what the document *draws* — see *Change
detection*. `set_display` stamps it, and also stamps `meta.generated` to the
moment of that publish. `display-mcp-cli stamp`, on a file on disk, writes
`meta.hash` only and leaves `generated` exactly as it found it — absent
stays absent, present stays whatever it was. This is deliberate, not an
oversight: `generated` means *published at*, and a file on disk has not
been published — it may be headed for `set_display`, or it may be served
straight off disk (see *Workflow*) or read by a tool that never touches the
store at all, and none of those are a publish event `stamp` could honestly
record. `Store.publish()` stays the only code path that stamps either field
of `meta`; see `docs/PLAN.md`.

Because `meta.hash` deliberately excludes `generated` (see *Change
detection*), this costs nothing on identity: `stamp` run twice on an
unchanged file is a true no-op — byte-identical output — while `set_display`
run twice on identical content always moves `generated` and still produces
the same hash. Two documents that hash the same but differ in `generated`
are not a bug in either path; they're the point of excluding it.

Anything else under `meta` is the author's and is read by nothing here — in
particular there is no `ttl`: the wake interval is the panel's own hourly
schedule, not something the document controls.

`palette` maps your names onto the six inks, so restyling is one line rather
than a find-and-replace through every op. Aliases resolve up to 8 hops; a
cycle falls back to black with a warning rather than hanging.

Canvas is **1200 × 1600**, origin top-left, y down.

## Ops

Every op takes `c` (an ink, a built-in mix, or a palette name; default
`black`). One bad entry never takes down the whole render, but the two
failures look different on the wall and it is worth knowing which you are
looking at:

- an unknown **op, font or icon** logs a warning and **skips that op** — the
  text or icon simply is not there
- an unknown **colour** logs a warning and **falls back to black**; the op
  still draws

So a typo'd font makes something vanish, while a typo'd colour leaves it
present and black. If an element is missing entirely, suspect `f` or `n`,
not `c`.

| op | fields | notes |
|---|---|---|
| `rect` | `x y w h` · `fill` (default true) · `t` · `r` | `fill: false` draws an outline `t` px thick; see below |
| `line` | `x y x2 y2` · `t` | thickness works on H/V lines; diagonals thicken vertically only |
| `circle` | `x y r` · `fill` (default true) · `t` | `x,y` is the centre |
| `text` | `x y s f` · `a` · `w` · `wrap` · `lines` · `lh` · `deco` | see below |
| `icon` | `x y n z` · `bgc` | `n` = icon name, `z` = slot or its px count (default `md`), `x,y` = top-left |
| `fmt` | `x y s` · `f` · `a` | `text` without wrap whose `s` is a template of system fields: `{hash}` `{hash16}` `{time}` `{time24}` `{battery}` `{battv}`; `f` defaults to `xs` |
| `sprite` | `x y cell rows palette` · `mirror` | pixel art — a grid of characters, one `palette` entry per colour; no `c` (see below) |
| `poly` | `pts` · `c` · `fill` (default true) · `t` | a point list; `fill: false` draws an outline `t` px thick |

### rect

`r` (integer ≥ 0, default 0) rounds a **filled** rect's corners, clamped to
`(min(w, h) - 1) // 2` with a warning if it was larger — a corner disc is
`2r + 1` px across, so `min(w, h) // 2` itself can ink one row or column
past the box on an even `w` or `h`. A non-integer `r` warns and is treated
as 0. `r` on an unfilled rect (`fill: false`) is a warning and draws the
square-cornered outline unchanged — arcs on an outline aren't worth a
second drawing routine.

### text

`x,y` is the anchor and the **top** of the glyph box. `a` is `left` (default),
`center` or `right` — it moves what `x` means, not `y`.

`w` sets a maximum width and is worth setting on anything that comes from a
calendar or a todo list:

- `w` alone → truncate with an ellipsis, never splitting a UTF-8 codepoint
- `w` + `wrap: true` → greedy word wrap to `lines` (default 2), last line
  ellipsized if it overruns, and every line clipped to `w` so a single long
  word can't escape the box
- `lh` overrides line height (default ≈ 1.24 × font height)

`deco` (`text` only, not `fmt`) draws one filled rule under (`"underline"`)
or through (`"strike"`) every line the op prints, in the op's own colour.
The rule spans the line's layout width as the renderer measures it, under
whatever `a` says — a trailing space lengthens it, and the panel's own
measurement can differ from the preview's by a few px at the right edge,
the same eyeball parity the text's own position already has.

Thickness is never 1 px (a hairline rule can't hold a mixed ink) and is
fixed per font slot, from the compiled face's own line height — FreeType's,
which is 1 px under `describe().fonts[*].cell_height` on some faces, so it
is not simply `size / 14`:

| face | `xs` | `sm` | `md` | `lg` | `xl` | `mono/24` |
|---|---|---|---|---|---|---|
| thickness (px) | 2 | 2 | 3 | 4 | 7 | 2 |

An underline sits just below the baseline — like a browser's own
underline, it crosses descenders (`p`, `y`, `g`) rather than clearing them.
A strike sits through the x-height, in the upper third of the lowercase.
Absent or `null` means no decoration; any other value — the wrong type, or
a string that isn't one of the two — logs a warning naming the value and
draws the line plain, the same warn-and-degrade shape as everything else in
this file.

### icon

Nineteen names, each compiled at the same five slots a font uses —
`xs` 22 · `sm` 28 · `md` 36 · `lg` 48 · `xl` 84 — so `z` takes the slot or
its pixel count, exactly as `f` does (`check/lg` and `check/48` are the
same bitmap); the slot spelling is canonical, `describe().icons` lists
every name's slots and `describe().icon_aliases` lists the five px
spellings. `z` defaults to `md` (36 px). There is no icon ladder beyond
those five: a name/size pair that isn't one of them logs and skips, the
same as an unknown op or font.

Eleven names come from Material Design Icons, compiled in by name so
there are no codepoints to get wrong: `weather-sunny`,
`weather-partly-cloudy`, `weather-cloudy`, `weather-rainy`,
`weather-snowy`, `weather-night`, `check`, `map-marker`, `clock`, `alert`,
`battery`. Eight more are lucide icons named for a family activity —
`school-day`, `daycare`, `taekwondo`, `swim`, `helper`, `appointment`,
`family-meeting`, `closed` — rasterised once to committed 1-bit PNGs that
the firmware compiles and the preview blits, so these nineteen are the
first icons with real preview parity rather than a procedural stand-in.

`bgc` is accepted but ignored: every compiled icon is transparent
(`transparency: chroma_key`), so the pixels its glyph doesn't set are left
alone and whatever is already on the canvas shows through, regardless of
what `bgc` says.

### fmt

`text` without wrap whose `s` is a template. Fields are substituted at draw
time and never appear in the document, so `meta.hash` covers where and how
the line is drawn, never what it says:

| field | value |
|---|---|
| `{hash}` | last 5 characters of `meta.hash` (`no hash` if unstamped) |
| `{hash16}` | all 16 |
| `{time}` | when the panel drew this, `1:43 PM`, from its own clock (`--:--` until SNTP has synced) |
| `{time24}` | same, `13:43` |
| `{battery}` | the panel's battery as a percentage, `82%` (the preview shows a stand-in) |
| `{battv}` | the pack voltage, `3.9V` (stand-in in the preview) |

An unknown `{field}` is left literal and is a warning from `validate`, so
new fields can be added to the firmware and the preview without breaking
older documents. The footer the sample uses, with the stamp — hash, time,
battery — drawn in `grey-mid` since it is secondary to the date line
beside it:

```json
{"op": "text", "x": 48,   "y": 1552, "s": "Updated: 6:31 AM", "f": "xs"}
{"op": "fmt",  "x": 1045, "y": 1552, "s": "{hash}@{time24}", "f": "xs", "a": "right", "c": "grey-mid"}
{"op": "icon", "x": 1058, "y": 1545, "n": "battery", "z": "md", "c": "grey-mid"}
{"op": "fmt",  "x": 1100, "y": 1552, "s": "{battery}", "f": "xs", "c": "grey-mid"}
```

The percentage is left-aligned after the icon so its varying width never
moves the icon; the stamp is right-aligned against a fixed x for the same
reason.

A 304 never draws, so the stamp stays at the last real draw; that is the
point of it.

### sprite

Pixel art as rows of characters — one `cell` × `cell` square per character,
`palette` mapping each character to a colour name:

```json
{"op": "sprite", "x": 40, "y": 220, "cell": 40,
 "palette": {"K": "black", "O": "navy", "Y": "yellow"},
 "rows": [".........KK......KK.........",
          "........KOOK....KOOK........"],
 "mirror": "x"}
```

`x,y` is the top-left of the grid. `cell` is required and an integer ≥ 1.
`rows` is required, one string per grid row, one character per cell — rows
of different lengths are **ragged**: `check()` warns once and short rows are
padded transparent on the right. `palette` is required, a single character
mapped to a colour **name** — resolved exactly the way any other op's `c`
is (base ink → document `palette` → built-in mix) — **never** an inline
`{c, c2, mix}` object; a mix goes in the document's own `palette` and the
sprite entry names it, the same as everywhere else. `mirror`, if present,
must be `"x"`: every row is reversed before drawing, the wing-mirroring
case free of charge; any other value warns and is not mirrored.

There is no `c` on a sprite — colour is entirely `palette`'s job, and
writing `c` here is an ordinary "no such field" warning like any other
stray key.

`.` and space are always transparent (nothing drawn there) and cannot be
redefined by `palette`; trying to is a warning. A `palette` key that isn't
exactly one character is skipped with a warning and ignored — a character
in `rows` that uses it then falls into the next rule. A character that
appears in `rows` but has no `palette` entry draws black and is a warning,
once per distinct character — the same "unknown falls back to black" rule
as any other colour, and visible on the wall rather than silently skipped.
A `cell` under 1 or over 1600 (`max(WIDTH, HEIGHT)`), `rows` that isn't a
list of strings, or a `palette` that isn't an object each warn once and
skip the whole op — nothing sensible to draw — the one place a bad field
skips rather than drawing something anyway, mirroring the firmware, which
cannot draw a grid it cannot parse either. A mixed colour on a `cell`
under 2 px still can't carry a 25%/75% density, exactly as a thin rect
fill can't — see "Mixes" below.

### poly

A point list — a triangle, a chevron, an arrow, a ground shadow — filled or
outlined:

```json
{"op": "poly", "pts": [[100, 100], [300, 100], [200, 260]], "c": "navy"}
```

`pts` is required: at least three `[x, y]` integer pairs; fewer than three,
or any element that isn't exactly one, is malformed and the whole op is
skipped with one warning — nothing sensible to draw, the same rule
`sprite`'s `cell`/`rows`/`palette` are held to. `c` is an ordinary op
colour (default `black`). `fill` defaults to `true`; `t` (default `1`) is
read only for the outline.

**Filled**, both implementations paint the identical set of pixels: an
even-odd scanline fill, not left to PIL or to whatever the firmware's own
polygon primitive would do (there isn't one). For each integer scanline `y`
from `min(ys)` to `max(ys)` inclusive, every edge of the closed point list
— consecutive points, plus the edge closing the last back to the first —
with `y0 != y1` contributes a crossing when `y` is in
`[min(y0, y1), max(y0, y1))` — half-open, so a vertex two edges share is
counted on exactly one of them — at
`x = x0 + (y - y0) * (x1 - x0) // (y1 - y0)`, floor division (rounding
toward negative infinity for a negative operand on either side; Python's
`//` already means that, the firmware reaches for a small sign-correct
`floor_div()` since its `/` truncates toward zero instead). Crossings on a
scanline are sorted and filled in pairs, **inclusive** of both ends, as
horizontal runs — through the same dithering path a `rect` fill uses, so a
mixed `c` interleaves with the same absolute phase. This makes x and y
asymmetric: x-spans are inclusive of both ends but the scanline itself is
half-open, so a poly matching `rect x,y,w,h`'s box puts its points at
`x`/`x+w-1` on the sides but `y`/`y+h` — not `y+h-1` — on the top/bottom.

**Outlined** (`fill: false`): every edge, including the one closing the
shape, drawn `t` px thick — the same primitive and thickness rule the
`line` op uses.

Off-canvas is judged on the bounding box of every point — `min`/`max` of
`pts`, the same ±64px tolerance every other op's `x`/`y` gets — since a
poly has no single anchor of its own to check.

`tests/parity/test_poly.py` extracts the C++ scanline function
(`poly_spans()`) and the outline's own line-walking primitive, compiles
them, and diffs both the fill and the outline pixel-for-pixel against
`display_mcp.render` over convex, concave and self-touching shapes.

## Device-safety bounds

Decided in `docs/plans/firmware-bounds.md`, after a sprite whose grid
exceeded internal SRAM crashed the panel on every wake
(`docs/plans/wake-sleep-flow.md`). Over-limit content is skipped with a
warning, never rejected at publish time (warnings never block a publish)
and never drawn wrong — the panel only ever skips, it never reboots.
`display_mcp.render.check()` warns identically, so the author sees it at
`validate`/`set_display` time, before the panel ever fetches the document.

- **Coordinate bound.** Every coordinate and size field of every op — `x`,
  `y`, `w`, `h`, `x2`, `y2`, `r`, `text`'s `lh`, each `poly` point, and a
  `sprite`'s pixel box (`x + cols*cell`, `y + rows*cell`) — must satisfy
  `|v| <= 4096`, more than twice the canvas on either axis; read as a
  64-bit float and bound-checked before it's ever narrowed to an integer,
  so a value too large (or non-integral) for a 32-bit int can't quietly
  read as zero and draw somewhere unintended. Past the bound, the op is
  skipped; a legal fractional value truncates toward zero. This one bound
  does *not* make every op's worst-case cost the same — see "what 4096
  actually costs" below.
- **Text length.** `text.s` and `fmt.s` (the template, before expansion)
  longer than 512 bytes skips the op. Wrapped `lines` past 64 is clamped
  to 64, not skipped.
- **Sprite grid.** At most 1200 columns, 1600 rows, and 64 distinct
  palette entries; past any of the three, the whole op is skipped. The
  "no palette entry for X" warning is itself capped at eight distinct
  characters plus one "...and more" line, so a sprite with many stray
  characters can't flood the warning list — nor the underlying set that
  tracks which characters have already been warned about.
- **Poly points.** At most 1024 points in `pts`; past it, the whole op is
  skipped (a distinct message from "fewer than three points").
- **Rect clipping.** A filled rect's fill, and each of a rounded rect's
  straight bands, are clipped to the canvas before drawing — the output is
  unchanged (a fill is purely position-based) but a rect that reaches well
  off canvas costs no more than the visible canvas itself. The four corner
  circles of a rounded rect are not separately clipped.
- **Line clipping.** Every segment `line` and `poly`'s outline draw is
  clipped (Cohen-Sutherland) to the canvas expanded by the thickness bound
  before it's walked — without it, an outline built from many long edges
  at heavy thickness could walk a diagonal millions of pixels long, per
  edge. Moving a clipped endpoint onto the boundary can shift a boundary
  pixel by one from what an *unclipped* walk would have drawn, which is
  within the existing eyeball-parity tolerance `line`/`rect` outlines
  already have with the preview — but the clip's own intersection math
  uses the same sign-correct floor division as the poly fill's own
  scanline (`floor_div()`/`//`, not `/`), on both sides, precisely so
  `poly`'s outline — the one draw here held to pixel-exact parity, not
  eyeball — stays exact through the clip too, not just up to it.
- **What 4096 actually costs.** The coordinate bound alone does not put
  every op's worst case in the same ballpark: a clipped rect fill costs at
  most the canvas itself (~1.92M px); an unclipped filled circle at
  `r == 4096` costs ~52.7M px (~2.6s); a rounded rect's corner circles are
  the same shape at a smaller radius; a sprite whose pixel box spans the
  full range on both axes costs up to ~67M px (~3.4s); a poly outline at
  the legal worst case (1024 edges, thickness 64), clipped to the real
  1200x1600 canvas, is the largest of the lot at ~87.0M px (~4.35s). The
  real safety argument is the draw budget and watchdog below, not a
  single per-op ceiling — 20s plus the ~4.4s worst single op still lands
  well inside the 30s watchdog.
- **Draw budget.** The panel's op loop reads its own clock once at entry
  and again before every op; past 20 seconds elapsed it logs a warning,
  stops, and draws whatever it already has. This is the backstop under a
  30 second task-watchdog timeout, not a substitute for the per-op bounds
  above — those are what keep any *single* op far under either number.
  There is no Python mirror: the preview has no device clock to measure
  against.
- **Document size.** 64 KB, enforced by the server at publish time and by
  the panel's own HTTP response buffer — see *Server* and the YAML's
  `max_response_buffer_size`, which a parity test asserts equals the
  server's own ceiling (parsed with ESPHome's own decimal, not binary,
  metric prefixes — "64kB" would silently mean 64000 bytes, not 65536).

## Vocabulary

**Fonts** — four families, `petrona`, `instrument` (Instrument Sans),
`karla`, each in regular/`-bold`/`-italic`, plus `mono` (JetBrains Mono,
regular only) — 110 faces, eleven sizes apiece: the five slots `xs` 22,
`sm` 28, `md` 36, `lg` 48, `xl` 84, plus 24 26 32 40 44 54 as pixel-only
sizes with no slot name. Adding a size or a family is a rebuild, so the
scale is a commitment. Every face compiles GF_Latin_Core; `mono` also
compiles box drawing and block elements (U+2500–U+259F) — a character
outside that set previews fine and silently has no glyph on the wall,
which `check()` warns about.

**Icons** — nineteen names, each at the same five slots fonts use (`xs`
22, `sm` 28, `md` 36, `lg` 48, `xl` 84 px): eleven Material Design icons —
`weather-{sunny,partly-cloudy,cloudy,rainy,snowy,night}`, `check`,
`map-marker`, `clock`, `alert`, `battery` — and eight lucide activity
icons, rasterised to committed PNGs rather than compiled from an `mdi:`
name — `school-day`, `daycare`, `taekwondo`, `swim`, `helper`,
`appointment`, `family-meeting`, `closed`.

**Colours** — six inks, `black white yellow red blue green`, plus any
two-ink **mix** declared in the palette (below). Nothing else exists.

**Ops** — `rect`, `line`, `circle`, `text`, `icon`, `fmt`, `sprite`, `poly`.
Eight, compiled in; adding one is a rebuild.

## Mixes

The panel has six inks and no grey. Any two of them can be interleaved on a
1 px checkerboard, which fuses into a third colour at reading distance. The
tested ones are named and built in (below); to define your own, or to
redefine a built-in name, a palette entry may be an object instead of an
alias:

```json
"palette": {
  "accent": "red",
  "navy":   {"c": "black", "c2": "blue",  "mix": 50},
  "grey-light": {"c": "black", "c2": "white", "mix": 75}
}
```

| field | | |
|---|---|---|
| `c` | required | base ink |
| `c2` | required | second ink |
| `mix` | default `50` | percentage of **`c2`**, one of 25 / 50 / 75 |

A mix is legal anywhere an ink name is: `c`, `bgc`, and the document `bg`.
`c` and `c2` may be palette aliases but may not themselves be mixes. A
malformed entry warns and draws something rather than skipping the op —
`mix` outside 25/50/75 rounds to the nearest, a missing `c2` draws solid.

Two things bite if you don't know them:

- **`mix` is the share of `c2`, not of the ink.** With `c: black, c2: white`
  a *higher* number is *lighter*. This reads backwards to print habits where
  "25% black" is a pale tint, so name entries for how they look —
  `grey-light`, not `grey-75`.
- **A feature thinner than 2 px can't carry 25% or 75%.** The mask is 2×2,
  so a 1 px run samples one row of it: at 25% it renders at 0% or 50%
  depending on its coordinate parity, at 75% at 50% or 100%. Only 50% is
  parity-independent. Rules and hairlines want 50%, or 2 px.

## The named palette

These are **built in** — write `"c": "navy"` and it works, no palette entry
needed. They are combinations that have been drawn on a real panel and
judged, grouped by what each turned out to be good for. The hex is what the
dither averages to at reading distance — not a colour the panel makes at any
single pixel. It is also exactly what the MCP `preview` tool paints for that
name — a test renders all twenty-one and compares them against this table,
parsed from this file, so the two cannot drift apart.

Names resolve **base inks → document `palette` → built-in mixes**, so the six
ink names are immutable, and a document that declares its own `navy` shadows
the one below.

The tiers below answer one question: **what text reads well when this colour
fills the space behind it** — a rect, a bar, a panel. That is not the same
question as whether the colour works *as* the text itself, and the two can
disagree sharply. `grey-mid` is a bad colour to put text on — black text over
it is only 4.1:1 — while `grey-mid` used *as* the text, sitting on the white
page, is 12.1:1, which is exactly what the footer stamp is. A mixed glyph is
legible when **either** of its two inks stands out from whatever is behind
it, because those pixels alone draw the letterform; a fill has to carry a
whole colour against whatever sits on top of it. A mixed *background* is
therefore judged as the single colour it fuses to — the hex in these tables
— since a fill has pixels enough to average and a glyph does not. So read a tier as advice
about backgrounds, and judge a mix used as text by its own contrast against
whatever it's sitting on.

**Dark backgrounds — put white text on these**

| name | recipe | hex | | name | recipe | hex |
|---|---|---|---|---|---|---|
| `navy` | black+blue 50 | `#272F50` | | `teal` | blue+green 50 | `#3B5561` |
| `maroon` | black+red 50 | `#5E2725` | | `brown` | red+green 50 | `#724D36` |
| `plum` | red+blue 50 | `#653655` | | `grey-dark` | black+white 25 | `#50504E` |
| `forest` | black+green 50 | `#344631` | | | | |

**Light backgrounds — put black text on these**

| name | recipe | hex | | name | recipe | hex |
|---|---|---|---|---|---|---|
| `cream-pale` | yellow+white 75 | `#DAD2AD` | | `grey-light` | black+white 75 | `#AEAEAA` |
| `cream` | yellow+white 50 | `#D6C582` | | `sage` | green+white 50 | `#93A58D` |
| `sage-pale` | green+white 75 | `#B8C2B2` | | `pink` | red+white 50 | `#BD8681` |
| `slate-pale` | blue+white 75 | `#B2B6C2` | | `slate` | blue+white 50 | `#868EAC` |
| `pink-pale` | red+white 75 | `#CEB2AC` | | `chartreuse` | yellow+green 50 | `#8B8C37` |

**Mid-tone — don't put text on these; black and white both fall short (3–4:1)**

| name | recipe | hex | | name | recipe | hex |
|---|---|---|---|---|---|---|
| `grey-mid` | black+white 50 | `#7F7F7C` | | `orange` | yellow+red 50 | `#B56D2B` |
| `mustard` | black+yellow 50 | `#776626` | | `olive` | yellow+blue 50 | `#7E7556` |

**None of this is a whitelist.** Every ink pair and every density is
available inline, no permission needed; these are what each turned out to be
good for, not rules about what is allowed. Judge anything else the way these
were judged — see below.

Measurements are best case: the renderer's ink approximations, one panel,
one room. E-paper is reflective, so appearance tracks ambient light in a way
an emissive screen does not, and shifts with viewing angle, temperature,
refresh history and unit variance. Where your wall disagrees, trust the wall.

## Designing for six inks

**Contrast is the whole rule.** Every font size here qualifies as WCAG large
text (the smallest, `xs`, is 22 px bold), so **3:1** is the floor and
`check()` warns below it. Ratios on the ink table:

|  | black | white | yellow | red | blue | green |
|---|---|---|---|---|---|---|
| **black** | — | 12.06 | 7.42 | 2.20 | 1.64 | 2.71 |
| **white** | 12.06 | — | 1.63 | 5.48 | 7.34 | 4.44 |
| **yellow** | 7.42 | 1.63 | — | 3.37 | 4.52 | 2.73 |
| **red** | 2.20 | 5.48 | 3.37 | — | 1.34 | 1.23 |
| **blue** | 1.64 | 7.34 | 4.52 | 1.34 | — | 1.65 |
| **green** | 2.71 | 4.44 | 2.73 | 1.23 | 1.65 | — |

The real trap is **dark on dark**: red/blue 1.34, red/green 1.23, blue/green
1.65, black/blue 1.64. Those are the combinations that look reasonable in a
document and vanish on the wall.

Yellow is not a fill-only ink — it is 1.63:1 on white and 7.42:1 on black,
better than red on white. The problem was always the background, not the
ink. Likewise small coloured text reads fine; blue on white (7.34) beats red
(5.48).

Two things contrast doesn't cover:

- **A mixed glyph shifts toward its lighter ink.** A large fill averages its
  two inks; a glyph has too few pixels to average. `yellow+red` reads as
  proper orange as a swatch and noticeably yellowish as text. Mixes whose
  inks are close in luminance — `plum`, `brown`, `navy`, `maroon`, `forest`
  — hold their hue as text; `check()` warns about the rest.
- **No gradients, no anti-aliasing to hide behind.** Flat fills and real
  whitespace do the work.

## Workflow

This is the local CLI loop — for working on a file on disk without the MCP
tools attached (firmware development, offline checks, CI). An MCP caller
does not have a shell and instead runs `validate` → `preview` →
`set_display` → `status`, exactly as `compose_display` describes; the CLI
and the server share one renderer (`display_mcp.render`), so what `check`
reports and what `preview` returns cannot drift apart between the two paths.

```bash
display-mcp-cli stamp display.json                   # write meta.hash
display-mcp-cli render display.json -o preview.png   # look at it
display-mcp-cli publish display.json     # on the host: publish via the loopback MCP endpoint
display-mcp-cli check display.json                   # validate, no render
```

The render uses approximate *ink* colours, so it looks like the wall rather
than like a screen. The eight lucide activity icons blit the same committed
PNG the firmware compiles — real artwork, not a stand-in. The eleven MDI
icons are still procedural stand-ins — good for judging layout and weight,
not artwork.

The CLI always dithers mixes the way the panel does, which is what you want
when checking against firmware. Be aware that a 1 px checkerboard aliases to
a solid patch of just one of its two inks in any viewer that scales the PNG
down, so zoom to 100% before judging a mix's colour. The MCP `preview` tool
defaults to the opposite trade-off — it flattens each mix to the hex in the
named-palette table above — because its reader cannot zoom.

Then publish it with `set_display`, or drop it at the URL in
`firmware/epaper-schedule.yaml` and press *Fetch and draw*.

## Change detection

One value does both jobs. `meta.hash` is a hash of `bg` + `palette` + `ops`
only — deliberately **not** of the whole file, so a fresh `meta.generated`
timestamp on an otherwise identical document costs nothing.

```python
core  = {k: doc.get(k) for k in ("bg", "palette", "ops")}
canon = json.dumps(core, sort_keys=True, separators=(",", ":"))
h     = hashlib.sha256(canon.encode()).hexdigest()[:16]
```

Serve that same value as the ETag (`ETag: "1c772cd7a6ebc2c7"`) and put it in
`meta.hash`. Then:

- The device sends `If-None-Match` with the id it is currently showing. A
  match gets a **304** — no body, no parse, no refresh.
- On a **200** it reads `meta.hash` and compares. Different means redraw;
  identical means the server's ETag disagreed with its own content, and
  `meta.hash` saved the refresh anyway.

The device never reads the `ETag` response header. There is one identity, it
lives in the document, and the header is just how the server is told about it.

There is **no fallback**. A document without `meta.hash` is a server bug, and
hashing the raw bytes instead would quietly hide the fact that every wake is
doing a full refresh. So the device redraws unconditionally and logs an ERROR
naming the cost. `display-mcp-cli check` fails the same way, which is where you
want to find it.

What the log tells you:

| line | meaning |
|---|---|
| `unchanged (304)` | the ETag matched; nothing transferred |
| `its ETag does not match meta.hash` | server ETag is mtime-derived; fix it at the source |
| `BUG: document has no meta.hash` | refreshing every wake; ~36 mAh/day, roughly half your runtime |

No `online_image`, so none of the 3.84 MB PSRAM decode buffer. The panel
framebuffer still needs PSRAM.

## Server

`server/` is the Pi side: one process with two listeners on deliberately
different interfaces.

| | |
|---|---|
| `127.0.0.1:8001/mcp` | Claude writes here, via a Cloudflare Tunnel |
| `<host-lan-ip>:8080/display.json` | the panel reads here, LAN only |

Ten tools: `set_display(document)` validates, stamps `meta.hash` and
`meta.generated`, and writes atomically; `copy_display(source, name)`
republishes `source`'s document under `name` unchanged — same hash, fresh
`generated` — without resending the body; `validate(document)` runs the same
checks without rendering or publishing, and also returns the effective
colour of every name the document references and the document byte
ceiling; `preview(document)` returns a PNG plus `check()`'s warnings — the
same `display_mcp.render` behind both, so what Claude sees and what
`validate` reports cannot disagree; `get_display(name)` returns what's
currently published; `status(name)` says whether the panel has collected it
— `recent_fetch_status: 304` is the healthy answer; `clear_display(name)`
unpublishes; `describe()` returns the op vocabulary — inks, mixes, fonts,
icons, per-op fields — as one JSON object built from the renderer's own
tables; `guide()` returns the prose composing guide as plain text;
`swatches(document?, include_document=False)` returns a flat PNG of every
ink and built-in mix as a labelled chip, plus `document`'s own palette
appended — the sheet is itself a document; pass `include_document=True` to
get it as a third block and `set_display` it, putting every one of those
colours on the wall.

The panel endpoint is read-only and unauthenticated on purpose. The worst case
is a neighbour reading your schedule; everything that *writes* is behind
Cloudflare. `Store.publish()` — behind `set_display` and `copy_display` —
is the only thing that stamps a hash, so writing
`/var/lib/display-mcp/default.json` by hand is what produces the
`BUG: document has no meta.hash` line on the device.

`deploy/setup.sh install` does the whole thing and is safe to re-run; `sync`
is the code-only redeploy; `uninstall` puts the machine back. `--dry-run`
prints the plan. `docs/RUNBOOK.md` is the same sequence with a gate on each
step, which is where to look when one of them fails.

## Testing

- `firmware/epaper-schedule.yaml` validates under `esphome config` and builds
  under ESPHome 2026.8.2 with `philippwaller/esphome-epaper-spectra6-133`
  v0.5.0; the Google Fonts and MDI entries resolve and download.
- `fit_line`, `wrap` and `utf8_prev` are extracted from the shipped header,
  compiled, and diffed against the Python across 12 cases including multibyte
  truncation and overlong single words. Identical.
- `firmware/display_list.h` compiled against real ESPHome headers unmodified
  on its first build (2026-09-09) and has been verified on the panel: a full
  document parses and draws, an unchanged hash skips the refresh, a changed
  hash triggers one. Two things bit in the YAML rather than the header:
  templated request-header lambdas must return `const char*`, and
  `http_request.get` truncates captured bodies at 1 kB unless
  `max_response_buffer_size` is raised.
