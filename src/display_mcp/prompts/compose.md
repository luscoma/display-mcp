# Composing a display

You are building the document an e-paper panel will draw next. There is no
other context beyond what you're given here and whatever the caller told
you: no memory of a previous run, no clock unless you look one up. Fetch
`display://sample` before you start — it is a known-good document worth
copying the shape of.

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
a warning and the op still draws. Check `warnings` either way.

- **`rect`** — `x y w h`, `fill` (default true), `t` (outline thickness when
  `fill: false`).
- **`line`** — `x y x2 y2`, `t` (thickness; works on horizontal/vertical
  lines, diagonals only thicken vertically).
- **`circle`** — `x y r` is the centre and radius, `fill` (default true), `t`.
- **`text`** — `x y s f` (`f` defaults to `md`), `a` (`left`/`center`/`right`, default `left`,
  changes what `x` means — not `y`), `w` (max width), `wrap` (bool), `lines`
  (default 2 when wrapping), `lh` (line height override). `x,y` is the top
  of the glyph box, not its baseline.
  - `w` alone → ellipsis-truncates, never splitting a codepoint.
  - `w` + `wrap: true` → greedy word wrap to `lines`, last line ellipsized
    if it overruns, every line clipped to `w`.
  - Always set `w` on anything sourced from a calendar or a list — you
    don't control how long those strings get.
- **`icon`** — `x y n z`. `x,y` is the top-left of the icon's box. `n` is the
  MDI name below; only these eleven exist, anything else is skipped.
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

Fixed, compiled into the firmware — five sizes, nothing between them:

| name | px | weight | default line height |
|---|---|---|---|
| `xl` | 84 | bold | 104 |
| `lg` | 48 | bold | 60 |
| `md` | 36 | regular | 45 |
| `sm` | 28 | regular | 35 |
| `xs` | 22 | bold | 27 |

Default line height is `round(size * 1.24)` — what wrapped `text` uses when
you don't set `lh`, so it's also what to stack lines by hand: a `lg` title
over an `md` subtitle sits the second line's `y` at `title_y + 60`.

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
resource → "The named palette"). Redefine one, or invent your own, as a
`palette` entry:
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
   up front.
2. `preview(document=...)` — renders the actual PNG, ink-approximated the
   way the panel will look on the wall, and returns `validate`'s warnings
   with it. Look at it before publishing; the panel wakes roughly once an
   hour, and a wasted `set_display` either changes nothing (same hash) or
   costs the panel a ~1.5 mAh full redraw next time it wakes versus
   ~0.15 mAh for a 304 it would otherwise get.

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
4. `status(name=...)` — confirm the panel actually picked it up. A `200`
   means the panel fetched and redrew; every wake after that is a `304`,
   which is what you want — it is the steady state, not a one-time
   coincidence right after publishing. If `first_fetch_at` is older than
   `published_at`, the panel just hasn't woken since; give it an hour
   before worrying.

If `name` already has something published, start from that instead of the
sample — `get_display` or `display://current/{name}` — and edit it rather
than building from a blank ops list.
