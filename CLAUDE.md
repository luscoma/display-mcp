# display-mcp

One Python process, two listeners: a LAN-only panel endpoint the e-paper
fetches JSON from, and an MCP endpoint Claude publishes to. Read
`docs/PLAN.md` before changing anything; it is the design and the contract
between work packages. `docs/SPEC.md` is the document language and the
firmware (`firmware/display_list.h`) is authoritative for rendering
semantics.

## Layout

- `src/display_mcp/render/` renderer port of dlpreview.py, split by
  concern: `__init__.py` the op loop, `check()`, the op-field table and
  vocabulary(); `canvas.py` WIDTH/HEIGHT/BEZEL_MARGIN/
  OFF_CANVAS_TOLERANCE; `colour.py` inks, mixes, Ctx; `fonts.py` the Face
  table and load_font; `shapes.py` rounded rect, icon stencil, poly
  geometry, the device-safety limits; `swatches.py`
  swatch_document/swatch_groups; `firmware_yaml.py` generates
  `epaper-schedule.yaml`'s font/icon fences from the tables above;
  `font_metrics.json` the committed cell_height/ink_height data
  `display-mcp-cli font-metrics` writes; `icons/` the forty committed
  lucide-activity-icon PNGs. `cli.py` its CLI.
- `src/display_mcp/store.py`, `panel.py`, `main.py`, `config.py` core
- `src/display_mcp/mcp_server.py`, `auth.py`, `prompts/` the MCP side
- `tests/renderer/` the renderer's tests, one file per concern
  (fields, colour, fonts/text, text_deco, shapes, icon_assets, sprite,
  poly, swatches); `tests/parity/` the host-compiled firmware diffs
  (poly's scanline, the sprite/rect/circle harnesses, `test_text_deco.py`'s
  draw_text_deco() harness, the device-safety constants,
  `test_mix_table.py`'s mix_on()/built-in-mix table diff,
  `test_size_normalise.py`'s font/icon key normaliser,
  `test_arduinojson_type_guards.py`'s type-guard idiom against the real
  vendored ArduinoJson).
- `deploy/` systemd unit, setup.sh, fonts fetch
- `samples/display.json` known-good document, hash `ab71629b1ca76ea6`
- `firmware/` ESPHome project, the source of truth for the panel:
  `epaper-schedule.yaml`, `display_list.h`, `fetch_and_watch.py`,
  `icons/` (the lucide SVG sources and `rasterize.py`, which produces the
  PNGs `firmware_yaml.py`'s generated `image:` block references under
  `src/display_mcp/render/icons/` — the YAML therefore only builds from a
  full checkout, never `firmware/` copied out on its own).
  `secrets.yaml` and `.esphome/` live there too and are gitignored.
- `mount/` the hardware: `epaper_frame_bezel.scad`, the picture-frame bezel
  the panel hangs behind, and `epaper_frame_carrier.scad`, the rib web behind
  the backing board that holds the driver board and battery; mock-ups and
  STLs alongside. Decisions in
  `docs/plans/frame-bezel.md`; the bezel hides 1 mm of image per edge, which
  is why `check()` has `BEZEL_MARGIN`.

## Rules that are settled

- `Store.publish()` is the only thing that stamps `meta.hash`. The hash
  covers `bg` + `palette` + `ops` only. The ETag is that hash in quotes.
- The panel endpoint is unauthenticated and read-only, bound explicitly to
  the LAN address plus 127.0.0.1, never a wildcard. The MCP endpoint binds
  loopback; a Cloudflare Tunnel fronts it. That tunnel is the only edge —
  the old reverse-proxy/nftables path is gone, don't reintroduce it.
- Warnings from the renderer never block a publish. Hard errors do.
- Field names in `store.py` and the tool return shapes in `docs/PLAN.md`
  are final; other packages code against them.
- Python 3.11+, mcp SDK v2 (`MCPServer`, `mcp.Client` for tests), Starlette,
  uvicorn, Pillow, PyJWT.
- The pixel-hash pins (`test_scaffold.py`'s sample/sprite render hashes,
  `test_swatches.py`'s swatch-sheet hash) are updated only when a
  vocabulary change deliberately reflows a sample — and only after
  re-rendering `docs/images/sample.png` to match, not before.

## Working

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
deploy/fetch-fonts.sh ./fonts        # once; gitignored
.venv/bin/pytest
DISPLAY_MCP_FONT_DIR=./fonts DISPLAY_MCP_STATE_DIR=./state .venv/bin/display-mcp
```
