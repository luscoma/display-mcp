# Proxmox: an LXC straight from the image


Proxmox VE 9.1 and later can pull an OCI image and run it as an LXC, with no
Docker anywhere. The feature is a technology preview. `/healthz` is the
check at every step.

## The script

`deploy/proxmox-lxc.sh` does every step below. It is self-contained, so copy
it to the Proxmox host and run it as root in its shell; no checkout needed.
Start with `--dry-run`.

```bash
./proxmox-lxc.sh install --image ghcr.io/<owner>/display-mcp:sha-<short> \
    --ip 192.168.1.20/24 --gw 192.168.1.1 \
    --access-team-domain https://<team>.cloudflareaccess.com --access-aud <tag> \
    --dry-run

./proxmox-lxc.sh upgrade --ctid 120 --image ghcr.io/<owner>/display-mcp:sha-<newer>
./proxmox-lxc.sh status --ctid 120
./proxmox-lxc.sh --help
```

**`install`**
- Pulls the image as a template, via `pvesh create
  /nodes/<node>/storage/<storage>/oci-registry-pull`.
- Creates an unprivileged container with one or more NICs and a mount point
  for `/var/lib/display-mcp`. `--ip/--gw` describe a single static NIC; for
  more, or a VLAN tag or DHCP, repeat `--net` (see "Two networks" below).
- Merges the `DISPLAY_MCP_*` settings into the container's `env` and reads
  them back.
- Makes the mount point writable by the image's uid from the host, before
  the first start.
- Optionally unpacks an old state directory (`--state-from state.tar`).
- Starts the container and waits for `/healthz`.

**`upgrade`**
- Creates a new container from a new tag with the old one's settings, and
  moves the state volume across with `pct move-volume`.
- If the new container never goes healthy, it puts the volume back and
  restarts the old one.
- The old container is left stopped either way; `pct destroy` it when
  you're happy.
- Rolling back is an upgrade to the previous tag.

**Two networks, a VLAN, or DHCP.** Each `--net` is one NIC, `eth0` first:

```bash
./proxmox-lxc.sh install --image ghcr.io/<owner>/display-mcp:sha-<short> \
    --storage local-lvm \
    --net bridge=vmbr0,ip=dhcp,tag=2,hwaddr=BC:24:11:00:00:01 \
    --net bridge=vmbr1,ip=10.0.30.5/24 \
    --panel-bind 0.0.0.0 --server-host 10.0.30.5
```

- Only one NIC can carry `gw=`. `upgrade` carries every NIC across, `hwaddr`
  included.
- The service binds each address in `--panel-bind` exactly. With a static
  `ip=` the default is `<eth0 ip>,127.0.0.1`. With `ip=dhcp` the address is
  unknown up front, so `--panel-bind` is required. Pin the MAC with
  `hwaddr=`, start with `0.0.0.0`, read the leased address from `status`,
  reserve it in the DHCP server, then bind to it:
  `./proxmox-lxc.sh set-env --ctid <ctid> --panel-bind <address>` (it
  reboots the container; `--server-host` and `--env KEY=VALUE` work too).
- `0.0.0.0` must stand alone: `0.0.0.0,127.0.0.1` fails with "address in
  use", and the script refuses it.
- `/healthz` is checked from inside the container, on loopback, so the host
  need not reach the container's VLAN.

**Validated** on Proxmox VE 9.2.21 (install, publish and upgrade, with two NICs:
a VLAN-tagged DHCP one and a static one), these being the guesses the
script was written on:
- **The pull**: works. The multi-arch index with provenance entries pulls
  fine. `pvesh create .../oci-registry-pull` runs the task to completion and
  streams its log; it does not return a UPID to poll.
- **`env`**: `pct set --env` cannot be driven from a shell. The value must
  be NUL-separated, and bash cannot hold a NUL: `"A=1\0B=2"` is stored as one
  variable with a literal backslash-zero, and `$(printf 'A=1\0B=2')` loses
  the NUL (see bugzilla.proxmox.com/show_bug.cgi?id=7377). The script writes
  `env` through PVE's own `PVE::LXC::Config` and reads it back with
  `tr '\0' '\n'`. The GUI (Options → Environment) works too.
- **`pct mount`**: mounts the state volume under
  `/var/lib/lxc/<ctid>/rootfs`.
- **`pct move-volume`**: with `--target-vmid` it keeps `mp=`, and the
  state (the published display and its hash) survives an upgrade.

## By hand

The same steps in the GUI, for when the script falls over or you want to see
each one.

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

A moving tag such as `:main` is fine for a container you follow along with,
but a new `upgrade` has to fetch it again. The script does that: it keeps a
cached template only for `sha-` tags and digests, which never change, and
re-pulls any other tag every time. By hand, delete the old template in the
storage's CT Templates first, because Proxmox will not pull over an existing
one. Nothing needs the template once a container has been made from it.

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
reaches it on (CONTAINER.md, "Choosing the addresses").

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

If `DISPLAY_MCP_SERVER_HOST` is not loopback, the CLI's default
(`http://127.0.0.1:8001/mcp`) has nothing to talk to; add
`--url http://<server-host>:8001/mcp`.

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

This is optional. The state directory holds only the published displays
(`<name>.json`) and the panel's fetch history (`<name>.meta.json`: first and
latest fetch, battery, wakes). Nothing else lives there, and the displays are
just documents Claude published. So the move buys two things:

- Any display that exists only on the old host survives. If you can have
  Claude publish it again, you lose nothing; if you can't, copy it across.
- The panel keeps its history and does not redraw. A republished document
  with the same content has the same hash, so the panel gets a 304 either
  way; the copy mostly spares you the republishing and keeps the status
  history.

If you would rather start fresh, skip this section: install, publish what you
want shown, and retire the old host when you are happy.

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

