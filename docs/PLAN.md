# display-mcp — implementation plan

One service on a host on the panel's network, two listeners. Claude publishes
a display-list JSON document over MCP; the e-paper panel fetches that JSON
over the LAN. Everything the panel understands is defined by `docs/SPEC.md`
and the firmware's `firmware/display_list.h`, which stay authoritative. This
repo replaces an earlier server-only repo — since 2026-09-09 its `firmware/`
and `mount/` live here too — and keeps the renderer, hash and ETag semantics
bit-identical. That repo is superseded entirely; this one is authoritative.

## Decisions

| Decision | Choice |
|---|---|
| Process model | one process, two listeners (panel on LAN, MCP on loopback) |
| MCP SDK | official `mcp>=2,<3`, FastMCP class, streamable HTTP, stateless |
| Edge | Cloudflare Tunnel (`cloudflared` on the host, outbound only) to the loopback MCP listener; no public port, and no requirement that the host have a routable address of its own. Decided 2026-09-09; the earlier public-origin design (a reverse proxy with an Origin Certificate, plus an nftables allowlist) was dropped rather than kept as an option. |
| App auth | a Starlette middleware in front of the MCP app verifies the `Cf-Access-Jwt-Assertion` header (JWKS, issuer, AUD). Authless when unconfigured, for local dev. |
| Displays | keyed by name from day one; `default` is the alias for `/display.json` |
| Tools | `set_display`, `preview` (published or draft), `validate`, `get_display`, `status`, `clear_display`; resources `spec`, `current`, `sample`; prompt `compose_display` |
| Status | per display: `published_at`, `first_fetch_at` (first 200 for the current hash), `recent_fetch_at` + `recent_fetch_status` + `recent_fetch_ip`. Persisted. |
| Preview colours | ink approximation only; the pure-RGB `--ideal` mode stays a CLI flag |

## Layout

```
display-mcp/
  README.md
  pyproject.toml            package `display_mcp`, scripts `display-mcp` (serve) and `display-mcp-cli`
  src/display_mcp/
    __init__.py
    main.py                 entrypoint: two uvicorn servers on one asyncio loop
    config.py               env → settings (binds, state dir, font dir, Access team/AUD)
    store.py                per-display state: atomic write, fetch tracking, persistence
    panel.py                Starlette app: /display.json, /d/<name>.json, /healthz
    mcp_server.py           FastMCP: tools, resources, prompt → streamable_http_app()
    auth.py                 Cloudflare Access JWT TokenVerifier
    render/                 port of dlpreview.py (render, render_hash, fit_line, wrap_lines)
    cli.py                  `display-mcp-cli check|stamp|render <file>`
    prompts/compose.md      the compose_display prompt text
  tests/
  samples/display.json      the sample document (hash 3cd62aa76e731d2d)
  docs/
    PLAN.md                 this file
    SPEC.md                 carried over from the earlier repo, unchanged
    RUNBOOK.md              the earlier setup guide, ported to this service
    plans/                  one file per decision thread (footer-stamp, frame-bezel)
  deploy/
    setup.sh                ported from the earlier repo
    display-mcp.service
    fetch-fonts.sh          the Instrument Sans download, for local dev too
  firmware/                 the ESPHome project; source of truth for the panel
    epaper-schedule.yaml    device config: vocabulary, wake cycle, deep sleep
    display_list.h          the on-device interpreter (authoritative semantics)
    fetch_and_watch.py      hold the panel awake, press Fetch and draw, tail logs
    secrets.yaml            wifi/OTA secrets, gitignored; .esphome/ likewise
  mount/                    the hardware; see docs/plans/frame-bezel.md
    epaper_frame_bezel.scad the picture-frame bezel (4.85 mm, four dovetailed quarters)
    epaper_frame_carrier.scad  rib web on the backing board, screwed to the frame, for the driver board and battery
    bezel_*.png             mock-ups; stl/ everything exported at the defaults
    README.md               numbers, print procedure, coupons
```

## Runtime shape

| Listener | Bind | Who |
|---|---|---|
| panel | `<pi-lan-ip>:8080`, plain HTTP | the e-paper, LAN only, unauthenticated, read-only |
| MCP | `127.0.0.1:8001/mcp` | Claude, via Cloudflare Access → the tunnel |

Both listeners are Starlette apps run by `uvicorn.Server` instances on one
event loop, sharing one in-memory `Store`. The MCP tools call the store
directly; there is no internal HTTP API.

Env (all `DISPLAY_MCP_*`): `PANEL_BIND` (comma-separated addresses, each
bound explicitly; wildcards refused; setup.sh writes `<lan-ip>,127.0.0.1`),
`PANEL_PORT`, `MCP_HOST`,
`MCP_PORT`, `MCP_PATH`, `STATE_DIR`, `FONT_DIR`, `CF_ACCESS_TEAM_DOMAIN`,
`CF_ACCESS_AUD`. Same shape as the existing unit; `EPAPER_*` is gone.

## Panel listener

- `GET|HEAD /d/<name>.json`, and `/display.json` ≡ `/d/default.json`.
  Names match `[a-z0-9-]{1,32}`.
- `ETag` is `"<meta.hash>"`. `If-None-Match` match → `304`, no body.
  `503 no display list yet` before the first publish. `Cache-Control:
  no-cache`. HEAD works (curl -I is how the runbook inspects the ETag).
- Each request updates the display's fetch record: `recent_fetch_at`,
  `recent_fetch_status`, `recent_fetch_ip` always; `first_fetch_at` the first
  time a 200 is served for the current hash. A new publish resets
  `first_fetch_at`.
- `GET /healthz` → `{ok, fonts_loaded, state_dir_writable, displays: [...]}`.
  Used by `setup.sh status` and the runbook gates.

## Store

`/var/lib/display-mcp/<name>.json` is the document, written atomically
(temp file, fsync, rename) so the panel can never read half a document.
`/var/lib/display-mcp/<name>.meta.json` holds `published_at`, `first_fetch_at`,
`recent_fetch_at`, `recent_fetch_status`, `recent_fetch_ip`. Both are reloaded on start. One lock per display.

`Store.publish(name, doc)` is the only code path that stamps `meta.hash`
and `meta.generated`; the spec's "one identity, stamped in one place" rule.
Validation warnings never block a publish. Hard errors (not an object, no
`ops` list, unknown display name, body over 256 KB) raise and become tool
errors.

## Renderer (`display_mcp.render`)

Straight port of `dlpreview.py` with the same public surface:
`render(doc, ideal=False) -> (PIL.Image, problems)`, `render_hash(doc)`,
`fit_line`, `wrap_lines`. Same Instrument Sans Regular/Bold pair, same
variable-font "Bold" instance selection, same ink and ideal tables.

Fixes carried in during the port:

- `ICONS` is missing `weather-snowy`, which the firmware compiles in, so the
  preview flags a valid icon as unknown. Add it.
- Icons become `{name: {size classes}}` so `z` is validated too; the firmware
  keys icons as `name/z` and `check/lg` does not exist on the panel.
- Off-canvas check also covers `x+w` / `y+h` for rects.

`display-mcp-cli check|stamp|render` keeps `dlpreview.py`'s flags and
output, since `setup.sh` and the runbook use `--check` as a gate.

## MCP server

Stateless streamable HTTP at `/mcp`. Tool descriptions carry the energy
story (why 304 matters, why the hash is stamped server-side, why a draft
preview beats publishing three times).

| Tool | Args | Returns |
|---|---|---|
| `set_display` | `document`, `name="default"` | `{name, hash, etag, ops, bytes, warnings}` |
| `preview` | `document?`, `name="default"` | PNG. No document → what is published; with one → render the draft, publish nothing |
| `validate` | `document` | `{hash, ops, bytes, warnings}` |
| `get_display` | `name="default"` | the published document, or an error if none |
| `status` | `name?` | one display, or all: `{published, hash, ops, bytes, published_at, first_fetch_at, recent_fetch_at, recent_fetch_status, recent_fetch_ip}`; timestamps are ISO 8601 plus a matching `*_ago` string |
| `clear_display` | `name="default"` | `{name, cleared}` |

Resources: `display://spec` (SPEC.md), `display://sample`
(`samples/display.json`), `display://current/<name>`.

Prompt `compose_display`: canvas size, type scale, the eleven icons and
their size classes, the six-ink rules, the workflow `validate → preview →
set_display → status`. Kept in `prompts/compose.md` so it can be edited
without touching code.

### Auth

The SDK's own auth layer only reads `Authorization: Bearer`, so it cannot see
the header Access actually sets. Here we skip the SDK's auth layer entirely: `auth.py` is a Starlette middleware wrapped around the
MCP app that reads `Cf-Access-Jwt-Assertion` (falling back to
`Authorization: Bearer`), verifies it as a Cloudflare Access JWT, and
returns 401 otherwise. Verification: JWKS from
`https://<team>.cloudflareaccess.com/cdn-cgi/access/certs` (cached,
refreshed on an unknown `kid`), `iss` equal to the team domain, `aud`
containing the configured AUD tag, RS256, 60 s leeway. The verified
`email`/`sub` is logged with each tool call. Unset env → authless, and
startup logs that loudly. Nothing between Cloudflare and the app rewrites
headers.

## deploy/

`setup.sh` is ported, not rewritten: same `--dry-run`, `install`, `sync`,
`status`, `uninstall [--purge]`, same font download. Changes: paths under
`/opt/display-mcp`, state in `/var/lib/display-mcp`, `display-mcp-cli
check` as the gate, `--with-tunnel` as the only edge, and the unit carries
`DISPLAY_MCP_CF_ACCESS_*`.

`docs/RUNBOOK.md` is the seven-step runbook with the gates updated: step 4
checks `/healthz`, 503, then 200 + ETag, then 304; step 7 adds finding the
Access AUD tag and team domain.

## Tests

- `render_hash(samples/display.json) == "3cd62aa76e731d2d"`.
- wrap/fit cases from the spec (multibyte truncation, overlong single word,
  exact fit, empty) as pytest fixtures, so a later C++ diff has something to
  run against.
- Panel listener through Starlette `TestClient`: 503 → 200 + ETag → 304,
  HEAD, unknown name, bad name.
- Store: atomic write leaves no temp file on failure; fetch records persist
  across a reload; publish resets `first_fetch_at`.
- MCP tools through the SDK's in-memory client: each tool's happy path, draft
  preview does not publish, `clear_display` yields 503 on the panel side.
- Auth: a locally signed JWT against a fake JWKS; wrong `aud`, wrong `iss`,
  expired, missing header, the bearer fallback, and unconfigured → allow.

## Work packages (one worktree each)

| # | Package | Scope | Depends on |
|---|---|---|---|
| 0 | scaffold | `pyproject.toml`, package skeleton with typed stubs for `Store` and `render`, copy SPEC.md + sample, test config, README skeleton | — |
| 1 | renderer | `render/` port + CLI + hash and wrap tests | 0 |
| 2 | core | `store.py`, `panel.py`, `main.py`, `config.py` + tests | 0 |
| 3 | mcp | `mcp_server.py`, `auth.py`, `prompts/compose.md` + tests (against the stubbed store) | 0 |
| 4 | deploy | unit, `setup.sh` port, `fetch-fonts.sh`, RUNBOOK.md | 0 |
| 5 | integration | merge 1–4, run the service locally, drive it with an MCP client, walk the runbook gates, fix drift | 1–4 |

Package 0 is done first, on `main`. Packages 1–4 branch from it and run in
parallel; the stubs in the scaffold are the contract they code against.
Each ends with `pytest` green and a short note of anything decided beyond
this plan.

## Local development

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
deploy/fetch-fonts.sh ./fonts
DISPLAY_MCP_FONT_DIR=./fonts DISPLAY_MCP_STATE_DIR=/tmp/display-mcp \
  DISPLAY_MCP_PANEL_BIND=127.0.0.1 .venv/bin/display-mcp
# panel: http://127.0.0.1:8080/display.json   mcp: http://127.0.0.1:8001/mcp
```

## Firmware

`firmware/` is the ESPHome project and the only copy that matters; the one in
the earlier repo is superseded. Build and flash from that directory:

```bash
cd firmware && esphome run epaper-schedule.yaml --device epaper-13e6.local
```

`dl_url` points at the host's LAN address on port 8080 — a raw address on
purpose, so a DNS change cannot freeze the wall on its last image. OTA (3232)
and the native API (6053) are reachable from the LAN. A sleeping panel wakes
only from the boot button or a power cycle. The "Stay awake" switch persists across reboots and
defeats deep sleep entirely, so turn it off before running on battery
(`fetch_and_watch.py --release`).

## Mount

`mount/` is the hardware side and lives here now. The panel hangs portrait in
a 12 1/16" × 10 1/16" picture frame with no glazing, behind a printed bezel
ring whose window is the active area less 1 mm per edge; the renderer's
`check()` warns about type inside that 24 px band. Thickness was measured
with printed coupons at 4.85 mm. The decisions and what is still open are in
`docs/plans/frame-bezel.md`.

## Out of scope

The earlier repo itself beyond what was copied in; it is archived.
