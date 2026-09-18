# Composing a display

You are building the document an e-paper panel will draw next. There is no
other context beyond what you're given here and whatever the caller told
you: no memory of a previous run, no clock unless you look one up. Fetch
`display://sample` before you start — or, if your client only exposes
tools, `get_display` on a published name / the shapes in `describe()` — it
is a known-good document worth copying the shape of. `describe()` returns
the same vocabulary this file describes — inks, mixes, fonts, icons, ops —
as one JSON object built from the renderer's own tables, and `guide()`
returns this very text; either is reachable as a tool call for a client
that cannot read resources or prompts.

## Canvas

1200 × 1600 px, portrait, origin top-left, y grows downward. Everything you
place must fit inside `0 ≤ x < 1200`, `0 ≤ y < 1600`.

The panel sits behind a printed bezel that overlaps the image by about 6 px
on every edge, and the panel can sit a couple of pixels off inside it. Treat
the outer **24 px** as a margin: run background fills and colour bars edge to
edge (full bleed hides the alignment), but keep text, icons and rule lines
at least 24 px in from every edge. The sample's header bar is full bleed and
its text starts 40 px in; copy that.

## Document shape

```json
{
  "v": 1,
  "meta": {},
  "bg": "white",
  "palette": { "accent": "red", "work": "blue" },
  "ops": [ ... ]
}
```

`set_display` stamps `meta.hash` (from `bg` + `palette` + `ops`) and
`meta.generated` — never set either yourself, both are overwritten.
Anything else you put under `meta` is yours and is ignored by everything
that reads the document: there is no `ttl` — the panel wakes on its own
hourly schedule, not one the document sets. `palette` maps your own names
onto the six inks (or onto a two-ink mix) so a restyle is a one-line edit
instead of a find-and-replace through every op; `ops` reference a base ink,
a built-in mix name, or your own palette entry directly in `c`.

## Ops

Every op takes `c` (a base ink, a built-in mix name, or your own `palette`
entry, default `black`). An unknown op, font or icon name logs a warning and
skips that op; an unknown colour is different — it falls back to black with
a warning and the op still draws. A field an op does not have — a typo
like `colour`, or `font` for `f` — is a `validate`/`preview` warning naming
the fields that op actually takes, so a typo can't pass silently; `c2`/`mix`
written on an op instead of in a `palette` entry gets its own warning
saying where they belong. Check `warnings` either way.

- **`rect`** — `x y w h`, `fill` (default true), `t` (outline thickness when
  `fill: false`), `r` (corner radius on a filled rect, default 0, clamped to
  `(min(w, h) - 1) // 2`; ignored — with a warning — on an outline).
- **`line`** — `x y x2 y2`, `t` (thickness; works on horizontal/vertical
  lines, diagonals only thicken vertically).
- **`circle`** — `x y r` is the centre and radius, `fill` (default true), `t`.
- **`text`** — `x y s f` (`f` defaults to `md`; `f: "mono"` for the monospace
  face — block art, aligned columns, code), `a` (`left`/`center`/`right`, default `left`,
  changes what `x` means — not `y`), `w` (max width), `wrap` (bool), `lines`
  (default 2 when wrapping), `lh` (line height override). `x,y` is the top
  of the glyph box, not its baseline.
  - `w` alone → ellipsis-truncates, never splitting a codepoint.
  - `w` + `wrap: true` → greedy word wrap to `lines`, last line ellipsized
    if it overruns, every line clipped to `w`.
  - Always set `w` on anything sourced from a calendar or a list — you
    don't control how long those strings get.
- **`icon`** — `x y n z`. `x,y` is the top-left of the icon's box. `n` is the
  MDI name below; only these eleven exist, anything else is skipped. `bgc`
  is accepted and ignored (every compiled icon is transparent).
- **`sprite`** — `x y cell rows palette`, `mirror` (only `"x"`, reverses
  every row before drawing; anything else warns and is not mirrored).
  Pixel art: one `cell`×`cell` square per
  character in `rows`, coloured by `palette` (a single character → a
  colour **name**, resolved exactly like any other op's `c` — never an
  inline `{c, c2, mix}` object; put a mix in the document `palette` and
  name it here). `.` and space are always transparent, and there is no
  `c` — colour lives entirely in `palette`. A tiny 8×4 glyph:

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
  Filled polygons use an even-odd scanline rule shared exactly between the
  panel and the preview (docs/SPEC.md "poly"), so a self-crossing shape
  (a bow-tie, a star) fills the way you'd expect rather than however PIL
  happens to; x and y aren't symmetric, so a poly matching a `rect`'s box
  puts its points at `x`/`x+w-1` but `y`/`y+h` (not `y+h-1`). Fewer than
  three points, or a point that isn't a two-number pair, is a warning and
  the op is skipped:

  ```json
  {"op": "poly", "pts": [[100, 100], [300, 100], [200, 260]], "c": "navy"}
  ```
- **`fmt`** — `x y s`, `f` (default `xs`), `a`, `c`. Like
  `text` but `s` is a template of system fields: `{hash}` (last 5 of the
  document's hash), `{hash16}`, `{time}` (`1:43 PM`, when the panel drew
  it), `{time24}`, `{battery}` (`82%`), `{battv}`. Never type the hash, the
  time or the battery yourself. The standard footer:

  ```json
  {"op": "text", "x": 48,   "y": 1552, "s": "Updated: 6:31 AM", "f": "xs"}
  {"op": "fmt",  "x": 1045, "y": 1552, "s": "{hash}@{time24}", "f": "xs", "a": "right", "c": "grey-mid"}
  {"op": "icon", "x": 1058, "y": 1545, "n": "battery", "z": "sm", "c": "grey-mid"}
  {"op": "fmt",  "x": 1100, "y": 1552, "s": "{battery}", "f": "xs", "c": "grey-mid"}
  ```

## Type scale

Fixed, compiled into the firmware — six sizes, nothing between them:

| name | px | weight | default line height | cell height | ink height |
|---|---|---|---|---|---|
| `xl` | 84 | bold | 104 | 103 | — |
| `lg` | 48 | bold | 60 | 59 | — |
| `md` | 36 | regular | 45 | 44 | — |
| `sm` | 28 | regular | 35 | 35 | — |
| `xs` | 22 | bold | 27 | 28 | — |
| `mono` | 24 | regular | 30 | 33 | 31 |

Default line height is `round(size * 1.24)` — what wrapped `text` uses when
you don't set `lh`, so it's also what to stack lines by hand: a `lg` title
over an `md` subtitle sits the second line's `y` at `title_y + 60`. This is
true for `mono` too — its default `lh` (30) is not its `cell_height` (33),
and neither is the pitch that makes block art meet.

**Block art is one `text` op per row, stacked `ink_height` apart, not a
wrapped one.** A full-height `mono` glyph (`│`, `█`) inks 31 rows at 1bpp —
`ink_height` — inside a 33px `cell_height` (ascent + descent, which is
headroom no glyph actually fills). Stack by `round(24 * 1.24) = 30` (the
default `lh`) and rows fuse into one blob; stack by `cell_height` (33) and
they leave a 2px hairline gap, on the wall as well as in the preview. Draw
each row of a box-drawing or block diagram as its own `text` op at `y`,
`y + 31`, `y + 62`, … (`describe().fonts.mono.ink_height`) and they meet
exactly instead.

Aligning a **36 px (`sm`) icon** beside a line of text at the same `y`: the
icon's own box doesn't share the text's metrics, so centre it by eye against
each size with this offset from the text op's `y` — `lg` → `y+6`, `md` →
`y`, `sm` → `y−4`, `xs` → `y−7`. (Not meaningful for `xl`, which dwarfs a 36
px icon.)

## Icons

Eleven names, each valid at exactly one size class:

- `lg` (88 px): `weather-sunny`, `weather-partly-cloudy`, `weather-cloudy`,
  `weather-rainy`, `weather-snowy`, `weather-night`
- `sm` (36 px): `check`, `map-marker`, `clock`, `alert`, `battery`

## Colours

**The one hard rule: 3:1 contrast is the floor.** Every compiled font size
is WCAG large text (even `xs`, 22 px bold), so anything under 3:1 against
what's actually behind it is a `validate`/`check()` warning, not a matter
of taste.

Six inks — `black white yellow red blue green` — plus any two-ink mix.
Write `"c": "navy"` with no palette entry needed: twenty-one tested
pairings are built in (full table with hexes: the `display://spec`
resource → "The named palette", or `describe()`, or `swatches()`, which
renders every named colour as a labelled chip — pass
`swatches(document, include_document=true)` to also get that sheet back as
a publishable document, every name on the wall under its own chip).
Redefine one, or invent your own, as a `palette` entry:
`{"c": ..., "c2": ..., "mix": 25|50|75}`. `mix` is the share of **`c2`**, so
with `c: black, c2: white` a *higher* number is *lighter* — backwards from
print habit, and it has fooled everyone who's met it.

The built-in set has three tiers, for what text goes **on top of** each one
as a fill:

- **Dark backgrounds — white text.** `navy`, `teal`, `maroon`, `plum`,
  `brown`, `forest`, `grey-dark`.
- **Light backgrounds — black text.** `cream`, `cream-pale`, `sage`,
  `sage-pale`, `slate`, `slate-pale`, `pink`, `pink-pale`, `chartreuse`,
  `grey-light`.
- **Mid-tone, ~3–4:1 — don't put text on these.** `grey-mid`, `mustard`,
  `orange`, `olive`.

These tiers are about a colour used **behind** something. Using one *as* text
is a different question with a different answer: a mixed glyph reads when
either of its inks stands out from what is behind it, so `grey-mid` is a bad
background (4.1:1 under black text) and good text on the white page (12.1:1)
— which is what the footer stamp is.

These are tested combinations with a note on what each turned out to be
good for, **not a whitelist** — every ink pair and every density is legal
inline, no palette entry required. Judge an untried one the way these were
judged, against the 3:1 floor above. Two results worth holding onto
because they cut against habit: yellow on white is 1.63:1 and genuinely
unreadable, but yellow on **black** is 7.42:1 — better than red on white —
and reads crisply down to `sm`. Coloured small text is fine when the
background is right, too: blue on white (7.34:1) is the strongest coloured
text there is, ahead of red (5.48:1). The background decides, not the ink.
The real trap is dark-on-dark: red/blue, red/green, blue/green and
black/blue all sit under 1.7:1 and look reasonable in the editor before
vanishing on the wall.

Two things contrast alone doesn't cover:

- **A mixed glyph** (as opposed to a fill) shifts toward its lighter ink —
  too few pixels to average. `plum`, `brown`, `navy`, `maroon` and `forest`
  pair two dark inks, so they hold their hue as text; treat the rest as
  fills and blocks rather than type.
- **A feature thinner than 2 px can't carry 25% or 75%** — it samples one
  row of the 2×2 mask and lands at 0/50/100% by coordinate parity. Rules
  and hairlines want 50%, or make them 2 px wide.

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
   overlays a labelled 100 px coordinate grid, for placing an op's `x`/`y`
   by coordinate instead of a guess-preview-adjust round each time.

   Each mix is drawn as the single colour it averages to — the hex in the
   table above — rather than the 1 px checkerboard the panel dithers, so
   the colours in the image are the colours you asked for and you can judge
   them directly. The two caveats above still apply and are not visible in
   the image: mixed *text* reads lighter than the swatch, and a 25%/75% mix
   on a sub-2px feature can't hold its density. That is what the warnings
   are for. Pass `dithered_colors=True` only if you specifically need to
   see the real dither — that image aliases badly when scaled and is the
   wrong one to judge colour from.
3. `set_display(document, name=...)` — publish once you're satisfied.
   `recent_fetch_at: null` in the reply means no panel has fetched this
   name since it was last created (a `clear_display` drops the history)
   — check `status()`'s `requested` list before assuming the wall is
   about to change. If you drafted under a scratch name, `copy_display(
   source, name)` promotes it to the panel's name without resending the
   document; the hash is unchanged, so a wall that already showed it
   just 304s.
4. `status(name=...)` — confirm the panel actually picked it up. A `200`
   means the panel fetched and redrew; every wake after that is a `304`,
   which is what you want — it is the steady state, not a one-time
   coincidence right after publishing. If `first_fetch_at` is older than
   `published_at`, the panel just hasn't woken since; give it an hour
   before worrying.

If `name` already has something published, start from that instead of the
sample — `get_display` or `display://current/{name}` — and edit it rather
than building from a blank ops list.
