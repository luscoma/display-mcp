# display-mcp Runbook

Standing up the display-list server: a Python service on a host on your
network that Claude writes to over MCP and the panel reads from over the LAN.
No Docker, no browser. The host is a plain Debian box; nothing below is
Pi-specific. It is easiest if the host and the panel share a network segment,
but they don't have to — see step 5.

## What you're building

One process, two listeners, deliberately on different interfaces. The write
side is authenticated and reachable from the internet; the read side never
leaves your network.

| Listener | Bind | Who |
|---|---|---|
| MCP | `127.0.0.1:8001/mcp` | Claude, via Cloudflare Tunnel + Access |
| Panel | `<host-lan-ip>:8080/display.json` (and `127.0.0.1:8080` for you) | the e-paper, LAN only |

Six MCP tools: `set_display` publishes a document, `preview` returns a
rendered PNG so I can see what the wall will look like before publishing,
`validate` checks a draft without publishing, `get_display` reads back what's
live, `status` reports whether the panel has collected it, and
`clear_display` takes a display down. `compose_display` is a prompt that
teaches the op vocabulary and design rules so a session can write a document
without being handed the spec each time.

The steps are ordered so the cheap failures happen first. Everything through
step 4 works with no networking at all.

## The short version

Everything below is in `deploy/setup.sh`, which is idempotent and reversible.
It detects the host's LAN address itself, so on a machine that only needs the
panel endpoint:

```bash
cd display-mcp
chmod +x deploy/setup.sh                    # if the repo came as a zip

sudo ./deploy/setup.sh install --dry-run    # prints the plan, changes nothing
sudo ./deploy/setup.sh install

# when you're ready to expose the MCP side (tunnel token from the Zero Trust dashboard):
sudo ./deploy/setup.sh install --with-tunnel --tunnel-token '<token>'

./deploy/setup.sh status
sudo ./deploy/setup.sh sync                 # later: code-only redeploy
sudo ./deploy/setup.sh uninstall            # --purge also drops state and the user
```

It puts local settings in a systemd drop-in rather than editing the unit, so
`uninstall` removes a whole directory instead of trying to un-edit a file.
Nothing it writes lives outside `/opt/display-mcp`, `/var/lib/display-mcp`
and `/etc/systemd/system` — the tunnel is the one exception, and that is
`cloudflared`'s own installer, which `uninstall` calls to undo.

Read the steps below anyway the first time. They are what the script does, in
the order it does it, and they are where you look when a gate fails.

## Step 1 — Packages and a service user

All stock; the only third-party package is `cloudflared`, and it doesn't
arrive until step 6.

```bash
sudo apt update
sudo apt install -y python3-venv curl ca-certificates

sudo adduser --system --group --home /opt/display-mcp display-mcp
sudo install -d -o display-mcp -g display-mcp /opt/display-mcp/fonts
```

**Done when:** `id display-mcp` resolves.

## Step 2 — Fonts

The preview must use the *same faces the firmware compiles in*, or it will
wrap text in different places than the panel does — which defeats the point
of previewing.

```bash
sudo -u display-mcp ./deploy/fetch-fonts.sh /opt/display-mcp/fonts
file /opt/display-mcp/fonts/*.ttf     # both should say TrueType, not "JSON text"
```

Google Fonts ships Instrument Sans as a single variable font, which is why
both names point at the same file — the renderer selects the Bold instance
itself. If the GitHub API is rate limited or the raw URL 404s, browse
`ofl/instrumentsans` in `google/fonts` yourself and take whatever `.ttf` is
there, or pass `--fonts-from <dir>` to `setup.sh install`. Any static Regular
+ Bold pair works too, so long as the ESPHome config compiles the same
family.

**Done when:** `file *.ttf` reports TrueType for both. Step 3 checks that the
renderer can actually load them.

## Step 3 — Install the service

From the repo root. `setup.sh install` copies `pyproject.toml`, `README.md`,
`src/`, `samples/` and `docs/SPEC.md` into `/opt/display-mcp/app` and
pip-installs it non-editable into `/opt/display-mcp/venv` — that's what keeps
`preview` and `display-mcp-cli check` unable to disagree about what a
document draws, since they share one renderer package.

```bash
sudo -u display-mcp python3 -m venv /opt/display-mcp/venv
sudo -u display-mcp /opt/display-mcp/venv/bin/pip install /opt/display-mcp/app

sudo install -m 0644 deploy/display-mcp.service /etc/systemd/system/
```

Then edit one line in the unit — **the host's own LAN address**, keeping
loopback after the comma:

```bash
sudoedit /etc/systemd/system/display-mcp.service

# Environment=DISPLAY_MCP_PANEL_BIND=192.168.1.10,127.0.0.1   <- yours
```

Each address is bound explicitly. The LAN one is for the panel; loopback is
for you, so every check below works from the host itself. Binding addresses
rather than `0.0.0.0` means the panel endpoint can't quietly appear on an
interface you forgot about, and the service refuses to start if a wildcard
sneaks into the list.

Now prove the renderer works before anything is listening. This loads both
fonts, walks every op in the sample document and reports the hash it would
stamp — the one command that catches a bad font download, a broken venv and
a malformed document at once:

```bash
sudo -u display-mcp /opt/display-mcp/venv/bin/display-mcp-cli check \
  samples/display.json --font-dir /opt/display-mcp/fonts
```

**Done when:** `display-mcp-cli check` reports `21a77f4c46f1534d` with no
problems, and `systemd-analyze verify /etc/systemd/system/display-mcp.service`
is silent.

## Step 4 — First run

No firewall, no DNS, no certificates. If this doesn't work, none of the
networking matters yet.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now display-mcp
systemctl status display-mcp --no-pager

curl -i http://127.0.0.1:8080/healthz
```

You should get `200` from `/healthz` — that's the liveness check, and it
comes up whether or not a document has ever been published. Now check the
panel endpoint itself:

```bash
curl -i http://127.0.0.1:8080/display.json
```

You should get `503 no display list yet` — the right answer before a first
publish. Seed the state directory with the sample and restart so the service
reads it:

```bash
sudo install -o display-mcp -g display-mcp -m 0644 \
  samples/display.json /var/lib/display-mcp/default.json
sudo systemctl restart display-mcp

# 200 with an ETag …
curl -sI http://127.0.0.1:8080/display.json | grep -i etag

# … and a 304 when you hand it back
ETAG=$(curl -sI http://127.0.0.1:8080/display.json | awk -F'"' '/[Ee][Tt]ag/{print $2}')
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "If-None-Match: \"$ETAG\"" http://127.0.0.1:8080/display.json
```

**Done when:** `/healthz` answers `200`, `/display.json` answers `503` before
seeding, `200` with an `ETag` after, and that last `If-None-Match` request
prints `304`. That is the whole battery strategy working in one line.

## Step 5 — Give the panel its endpoint

The LAN address has been listening since step 4; confirm it from another
machine on the panel's network, or from the host itself:

```bash
curl -sI http://<host-lan-ip>:8080/display.json | head -1
```

In `firmware/epaper-schedule.yaml`, point the device at it and reflash:

```yaml
dl_url: "http://<host-lan-ip>:8080/display.json"
```

**If the panel and the host are on different network segments**, this hop
needs a firewall rule: source the panel's address (give it a DHCP reservation
first), destination the host on 8080. Narrow it to that one pair rather than
opening the segments to each other. A panel logging `select() timeout` means
the rule is missing, not that the server is down.

**Done when:** the panel draws the sample schedule, and its log shows
`unchanged (304)` on the following wake.

## Step 6 — The edge: a Cloudflare Tunnel

The host has no public address of its own, and it does not need one. A
small daemon, `cloudflared`, opens outbound connections to Cloudflare and
carries `https://<your-mcp-hostname>/mcp` down to the MCP listener on
`127.0.0.1:8001`. Nothing listens on a public port, so there is nothing to
firewall, no certificate to mint and no DNS record to create by hand. The MCP
listener stays on loopback exactly as in step 4; the panel listener is
untouched.

**In the Zero Trust dashboard** (`Networks → Tunnels → Create a tunnel`,
type Cloudflared):

1. Name it, and copy the **token** from the install command it shows. That
   token is the credential for the tunnel; treat it like a password.
2. Under **Public Hostname** add the hostname you want to serve → service
   `HTTP`, URL `localhost:8001`. Cloudflare creates the DNS record itself.
   That hostname is what `--domain` (or `DISPLAY_MCP_DOMAIN`) records, so
   `setup.sh` can print it back to you.

**On the host:**

```bash
sudo ./deploy/setup.sh install --with-tunnel --tunnel-token '<token>'
```

That adds Cloudflare's apt repository, installs `cloudflared`, and runs
its own `cloudflared service install <token>`, which writes and enables
`cloudflared.service` exactly as the dashboard's instructions would.
Re-running `install` without `--tunnel-token` leaves the service alone;
pass a new token to replace it. If you would rather not put the token on a
command line, omit the flag and the script prompts for it with echo off.

**Done when:** `setup.sh status` shows `tunnel active`, the dashboard shows
the tunnel **Healthy**, and from off your network
`curl -o /dev/null -w '%{http_code}' https://<your-mcp-hostname>/mcp` prints
**400** (a bare GET is not a valid MCP request; anything other than a hang
or a TLS error is the tunnel working). Do this before step 7 adds Access,
which will turn that 400 into a redirect to the login page.

## Step 7 — Connect it to Claude

Add `https://<your-mcp-hostname>/mcp` as a custom connector, with Cloudflare
Access in front of it. The Access application sits on the tunnel's public
hostname; the app receives `Cf-Access-Jwt-Assertion` through the tunnel like
any other proxied request and verifies it.

### Finding the AUD tag and team domain

In the Cloudflare Zero Trust dashboard: **Settings → Custom Pages** shows
your team domain (`https://<team>.cloudflareaccess.com`). **Access →
Applications**, open the application in front of your hostname, and its
**Overview** tab shows the **Application Audience (AUD) Tag**. Put both into
the systemd drop-in with:

```bash
sudo ./deploy/setup.sh install \
  --access-team-domain https://<team>.cloudflareaccess.com \
  --access-aud <aud tag>
```

Without these, `DISPLAY_MCP_CF_ACCESS_TEAM_DOMAIN` and
`DISPLAY_MCP_CF_ACCESS_AUD` stay unset, the MCP endpoint verifies nothing,
and `setup.sh status` says so under `mcp auth`. Fine for the loopback testing
in steps 1–5; not fine once step 6's tunnel is healthy and the endpoint is
reachable from the internet. `publish` from the host itself keeps working
without a token: a loopback request that did not come through the tunnel
is the local operator.

**Done when:** a Claude session with no desktop bridge can call `status` and
then `preview`, and the image comes back.

## What good looks like

Ask for `status` an hour after publishing. This is the healthy shape:

```json
{
  "published": true,
  "hash": "21a77f4c46f1534d",
  "ops": 54,
  "bytes": 3137,
  "published_at": "2026-09-08T06:31:00-07:00",
  "published_at_ago": "58m ago",
  "first_fetch_at": "2026-09-08T06:32:10-07:00",
  "first_fetch_at_ago": "57m ago",
  "recent_fetch_at": "2026-09-08T07:26:00-07:00",
  "recent_fetch_at_ago": "3m ago",
  "recent_fetch_status": 304,
  "recent_fetch_ip": "192.168.1.42"
}
```

`recent_fetch_status: 304` is the number to watch. It means the panel woke,
asked, learned nothing had changed, and went back to sleep without a
thirty-second refresh. That path costs about 0.15 mAh; the alternative costs
1.5. `first_fetch_at` should stay fixed across many `status` calls once the
panel has picked up the current hash — if it keeps moving, something is
stamping a new hash each build.

If you see `200` on every wake while the content is visibly identical, check
that your generator hashes only `bg`, `palette` and `ops`, not the whole
document — `set_display` does this for you; nothing else should touch
`meta.hash`.

## When it doesn't

| Symptom | Look at |
|---|---|
| `503 no display list yet` | Expected before the first publish. After one, check `/var/lib/display-mcp/default.json` exists and parses. |
| Service won't start | `journalctl -u display-mcp -n 50`. Usually the venv path or a missing font file. |
| `preview` raises about fonts | `DISPLAY_MCP_FONT_DIR` and that both `.ttf` names exist. |
| `/healthz` says `fonts_loaded: false` | Same as above — fonts missing or unreadable by the `display-mcp` user. |
| Panel: `select() timeout` | The panel cannot reach the host on 8080: a firewall between segments, if they differ. Not the server. |
| Panel: `BUG: document has no meta.hash` | Something wrote the file directly, bypassing `set_display`. It stamps; nothing else does. |
| Panel refreshes every hour regardless | Your ETag or hash is timestamp-derived. Compare `status.hash` across two publishes of identical content. |
| Claude can't reach the connector | The tunnel first (`journalctl -u cloudflared`, and **Healthy** in the dashboard), then whether the Access application still sits on that hostname. |
| MCP calls succeed with no login prompt | Access isn't configured — `setup.sh status` will say `mcp auth: not configured`. Fine for local testing, not for the internet-facing endpoint. |

## Still to come

The `compose_display` prompt exists now — the op vocabulary, the type scale,
the six-ink design rules, and the `validate → preview → set_display → status`
workflow are all written down, so a scheduled session doesn't need the spec
handed to it each time.

What's left is proving that end to end: a real unattended session composing
tomorrow's schedule, publishing it, and the panel picking it up on its next
wake with no human in the loop. Worth doing once the pipeline above is
running for real, not before — the instructions want to describe something
that already works.
