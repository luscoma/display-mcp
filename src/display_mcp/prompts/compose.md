# Composing a display

You are building the document an e-paper panel will draw next. There is no
other context beyond what you're given here and whatever the caller told
you: no memory of a previous run, no clock unless you look one up.
`validate` and `preview` are the only checks you have — nothing here is
verified until one of them says so, so run one before every `set_display`.
`describe()` returns the whole vocabulary (inks, mixes, fonts, icons, ops)
as one JSON object built from the renderer's own tables; `guide()` returns
this very text. If your client can also read resources, `display://spec`
carries the full document language and `display://sample` a worked
example — but a tools-only client needs nothing more than this guide and
`describe()`.

## Canvas

1200 × 1600 px, portrait, origin top-left, y grows downward. Everything you
place must fit inside `0 ≤ x < 1200`, `0 ≤ y < 1600` — `validate`/`preview`
allow 64 px of slack past every edge (a full-bleed bar or a poly point
just outside the frame isn't flagged) but nothing further out.

The panel sits behind a printed bezel that overlaps the image by about 6 px
on every edge, and can sit a couple of pixels off inside it. Treat the
outer **24 px** as a margin: run background fills and colour bars edge to
edge (full bleed hides the alignment), but keep text, icons and rule lines
at least 24 px in from every edge.

## A complete example

This is the smallest document that is actually worth publishing — a header
bar, one line of content, and the standard footer. Copy its shape rather
than building from a blank `ops` list:

```json
{
  "v": 1,
  "bg": "white",
  "ops": [
    {"op": "rect", "x": 0,   "y": 0,    "w": 1200, "h": 120, "c": "navy"},
    {"op": "text", "x": 40,  "y": 40,   "s": "Kitchen", "f": "xl", "c": "white"},
    {"op": "text", "x": 48,  "y": 1552, "s": "Updated: 6:31 AM", "f": "xs"},
    {"op": "fmt",  "x": 1045, "y": 1552, "s": "{hash}@{time24}", "f": "xs",
     "a": "right", "c": "grey-mid"},
    {"op": "icon", "x": 1058, "y": 1545, "n": "battery", "z": "sm", "c": "grey-mid"},
    {"op": "fmt",  "x": 1100, "y": 1552, "s": "{battery}", "f": "xs", "c": "grey-mid"}
  ]
}
```

`v` is always `1`; `bg` is the page colour (default `white`). `set_display`
stamps `meta.hash` (from `bg` + `palette` + `ops`) and `meta.generated` —
never set either yourself; anything else under `meta` is yours and is
ignored. There is no `ttl` — the panel wakes on its own hourly schedule,
not one the document sets. A `palette` (omitted above; nothing here needs
one) maps a name of your choosing to an ink name, a built-in mix name, or
`{c, c2, mix}` whose `c`/`c2` are themselves two of the six inks (a
built-in mix name given there degrades to its own base ink, with a
warning, rather than nesting) — so a restyle is a one-line edit instead of
a find-and-replace through every op.

The two `text`/`fmt` pairs at the bottom are the **standard footer**: an
`Updated:` line you write by hand — content, part of the document and
`meta.hash`, so it only changes when you republish — next to
`{hash}@{time24}`, filled in by the panel's own clock and this publish's
hash *at draw time*, never in the document. Show both, so a reader can
tell a stale wall from a current one at a glance.

If `name` already has something published, start from that (`get_display`)
rather than building fresh.

## Ops

Every op takes `c` (a base ink, a built-in mix name, or your own `palette`
entry, default `black`). An unknown op, font or icon name skips that op
with a warning; an unknown colour instead falls back to black with a
warning and still draws. A required field missing or the wrong type (a
`text` with no `s`, an `x` that's a string) also skips the op, naming
every *required* field that op takes; a field an op doesn't have at all —
`colour`, or `font` for `f` — warns the same way instead of passing silently;
`c2`/`mix` written on an op rather than in a `palette` entry gets its own
warning saying where they belong. Check `warnings` either way.

- **`rect`** — `x y w h`, `fill` (default true), `t` (outline thickness when
  `fill: false`), `r` (corner radius on a filled rect, default 0, clamped to
  `(min(w, h) - 1) // 2`; ignored — with a warning — on an outline).
- **`line`** — `x y x2 y2`, `t` (thickness; works on horizontal/vertical
  lines, diagonals only thicken vertically).
- **`circle`** — `x y r` is the centre and radius, `fill` (default true), `t`.
- **`text`** — `x y s f` (`f` defaults to `md`; `f: "mono/24"` for the
  monospace face — block art, aligned columns, code), `a` (`left`/`center`/`right`,
  default `left`, changes what `x` means, not `y`), `w` (max width), `wrap`
  (bool), `lines` (default 2 when wrapping), `lh` (line height override).
  `x,y` is the top of the glyph box, not its baseline.
  - `w` alone → ellipsis-truncates, never splitting a codepoint.
  - `w` + `wrap: true` → greedy word wrap to `lines`, last line ellipsized
    if it overruns, every line clipped to `w`.
  - Always set `w` on anything sourced from a calendar or a list — you
    don't control how long those strings get.
- **`icon`** — `x y n z`. `x,y` is the top-left of the icon's box. `n` is the
  MDI name; only these eleven exist, anything else is skipped. `z` is the
  size class — `lg` (88 px): `weather-sunny`, `weather-partly-cloudy`,
  `weather-cloudy`, `weather-rainy`, `weather-snowy`, `weather-night`; `sm`
  (36 px): `check`, `map-marker`, `clock`, `alert`, `battery`. `bgc` is
  accepted and ignored (every compiled icon is transparent).
- **`sprite`** — `x y cell rows palette`, `mirror` (only `"x"`, reverses
  every row before drawing; anything else warns and is not mirrored).
  Pixel art: one `cell`×`cell` square per character in `rows`, coloured by
  `palette` (a character → a colour **name**, resolved like any other op's
  `c` — never an inline `{c, c2, mix}` object; put a mix in the document
  `palette` and name it here). `.` and space are always transparent, and
  there is no `c` — colour lives entirely in `palette`. A tiny 8×4 glyph:

  ```json
  {"op": "sprite", "x": 100, "y": 100, "cell": 20,
   "palette": {"K": "black"},
   "rows": ["..KKKK..",
            ".K....K.",
            ".K....K.",
            "..KKKK.."]}
  ```

  This is how pixel art gets drawn at all — never as a hand-compiled wall
  of `rect` ops standing in for stair-stepped pixels.
- **`poly`** — `pts` (at least three `[x, y]` integer pairs), `c`, `fill`
  (default true), `t` (outline thickness when `fill: false`). A triangle,
  chevron, arrow or ground shadow — whatever `rect`/`circle` can't shape.
  Filled polygons use an even-odd scanline rule shared exactly between
  panel and preview, so a self-crossing shape (a bow-tie, a star) fills
  the way you'd expect; x and y aren't symmetric, so a poly matching a
  `rect`'s box puts its points at `x`/`x+w-1` but `y`/`y+h` (not `y+h-1`).
  Fewer than three points, or a point that isn't a two-number pair, warns
  and the op is skipped:

  ```json
  {"op": "poly", "pts": [[100, 100], [300, 100], [200, 260]], "c": "navy"}
  ```
- **`fmt`** — `x y s`, `f` (default `xs`), `a`, `c`. Like `text` but `s` is
  a template of system fields: `{hash}` (last 5 of the document's hash),
  `{hash16}`, `{time}` (`1:43 PM`, when the panel drew it), `{time24}`,
  `{battery}` (`82%`), `{battv}`. Never type the hash, the time or the
  battery yourself — see the footer above. An empty or missing `s` warns
  and draws nothing; an unknown `{field}` is left literal and also warns.

## Type scale

A font name is `family[-bold|-italic]/size`. Every family is compiled at
the same eleven sizes — 22 24 26 28 32 36 40 44 48 54 84 — and `size` is
either a bare pixel count or one of the five slots below; both spellings
of the same face work (`instrument/lg` and `instrument/48` are the same
face) and the slot spelling is recommended.

| slot | px |
|---|---|
| `xl` | 84 |
| `lg` | 48 |
| `md` | 36 |
| `sm` | 28 |
| `xs` | 22 |

Three families in regular, `-bold` and `-italic`, plus mono (regular only):

| family | typeface | regular | `-bold` | `-italic` | the family write-up uses it for |
|---|---|---|---|---|---|
| `petrona` | Petrona | 600 | 800 | 500 italic | the day name, section headings; the italic for a subtitle or callout heading |
| `instrument` | Instrument Sans | 400 | 700 | 400 italic | the default — everything else, and what the five bare names mean |
| `karla` | Karla | 400 | 700 | 400 italic | bold for event titles and chip labels; regular for times and cues |
| `mono` | JetBrains Mono | 400 | — | — | the monospace face — block art, aligned columns, code (`mono/24`, or any other size) |

That last column is guidance from the design write-up, not a renderer
rule — a style skill's own mapping wins if it says otherwise.

The bare legacy names `xl lg md sm xs` still work, unchanged: they mean
Instrument Sans, at `instrument-bold/xl`, `instrument-bold/lg`,
`instrument/md`, `instrument/sm` and `instrument-bold/xs` respectively, so
nothing already written needs rewriting. There is no bare `mono` — write
`mono/24` (or `mono/sm`, `mono/lg`, …) explicitly, and there is no bare
italic — an italic always names its family, e.g. `petrona-italic/40`, a
size with only the pixel spelling since 40 isn't one of the five slots.
`describe().fonts[*]` lists every face's `px`, `slot`, `aliases`, `family`,
`style`, `line_height`, `cell_height` and `ink_height`;
`describe().font_families[*]` (keyed by `family`, or `family-style` for a
non-regular one) carries the constants that don't vary by size —
`typeface` (the human name), `weight`, `italic`, `glyphs`. Both are the
source of truth for what's compiled — the table above is a summary, not a
substitute for reading them. An unknown font name still skips the op; the
warning says which half is wrong — a bad size on a real family names that
family's own compiled sizes, a bad family lists every compiled family and
its styles, plus the five bare legacy names and what they mean.

Default line height is `round(size * 1.24)` — what wrapped `text` uses when
you don't set `lh`, so it's also what to stack lines by hand: an
`instrument-bold/lg` title over an `instrument/md` subtitle sits the
second line's `y` at `title_y + 60`. This is true for `mono` too — its
default `lh` is not its `cell_height`, and neither is the pitch that makes
block art meet (below).

Every face only compiles GF_Latin_Core, plus box drawing and block
elements for `mono` alone. A character outside that — `✓`, `→`, an emoji,
anything beyond plain Latin letters/digits/punctuation — previews fine
and has no glyph on the wall; `validate`/`preview` list every such
character by name and code point. `describe().font_families[*].glyphs`
names the compiled set for each family-style.

**Block art is one `text` op per row, stacked by the mono size's own
`ink_height` apart, not a wrapped one.** A full-height `mono` glyph (`│`,
`█`) inks `ink_height` rows at 1bpp, inside a taller `cell_height` (ascent
+ descent, headroom no glyph fills) — stack by the default `lh` and rows
fuse into one blob; stack by `cell_height` and they leave a hairline gap.
Draw each row at `y`, `y + h`, `y + 2h`, … where `h` is
`describe().fonts["mono/24"].ink_height` (or whichever mono size you're
using) and they meet exactly.

Aligning a **36 px `z: "sm"` icon** beside a line of `f: "sm"` text at the
same `y` (two different fields that happen to share the name `"sm"` —
one an icon size class, the other a font): the icon's own box doesn't
share the text's metrics, so centre it by eye against each font size with
this offset from the text op's `y` — `lg` → `y+6`, `md` → `y`, `sm` →
`y−4`, `xs` → `y−7`. (Not meaningful for `xl`, which dwarfs a 36 px icon.)
These offsets were measured against `instrument` text; Petrona and Karla
sit a few px off at the same size (B4b re-measures them).

## Colours

**The one hard rule: 3:1 contrast is the floor.** Every compiled font size
is WCAG large text (even `xs`, 22 px bold), so anything under 3:1 against
what's actually behind it is a `validate`/`preview` warning, not a matter
of taste.

Six inks — `black white yellow red blue green` — plus any two-ink mix.
Write `"c": "navy"` with no palette entry needed: twenty-one tested
pairings are built in, three tiers by what text goes **on top of** each one
as a fill:

- **Dark backgrounds — white text.** `navy`, `teal`, `maroon`, `plum`,
  `brown`, `forest`, `grey-dark`.
- **Light backgrounds — black text.** `cream`, `cream-pale`, `sage`,
  `sage-pale`, `slate`, `slate-pale`, `pink`, `pink-pale`, `chartreuse`,
  `grey-light`.
- **Mid-tone, ~3–4:1 — don't put text on these.** `grey-mid`, `mustard`,
  `orange`, `olive`.

Call `describe()` or `swatches()` for the full table with hexes;
`swatches(document, include_document=true)` also renders every named
colour as a labelled chip and, on request, hands that sheet back as a
publishable document.

These tiers are about a colour used **behind** something; *as* text is a
different question — a mixed glyph reads when either of its inks stands
out from what's behind it, so `grey-mid` is a bad background (4.1:1 under
black text) and good text on the white page (12.1:1), which is what the
footer stamp is. Two things contrast alone doesn't cover:

- **A mixed glyph** (as opposed to a fill) shifts toward its lighter ink —
  too few pixels to average. `plum`, `brown`, `navy`, `maroon` and `forest`
  pair two dark inks, so they hold their hue as text; treat the rest as
  fills and blocks rather than type.
- **A feature thinner than 2 px can't carry 25% or 75%** — it samples one
  row of the 2×2 mask and lands at 0/50/100% by coordinate parity. Rules
  and hairlines want 50%, or make them 2 px wide.

Redefine a built-in, or invent your own, as a `palette` entry (shape
above). `mix` is the share of **`c2`**, backwards from print habit: with
`c: black, c2: white` a *higher* number is *lighter*. Every ink pair and
density is legal as a palette entry, no built-in name needed — the
twenty-one above are tested and named, not a whitelist; judge an untried
one against the 3:1 floor the same way. Worth
remembering: yellow on white is 1.63:1 (unreadable) but yellow on
**black** is 7.42:1 (crisp down to `sm`); blue on white (7.34:1) beats red
on white (5.48:1). The trap is dark-on-dark — red/blue, red/green,
blue/green and black/blue all sit under 1.7:1 and look fine in the editor
before vanishing on the wall.

The hexes are this panel's dither average at reading distance in one room's
light, not a promise — e-paper is reflective and shifts with ambient light,
angle, temperature and unit variance. Trust the wall over the number.

- **Red is the one accent.** Spend it on a single thing per screen — the
  item that actually matters right now, not every deadline.
- **No gradients.** Flat fills and real whitespace do the layout work;
  there's no anti-aliasing to hide behind.

## Workflow

1. `validate(document)` — cheap, no rendering artifacts to look at, but
   catches structural problems and gives you the hash/op count/byte size
   up front. `validate().max_bytes` (same as `describe().limits.max_bytes`)
   is the ceiling `set_display` enforces — `bytes` above it is refused,
   not just a warning.
2. `preview(document=...)` — renders the actual PNG, ink-approximated the
   way the panel will look on the wall, and returns `validate`'s warnings
   with it. Look at it before publishing; the panel wakes roughly once an
   hour, and a wasted `set_display` either changes nothing (same hash) or
   costs the panel a ~1.5 mAh full redraw next time it wakes versus
   ~0.15 mAh for a 304 it would otherwise get. `preview(document, grid=true)`
   overlays a labelled 100 px coordinate grid for placing an op's `x`/`y`
   by coordinate — an overlay only, never part of the document.

   Each mix is drawn flat, as the hex it averages to, not the panel's 1 px
   checkerboard, so what you see is the colour you asked for — but mixed
   *text* still reads lighter than that, and a 25%/75% mix under 2 px still
   can't hold its density; that is what the warnings are for. Pass
   `dithered_colors=True` only to see the real dither, which aliases badly
   when scaled and is the wrong image to judge colour from.
3. `set_display(document, name=...)` — publish once you're satisfied.
   `recent_fetch_at: null` means no panel has fetched this name since it
   was last created (`clear_display` drops the history) — check
   `status()`'s `requested` list before assuming the wall is about to
   change. If you drafted under a scratch name, `copy_display(source,
   name)` promotes it without resending the document; the hash is
   unchanged, so a wall that already showed it just 304s.
4. `status(name=...)` — confirm the panel actually picked it up. See
   "Reading status" below for what the fields mean together.

## Reading status

One rule: the wall is current when `recent_fetch_status` is `200` or `304`
**and** `recent_fetch_at` is later than `published_at`; `first_fetch_at`
staying `null` just means the panel already had this hash and has only
ever 304'd it, not that the publish was missed.
