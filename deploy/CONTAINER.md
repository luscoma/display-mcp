# Running in a container (Proxmox)

The same process `setup.sh` installs, packaged as an OCI image and published
to GitHub Container Registry by `.github/workflows/container.yml`. On Proxmox
it runs in a VM with two network legs:

| Listener | Bind | Reached by |
|---|---|---|
| panel | `<lan-ip>:8080`, `127.0.0.1:8080` | the e-paper, over the LAN |
| MCP | `<tunnel-net-ip>:8001`, `127.0.0.1:8001` | a cloudflared LXC on a tunnel-only network; you, on the VM |

The MCP endpoint never listens on the LAN, and neither listener takes a
wildcard (`main.py` refuses one). Binding MCP off loopback is refused unless
Cloudflare Access is configured. Off loopback, `auth.py`'s local-operator
exemption never applies, so every request through the tunnel needs an Access
JWT.

| Piece | Where |
|---|---|
| `Dockerfile` | the image: venv, fonts baked in, non-root (uid 10001), `/healthz` healthcheck |
| `deploy/compose.yaml` | display-mcp on host networking |
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

## Network

The addresses below are examples: `192.168.1.0/24` is the LAN on `vmbr0`,
and `10.99.0.0/24` is a tunnel-only network on a new bridge, `vmbr1`. Pick a
range your LAN doesn't use.

```
internet ── vmbr0 (LAN, 192.168.1.0/24) ── panel, your machines
              │
         Proxmox host ── NAT, no route to the LAN ──┐
                                                    │
            vmbr1 (tunnel-only, 10.99.0.0/24, no physical port)
              ├── cloudflared LXC   10.99.0.2
              └── display-mcp VM    10.99.0.20  (+ 192.168.1.20 on vmbr0)
```

cloudflared's only network is `vmbr1`. It can reach whatever has a leg on
that bridge, plus the internet through the host's NAT, and nothing on the
LAN. A service is exposed by giving it a second NIC on `vmbr1` and a public
hostname in the tunnel. Anything without a `vmbr1` leg is out of
cloudflared's reach, whatever happens to cloudflared.

### The bridge, on the Proxmox host

`vmbr1` has no physical port, so the host has to route and NAT for it. In
`/etc/network/interfaces` (then `ifreload -a`):

```
auto vmbr1
iface vmbr1 inet static
    address 10.99.0.1/24
    bridge-ports none
    bridge-stp off
    bridge-fd 0
    post-up   echo 1 > /proc/sys/net/ipv4/ip_forward
    post-up   iptables -t nat -A POSTROUTING -s 10.99.0.0/24 -o vmbr0 -j MASQUERADE
    post-up   iptables -I FORWARD -i vmbr1 -d 192.168.1.0/24 -j DROP
    post-up   iptables -I INPUT -i vmbr1 -m conntrack ! --ctstate ESTABLISHED,RELATED -j DROP
    post-down iptables -t nat -D POSTROUTING -s 10.99.0.0/24 -o vmbr0 -j MASQUERADE
    post-down iptables -D FORWARD -i vmbr1 -d 192.168.1.0/24 -j DROP
    post-down iptables -D INPUT -i vmbr1 -m conntrack ! --ctstate ESTABLISHED,RELATED -j DROP
```

- The `MASQUERADE` rule gives the bridge internet access.
- The `FORWARD` drop keeps it off the LAN. Without it the host routes
  `vmbr1` traffic to `192.168.1.x` happily.
- The `INPUT` drop keeps it off the host itself, including the Proxmox UI on
  `10.99.0.1:8006`. Because of that, guests on `vmbr1` can't use the host
  for DNS; give them a public resolver.
- If the Proxmox firewall is enabled on these guests' NICs, also add the
  conntrack-zone line from the Proxmox admin guide's "Masquerading (NAT)
  with iptables" section, or the NAT'd replies get dropped.

Datacenter → SDN → a Simple zone with SNAT does the bridge and the NAT from
the GUI instead. The two drop rules are still yours to add.

### The cloudflared LXC

A small unprivileged Debian LXC with one NIC, on `vmbr1`: `10.99.0.2/24`,
gateway `10.99.0.1`, DNS `1.1.1.1`. Install cloudflared from Cloudflare's apt
repository and run `cloudflared service install <token>`. One tunnel serves
every exposed service. In the Zero Trust dashboard, set display-mcp's public
hostname to the service `http://10.99.0.20:8001`, behind its Access
application.

### The display-mcp VM

**A small Debian VM running Docker Engine.** 1 vCPU, 1 GB RAM and 8 GB of
disk is plenty. An unprivileged LXC with `nesting=1,keyctl=1` also runs
Docker, but Proxmox recommends a VM for Docker.

It gets two NICs:

- **`net0` on `vmbr0`**: the LAN address, fixed (static, or a DHCP
  reservation), with the default route. `DISPLAY_MCP_PANEL_BIND` and the URL
  compiled into the panel's firmware both depend on it. Giving the VM the
  old host's address means the panel needs no reflash.
- **`net1` on `vmbr1`**: `10.99.0.20/24`, static, with **no gateway**. That
  keeps the default route on the LAN, so the VM's own traffic never goes
  through the tunnel network.

Docker sets the VM's `FORWARD` policy to `DROP`, so the VM does not route
between its two legs.

*Why not Proxmox's own OCI-image-to-LXC path?* Host networking is what lets
one process bind the panel and the MCP endpoint to different interfaces. An
LXC built from the image gets one network namespace of its own, and you'd be
back to configuring that by hand.

## First start

On the VM, with Docker Engine and the compose plugin installed:

```bash
git clone https://github.com/<owner>/display-mcp.git ~/display-mcp
cd ~/display-mcp
cp deploy/compose.env.example deploy/.env
$EDITOR deploy/.env          # image, both addresses, the Access settings
docker compose -f deploy/compose.yaml up -d
docker compose -f deploy/compose.yaml ps        # wait for (healthy)
```

With `DISPLAY_MCP_MCP_HOST=10.99.0.20,127.0.0.1` and the Access settings
empty, the container exits at once and says why. That's deliberate.

The runbook's gates hold unchanged: `curl http://127.0.0.1:8080/healthz`,
then `/display.json` is 503, then 200 + ETag after a publish, then 304 with
`If-None-Match`. Publishing from the VM itself goes over loopback, which
needs no Access token:

```bash
docker compose -f deploy/compose.yaml exec -T display-mcp display-mcp-cli publish /dev/stdin < samples/display.json
```

To check the separation, from a LAN machine `curl http://192.168.1.20:8001/`
should be refused, because nothing listens there. From the cloudflared LXC,
`curl http://10.99.0.20:8001/mcp` should answer 401, and
`curl http://192.168.1.20:8080/healthz` should time out.

## Moving from the systemd host

1. Stop the old service and its tunnel connector, so nothing publishes
   mid-copy and the tunnel has only the new connector:
   `sudo systemctl stop display-mcp cloudflared`.
2. Copy its state into the new volume. The old uid does not carry over; the
   image runs as 10001:

   ```bash
   scp -r old-host:/var/lib/display-mcp ./old-state
   docker compose -f deploy/compose.yaml create display-mcp
   docker run --rm --user 0 --entrypoint sh \
     -v display-mcp_state:/dst -v "$PWD/old-state:/src:ro" \
     "$(docker compose -f deploy/compose.yaml images -q display-mcp)" \
     -c 'cp -a /src/. /dst/ && chown -R 10001:10001 /dst'
   ```

3. Install the same tunnel token in the cloudflared LXC. Change the public
   hostname's service from `http://localhost:8001` to
   `http://10.99.0.20:8001`.
4. Start the stack and check `/healthz` lists the old displays with their
   hashes. The panel's next wake gets a 304: same document, same ETag.
5. Once it has, run `sudo ./deploy/setup.sh uninstall` on the old host.

## Updating and rolling back

```bash
docker compose -f deploy/compose.yaml pull
docker compose -f deploy/compose.yaml up -d
```

For a deploy you can roll back, pin `DISPLAY_MCP_IMAGE` in `deploy/.env` to a
version or `sha-<short>` tag instead of `latest`; rolling back is setting the
previous tag and running the same two commands. State lives in the
`display-mcp_state` volume and survives both.
