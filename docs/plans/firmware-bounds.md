# Firmware bounds: nothing a legal document contains may reboot the panel

Status: decided 2026-09-19, implementation dispatched the same day. Follows
the sprite crash in `docs/plans/wake-sleep-flow.md` and the memory audit of
`firmware/display_list.h` that came after it.

## The problem

The audit found that after the sprite fix the header still has a dozen
places where memory or draw time scales with document *content* and nothing
bounds it: text length (`fit_line` is quadratic, `wrap` holds a string per
word), poly point count, sprite rows/columns/palette, every coordinate and
size field except poly's, a circle ring that sizes a vector from `r`, and an
op loop with no time budget. Two things reboot the chip: a failed
allocation in internal SRAM (exceptions are off, `operator new` aborts) and
any single display-lambda call longer than the task watchdog, which ESPHome
arms on the loop task at 5 s with panic. The server hard-rejects only size
(256 KB), so every one of these is reachable from an ordinary `set_display`.
Because the next boot refetches the same document, each is a boot loop
until safe mode.

## Decisions

**D1. Skip, never reboot.** Over-limit content is skipped on the panel with
a warning, in exactly the style of the existing `kThickMax` /
`kSpriteMaxCell` / `kPolyMaxCoord` checks, and `display_mcp.render.check()`
warns identically so the author sees it at `validate`/`set_display` time.
Warnings still never block a publish (CLAUDE.md). Rejecting at publish was
acceptable to the owner if skipping proved risky; it did not.

**D2. The task watchdog goes to 30 s** (`esp32: watchdog_timeout: 30s`). A
complex full-page draw taking 20-30 s is acceptable; a reboot never is.
`draw_display_list` still does not feed the watchdog.

**D3. A 20 s draw budget in the op loop.** `draw_display_list` reads
`millis()` at entry; when an op would start past 20 s it logs
`draw budget exceeded after N ops; M skipped` at WARN, stops, and returns
what it has. This is the backstop under D2; the per-op bounds below are what
keep any *single* op far under it. No Python mirror (no device clock to
mirror); documented in SPEC.md.

**D4. One coordinate bound for every op: `kMaxCoord = 4096`.** Every
coordinate and size field of every op — `x`, `y`, `w`, `h`, `x2`, `y2`, `r`,
each poly point, and a sprite's pixel box (`x + cols*cell`,
`y + rows*cell`) — must satisfy `|v| <= 4096` or the op is skipped with a
warning. 4096 is more than twice the canvas on either axis, so full-bleed
overhang and the existing 64 px off-canvas *warning* are unaffected, while
the worst single op is a 4096x4096 fill, about 0.8 s. `kPolyMaxCoord`
(1 << 20) is retired in favour of this one name: the int64 crossing
arithmetic it protected is trivially safe at 4096. `MAX_COORD` mirrors it in
`render/shapes.py`; `POLY_MAX_COORD` goes.

**D5. Rects clip to the canvas before drawing.** `filled_rectangle` on the
intersection of the rect (and each outline strip) with `[0,W)x[0,H)` draws
pixel-identical output — fills and the Bayer mix are position-based — so a
rect's cost is bounded by the canvas regardless of D4. Lines, circles and
text are bounded by D4 alone (a line is O(max(|dx|,|dy|)) * t, a filled
circle O(r^2) <= 16.7 M px, both fine).

**D6. Text and template length: `kTextMaxLen = 512` bytes.** `s` on `text`
and `fmt` (the template, before expansion) longer than this skips the op
with a warning. At 512 the quadratic `fit_line` is ~7 ms and `wrap`'s word
vector ~6 KB; no algorithmic change needed. `lines` is bounded to
`kTextMaxLines = 64`.

**D7. Sprite: `kSpriteMaxCols = 1200`, `kSpriteMaxRows = 1600`,
`kSpriteMaxPalette = 64`**, each warn-and-skip; the per-character "no
palette entry" warning set is capped at 8 distinct characters plus one
"...and more" line. With D4 on the pixel box this bounds the ragged-row
walk at 1.92 M cell visits. The implementer should also avoid constructing
a `std::string` per cell visit in the run-merge loop if a span compare is
straightforward; it is the hot loop.

**D8. Poly: `kPolyMaxPts = 1024`**, enforced *while* pushing into `pts` so the
vector never grows past it; the scanline `xs` vector is hoisted out of the
per-row loop and `clear()`ed.

**D9. The document ceiling is 64 KB and it is one number.**
`store.MAX_DOC_BYTES = 64 * 1024`; `max_response_buffer_size: 64kB` in the
YAML; a parity test asserts the YAML value equals `MAX_DOC_BYTES`. The YAML's
`on_response` does `id(dl_body) = std::move(body)` — the trigger passes a
mutable `std::string &` — so the body exists once in internal SRAM, not
twice. Docs that say 256 KB (PLAN.md, SPEC.md, the YAML comment, the
header comment) say 64 KB.

**Out of scope here**, tracked in `wake-sleep-flow.md`: the `wake_cycle`
hardening (verify the draw before stamping the hash, clear `dl_body` each
cycle, INFO-level log lines, log the wake cause). Also not done: replacing
`document_id()`'s second parse with the ETag header (PSRAM only, ~50 ms).

## Work

1. `firmware/display_list.h`: D3-D8. One constant per bound at namespace
   scope next to `kThickMax`, so `_firmware_const_value` can read them.
2. `src/display_mcp/render/`: mirror every bound and warning text
   (`shapes.py` constants, `check()` warnings in `__init__.py`), retire
   `POLY_MAX_COORD`, export the new names the way the old three are.
3. `firmware/epaper-schedule.yaml`: D2, D9.
4. `src/display_mcp/store.py`: D9. Anything that prints the ceiling
   (`vocabulary`, prompts under `src/display_mcp/prompts/`, `docs/SPEC.md`,
   `docs/PLAN.md`) follows.
5. Tests — the template is `tests/renderer/test_poly.py::
   test_poly_extreme_coordinate_is_rejected_and_fast`, which asserts both the
   warning text and a wall-clock bound:
   - `tests/parity/test_limits_and_dispatch.py`: every new constant diffed
     against the header; the YAML buffer size equals `MAX_DOC_BYTES`.
   - `tests/renderer/test_text.py`: a 200 KB string with `w` set is skipped
     with the warning in well under a second; `lines` past the bound.
   - `tests/parity/test_sprite.py` and `tests/renderer/test_sprite.py`: at
     and past cols/rows/palette; the ragged case (one long row plus
     thousands of empty rows) skipped and fast; the warning set capped.
   - `tests/parity/test_poly.py`: at and past `kPolyMaxPts`; a point past
     `kMaxCoord`; timing through the compiled `poly_spans`.
   - `tests/parity/test_rect_circle.py`: `r` past the bound through the ring
     harness; a rect straddling the canvas edge still pixel-identical to
     Python after clipping.
   - `tests/test_mcp_preview_render.py` / `tests/test_store.py`: the 64 KB
     ceiling, at and past.
6. `esphome compile` of the real firmware to prove the header builds on the
   Xtensa toolchain, not only in the host harness.

## Review amendments (2026-09-19)

An adversarial review of the implementation found several places where the
bound as first shipped didn't actually deliver the safety property this
plan claims, or where the worst-case cost was stated wrong. Corrections,
not new decisions:

- **The sprite warning cap (D7) capped log lines, not the set.** The first
  cut inserted into `warned` (`std::set<std::string>`)/`warned_chars`
  unconditionally and only throttled which insertions also printed a
  line — a sprite with thousands of distinct offending characters still
  grew the set (and heap-allocated a `std::string` per entry) without
  limit. Fixed on both sides to check the cap *before* inserting. A
  second pass found that the *check itself* was still wrong at exactly
  the boundary: once the set held 8 entries, a *repeat* of a character
  already among those 8 fell into the "...and more" branch on the
  firmware (not the Python mirror, which already checked membership
  first) — `rows: ["ABCDEFGHA"]` with an empty palette logged the second
  `"A"` as if it were a ninth distinct character. Fixed by checking
  `warned.count(ch)` before the size check, mirroring the Python side
  exactly; both sides now have a test for a repeated already-warned
  character straddling the cap.
- **Poly's outline had no bound of its own.** D4's coordinate bound limits
  where a point can be, but not how long the line between two legal
  points is — a `poly` outline (`fill: false`) could have up to
  `kPolyMaxPts` edges, each as long as `2 * kMaxCoord`, each drawn `t` (up
  to `kThickMax`) times: hundreds of millions of pixel writes, well past
  either the 30s watchdog or (in the Python preview) any reasonable
  `check()` latency. Fixed by clipping every segment `thick_line()` draws
  to the canvas expanded by `kThickMax`, via Cohen-Sutherland
  (`clip_line_cs()`/`cs_outcode()` in the header, `_clip_line_cs()`/
  `_cs_outcode()` in `render/shapes.py`), before Bresenham ever sees it.
  Measured after the fix, on the real 1200x1600 canvas (not the small
  harness canvas most other parity tests use for a compact pixel diff --
  a small canvas clips much sooner, understating the real cost): the full
  legal worst case (1024 edges, `t: 64`, every point at `+/-MAX_COORD`)
  is ~87.0M pixel writes, about 4.35s compiled
  (`tests/parity/test_poly.py::
  test_poly_outline_many_long_edges_is_fast_through_the_harness`) —
  the single largest per-op cost this plan bounds, ahead of the sprite
  pixel box's ~3.4s, and still well inside the 30s watchdog on top of the
  20s draw budget. The Python preview, walking the same clipped pixels
  one `dr.point()` call at a time rather than in compiled code, is
  measured at a smaller scale instead (`tests/renderer/test_poly.py::
  test_poly_outline_many_long_edges_is_fast`) since the full 1024-edge
  case is genuinely tens of seconds in pure Python -- slow, not unsafe,
  since nothing on the preview side has a watchdog to trip.
- **`clip_line_cs()`'s intersection math used `/`, not `floor_div()`.**
  `/` truncates toward zero; the Python mirror's `//` is already a
  genuine floor. For an edge crossing the clip boundary with a negative
  numerator or denominator the two could round to different integers --
  confirmed by brute force over legal edges against the production clip
  box (the canvas expanded by `kThickMax`, not `MAX_COORD`): about 11.5%
  of off-canvas edges clipped to an endpoint one row or column apart, 369
  of them (out of the swept sample) drawing a visibly different pixel set
  between the two sides, e.g. `(-1000,800)->(600,799)` clipping to
  `(-64,800)` in C++ and `(-64,799)` in Python. `poly`'s outline is the
  one draw in this file held to pixel-exact, not eyeball, parity, so this
  mattered. Fixed by routing all four intersection expressions through
  the header's own `floor_div()` (moved earlier in the file, ahead of its
  new use here, with a forward-looking comment rather than a forward
  declaration); the Python side needed no change, since `//` was already
  correct. `tests/parity/test_poly.py` gained a full-canvas pixel diff
  using exactly the edge the brute force found.
- **`draw_circle_ring()` had no bound of its own either.** Reachable only
  through its own compiled test harness (the op loop's `circle: r out of
  range` check already keeps a real document from ever calling it with an
  illegal `r`), but `circle_half_widths()` allocates two `(r + 1)`-int
  vectors sized directly off whatever `r` it's given. Fixed by bounding
  `r` inside `draw_circle_ring()` itself.
- **`o["field"] | 0` silently reads 0 for a float, not just an
  out-of-range integer.** `"x": 1e10` (or any JSON value with a decimal
  point or exponent) failed ArduinoJson's `is<int>()` check and read as
  the default -- 0 -- drawing at the origin instead of being rejected.
  Every coordinate/size field D4 governs is now read as a `double`
  (`o["field"] | 0.0`), bound-checked as a double, and only then narrowed
  to `int`. `text`'s `lh` joins the same bound for the same reason: with
  `lines` up to `kTextMaxLines`, `y + n * lh` is the same size-field
  arithmetic as everywhere else D4 applies. `render/__init__.py` gained a
  matching `_int_coord()` (truncate toward zero, matching
  `static_cast<int>(double)`) so a legal fractional coordinate lands on
  the same pixel on both sides instead of Pillow rounding it its own way.
- **The YAML's `64kB` would have meant 64000 bytes, not 65536.**
  ESPHome's `validate_bytes()` (`config_validation.py`) treats metric
  prefixes decimally -- `k` is 1000 -- so the literal that looked right at
  a glance was 1536 bytes short of `MAX_DOC_BYTES`. Spelled as `65536B`
  instead; the parity test now parses the YAML value with the same
  decimal rule rather than assuming binary KB.
- **Warning text for a bounded value used `repr()`, not `%g`.** The
  firmware's `ESP_LOGW` prints a rejected coordinate/`lh` with `%g`
  (`1e10` -> `"1e+10"`, `2e9` -> `"2e+09"`); the Python mirror used an
  f-string's default `!r}`, giving `"10000000000.0"` and `"2000000000.0"`
  for the same values -- the two warnings, meant to be the same text
  modulo the `ops[i]` prefix, disagreed for any float outside a small
  range. Fixed with a small `_g()` helper (`format(float(v), "g")`, which
  matches `%g` exactly at these magnitudes) used everywhere `render/
  __init__.py` names a bounded value in a warning.
- **The stated worst-case single-op cost was for rects, not every op.**
  "A 4096x4096 fill, about 0.8s" was only ever true for a *clipped* rect
  fill (and even that undersold it before D5's clipping fix). The other
  shapes D4 bounds have their own, larger worst cases: an unclipped
  filled circle at `r == kMaxCoord` costs ~52.7M px (~2.6s); a sprite
  whose pixel box spans the full legal range on both axes costs up to
  ~67M px (~3.4s); a poly outline at its worst case, measured on the real
  1200x1600 canvas, is the largest of the lot at ~87.0M px (~4.35s,
  above). None of these were the actual safety argument even before this
  correction -- the 20s draw budget (D3) plus every single op finishing
  well under the 30s watchdog (D2) is: 20s + ~4.4s still lands well
  inside 30s -- but the header comment and docs/SPEC.md stated a single
  number as if it covered every op, which it didn't. Both now say so.
