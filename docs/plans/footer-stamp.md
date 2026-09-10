# Footer stamp: "Updated 6:31 AM  |  Rendered f038e1fe@13:43" in light grey

Status: implemented 2026-09-09. Renderer/spec/sample in 6d15d13, firmware in
552e23f. The user judged the light tone on the glass and it reads right;
`tone` stays in the vocabulary. SNTP syncs a few seconds after Wi-Fi on every
wake with the default pool servers.

## What we want on the wall

```
Updated 6:31 AM   |   Rendered f038e1fe@1:43 PM                    Battery 82%
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^ lighter than the rest
```

- **Updated** is the document's content time. The author writes it as plain
  `text`, exactly as today.
- **Rendered** is the document's identity plus the time the panel drew it, so
  a glance at the wall answers both "which version is this" and "when did it
  last refresh". The hour of latency between a publish and the panel's next
  wake is precisely what this makes visible.
- The Rendered half is visually quieter than the rest of the footer.

## Decision 1: a general `fmt` op replaces `hash`. (Decided 2026-09-09.)

Instrument Sans is proportional, so "hash then `@` then time" as three ops
needs hand-tuned x positions that break as soon as the hex digits change
width. One op that composes the string is robust, and once it exists the
hash is just one of several system fields it can print. So the `hash` op
shipped earlier today is replaced (not kept as an alias; nothing depends on
it yet) by:

```json
{"op": "fmt", "x": 262, "y": 1552, "s": "|  Rendered {hash}@{time24}", "f": "xs", "tone": "light"}
```

`fmt` is `text` without wrap, whose `s` is a template. Fields: `x y s`, `f`
(default `xs`), `a`, `c`, `bgc`, `tone`. Fields available today:

| field | value | source |
|---|---|---|
| `{hash}` | last 8 characters of `meta.hash` | the document |
| `{hash16}` | all 16 | the document |
| `{time}` | time the panel drew the document, `1:43 PM` | the panel's clock, see decision 2 |
| `{time24}` | same, `13:43` | the panel's clock |

An unknown `{field}` is left literal on the panel and is a warning from
`validate`. That is the versioning story: new fields can be added to the
firmware and the renderer at any time, and a document that uses one the
firmware does not know yet still draws, just with the placeholder showing.
Good candidates for later: `{battery}` (the panel has the ADC; the sample
currently hard-codes "Battery 82%"), `{date}`, `{wake}` (wake count).

## Decision 2: the time is the panel's own clock, read at draw time.

`{time}` means "when the panel actually drew this". Only a `200` with a new
hash draws; a `304` never touches the wall, so the stamp stays at the last
real draw and that is the intended meaning. The value therefore has to come
from the device, not the server.

Firmware: ESPHome `time:` with `platform: sntp` and
`timezone:` set to the same zone the server stamps in, so "Updated" and
"Rendered" agree. Confirmed for this board and build by the firmware
session: the sdkconfig has `CONFIG_ESP_TIME_FUNCS_USE_RTC_TIMER=y`, so
system time survives deep sleep. The RTC slow clock is the internal 150 kHz
RC oscillator (no external crystal on the Waveshare board), which drifts
seconds to a few tens of seconds over an hour of sleep; immaterial at
minute resolution, and every wake has Wi-Fi so SNTP corrects it. After a
power cycle the clock reads 1970 until SNTP answers.

In `wake_cycle`, on the redraw branch only (after the hash comparison,
never on the 304 path), add `wait_until: time.has_time` with a 5 s timeout.
If time is still not valid, draw anyway and print `--:--` rather than skip
the refresh.

The display lambda fills `a.time` / `a.time24` from `id(sntp_time).now()`
using the `ESPTime` fields, not `strftime`: the `%-I` no-padding flag is a
glibc extension that ESP-IDF's newlib may print literally. So
`h = hour % 12; if h == 0: h = 12` then `"%d:%02d %s"`, and `"%02d:%02d"`
for `{time24}`; empty strings when `is_valid()` is false.

NTP egress: the user confirms UDP 123 out of the IoT VLAN works, so the
default `pool.ntp.org` is fine. The first flash confirms it: the sntp
component logs "Synchronized time" right after Wi-Fi.

Battery: none. The RTC domain is already powered through deep sleep (the
RTC timer is what wakes the panel hourly), so keeping system time is the
same counter running. SNTP is one UDP exchange per wake while Wi-Fi is up
anyway. The 5 s `wait_until` only runs after a power cycle, on the redraw
path.

Alternative considered and rejected: a server response header carrying the
fetch time. Simpler on the device, but it is the fetch time, not the draw
time, and it makes the panel's clock a property of whatever served the
document. The user wants the panel's own timestamp.

Preview side (Python): `render(doc, font_dir, now=None)` formats the host's
current local time in the same two formats; tests pass a fixed `now`.
Nothing changes in `panel.py`.

## Decision 3: "light grey" is a 1-pixel checkerboard, opt-in per op.

Spectra 6 has six inks and no grey. The panel is 5.9 px/mm, so a
checkerboard that clears every other pixel of a glyph reads as a lighter
tone at arm's length rather than as a pattern. It is the only way to get a
second text weight without a second colour, and it is nearly free.

- New optional attribute `tone: "light"` on `text` and `fmt` ops (the only
  ops that draw glyphs). Default is full ink, as today.
- Implementation, identical in both renderers: draw the text normally, then
  for every pixel `(px, py)` in the text's measured box where
  `(px + py) % 2 == 0`, write the background colour (`bgc` if given, else the
  document `bg`). Box = the bounds of the final string, offset for `a`
  (left/center/right) and for `wrap` lines individually.
- **`bgc` is required when the text sits on a filled rect** (white text on
  the black header, say); otherwise the overlay speckles the document `bg`
  into the fill. `check()` cannot know what is underneath, so the spec and
  the compose prompt say it, and the sample demonstrates it.
- Firmware: use `Display::get_text_bounds(x, y, text, font, align, &x1, &y1,
  &w, &h)` for the box; it does the `TextAlign` and font `x_offset` math
  exactly as `print()` does, so a centred or right-aligned box lands on the
  ink. Then `it.draw_pixel_at(px, py, bg)` over the box: a few thousand
  writes for a 22 px footer string, negligible next to the 30 s refresh.
- Python: same loop over the PIL image region.
- Pixel-for-pixel parity between the two is not the goal (glyph rasterisers
  differ). Tone parity is: both halve the ink density in the same box.

Risk worth a real test before adopting it widely: at `xs` (22 px) strokes
are about 2 px wide, so half of each stroke survives. It may read as "grey"
or as "speckled". Encouraging data point: this same glass showed
Atkinson-dithered images legibly in the earlier `online_image` build, so
dithered grey at area scale is known to work; 50% dropout on 2 px strokes
is the specific unknown. The first firmware build should draw one `tone: light`
line under a normal one and the user judges it on the wall. If it fails,
the fallback is to drop `tone` and use the plain hash op; nothing else in
this plan depends on it.

## Wire format summary

```json
{"op": "text", "x": 48,   "y": 1552, "s": "Updated 6:31 AM", "f": "xs"}
{"op": "fmt",  "x": 262,  "y": 1552, "s": "|  Rendered {hash}@{time24}", "f": "xs", "tone": "light"}
{"op": "text", "x": 1152, "y": 1552, "s": "Battery 82%", "f": "xs", "a": "right"}
```

`meta.hash` covers all of these ops as written. Fields are substituted at
draw time and never appear in the document, so the hash cannot be circular
and the clock never costs a refresh.

Validation (`check()` / `validate`): an unknown `{field}` is a warning and
is left literal on the panel; an unknown `tone` value is a warning and
draws at full ink. Never a skipped op. When `meta.hash` is absent, `{hash}`
substitutes `no hash`.

## Work split

**display-mcp side** (this session, no firmware knowledge needed):

1. `render/__init__.py`: `fmt` op replacing `hash`, fields `{hash}`
   `{hash16}` `{time}` `{time24}`; `now` parameter; `tone: light`
   checkerboard for `text` and `fmt`; warnings for unknown fields/tones;
   tests including a density check (ink pixel count roughly halves).
2. `docs/SPEC.md` (and the bundled copy), `prompts/compose.md`: document
   `fmt`, `tone`, and the footer pattern as the recommended layout.
3. `samples/display.json`: footer becomes the wire format above; restamp,
   propagate the new sample hash.
4. Push, then `./deploy.sh` (pulls on the host, syncs, restarts).

**firmware side** (the YAML session):

1. `firmware/epaper-schedule.yaml`: `time: platform: sntp` with the
   timezone; `wait_until: time.has_time` (5 s timeout) on the redraw path
   only; `DisplayListAssets` gains `time` and `time24`, the lambda fills
   them from `now()` or leaves them empty when the clock is not valid.
2. `firmware/display_list.h`: replace the `hash` op with `fmt`: substitute
   the four fields in `s` (plain string replace, no formatting library,
   unknown fields left literal); `text` and `fmt` honour `tone: "light"` via
   a shared `lighten_box()` helper built on `get_text_bounds()`.
3. Build, flash, then publish the updated sample and judge the tone on the
   wall. If the checkerboard does not read as grey, say so and we drop
   `tone` before it spreads into documents. Report whether SNTP synced.

Sequencing: display-mcp first (backwards compatible, the old firmware
ignores `fmt` and `tone` and just prints the hash), then firmware, then the
sample publish. Nothing breaks mid-way.

## Resolved with the user (2026-09-09)

- Op name: `fmt`, with system fields; `hash` op removed.
- Separator folded into the format string.
- Both `{time}` (`1:43 PM`) and `{time24}` (`13:43`) exist; the sample uses
  `{time24}`.
- NTP egress from the IoT VLAN is allowed; default servers.
- The checkerboard tone gets a real test on the wall.
