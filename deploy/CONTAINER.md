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
