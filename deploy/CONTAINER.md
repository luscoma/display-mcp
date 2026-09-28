# Running in a container (Proxmox)

The same process `setup.sh` installs, packaged as an OCI image and published
to GitHub Container Registry by `.github/workflows/container.yml`. The bind
rules do not change: the panel binds the host's LAN address plus 127.0.0.1,
never a wildcard (`main.py` still refuses one), the MCP endpoint binds
loopback, and a Cloudflare Tunnel is the only edge.

| Piece | Where |
|---|---|
| `Dockerfile` | the image: venv, fonts baked in, non-root (uid 10001), `/healthz` healthcheck |
| `deploy/compose.yaml` | display-mcp + an optional `cloudflared`, both on host networking |
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

## Where it runs on Proxmox

**A small Debian VM running Docker Engine.** 1 vCPU, 1 GB RAM, 8 GB disk is
plenty. An unprivileged LXC with `nesting=1,keyctl=1` also runs Docker, but
Proxmox recommends a VM for Docker and the VM costs little more here.

Give it a fixed address — a static IP or a DHCP reservation. Two things
depend on it: `DISPLAY_MCP_PANEL_BIND`, and the URL compiled into the panel's
firmware. Giving the VM the old host's address means the panel needs no
reflash.

*Why not Proxmox's own OCI-image-to-LXC path?* It runs the image as an LXC
with its own network namespace, so `cloudflared` cannot share the MCP
listener's loopback without moving the MCP bind off 127.0.0.1. Compose with
host networking keeps every address meaning what it means under systemd.

## First start

On the VM, with Docker Engine and the compose plugin installed:

```bash
git clone https://github.com/<owner>/display-mcp.git ~/display-mcp
cd ~/display-mcp
cp deploy/compose.env.example deploy/.env
$EDITOR deploy/.env          # image, the VM's LAN address, Access, tunnel token
chmod 600 deploy/.env        # it holds the tunnel token

docker compose -f deploy/compose.yaml up -d                     # panel + MCP
docker compose -f deploy/compose.yaml --profile tunnel up -d    # + cloudflared
docker compose -f deploy/compose.yaml ps                        # wait for (healthy)
```

The runbook's gates hold unchanged: `curl http://127.0.0.1:8080/healthz`,
then `/display.json` is 503, then 200 + ETag after a publish, then 304 with
`If-None-Match`. To publish from the VM itself:

```bash
docker compose -f deploy/compose.yaml exec -T display-mcp display-mcp-cli publish /dev/stdin < samples/display.json
```

## Moving from the systemd host

1. Stop the old service so nothing publishes mid-copy:
   `sudo systemctl stop display-mcp cloudflared`.
2. Copy its state into the new volume (the old uid does not carry over; the
   image runs as 10001):

   ```bash
   scp -r old-host:/var/lib/display-mcp ./old-state
   docker compose -f deploy/compose.yaml create display-mcp
   docker run --rm --user 0 --entrypoint sh \
     -v display-mcp_state:/dst -v "$PWD/old-state:/src:ro" \
     "$(docker compose -f deploy/compose.yaml images -q display-mcp)" \
     -c 'cp -a /src/. /dst/ && chown -R 10001:10001 /dst'
   ```

3. Reuse the same tunnel token. The tunnel's public-hostname service stays
   `http://localhost:8001`.
4. Start the stack and check `/healthz` lists the old displays with their
   hashes. The panel's next wake gets a 304 — same document, same ETag.
5. Once it has, `sudo ./deploy/setup.sh uninstall` on the old host.

## Updating and rolling back

```bash
docker compose -f deploy/compose.yaml pull
docker compose -f deploy/compose.yaml up -d
```

For a deploy you can roll back, pin `DISPLAY_MCP_IMAGE` in `deploy/.env` to a
version or `sha-<short>` tag instead of `latest`; rolling back is setting the
previous tag and running the same two commands. State lives in the
`display-mcp_state` volume and survives both.
