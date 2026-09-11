# Display list — spec

A few KB of JSON describing what to draw. The firmware is a renderer, not a
design: layout lives entirely in the document, so changing the dashboard is a
file edit. Only the **vocabulary** — five font sizes, eleven icons, six ops —
is compiled in, and changing that is a rebuild.

Two implementations must agree:

| | |
|---|---|
| `display_list.h` | runs on the panel. **Authoritative.** |
| `display_mcp.render` (`display-mcp-cli`) | renders a PNG so you can look before flashing |

The wrap and truncate logic is differentially tested between them (see
*Testing* below). Everything else is eyeball parity.

## Document

```json
{
  "v": 1,
  "meta": { "generated": "...", "hash": "3cd62aa76e731d2d" },
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
| `rect` | `x y w h` · `fill` (default true) · `t` | `fill: false` draws an outline `t` px thick |
| `line` | `x y x2 y2` · `t` | thickness works on H/V lines; diagonals thicken vertically only |
| `circle` | `x y r` · `fill` (default true) · `t` | `x,y` is the centre |
| `text` | `x y s f` · `a` · `w` · `wrap` · `lines` · `lh` | see below |
| `icon` | `x y n z` · `bgc` | `n` = MDI name, `z` = size class, `x,y` = top-left |
| `fmt` | `x y s` · `f` · `a` | `text` without wrap whose `s` is a template of system fields: `{hash}` `{hash16}` `{time}` `{time24}` `{battery}` `{battv}`; `f` defaults to `xs` |

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

### icon

Icons are Material Design Icons compiled in **by name**, so there are no
codepoints to get wrong. Only the eleven in the YAML exist; anything else logs
and skips.

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
{"op": "icon", "x": 1058, "y": 1545, "n": "battery", "z": "sm", "c": "grey-mid"}
{"op": "fmt",  "x": 1100, "y": 1552, "s": "{battery}", "f": "xs", "c": "grey-mid"}
```

The percentage is left-aligned after the icon so its varying width never
moves the icon; the stamp is right-aligned against a fixed x for the same
reason.

A 304 never draws, so the stamp stays at the last real draw; that is the
point of it.

## Vocabulary

**Fonts** — `xl` 84 bold, `lg` 48 bold, `md` 36, `sm` 28, `xs` 22 bold
(Instrument Sans). Adding a size is a rebuild, so the scale is a commitment.

**Icons** — `weather-{sunny,partly-cloudy,cloudy,rainy,snowy,night}` at `lg`
(88 px); `check`, `map-marker`, `clock`, `alert`, `battery` at `sm` (36 px).

**Colours** — six inks, `black white yellow red blue green`, plus any
two-ink **mix** declared in the palette (below). Nothing else exists.

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
single pixel.

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
whole colour against whatever sits on top of it. So read a tier as advice
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
display-mcp-cli render display.json --ideal          # pure RGB instead of ink colours
```

The default render uses approximate *ink* colours, so the preview looks like
the wall rather than like a screen. Icons are procedural stand-ins — good for
judging layout and weight, not icon artwork.

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

Serve that same value as the ETag (`ETag: "3cd62aa76e731d2d"`) and put it in
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

Six tools: `set_display(document)` validates, stamps `meta.hash` and
`meta.generated`, and writes atomically; `validate(document)` runs the same
checks without rendering or publishing; `preview(document)` returns a PNG
rendered by the same `display_mcp.render`, so what Claude sees and what
`validate` reports cannot disagree; `get_display(name)` returns what's
currently published; `status(name)` says whether the panel has collected it
— `recent_fetch_status: 304` is the healthy answer; `clear_display(name)`
unpublishes.

The panel endpoint is read-only and unauthenticated on purpose. The worst case
is a neighbour reading your schedule; everything that *writes* is behind
Cloudflare. `set_display` is the only thing that stamps a hash, so writing
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
