# Display list — spec

A few KB of JSON describing what to draw. The firmware is a renderer, not a
design: layout lives entirely in the document, so changing the dashboard is a
file edit. Only the **vocabulary** — five font sizes, eleven icons, seven ops —
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
  "meta": { "generated": "...", "ttl": 3600, "hash": "21a77f4c46f1534d" },
  "bg": "white",
  "palette": { "accent": "red", "work": "blue" },
  "ops": [ ... ]
}
```

`meta.hash` is the identity of what the document *draws* — see *Change
detection*. `set_display` stamps it; for a file on disk, `display-mcp-cli stamp`.

`palette` maps your names onto the six inks, so restyling is one line rather
than a find-and-replace through every op. Aliases resolve up to 8 hops; a
cycle falls back to black with a warning rather than hanging.

Canvas is **1200 × 1600**, origin top-left, y down.

## Ops

Every op takes `c` (colour name, default `black`). Unknown ops, colours, fonts
and icons log a warning and skip that op — one bad entry never takes down the
whole render.

| op | fields | notes |
|---|---|---|
| `rect` | `x y w h` · `fill` (default true) · `t` | `fill: false` draws an outline `t` px thick |
| `line` | `x y x2 y2` · `t` | thickness works on H/V lines; diagonals thicken vertically only |
| `circle` | `x y r` · `fill` (default true) · `t` | `x,y` is the centre |
| `text` | `x y s f` · `a` · `w` · `wrap` · `lines` · `lh` | see below |
| `icon` | `x y n z` · `bgc` | `n` = MDI name, `z` = size class, `x,y` = top-left |
| `fmt` | `x y s` · `f` · `a` · `bgc` · `tone` | `text` without wrap whose `s` is a template of system fields: `{hash}` `{hash16}` `{time}` `{time24}`; `f` defaults to `xs` |

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

`bgc` is the colour drawn behind the glyph, defaulting to the document `bg`.
It only matters if you drop `transparency: chroma_key` from an image entry.

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
older documents. The footer the sample uses:

```json
{"op": "text", "x": 48,   "y": 1552, "s": "Updated: 6:31 AM", "f": "xs"}
{"op": "fmt",  "x": 1045, "y": 1552, "s": "{hash}@{time24}", "f": "xs", "a": "right", "tone": "light"}
{"op": "icon", "x": 1058, "y": 1545, "n": "battery", "z": "sm", "tone": "light"}
{"op": "fmt",  "x": 1100, "y": 1552, "s": "{battery}", "f": "xs", "tone": "light"}
```

The percentage is left-aligned after the icon so its varying width never
moves the icon; the stamp is right-aligned against a fixed x for the same
reason.

A 304 never draws, so the stamp stays at the last real draw; that is the
point of it.

### tone

`text`, `fmt` and `icon` accept `tone: "light"`: the glyphs are drawn, then every
other pixel of their box is cleared to the background, which reads as a
lighter tone on a panel that has no grey. `bgc` names what is underneath
(default: the document `bg`); **text on a filled rect must set `bgc`** or
the overlay speckles the document background into the fill. An unknown
`tone` is a warning and draws at full ink.

## Vocabulary

**Fonts** — `xl` 84 bold, `lg` 48 bold, `md` 36, `sm` 28, `xs` 22 bold
(Instrument Sans). Adding a size is a rebuild, so the scale is a commitment.

**Icons** — `weather-{sunny,partly-cloudy,cloudy,rainy,snowy,night}` at `lg`
(88 px); `check`, `map-marker`, `clock`, `alert`, `battery` at `sm` (36 px).

**Colours** — `black white yellow red blue green`. Nothing else exists.

## Designing for six inks

Rules the sample follows, learned the hard way on this class of panel:

- **Yellow is a fill, never text.** Yellow on white is close to invisible.
  Use it as a block behind black text — that's the `now` row in the sample.
- **Small text is always black.** Blue and green are dark enough to read
  large; at 28 px they turn to mud.
- **Red is the strongest accent.** Spend it on one thing per screen.
- **No gradients, no anti-aliasing to hide behind.** Flat fills and real
  whitespace do the work.
- On black, white text and yellow icons both read well.

## Workflow

The CLI and the server share one renderer (`display_mcp.render`), so what
`check` reports and what `preview` returns cannot drift apart.

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

Serve that same value as the ETag (`ETag: "21a77f4c46f1534d"`) and put it in
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

Three tools: `set_display(document)` validates, stamps `meta.hash` and writes
atomically; `preview()` returns a PNG rendered by the same `display_mcp.render`, so
what Claude sees and what `--check` reports cannot disagree; `status()` says
whether the panel has collected it — `panel_last_status: 304` is the healthy
answer.

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
