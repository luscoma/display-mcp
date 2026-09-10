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
  "meta": { "generated": "...", "ttl": 3600, "title": "..." },
  "bg": "white",
  "palette": { "accent": "red", "work": "blue" },
  "ops": [ ... ]
}
```

`meta.hash` is stamped by `set_display` from `bg` + `palette` + `ops` —
never set it yourself. `palette` maps your own names onto the six inks so a
restyle is a one-line edit instead of a find-and-replace through every op;
`ops` reference either a palette name or an ink name directly in `c`.

## Ops

Every op takes `c` (ink or palette name, default `black`). An unknown op,
colour, font or icon name logs a warning and that one op is skipped — it
does not fail the whole render, so check `warnings` anyway.

- **`rect`** — `x y w h`, `fill` (default true), `t` (outline thickness when
  `fill: false`).
- **`line`** — `x y x2 y2`, `t` (thickness; works on horizontal/vertical
  lines, diagonals only thicken vertically).
- **`circle`** — `x y r` is the centre and radius, `fill` (default true), `t`.
- **`text`** — `x y s f`, `a` (`left`/`center`/`right`, default `left`,
  changes what `x` means — not `y`), `w` (max width), `wrap` (bool), `lines`
  (default 2 when wrapping), `lh` (line height override). `x,y` is the top
  of the glyph box, not its baseline.
  - `w` alone → ellipsis-truncates, never splitting a codepoint.
  - `w` + `wrap: true` → greedy word wrap to `lines`, last line ellipsized
    if it overruns, every line clipped to `w`.
  - Always set `w` on anything sourced from a calendar or a list — you
    don't control how long those strings get.
- **`icon`** — `x y n z`, `bgc` (background behind the glyph, default `bg`).
  `x,y` is the top-left of the icon's box. `n` is the MDI name below; only
  these eleven exist, anything else is skipped.
- **`fmt`** — `x y s`, `f` (default `xs`), `a`, `c`, `bgc`, `tone`. Like
  `text` but `s` is a template of system fields: `{hash}` (last 5 of the
  document's hash), `{hash16}`, `{time}` (`1:43 PM`, when the panel drew
  it), `{time24}`, `{battery}` (`82%`), `{battv}`. Never type the hash, the
  time or the battery yourself. The standard footer: `"Updated: 6:31 AM"`
  as text at the left, and at the right in `xs` with `tone: "light"`: a
  right-aligned `fmt` `"{hash}@{time24}"` at x 1045, the `battery` icon at
  x 1058, and a left-aligned `fmt` `"{battery}"` at x 1100.
- **`tone: "light"`** on `text`, `fmt` or `icon` draws at half ink
  (checkerboard) for secondary information. Set `bgc` when it sits on a
  filled rect.

## Type scale

Fixed, compiled into the firmware — five sizes, nothing between them:

| name | px | weight |
|---|---|---|
| `xl` | 84 | bold |
| `lg` | 48 | bold |
| `md` | 36 | regular |
| `sm` | 28 | regular |
| `xs` | 22 | bold |

## Icons

Eleven names, each valid at exactly one size class:

- `lg` (88 px): `weather-sunny`, `weather-partly-cloudy`, `weather-cloudy`,
  `weather-rainy`, `weather-snowy`, `weather-night`
- `sm` (36 px): `check`, `map-marker`, `clock`, `alert`, `battery`

## The six inks

`black white yellow red blue green` — nothing else exists. Rules, learned
from what actually reads on this class of panel:

- **Yellow is a fill, never text.** Yellow text on white is nearly
  invisible; use it as a block behind black text instead (see the "now" row
  in the sample).
- **Small text is always black.** Blue and green are legible at `lg`/`xl`
  but turn to mud at `sm`/`xs`.
- **Red is the one accent.** Spend it on a single thing per screen — the
  item that actually matters right now, not every deadline.
- **No gradients.** Flat fills and real whitespace do the layout work;
  there's no anti-aliasing to hide behind.
- **On a black background, use white text and yellow icons.** Everything
  else reads poorly on black.

## Workflow

1. `validate(document)` — cheap, no rendering artifacts to look at, but
   catches structural problems and gives you the hash/op count/byte size
   up front.
2. `preview(document=...)` — renders the actual PNG, ink-approximated the
   way the panel will look on the wall. Look at it before publishing;
   the panel wakes roughly once an hour, and a wasted `set_display` either
   changes nothing (same hash) or costs the panel a ~1.5 mAh full redraw
   next time it wakes versus ~0.15 mAh for a 304 it would otherwise get.
3. `set_display(document, name=...)` — publish once you're satisfied.
4. `status(name=...)` — confirm the panel actually picked it up.
   `recent_fetch_status: 304` means it already had this exact document
   (only possible right after a publish that didn't change anything);
   `200` means it just redrew. Give it until the next hourly wake before
   worrying that `first_fetch_at` hasn't moved.

Start from `display://sample` (`display://sample` resource, or
`get_display`/`display://current/{name}` if a display is already published)
and edit rather than building from a blank ops list — it already follows
the ink rules above and is close in size to what you'll draw.
