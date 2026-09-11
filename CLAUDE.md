# display-mcp

One Python process, two listeners: a LAN-only panel endpoint the e-paper
fetches JSON from, and an MCP endpoint Claude publishes to. Read
`docs/PLAN.md` before changing anything; it is the design and the contract
between work packages. `docs/SPEC.md` is the document language and the
firmware (`firmware/display_list.h`) is authoritative for rendering
semantics.

## Layout

- `src/display_mcp/render/` renderer port of dlpreview.py; `cli.py` its CLI
- `src/display_mcp/store.py`, `panel.py`, `main.py`, `config.py` core
- `src/display_mcp/mcp_server.py`, `auth.py`, `prompts/` the MCP side
- `deploy/` systemd unit, setup.sh, fonts fetch
- `samples/display.json` known-good document, hash `21a77f4c46f1534d`
- `firmware/` ESPHome project, the source of truth for the panel:
  `epaper-schedule.yaml`, `display_list.h`, `fetch_and_watch.py`.
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

## Working

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
deploy/fetch-fonts.sh ./fonts        # once; gitignored
.venv/bin/pytest
DISPLAY_MCP_FONT_DIR=./fonts DISPLAY_MCP_STATE_DIR=./state .venv/bin/display-mcp
```
