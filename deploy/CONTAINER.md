# Running in a container

The same process `setup.sh` installs, packaged as an OCI image and published
to GitHub Container Registry by `.github/workflows/container.yml`. It runs two
listeners and binds each to whatever addresses you give it:

| Listener | Setting | Default | Serves |
|---|---|---|---|
| panel | `DISPLAY_MCP_PANEL_BIND`, `DISPLAY_MCP_PANEL_PORT` | `127.0.0.1:8080` | `/display.json` to the e-paper; unauthenticated, read-only |
| MCP | `DISPLAY_MCP_SERVER_HOST`, `DISPLAY_MCP_SERVER_PORT` | `127.0.0.1:8001` | `/mcp`; Cloudflare Access JWTs when `DISPLAY_MCP_CF_ACCESS_*` is set |

Both bind settings take a comma-separated list, and each address is bound as
given. That includes `0.0.0.0`, so which interfaces each listener appears on
is up to the deployment.

| Piece | Where |
|---|---|
| `Dockerfile` | the image: venv, fonts baked in, non-root (uid 10001), `/healthz` healthcheck |
| `deploy/compose.yaml` | the same image under Docker Compose, on host networking |
| `deploy/compose.env.example` | the settings; copy to `deploy/.env` (gitignored) |
| `.github/workflows/container.yml` | test → build → smoke-test → push amd64 + arm64 |

## Building and publishing

CI does it; there is nothing to run by hand.

| Event | Tags pushed to `ghcr.io/<owner>/display-mcp` |
|---|---|
| push to `main` | `main`, `latest`, `sha-<short>` |
| tag `v1.2.3` | `1.2.3`, `1.2`, `sha-<short>` |
| pull request | none — built and smoke-tested only |

The workflow runs the test suite first, then builds the native image, starts
it and checks it goes healthy and answers 503 before a publish, and only then
pushes the multi-arch image. It authenticates with the job's own
`GITHUB_TOKEN`, so no secret needs adding. A release is a tag:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

The first push creates the package private, following the repo. Either make
it public (GitHub → Packages → display-mcp → Package settings), or log the
Docker host in once with a classic token scoped to `read:packages`:

```bash
echo "$TOKEN" | docker login ghcr.io -u <github-user> --password-stdin
```

Building locally is the same Dockerfile:

```bash
docker build -t display-mcp .
docker build --build-context fonts=./fonts -t display-mcp .   # reuse fetched fonts
```

## Choosing the addresses

The two listeners need very different exposure, and a container makes it easy
to give them different networks:

- **The panel** only ever needs to reach the e-paper. It has no
  authentication, so it should not be reachable from anywhere you would not
  hand the displayed document to.
- **The MCP endpoint** takes writes. Without the Access settings it accepts
  any request, and startup logs that loudly. Unless it is behind something
  that authenticates, keep it on loopback, or on a network only the
  authenticating proxy shares. With Access configured, every request from
  anywhere but an unproxied loopback peer needs a valid JWT.

In practice: the LAN address for the panel, and loopback (or an address on a
network only your authenticating proxy shares) for MCP. Add `127.0.0.1` to
each for your own curl and `display-mcp-cli`. A request from loopback with no
proxy headers counts as the local operator and needs no Access token.

## Proxmox: an LXC straight from the image

Proxmox VE 9.1 and later can pull an OCI image and run it as an LXC, with no
Docker anywhere. The feature is a technology preview, and these steps have
not been run against a real Proxmox host yet. `/healthz` is the check at
every step.

What carries over from the image: the entrypoint (`display-mcp`), the
`DISPLAY_MCP_*` defaults, and the baked-in fonts. What does not: the
`HEALTHCHECK` (LXC has no equivalent; poll `/healthz` yourself) and the
Compose file's confinement settings. The unprivileged container is the
isolation instead.

### 1. Make the image pullable

The first CI push creates `ghcr.io/<owner>/display-mcp` as a private
package. Proxmox's pull has no documented way to log in to a registry, so
make the package public: GitHub → your profile → Packages → display-mcp →
Package settings → Change visibility. Nothing secret is in the image;
settings and state live outside it.

### 2. Pull it as a template

Datacenter → your node → a storage with *CT Templates* content (`local`,
usually) → CT Templates → **Pull from OCI Registry**. Use the full
reference with an explicit tag:

```
ghcr.io/<owner>/display-mcp:sha-<short>
```

A bare name means Docker Hub. A `sha-` or version tag, rather than `latest`,
is what makes the container's version something you can name and roll back
to.

### 3. Create the container

Create CT from that template:

- **Unprivileged**: yes.
- **Resources**: 1 core, 512 MB RAM, 2 GB root disk is plenty.
- **Network**: `net0` on `vmbr0` with a **static** address, e.g.
  `192.168.1.20/24`. The URL compiled into the panel's firmware points at
  it. Giving the container the old host's address means the panel needs no
  reflash.
- **Don't start it yet.**

Then two additions before the first start.

**A mount point for state.** Recreating the container is how it gets
updated (step 6), and only a mount point survives that. Resources → Add →
Mount Point: 1 GB, path `/var/lib/display-mcp`. Or from the host shell:

```bash
pct set <ctid> -mp0 local-lvm:1,mp=/var/lib/display-mcp
```

**The environment.** Options → Environment shows the image's defaults; add
or change:

```
DISPLAY_MCP_PANEL_BIND=192.168.1.20,127.0.0.1
DISPLAY_MCP_SERVER_HOST=127.0.0.1
DISPLAY_MCP_CF_ACCESS_TEAM_DOMAIN=https://<team>.cloudflareaccess.com
DISPLAY_MCP_CF_ACCESS_AUD=<aud tag>
```

Put on `DISPLAY_MCP_SERVER_HOST` whatever address your authenticating proxy
reaches it on (see "Choosing the addresses").

### 4. Let the app write its state

A fresh mount point is owned by root, and the image runs as uid 10001, so
the first start reports `"state_dir_writable": false`. From the Proxmox host:

```bash
pct start <ctid>
pct exec <ctid> -- chown 10001:10001 /var/lib/display-mcp
pct reboot <ctid>
```

If `pct exec` won't run in an application container, chown it from the host
instead. In an unprivileged container, uid 10001 inside is 110001 outside:

```bash
pct stop <ctid> && pct mount <ctid>
chown 110001:110001 /var/lib/lxc/<ctid>/rootfs/var/lib/display-mcp
pct unmount <ctid> && pct start <ctid>
```

### 5. Check it

From a LAN machine:

```bash
curl http://192.168.1.20:8080/healthz      # fonts_loaded and state_dir_writable both true
curl -i http://192.168.1.20:8080/display.json  # 503 until the first publish
```

Then the rest of the runbook's gates: 200 + ETag after a publish, then 304
with `If-None-Match`. To publish the sample from the Proxmox host, over the
container's own loopback, which needs no token:

```bash
pct exec <ctid> -- sh -c '/opt/display-mcp/venv/bin/display-mcp-cli publish /opt/display-mcp/venv/lib/python3*/site-packages/display_mcp/prompts/sample.json'
```

### 6. Updating and rolling back

Proxmox squashes the image into the container's root filesystem when it
creates it, so there is no swapping in a new image underneath a running
container. An update is a new container on the same mount point:

1. Pull the new tag as a template (step 2).
2. `pct stop <old>`, then detach its state volume: Resources → the mount
   point → Detach. It becomes an unused disk.
3. Create the new container from the new template with the same address
   and environment (step 3, minus adding a new mount point). Reassign the
   old volume to it: on the old container, Resources → the unused disk →
   Disk Action → Reassign Owner → the new container. Then attach it at
   `/var/lib/display-mcp`.
4. Start the new container and check `/healthz` lists your displays.
   Delete the old container once you're happy.

Rolling back is the same, with the old tag's template. Ownership carries
over with the volume, so step 4 of the first install is not needed again.

### Moving from the systemd host

1. Stop the old service so nothing publishes mid-copy:
   `sudo systemctl stop display-mcp`.
2. Carry its state across, on the Proxmox host:

   ```bash
   ssh old-host 'sudo tar -C /var/lib/display-mcp -cf - .' > state.tar
   pct push <ctid> state.tar /tmp/state.tar
   pct exec <ctid> -- sh -c 'tar -C /var/lib/display-mcp -xf /tmp/state.tar && chown -R 10001:10001 /var/lib/display-mcp && rm /tmp/state.tar'
   pct reboot <ctid>
   ```

3. Point whatever fronts the MCP endpoint at its new address.
4. Check `/healthz` lists the old displays with their hashes. The panel's
   next wake gets a 304: same document, same ETag.
5. Once it has, run `sudo ./deploy/setup.sh uninstall` on the old host.

## Docker Compose

The same image anywhere Docker runs. `deploy/compose.yaml` uses host
networking, so the addresses in `deploy/.env` are the host's own, exactly as
under systemd.

```bash
git clone https://github.com/<owner>/display-mcp.git ~/display-mcp
cd ~/display-mcp
cp deploy/compose.env.example deploy/.env
$EDITOR deploy/.env          # image, the two bind lists, the Access settings
docker compose -f deploy/compose.yaml up -d
docker compose -f deploy/compose.yaml ps        # wait for (healthy)
docker compose -f deploy/compose.yaml exec -T display-mcp display-mcp-cli publish /dev/stdin < samples/display.json
```

Bridge networking with published ports works too. Bind `0.0.0.0` inside the
container and choose the host address in the publish instead, e.g.
`192.168.1.20:8080:8080`. The cost is that a request from the host arrives
from the bridge gateway, not loopback, so publishing from the host needs an
Access token unless it goes through `docker compose exec`.

To update, pin `DISPLAY_MCP_IMAGE` in `deploy/.env` to the new tag, then run
`docker compose -f deploy/compose.yaml pull` and
`docker compose -f deploy/compose.yaml up -d`. Rolling back is the previous
tag and the same two commands. State lives in the `display-mcp_state` volume.
To bring state over from a systemd host:

```bash
scp -r old-host:/var/lib/display-mcp ./old-state
docker compose -f deploy/compose.yaml create display-mcp
docker run --rm --user 0 --entrypoint sh \
  -v display-mcp_state:/dst -v "$PWD/old-state:/src:ro" \
  "$(docker compose -f deploy/compose.yaml images -q display-mcp)" \
  -c 'cp -a /src/. /dst/ && chown -R 10001:10001 /dst'
```
