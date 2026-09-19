# The dragon session's feedback: what it got right, and the work it implies

Status: implemented 2026-09-18 on branch `claude/display-mcp-artifact-plan-dkw4zc`,
server side verified end-to-end twice, firmware host-compiled but **not yet
flashed** — the flash and the wall judgement are the open items. After the
plan's own commits, a quality pass (2026-09-19) rewrote comments to state
rules rather than history, split the renderer into `canvas`/`colour`/`fonts`/
`shapes`/`swatches`, merged the three host-compile harnesses into one, thinned
the tests from 789 to about 500 with no invariant unpinned, and — from a
review taken in the agent's own seat — made a missing or mistyped field a
warning-and-skip rather than a crash, and rewrote `guide()` for a reader who
can see nothing but the tools. The source is the doc
*Display MCP — feedback and proposed primitives*, written by an agent after
it drew a 28×28 pixel-art dragon on the panel through the MCP tools with no
access to this repo. It is a good report from a bad seat: nearly every point
is a real cost, but three of the facts it reasons from are wrong, and one of
those wrong facts is the whole of its "most actionable" section. This file
records the verdict on each point, the decisions that follow, and the order
the work lands in — as a sequence of small commits, not one change.

## What the report saw from where it sat

The agent's client exposed the six tools and nothing else. It never saw
`display://spec`, `display://sample`, `display://current/{name}` or the
`compose_display` prompt, all of which exist (`mcp_server.py` "resources",
"prompt") and answer most of its section 1 outright. That is not the agent's
mistake and it is not going to change: the Claude connector surfaces tools,
and a resource nobody can reach is documentation nobody can read. Everything
the report had to learn by trial and error is therefore a real gap in the
*tool* surface, whatever the resource surface says.

Three factual errors, each of which shaped a section:

| the report says | what is true | consequence |
|---|---|---|
| "ten inks" | six inks; the other four names it met (`mustard`, `grey-mid`, …) are built-in **mixes** | it tested "mixes of mixes", which the design forbids on purpose (ink-mixing.md decision 1) |
| `palette` "maps a name to a single ink" (§3b) | a palette entry has been allowed to be `{c, c2, mix}` since 2026-09-11 (SPEC.md "Mixes") | it never used the one mechanism that would have worked, and proposed it as new |
| a mix is "`c` + `c2` + `mix`" read off `validate`'s docstring (§2) | those are fields of a **palette entry**, not of an op | it wrote `"c": "red", "c2": "yellow", "mix": 50` on every op, and the renderer, firmware and `validate` all silently read only `c` |

## Section 2, "colour mixes appear not to render": an authoring failure the tools should have caught

Reproduced on this branch, fonts loaded:

| document | `check()` | what draws |
|---|---|---|
| `{"op": "rect", …, "c": "red", "c2": "yellow", "mix": 50}` | no warnings | solid red — `render()` reads `op.get("c")` and nothing else (`render/__init__.py`, the `ink = ctx.ink(op.get("c", "black"))` line); the firmware does the same at `resolve_ink(o["c"] | "black", palette)` |
| `"c": {"c": "red", "c2": "yellow", "mix": 50}` inline | **raises** `TypeError: unhashable type: 'dict'` | `validate` and `preview` error out; `set_display` still publishes, because `Store.publish()` catches the exception and downgrades it to a `validation unavailable` warning |
| `"palette": {"flame": {"c": "red", "c2": "yellow", "mix": 50}}`, `"c": "flame"` | no warnings | the mix, `#B56D2B` flat, a real checkerboard dithered |
| `{"op": "text", …, "font": "lg", "colour": "red"}` (typos) | no warnings | `md`, black |

So every observation in section 2 is correct and the diagnosis is not: the
mixes collapsed to `c` because `c` was the only field anything read. The
dragon on the wall *is* plain red, exactly as the report feared. Its
suggested experiment — publish a five-tile ladder and let the panel decide —
would have shown the same thing, since both renderers share the lookup.

Two things made this possible and both are ours:

- **No op-level field validation exists.** `render()` reads the fields it
  knows and ignores the rest, so a mix written in the wrong place, a British
  spelling of `colour`, or `font` for `f` all pass `validate` clean and draw
  something the author did not ask for. The bezel check, the contrast check
  and the drew-nothing check all exist because a silent wrong result is the
  worst outcome on a panel that redraws hourly; an unknown field is the same
  class of failure and has no check.
- **`validate`'s docstring describes a mix by its fields without saying
  where they live.** "a malformed mix entry (missing `c`/`c2`, `c2` equal to
  `c`, a `mix` outside 25/50/75)" reads naturally as op fields when you have
  never seen the spec.

The inline object in `c` raising is a third, smaller bug: an op field that
makes `validate` throw instead of warn breaks the rule that a bad value warns
and draws something.

## Decisions

Numbered to continue the style of the other plan files; "declined" is a
decision too.

### D1. `check()` warns on any field an op does not have

A per-op field table lives in `display_mcp.render` — required, optional with
defaults — and `render()` reports every key on an op that is not in it, plus
`op` itself. Two messages are special-cased because they are the ones the
report hit:

- `c2` or `mix` on an op: *"mixes are palette entries — write
  `palette: {name: {c, c2, mix}}` and `c: name` (docs/SPEC.md "Mixes")"*.
- `c` that is an object instead of a name: same message, and black, instead
  of a `TypeError`.

Never a skip, never a hard error: the op draws exactly as it does today, so
no published document changes. The firmware is not touched — it already logs
unknown ops, fonts and icons and ignores unknown fields, and an ESP32 is the
wrong place to spend bytes on authoring advice. The same table is what
`describe()` (D3) returns, so the tool that tells a caller which fields
exist and the check that enforces them cannot disagree.

### D2. A document may arrive as a JSON string

`set_display`, `validate` and `preview` accept `document: dict | str`. A
string is parsed; a parse failure is a `ToolError` that says the document
was a string and where parsing stopped. The report's Pydantic error is the
SDK's, not ours, and it reads as a schema bug; this turns it into the
sentence the caller needed.

Found in review (2026-09-18): the SDK does part of this itself. Any string
argument whose annotation is not plain `str` is JSON-decoded before the
tool runs, and an object is handed over as a dict — so the common case
never reaches our helper. What does reach it is a string that is not JSON,
or one that decodes to a scalar, and those get the message above. A string
that decodes to an array or `null` is still refused by the SDK's schema
check with *"Input should be a valid dictionary"*. The fix for that would
be to widen the parameter's type to include `list` and `None`, which would
make every client's view of the schema say a document may be a list. That
is a worse lie than the message it replaces, so it stays as it is; the
Pydantic sentence names the problem well enough.

### D3. `describe()` and `guide()` tools

`describe()` returns one static JSON object, built from the renderer's own
tables so it cannot drift from what `render()` accepts:

```
canvas      {w, h, bezel_margin}
inks        {name: hex}                          six, from INK
mixes       {name: {c, c2, mix, hex, tier}}      twenty-one, from BUILTIN_MIXES + Ink.avg
densities   [25, 50, 75]
fonts       {name: {px, bold, line_height,        from FONTS: line_height is round(px*1.24)
             cell_height, ink_height}}             for every face; cell_height is the loaded
                                                    face's ascent+descent; ink_height is the row
                                                    pitch a full-height glyph needs to meet with
                                                    no seam, `null` except for `mono` (D11/F1)
icons       {name: [size classes]}, icon_sizes {class: px}
anchors     [left, center, right]                 the values text.a/fmt.a accept
ops         {name: {required: [...], optional: {field: default}}}   the D1 table
fmt_fields  [hash, hash16, time, time24, battery, battv]
limits      {max_bytes: 65536}
```

The `tier` (dark / light / mid, the SPEC.md "named palette" headings) is a
small table added beside `BUILTIN_MIXES`; `tests/test_render.py` already
parses the SPEC tables to pin the hexes and extends to pin the tiers, so the
JSON, the spec and the renderer stay one thing. Roughly 3 KB; a session
calls it once.

`guide()` returns the text of `prompts/compose.md` — the same text the
`compose_display` prompt already carries, reachable as a tool because the
prompt is not. Nothing is written twice. The HA-style progressive guide the
report calls "the fancier version" is declined: two tools, one data and one
prose, are the progressive disclosure.

`README.md`, `docs/RUNBOOK.md` and `docs/SPEC.md` all say "six tools"; each
commit that adds a tool updates that count and the tool table in
`docs/PLAN.md`, which `CLAUDE.md` calls final — final for the fields that
exist, not closed to new ones.

### D4. `validate` reports the effective colour of every name it meets, and the byte ceiling

Two new fields in `validate`'s return, beside `hash`/`ops`/`bytes`/`warnings`:

- `colors`: every colour name the document references (`bg`, each op's
  `c`/`bgc`, each palette key) → `{recipe, hex}`, e.g.
  `"flame": {"recipe": "red+yellow 50", "hex": "#B56D2B"}`, `"red":
  {"recipe": "ink", "hex": "#9C2E2A"}`. Unknown names are absent here and
  present in `warnings`, as now. This is `Ctx.ink()` + `Ink.avg`, which the
  contrast check already computes and throws away.
- `max_bytes`: `MAX_DOC_BYTES`, 65536 (64 KB; lowered from the 256 KB this
  entry originally recorded -- see docs/plans/firmware-bounds.md D9).

The report also asked for "what the panel considers large". That number is
not known: the store's 64 KB limit and the firmware's
`max_response_buffer_size: 65536B` are ceilings, not a measured parse limit
on the ESP32-S3, and the largest document verified on the glass is the
fills coupon from `ink-mixing-coupon.py`, 169 ops and 15.6 KB. A soft
threshold above that would be invented, so there is none until it is
measured — the swatch sheet (D6) is a natural test document for that, and
"publish it, watch the panel log" goes in RUNBOOK.md as an optional step.

That step now exists: RUNBOOK.md's "Upgrading after a vocabulary change"
section ends with it, added alongside the docs pass below.

### D5. `preview(grid=True)` draws a coordinate grid

Lines every 100 px, heavier every 500, labelled at the top and left edges,
drawn in a colour outside the ink table onto a copy of the rendered image
*after* `render()` returns — never inside it, so
`test_render_emits_only_the_six_inks` stays true and the CLI is unaffected.
Labels are drawn in Instrument Sans at 22 px when the font directory has
it (the bitmap default is unreadable once a client scales the PNG down —
found by the Phase A end-to-end run), falling back to PIL's bitmap font so
the grid never fails a preview.
The text block gains one line: *grid lines are an overlay and are not in the
document.* Off by default.

### D6. A `swatches` tool, and the swatch sheet is itself a document

`swatches(document=None)` renders every ink and every built-in mix as a
labelled chip — name, recipe, hex — and, with a document, that document's
own palette entries too. It returns the PNG flat (`dithered_colors=False`,
the mode that shows what a mix averages to) plus a text list of the same
entries.

The chips are built as an ordinary display-list document by
`render.swatch_document(palette=None)`, then rendered through the same
`render()` as everything else. That is the cheapest implementation, and it
is also the closing coupon `ink-mixing.md` still lists as open: the same
document, published with `set_display`, puts every named mix on the wall
with its name under it. `display-mcp-cli swatches [-o]` writes it to disk.

This closes the report's "dithered mode is unusable for judging colour"
item without touching `preview`: `dithered_colors=True` stays what it is,
the mode for inspecting a specific artifact at 1:1, and the swatch sheet is
the colour-chip mode it asked for.

### D7. The tools say who has been fetching

The store already records requests for names nothing is published under
(`Store.note_fetch()` and the module docstring), and hides them from
`names()` on purpose. The tools now surface that:

- `Store.fetched_names()`: every name with a fetch record, published or not.
- `status()` with no name adds `"requested": {name: {recent_fetch_at,
  recent_fetch_ago, recent_fetch_status, recent_fetch_ip}}` for names the
  panel has asked for. That is the answer to "which name is the panel
  configured to request": the server cannot read the firmware's `dl_url`,
  but it can say what has actually been asked for and when.
- `set_display`'s return adds `recent_fetch_at` and `recent_fetch_ago`,
  taken from the record `publish()` keeps across a publish. `null` means no
  panel has ever asked for this name, and that is the whole signal: the
  docstring, `guide()` and `docs/PLAN.md` say so in one sentence each, and
  point at `status()` for the names that *have* been fetched. No prose
  `note` in the ack — the field is the fact, and a sentence restating it
  would be a second thing to keep true. (Decided 2026-09-18; an earlier
  draft had the note.)

### D8. `copy_display(source, name)`

`store.publish(store.get(source).doc, name=name)`. Same hash, fresh
`generated`, one tool. Trivial and exactly the "promote from a scratch name"
case the report describes.

### D9. A `sprite` op

The report's biggest ask and the right one: pixel art as a compiled rect
list is unreadable and uneditable, and the only alternative today is a
compiler on a scratch disk.

```json
{"op": "sprite", "x": 40, "y": 220, "cell": 40,
 "palette": {"K": "black", "O": "flame", "Y": "yellow"},
 "rows": [".........KK......KK.........",
          "........KOOK....KOOK........"]}
```

| field | | |
|---|---|---|
| `x y` | required | top-left of the grid |
| `cell` | required, ≥ 1 | pixels per grid cell, square |
| `rows` | required | strings; one character per cell |
| `palette` | required | character → colour **name**, resolved exactly as `c` is (base inks → document palette → built-in mixes) |
| `mirror` | optional | `"x"` reverses every row before drawing; cheap in both renderers and it is the wing case the report did by hand |

Rules, in the spirit of "warn and draw something":

- `.` and space are transparent and cannot be redefined.
- A character not in `palette` draws black and is a `validate`/`check()`
  warning, once per distinct character — the same fallback as an unknown
  colour, and visible on the wall, where a transparent fallback would hide
  the typo. Like every other warning it never blocks the publish or the
  draw: a sprite that is otherwise well-formed goes up with its stray cells
  in black, and the warning is how the author finds them. (Decided
  2026-09-18.)
- Ragged rows warn; short rows are padded transparent.
- Palette values are names, never inline `{c, c2, mix}` objects: mixes live
  in the document palette (ink-mixing.md decision 1), which keeps one
  resolver on each side and keeps the mix inside `meta.hash` for free. The
  report's example puts a mix object inside the sprite palette; that is the
  one thing in its sketch not adopted, and D1's warning names the fix.
- Off-canvas is judged on `x + cols·cell` and `y + rows·cell`, as `x+w`
  is for a rect.

Firmware: resolve each palette character to an `Ink` once, then per row
walk runs of equal characters and draw each run as one `filled_rectangle`
through a `MixDisplay` carrying that run's ink, so mixed cells dither as
rects do. The Python mirrors the run structure. Pixel parity is exact by
construction — a run is a rect on both sides.

The schedule sample stays untouched; its hash is pinned in more than a dozen
places and verified on the panel. A second sample, `samples/sprite.json`, carries the
new op (and D10–D12's additions), and README's "every op appears in the
sample" becomes "between the two samples". `describe()` does not need a
sample, and `guide()` names both.

### D10. `r` on a filled `rect`

Corner radius on a filled rect: three rects and four filled circles on the
firmware, drawn through the proxy so a mixed fill still dithers; the Python
draws the same seven shapes rather than PIL's `rounded_rectangle`, so the
two stay as close as the circle rasterisers allow — eyeball parity, which
is the standard for everything but wrap and the mask. `r` on `fill: false`
warns and draws the square outline; arcs are not worth a second drawing
routine until someone asks.

### D11. One monospace face: JetBrains Mono, `mono`, 24 px regular

Adds a sixth entry to the type scale, not a family switch. It serves the
report's ASCII-art case, aligned numeric columns, and code. Cost: one more
compiled glyph set (small on 16 MB), one more TTF for the renderer, and a
`FONTS` table that now carries a file name per entry.

Decided 2026-09-18 after rendering the Google Fonts monospace candidates
bilevel, the way the panel draws (the one-bit `fontmode`, ink-mixing.md
decision 7). Google Fonts is a constraint, not a preference: the ESPHome
`gfonts` source and `deploy/fetch-fonts.sh` both pull from there.

| face | box-drawing, block, shade glyphs | strokes at 1 bpp | columns at 24 px |
|---|---|---|---|
| **JetBrains Mono** | 128/128, 32/32, ░▒▓ | even, solid | 82 |
| Source Code Pro | same | slightly lighter | 82 |
| IBM Plex Mono | same, minus ▲▼●■ | solid | 82 |
| Fira Code | same | solid, built around ligatures | 82 |
| Inconsolata | same | thin at this size | 96 |
| Ubuntu Mono | 40/128, 4/32 | fine | 96 |
| DM Mono, Courier Prime, Space Mono | none | hairlines break up | 80 |

JetBrains Mono wins on the two things that matter here: it carries every
box-drawing, block and shade character, which is what turns "ASCII art"
into the block art people actually draw, and its strokes are uniform, so
nothing drops out with no anti-aliasing to hide behind. It is 0.6 em wide,
so 80-column art fits inside the 24 px bezel margin at 24 px. Source Code
Pro is the runner-up with identical coverage and no ligatures at all. Roboto
Mono was not evaluated; the fonts repo did not serve it.

Three findings from the test that the implementation has to carry:

- **The glyph set.** The firmware compiles `GF_Latin_Core`, which does not
  include U+2500–U+257F (box drawing) or U+2580–U+259F (block elements).
  The `mono` font entry in `epaper-schedule.yaml` adds those two ranges
  under `glyphs:`, or the characters that justify the face silently vanish
  on the wall while the preview shows them.
- **Ligatures and advances.** JetBrains Mono turns `<>`, `->` and `!=` into
  single glyphs under Pillow's default (raqm) layout, and positions glyphs
  at fractional advances — 14.4 px at 24 px — which at 1 bpp opened a 1 px
  gap in every box-drawing rule. The panel's bitmap font does neither: no
  ligatures, integer advances. The renderer loads this face with
  `ImageFont.Layout.BASIC`, which matches both, and a test pins that `<>`
  stays two glyphs and that `┌─┐` has no gap.
- **Line height.** Rows of `│` and `█` stack without seams only when `lh`
  equals the face's full cell height, which is 33 px at 24 px. The
  `round(24 × 1.24) = 30` the other sizes use would overlap rows by 3 px.
  `mono`'s default line height is therefore its cell height, not 1.24×,
  and `describe()` and the compose guide say so.

  Amended 2026-09-18: not as a per-face default, in the end — the firmware
  computes wrap's line height as `font_height(font) × 1.24` for every face,
  not `round(size × 1.24)`; the two formulas only agree approximately
  (`font_height` measures the loaded face's `"Ag"` box, which the Python
  side does not do at all), a divergence this predates and that is recorded
  on its own below ("Noted in passing: the wrap line-height formula only
  approximately agrees between the two sides"). A `mono`-shaped exception
  on the firmware side would still mean the header learning face names it
  otherwise has no reason to know, so the Python's own wrap default stays
  `round(size × 1.24)` for `mono` too (30, not 33); `cell_height` (33) is
  published beside `line_height` in `describe().fonts.mono` instead, for a
  composer stacking block art by hand — one `text` op per row, rather than
  `wrap`.

  Amended again 2026-09-18 (F1): `cell_height` (33) turned out not to be
  that pitch either — it's ascent + descent, headroom no glyph actually
  fills, not how tall a glyph's own ink is. Measured directly (render `█`
  bilevel, the same target FreeType's mono rasterising uses on the panel,
  and count inked rows): a full-height glyph inks 31 rows, 2px short of the
  33px cell. Stacking by `cell_height` leaves a 2px hairline seam, on the
  wall as well as in the preview; stacking by 31 — published as
  `ink_height`, beside `cell_height` and `line_height`, in
  `describe().fonts.mono` — is what actually closes it. The compose guide's
  block-art paragraph and the two `test_mono_stacked_bars_*` tests now say
  so.

Implementation:

- `FONTS` becomes `{name: Face(size, bold, file, cell_height, ink_height)}`;
  the Instrument Sans entries gain their file name the same way `mono` does,
  and `cell_height`/`ink_height` (see the amendments above) rather than a
  per-entry default line height. `ink_height` is `None` except for `mono`.
- `deploy/fetch-fonts.sh` fetches `ofl/jetbrainsmono` from the google/fonts
  repo alongside Instrument Sans (a variable font; the Regular instance is
  selected the way Bold is today) and `fonts_available()` requires it.
  `setup.sh sync` stays code-only — it deliberately never touches fonts, so
  that a deploy is not also a decision — and instead `setup.sh` gains a
  `fonts` subcommand that re-runs `fetch-fonts.sh` into `$PREFIX/fonts`;
  the runbook says to run it once after B3 lands, before the sync.
- A missing face is not fatal: `Ctx.font()` reports *"font 'mono' is not
  installed here"* and skips the op, the same abandonment an unknown font
  gets, instead of failing every render at `Ctx.__init__`.
- `guide()`'s type-scale table gains the row: `mono` 24 regular, line
  height (default `lh`) 30, cell height 33, ink height 31.

### D12. A `poly` op, filled, with the scanline shared

```json
{"op": "poly", "pts": [[100, 100], [300, 100], [200, 260]], "c": "navy"}
```

`fill` (default true) and `t` as for `rect`. Filled polygons are the one
place in this list where the two renderers could genuinely disagree, so the
fill is not left to PIL: both sides implement the same integer even-odd
scanline — for each `y`, the sorted crossings of the closed edge list,
filled in pairs as horizontal runs through the proxy — and
`tests/test_firmware_parity.py` extracts the C++ span function from the
header, compiles it and diffs it against the Python over a set of shapes,
the way `mix_on` is diffed today. `fill: false` draws the edges with
`thick_line`, closing edge included.

Last of the vocabulary changes because it is the most work, not because it
is in doubt — decided in 2026-09-18. Sprite covers the report's own
motivating case (stair-stepped wings at 40 px cells); `poly` earns its
place for UI shapes — chevrons, arrows, a timeline pointer — as much as for
the dragon.

Superseded 2026-09-19: the per-point coordinate bound this decision's
implementation carried (`kPolyMaxCoord` / `POLY_MAX_COORD`, `1 << 20`) is
now `kMaxCoord` / `MAX_COORD` (4096), one bound shared by every op's
coordinate and size fields — see `docs/plans/firmware-bounds.md` D4.

### D13. Declined: `group` with origin, scale and mirror

Scale cannot apply to compiled fonts or icons, so a `scale` that only moves
coordinates is a feature that works for some children and silently not for
others — the kind of half-rule this project has been removing. Mirror is on
`sprite` (D9), where it is a string reverse. An offset-only `group` is a
small, honest feature and can be added if hand-placed clusters turn out to
hurt; nothing here depends on it.

### Noted in passing: circle `t` is honoured by the preview and ignored by the panel

Review of A1 found that `render()` draws an unfilled `circle` with its
`t`, while `display_list.h` calls `mix.circle(x, y, r, c.a)` and drops it,
so a thick circle outline previews thick and draws 1 px on the wall.
SPEC.md lists `t` on `circle`, so the firmware is the one out of line. It
is a two-line loop in the header (concentric circles, as the rect outline
does) and rides Phase B's flash; recorded here so it is not lost.

Landed 2026-09-18, in B2, alongside the rounded rect it shares a loop shape
with.

Amended 2026-09-18 (R2): that concentric-circles loop left single-pixel
background holes near the 45° diagonals from `t == 2` up — consecutive
midpoint circles' octant boundaries don't land on the same pixels.
`display_list.h` fills the annulus by rows instead now
(`circle_half_widths()`/`draw_circle_ring()`), derived from the same
midpoint algorithm `filled_circle()` itself uses so the outer boundary
matches it exactly; a compiled parity test diffs the annulus against
`filled_circle(r) - filled_circle(r - t)` pixel for pixel. `t == 1` is
unchanged — still the plain `circle()` call this note originally
described, not routed through the annulus at all.

### Noted in passing: the wrap line-height formula only approximately agrees between the two sides

D11's amendment above found this while looking for a `mono`-specific
default: the *general* default wrap line height — every face, not just
`mono` — is `round(size × 1.24)` in `display_mcp.render` but
`font_height(font) × 1.24` in the firmware, where `font_height()` measures
the loaded face's `"Ag"` bounding box. The two only agree approximately —
for `md` (36 px), `font_height` measures roughly 44, giving `54` against
the Python's `45`. This predates B3 and applies to every face, not just
`mono`; it is recorded here, unmeasured on the actual wall, as an open
parity item rather than fixed now. To measure it: publish a wrapped
paragraph at the default `lh` and compare its line pitch against the
preview on the physical panel. If the wall disagrees enough to matter, the
fix is a per-face constant the firmware reads out of `DisplayListAssets`
(populated from Python's own `FONTS` table at build/publish time) rather
than computing `font_height` at all — not attempted here, since nothing
suggests it matters yet.

### Noted in passing: `line`/`rect` outline still centre their stroke; `poly`'s doesn't

Review of D12 found the asymmetry this leaves: the firmware's `thick_line()`
and the rect outline loop offset `t` parallel 1px lines to one side, while
the Python's `line`/`rect` outline both lean on PIL's `ImageDraw` `width=`,
which centres a thick stroke on the path instead. That gap was accepted as
eyeball parity for those two ops — nothing has ever diffed them — but
`poly`'s outline *is* diffed (`tests/test_firmware_parity.py`), so it earns
its own exact transcribed Bresenham walk (`_thick_line_points` /
`_bresenham_points` in `display_mcp.render`) instead of inheriting the gap.

Switching `line`/`rect` outlines to the same `_thick_line_points` walk is a
no-op for every `t: 1` document (the common case, and the only thickness
either preview has ever matched exactly) and makes a thick stroke preview
where the panel actually draws it for `t > 1`. It is a real behaviour
change, though — every existing `t > 1` `line`/`rect` outline shifts by up
to `t - 1` px on one side — so it is deferred rather than folded in here:
no shipped document pins a `t > 1` outline's hash today, but the change
deserves its own commit and its own note in the log, not a silent side
effect of a poly review.

### D14. The document version stays at 1

Everything above is additive: an old firmware meets `sprite` or `poly` and
logs *unknown op* and skips it; meets `r` and ignores it; meets `mono` and
logs *unknown font* and skips the op. No existing document changes what it
draws under any commit here, so `v` does not move (ink-mixing.md decision 5
sets the bar for a bump and this does not reach it).

## Commit sequence

One concern per commit, each leaving `pytest` green and the host deployable
by `sudo ./deploy/setup.sh sync`. Phase A needs no reflash and every commit
in it ships on its own. Phase B changes the compiled vocabulary and is
flashed **once**, after all four land; the server side of each is deployed
first and is backwards compatible with the old firmware (D14). Within a
Phase B commit the header, the renderer, the spec and the tests change
together, because the parity tests read the header and a half-landed
vocabulary entry is a red test, not a partial feature.

### Phase A — server only, `setup.sh sync`

| # | commit | touches | tests | closes | landed |
|---|---|---|---|---|---|
| A1 | `render: warn on fields an op does not have` | `render/__init__.py` (the field table, the warnings, the inline-object case); `mcp_server.py` (`validate` docstring says where a mix lives) | unknown field warns; `c2`/`mix` on an op gets the palette message; object in `c` warns and draws black instead of raising; sample and both samples-to-be stay clean; no existing warning text changes | §2, the bug | `render: warn on fields an op does not have`, on the branch |
| A2 | `mcp: a document may arrive as a JSON string` | `mcp_server.py` (`_coerce_document`) | string round-trips; bad string is a `ToolError` naming the parse position; a dict is untouched | §5a | `mcp: a document may arrive as a JSON string`, on the branch |
| A3 | `mcp: describe() and guide()` | `mcp_server.py`; `render/__init__.py` (`TIERS`); `tests/test_mcp.py` tool set; `docs/PLAN.md` tool table; README / RUNBOOK / SPEC "six tools" | every name in `describe().mixes` is in SPEC.md with the same hex and tier; `ops` equals the A1 table; `guide()` equals `compose.md`; `describe()` under 4 KB | §1, §3b | `mcp: describe() and guide()`, on the branch |
| A4 | `validate: the effective colour of every name, and the byte ceiling` | `mcp_server.py`; `docs/PLAN.md` tool table | `colors` covers bg, every op colour and every palette key; a mix reports its `Ink.avg` hex; an unknown name is in `warnings` and not in `colors`; `max_bytes == MAX_DOC_BYTES` | §4c, §4e | `validate: the effective colour of every name, and the byte ceiling`, on the branch |
| A5 | `preview: an optional 100 px grid` | `render/__init__.py` (`grid_overlay`); `mcp_server.py` | grid pixels appear only with `grid=True`; `render()` output is unchanged; the note names the overlay; six-ink test still passes | §4a | `preview: an optional 100 px grid`, on the branch |
| A6 | `swatches: every named colour as a chip, and the sheet is a document` | `render/__init__.py` (`swatch_document`); `mcp_server.py`; `cli.py` (`swatches`); `ink-mixing.md` "Still open" | the sheet validates clean; every ink and built-in appears once; a document's palette entries are appended; flat pixel at each chip equals the SPEC hex | §4b, §4d, ink-mixing.md's closing coupon | `swatches: every named colour as a chip, and the sheet is a document`, on the branch |
| A7 | `store, mcp: say who has been fetching` | `store.py` (`fetched_names`); `mcp_server.py` (`status` `requested`, `set_display` `recent_fetch_*`, docstrings); `prompts/compose.md`; `tests/fakes.py`; `docs/PLAN.md` | an unpublished fetched name shows in `status()`; publishing a never-fetched name returns `recent_fetch_at: null`; publishing a fetched name returns its last fetch; `names()` is unchanged | §5b, §5c | `store, mcp: say who has been fetching`, on the branch |
| A8 | `mcp: copy_display` | `mcp_server.py`; `tests/test_mcp.py`; `docs/PLAN.md` | copy has the same hash and a newer `generated`; unknown source is a `ToolError` | §5d | `mcp: copy_display`, on the branch |

A1 goes first because it is the bug and nothing depends on it. A3 before
A4–A6 because its field table and `TIERS` are reused. A2, A7 and A8 are
independent and can move. After A8: `git pull && sudo ./deploy/setup.sh
sync` on the host.

### Phase B — vocabulary, one flash

| # | commit | touches | tests | closes | landed |
|---|---|---|---|---|---|
| B1 | `sprite: pixel art as rows of characters` | `firmware/display_list.h`; `render/__init__.py`; `docs/SPEC.md`; `prompts/compose.md`; `describe()` table; `samples/sprite.json`; README | run structure: a row of `KKOO` draws two rects; `mirror`; transparent cells leave the ground; unknown character warns and is black; ragged rows warn; off-canvas on the far edge; mixed cells dither with absolute phase; the new sample validates clean and its hash is pinned | §3a | `sprite: pixel art as rows of characters`, on the branch |
| B2 | `rect: corner radius on a filled rect` | header (also `circle_half_widths()`/`draw_circle_ring()`); renderer; SPEC; compose; `describe()` | seven-shape construction fills the same box as `r: 0`, clamped to `(min(w,h)-1)//2`; `r` on an outline warns and draws square; corner pixel at `r` is bg; circle `t≥2` is an annulus matching `filled_circle(r)-filled_circle(r-t)` exactly, compiled and diffed, with no diagonal holes | §3f | `rect: corner radius on a filled rect`, on the branch |
| B3 | `fonts: JetBrains Mono as \`mono\`` | `epaper-schedule.yaml` (font entry with the box and block ranges); header untouched; `render/__init__.py` (`FONTS` as `Face(size, bold, file, cell_height, ink_height)`, basic layout, `None`-able mono face); `deploy/fetch-fonts.sh`; `deploy/setup.sh fonts`; RUNBOOK step 2; `tests/test_deploy.py`; SPEC; compose; `describe()` | glyph advance is a constant integer; `<>` stays two glyphs; `┌─┐` renders with no gap; `mono`'s `cell_height` (33) and measured `ink_height` (31) are published beside its `line_height` (30, `round(24×1.24)`, unchanged from every other face — amended above); a missing face skips the op with a problem instead of raising; `fonts_available` requires all three files; fetch script is still idempotent | §3e | `fonts: JetBrains Mono as \`mono\``, on the branch |
| B4 | `poly: a point list, filled by a shared scanline` | header; renderer; `tests/test_firmware_parity.py` (extract + compile `poly_spans`); SPEC; compose; `describe()`; `samples/sprite.json` gains one | C++ and Python spans agree over convex, concave and self-touching shapes; `fill: false` closes the edge; a two-point `pts` warns and skips | §3d | `poly: a point list, filled by a shared scanline`, on the branch |

A follow-up commit, `phase A: what the end-to-end run turned up`, landed between
B1's predecessors and B1 itself: a live run of the eight Phase A tools found
six seams between the tools' words and their behaviour (`validate`'s
`bytes` vs. `set_display`'s stamped body, the no-such-field warning naming
the fix, `guide()`/`describe()`'s docstrings catching up, `grid_overlay`
taking a real font), all fixed in that one commit, on the branch.

Then, once: `cd firmware && esphome run epaper-schedule.yaml`, publish
`samples/sprite.json`, judge on the wall, and record the verdict at the top
of this file. B4 is last only because it is the most work; nothing else
depends on it, so it can also land after the flash and ride the next one.

### Phase C — not now

Offset-only `group` (D13), a soft byte budget (D4, until measured), and a
progressive guide (D3) are recorded as declined-or-deferred with the reason,
so the next agent's report does not re-open them from scratch.

## For the user

- **The document itself.** Nothing here edits the feedback doc. If it should
  carry a pointer to this file, or a one-line note that §2 was an authoring
  issue the tools now warn about, that is a separate, small step.
