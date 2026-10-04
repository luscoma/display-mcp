#!/usr/bin/env bash
#
# proxmox-lxc.sh — run display-mcp on Proxmox VE 9.1+ as an LXC created
# straight from the published OCI image. No Docker, no checkout: run it as
# root in the Proxmox host's shell. deploy/PROXMOX.md explains each step.
#
#   ./proxmox-lxc.sh install --image ghcr.io/<owner>/display-mcp:sha-abc1234 \
#                            --ip 192.168.1.20/24 --gw 192.168.1.1
#   two networks (the tag and gateway on whichever carries them):
#                            --net bridge=vmbr0,ip=10.0.20.5/24,gw=10.0.20.1,tag=20 \\
#                            --net bridge=vmbr0,ip=192.168.1.20/24
#   ./proxmox-lxc.sh upgrade --ctid 120 --image ghcr.io/<owner>/display-mcp:sha-def5678
#   ./proxmox-lxc.sh status  --ctid 120
#
# --dry-run prints the plan and changes nothing. Use it first.
#
# install pulls the image as a template, creates an unprivileged container
# with a static address and a mount point for /var/lib/display-mcp, sets the
# DISPLAY_MCP_* environment, makes the mount point writable by the image's
# uid, starts it and waits for /healthz.
#
# upgrade creates a new container from a new image with the old one's
# settings, moves the state volume across, and starts it. If the new one
# never goes healthy, the volume goes back and the old container restarts.
# The old container is left stopped either way; destroy it when happy.
# Rolling back is an upgrade to the previous tag.

set -euo pipefail

# --- defaults -------------------------------------------------------------

CMD=""
IMAGE=""
CTID=""
NEW_CTID=""
IP=""
GW=""
BRIDGE=vmbr0
NETS=()              # one "bridge=..,ip=..[,gw=..][,tag=..]" per NIC, net0 first
TEMPLATE_STORAGE=local
STORAGE=local-lvm
ROOTFS_SIZE=2
STATE_SIZE=1
HOSTNAME_=display-mcp
CORES=1
MEMORY=512
NAMESERVER=""
PANEL_BIND=""
SERVER_HOST=127.0.0.1
SERVER_HOST_SET=0
ACCESS_TEAM_DOMAIN=""
ACCESS_AUD=""
STATE_FROM=""
EXTRA_ENV=()
DRY=0
VOLID=""

STATE_DIR=/var/lib/display-mcp
PANEL_PORT=8080
APP_UID=10001        # the image's USER; see the Dockerfile
NODE=$(hostname)

# --- output ---------------------------------------------------------------

if [ -t 1 ]; then B=$'\e[1m'; R=$'\e[31m'; Y=$'\e[33m'; G=$'\e[32m'; Z=$'\e[0m'
else B=""; R=""; Y=""; G=""; Z=""; fi

log()  { printf '%s==>%s %s\n' "$B" "$Z" "$*"; }
ok()   { printf '    %s+%s %s\n' "$G" "$Z" "$*"; }
skip() { printf '    %s=%s %s\n' "$Z" "$Z" "$*"; }
warn() { printf '    %s!%s %s\n' "$Y" "$Z" "$*" >&2; }
die()  { printf '%serror:%s %s\n' "$R" "$Z" "$*" >&2; exit 1; }

run() {
  if [ "$DRY" = 1 ]; then printf '    would run: %s\n' "$*"; return 0; fi
  "$@"
}

# --- pieces ---------------------------------------------------------------

need_pve() {
  [ "$(id -u)" = 0 ] || die "run this as root in the Proxmox host's shell"
  if ! command -v pct >/dev/null 2>&1 || ! command -v pvesh >/dev/null 2>&1; then
    die "pct/pvesh not found — this runs on a Proxmox VE host"
  fi
  local ver major minor
  ver=$(pveversion 2>/dev/null | sed -n 's|^pve-manager/\([0-9]*\.[0-9]*\).*|\1|p')
  major=${ver%%.*} minor=${ver#*.}
  if [ -z "$ver" ] || [ "$major" -lt 9 ] || { [ "$major" = 9 ] && [ "$minor" -lt 1 ]; }; then
    die "Proxmox VE 9.1+ is needed for OCI images (found ${ver:-unknown})"
  fi
}

# ghcr.io/owner/display-mcp:sha-abc1234 -> display-mcp_sha-abc1234. Already in
# the character set the pull normalises filenames to, so the name it writes
# is the name we look for.
template_name() {
  local ref=$1 repo tag
  case "$ref" in *:*) tag=${ref##*:}; repo=${ref%:*} ;; *) die "--image needs an explicit tag, not just a name" ;; esac
  [ "$tag" = latest ] && warn "pinning :latest means you cannot tell versions apart later; prefer a sha- or version tag"
  repo=${repo##*/}
  printf '%s_%s' "$repo" "$tag" | tr -c 'a-zA-Z0-9_.\n-' '_'
}

template_volid() {
  local name=$1
  { pvesm list "$TEMPLATE_STORAGE" --content vztmpl 2>/dev/null || true; } \
    | awk -v n="$name" '$1 ~ "/" n "\\.tar$" { print $1; exit }'
}

# Sets VOLID to the template's volume id.
pull_image() {
  local name
  name=$(template_name "$IMAGE")
  VOLID=$(template_volid "$name")
  if [ -n "$VOLID" ]; then
    # A sha- tag or a digest never changes, so a cached template is the image.
    # Any other tag (main, latest, a version) can move: drop the cached copy,
    # because pvesh refuses to pull over an existing file. Nothing references
    # a template once a CT has been made from it.
    case "$IMAGE" in
      *:sha-*|*@sha256:*) skip "template $VOLID already present"; return 0 ;;
    esac
    if [ "$DRY" = 1 ]; then
      printf '    would run: pvesm free %s (the tag can move; pulling it again)\n' "$VOLID"
    else
      warn "$IMAGE is a moving tag; re-pulling over the cached $VOLID"
      pvesm free "$VOLID" >/dev/null
    fi
  fi
  log "pulling $IMAGE into $TEMPLATE_STORAGE as $name.tar"
  if [ "$DRY" = 1 ]; then
    printf '    would run: pvesh create /nodes/%s/storage/%s/oci-registry-pull --reference %s --filename %s\n' \
      "$NODE" "$TEMPLATE_STORAGE" "$IMAGE" "$name"
    VOLID=$TEMPLATE_STORAGE:vztmpl/$name.tar
    return 0
  fi
  # pvesh runs the pull as a task and streams its log until it ends (it does
  # not hand back a UPID to poll); a failed task is a non-zero exit.
  pvesh create "/nodes/$NODE/storage/$TEMPLATE_STORAGE/oci-registry-pull" \
    --reference "$IMAGE" --filename "$name" >&2 \
    || die "the pull of $IMAGE failed (log above)"
  VOLID=$(template_volid "$name")
  [ -n "$VOLID" ] || die "the pull finished but no $name.tar is listed on $TEMPLATE_STORAGE; check: pvesm list $TEMPLATE_STORAGE --content vztmpl"
  ok "pulled $VOLID"
}

# The container's `env` is a list separated by real NUL bytes, which bash
# cannot hold in a variable or an argument, so `pct set --env` cannot be
# driven from here (a literal backslash-zero is stored as value text). Go
# through PVE's own config module instead: merge ours over whatever is there
# (the image's defaults, filled in at create), then read it back.
cur_env() { pct config "$1" | sed -n 's/^env: //p' | tr '\0' '\n'; }

set_env() {
  local ct=$1; shift
  local item want
  if [ "$DRY" = 1 ]; then
    printf '    would set env on CT %s (merged over the image defaults):\n' "$ct"
    for item in "$@"; do printf '      %s\n' "$item"; done
    return 0
  fi
  perl -MPVE::LXC::Config -e '
    my ($ct, @set) = @ARGV;
    PVE::LXC::Config->lock_config($ct, sub {
      my $conf = PVE::LXC::Config->load_config($ct);
      my %ours = map { (split /=/, $_, 2)[0] => 1 } @set;
      my @keep = grep { !$ours{(split /=/, $_, 2)[0]} } split(/\0+/, $conf->{env} // "");
      $conf->{env} = join("\0", @keep, @set);
      PVE::LXC::Config->write_config($ct, $conf);
    });' "$ct" "$@" || die "could not write the environment of CT $ct"
  for want in "$@"; do
    cur_env "$ct" | grep -qxF -- "$want" \
      || die "env on CT $ct did not take $want. Set it in the GUI (Options → Environment), then: pct start $ct"
  done
  ok "environment set ($# variables)"
}

# A fresh mount point is root-owned; the image runs as uid $APP_UID, which an
# unprivileged container maps to 100000+$APP_UID on the host. Fix it from the
# host before the first start, so the app never starts unable to write; and
# unpack --state-from into it while it is mounted.
prepare_state() {
  local ct=$1 root dir host_uid
  host_uid=$((100000 + APP_UID))
  if [ "$DRY" = 1 ]; then
    printf '    would run: pct mount %s; chown %s:%s <rootfs>%s\n' "$ct" "$host_uid" "$host_uid" "$STATE_DIR"
    [ -n "$STATE_FROM" ] && printf '    would unpack %s into it\n' "$STATE_FROM"
    printf '    would run: pct unmount %s\n' "$ct"
    return 0
  fi
  if pct config "$ct" | grep -q '^lxc.idmap'; then
    warn "CT $ct has a custom idmap; chowning from inside instead"
    return 1
  fi
  pct mount "$ct" >/dev/null
  root=/var/lib/lxc/$ct/rootfs
  dir=$root$STATE_DIR
  if ! mountpoint -q "$dir"; then
    pct unmount "$ct"
    warn "pct mount did not mount the state volume at $dir; chowning from inside instead"
    return 1
  fi
  if [ -n "$STATE_FROM" ]; then
    tar -C "$dir" -xf "$STATE_FROM"
    ok "unpacked $STATE_FROM"
  fi
  chown -R "$host_uid:$host_uid" "$dir"
  pct unmount "$ct"
  ok "state volume owned by uid $APP_UID inside the container"
}

# NETS -> NET_ARGS (the pct --netN strings) and IP (net0's address, which the
# default panel bind and the health check use).
build_nets() {
  NET_ARGS=(); STATIC_IPS=()
  local spec n=0 gws=0 first=""
  for spec in "${NETS[@]}"; do
    case ",$spec," in *,ip=*/*,*|*,ip=dhcp,*) ;; *) die "--net '$spec' needs ip=CIDR with a prefix length, or ip=dhcp" ;; esac
    case ",$spec," in *,bridge=*,*) ;; *) die "--net '$spec' needs bridge=NAME" ;; esac
    case ",$spec," in *,gw=*,*) gws=$((gws + 1)) ;; esac
    [ -n "$first" ] || first=$(printf '%s' "$spec" | sed -n 's/.*ip=\([^,]*\).*/\1/p')
    case ",$spec," in *,ip=dhcp,*) ;; *) STATIC_IPS+=("$(printf '%s' "$spec" | sed -n 's/.*ip=\([^,/]*\).*/\1/p')") ;; esac
    case ",$spec," in *,name=*,*) NET_ARGS+=("$spec") ;; *) NET_ARGS+=("name=eth$n,$spec") ;; esac
    n=$((n + 1))
  done
  [ "$gws" -le 1 ] || die "only one network can carry a gw= (the default route)"
  IP=$first
}

# Where the panel is, for the health check. Preferably from inside the CT on
# loopback (the host may not be on the CT's VLAN, and a DHCP address is not
# known up front); otherwise the first non-loopback panel-bind address.
HEALTH_CT=""
loopback_bound() { case ",$PANEL_BIND," in *,127.0.0.1,*|*,0.0.0.0,*) return 0 ;; esac; return 1; }

panel_addr() {
  local a
  for a in $(printf '%s' "$PANEL_BIND" | tr ',' ' '); do
    case "$a" in 127.*|::1|localhost|0.0.0.0) ;; *) printf '%s' "$a"; return ;; esac
  done
  # DHCP or a wildcard bind: ask LXC for the CT's addresses, skipping the static ones
  local ip s skip
  for ip in $(lxc-info -n "${HEALTH_CT:-$CTID}" -iH 2>/dev/null); do
    skip=0
    for s in ${STATIC_IPS[@]+"${STATIC_IPS[@]}"}; do [ "$ip" = "$s" ] && skip=1; done
    [ "$skip" = 0 ] && { printf '%s' "$ip"; return; }
  done
  case "$IP" in dhcp) printf '<eth0 DHCP address>' ;; *) printf '%s' "${IP%%/*}" ;; esac
}

healthz_url() { printf 'http://%s:%s/healthz' "$(panel_addr)" "$PANEL_PORT"; }

# One probe of /healthz; prints the body.
probe() {
  if loopback_bound && [ -n "$HEALTH_CT" ]; then
    pct exec "$HEALTH_CT" -- python3 -c \
      "import urllib.request as u;print(u.urlopen('http://127.0.0.1:$PANEL_PORT/healthz',timeout=3).read().decode())" 2>/dev/null
  else
    curl -fsS --max-time 3 "$(healthz_url)" 2>/dev/null
  fi
}

wait_healthy() {
  HEALTH_CT=$1
  local body
  [ "$DRY" = 1 ] && { printf '    would poll /healthz on CT %s (%s)\n' "$HEALTH_CT" "$(loopback_bound && echo 'inside it, on loopback' || healthz_url)"; return 0; }
  for _ in $(seq 45); do
    body=$(probe || true)
    case "$body" in
      *'"fonts_loaded":true'*'"state_dir_writable":true'*) ok "healthy: $(healthz_url)"; return 0 ;;
      *'"state_dir_writable":false'*) warn "up, but $STATE_DIR is not writable"; return 2 ;;
    esac
    sleep 2
  done
  return 1
}

# --- commands -------------------------------------------------------------

do_install() {
  [ -n "$IMAGE" ] || die "--image is required"
  if [ -n "$IP" ]; then
    [ -n "$GW" ] || die "--ip needs --gw (or describe the NIC with --net)"
    case "$IP" in */*) ;; *) die "--ip needs a prefix length, e.g. ${IP}/24" ;; esac
    NETS=("bridge=$BRIDGE,ip=$IP,gw=$GW" "${NETS[@]}")
  fi
  [ "${#NETS[@]}" -gt 0 ] || die "a static address is required: --ip CIDR --gw IP, or --net bridge=..,ip=CIDR[,gw=IP][,tag=N] (the panel's firmware points at it)"
  build_nets
  [ -z "$STATE_FROM" ] || [ -r "$STATE_FROM" ] || die "--state-from $STATE_FROM is not readable"
  need_pve
  [ -n "$CTID" ] || CTID=$(pvesh get /cluster/nextid)
  pct status "$CTID" >/dev/null 2>&1 && die "CT $CTID already exists"
  case "$IP" in
    dhcp) [ -n "$PANEL_BIND" ] || die "eth0 is dhcp, so its address is unknown: pass --panel-bind (a reserved address, or 0.0.0.0 for every NIC)" ;;
  esac
  : "${PANEL_BIND:=${IP%%/*},127.0.0.1}"
  case ",$PANEL_BIND," in
    *,0.0.0.0,*) [ "$PANEL_BIND" = 0.0.0.0 ] || die "--panel-bind: 0.0.0.0 already covers every address, and the service binds each entry exactly, so listing others with it fails (address in use). Use 0.0.0.0 alone." ;;
  esac   # IP is net0's address (build_nets)

  pull_image

  log "creating CT $CTID from $VOLID"
  local args=(
    "$CTID" "$VOLID" --description "image: $IMAGE"
    --hostname "$HOSTNAME_" --unprivileged 1 --onboot 1
    --cores "$CORES" --memory "$MEMORY" --swap 0
    --rootfs "$STORAGE:$ROOTFS_SIZE"
    --mp0 "$STORAGE:$STATE_SIZE,mp=$STATE_DIR"
  )
  local i
  for i in "${!NET_ARGS[@]}"; do args+=("--net$i" "${NET_ARGS[$i]}"); done
  [ -n "$NAMESERVER" ] && args+=(--nameserver "$NAMESERVER")
  run pct create "${args[@]}"
  ok "CT $CTID created"

  log "setting the environment"
  local env=(
    "DISPLAY_MCP_PANEL_BIND=$PANEL_BIND"
    "DISPLAY_MCP_SERVER_HOST=$SERVER_HOST"
  )
  [ -n "$ACCESS_TEAM_DOMAIN" ] && env+=("DISPLAY_MCP_CF_ACCESS_TEAM_DOMAIN=$ACCESS_TEAM_DOMAIN")
  [ -n "$ACCESS_AUD" ] && env+=("DISPLAY_MCP_CF_ACCESS_AUD=$ACCESS_AUD")
  env+=("${EXTRA_ENV[@]}")
  set_env "$CTID" "${env[@]}"

  log "preparing $STATE_DIR"
  local from_inside=0
  prepare_state "$CTID" || from_inside=1

  log "starting CT $CTID"
  run pct start "$CTID"
  if [ "$from_inside" = 1 ]; then
    run pct exec "$CTID" -- chown -R "$APP_UID:$APP_UID" "$STATE_DIR"
    [ -n "$STATE_FROM" ] && warn "--state-from was not unpacked; see PROXMOX.md, 'Moving from the systemd host'"
    run pct reboot "$CTID"
  fi
  local rc=0
  wait_healthy "$CTID" || rc=$?
  case "$rc" in
    0) ;;
    2) die "fix ownership by hand: pct exec $CTID -- chown -R $APP_UID:$APP_UID $STATE_DIR && pct reboot $CTID" ;;
    *) die "no healthy answer from $(healthz_url). Look at: pct console $CTID" ;;
  esac
  [ -z "$ACCESS_TEAM_DOMAIN" ] && warn "Cloudflare Access is not configured: the MCP endpoint on $SERVER_HOST is authless"

  cat <<EOF

${B}Done.${Z} CT $CTID runs $IMAGE.
  panel     http://$(HEALTH_CT=$CTID panel_addr):$PANEL_PORT/display.json
  health    $(healthz_url)
  mcp       $SERVER_HOST, port 8001, path /mcp

Point the panel's firmware at the panel URL if the address changed, and
whatever fronts the MCP endpoint at its address.
EOF
}

do_upgrade() {
  [ -n "$CTID" ] || die "--ctid (the running container) is required"
  [ -n "$IMAGE" ] || die "--image is required"
  need_pve
  pct status "$CTID" >/dev/null 2>&1 || die "CT $CTID does not exist"
  local conf
  conf=$(pct config "$CTID" | tr '\0' '\n')
  printf '%s\n' "$conf" | grep -q "^mp0: .*mp=$STATE_DIR" \
    || die "CT $CTID has no mp0 at $STATE_DIR; upgrade only moves that volume"

  local net0 rootfs rstore rsize
  # Every netN, hwaddr included: the new CT keeps the MAC, so a DHCP
  # reservation (and the panel bind that names its address) still holds. The
  # old CT is stopped before the new one starts, so the two never share it live.
  NET_ARGS=(); STATIC_IPS=()
  while IFS= read -r net0; do
    case "$net0" in *ip=*/*|*ip=dhcp*) ;; *) die "CT $CTID has a NIC with no ip= ($net0)" ;; esac
    NET_ARGS+=("$net0")
    case "$net0" in *ip=dhcp*) ;; *) STATIC_IPS+=("$(printf '%s' "$net0" | sed -n 's/.*ip=\([^,/]*\).*/\1/p')") ;; esac
  done < <(printf '%s\n' "$conf" | sed -n 's/^net[0-9]*: //p')
  [ "${#NET_ARGS[@]}" -gt 0 ] || die "CT $CTID has no network"
  IP=$(printf '%s' "${NET_ARGS[0]}" | sed -n 's/.*ip=\([^,]*\).*/\1/p')
  rootfs=$(printf '%s\n' "$conf" | sed -n 's/^rootfs: //p')
  rstore=${rootfs%%:*}
  rsize=$(printf '%s' "$rootfs" | sed -n 's/.*size=\([0-9]*\)G.*/\1/p')
  [ -n "$NEW_CTID" ] || NEW_CTID=$(pvesh get /cluster/nextid)

  pull_image

  log "creating CT $NEW_CTID from $VOLID with CT $CTID's settings"
  local args=(
    "$NEW_CTID" "$VOLID" --description "image: $IMAGE" --unprivileged 1 --onboot 1
    --hostname "$(printf '%s\n' "$conf" | sed -n 's/^hostname: //p')"
    --cores "$(printf '%s\n' "$conf" | sed -n 's/^cores: //p')"
    --memory "$(printf '%s\n' "$conf" | sed -n 's/^memory: //p')"
    --swap 0
    --rootfs "$rstore:${rsize:-$ROOTFS_SIZE}"
  )
  local i
  for i in "${!NET_ARGS[@]}"; do args+=("--net$i" "${NET_ARGS[$i]}"); done
  local ns; ns=$(printf '%s\n' "$conf" | sed -n 's/^nameserver: //p')
  [ -n "$ns" ] && args+=(--nameserver "$ns")
  run pct create "${args[@]}"

  # The old container's DISPLAY_MCP_* settings, over the new image's defaults.
  local env=() item
  while IFS= read -r item || [ -n "$item" ]; do
    case "$item" in
      DISPLAY_MCP_*) env+=("$item") ;;
    esac
    case "$item" in DISPLAY_MCP_PANEL_BIND=*) PANEL_BIND=${item#*=} ;; esac
  done < <(cur_env "$CTID")
  env+=("${EXTRA_ENV[@]}")
  set_env "$NEW_CTID" "${env[@]}"

  log "moving the state volume from CT $CTID to CT $NEW_CTID"
  run pct stop "$CTID"
  run pct set "$CTID" --onboot 0
  run pct move-volume "$CTID" mp0 --target-vmid "$NEW_CTID" --target-volume mp0
  if [ "$DRY" = 0 ]; then
    local vol; vol=$(pct config "$NEW_CTID" | sed -n 's/^mp0: \([^,]*\).*/\1/p')
    if [ -z "$vol" ]; then
      run pct set "$CTID" --onboot 1
      run pct start "$CTID"
      die "the state volume did not arrive on CT $NEW_CTID; CT $CTID restarted. Look at: pct config $CTID; pct config $NEW_CTID"
    fi
    pct config "$NEW_CTID" | grep -q "^mp0: .*mp=$STATE_DIR" || pct set "$NEW_CTID" --mp0 "$vol,mp=$STATE_DIR"
  fi

  run pct start "$NEW_CTID"
  if ! wait_healthy "$NEW_CTID"; then
    warn "CT $NEW_CTID did not go healthy; putting CT $CTID back"
    run pct stop "$NEW_CTID"
    run pct move-volume "$NEW_CTID" mp0 --target-vmid "$CTID" --target-volume mp0
    run pct set "$CTID" --onboot 1
    run pct start "$CTID"
    die "upgrade rolled back; CT $NEW_CTID is left stopped for a look (pct console $NEW_CTID)"
  fi

  cat <<EOF

${B}Done.${Z} CT $NEW_CTID runs $IMAGE on CT $CTID's address and state.
CT $CTID is stopped and will not start on boot. When you are happy:
  pct destroy $CTID
EOF
}

do_status() {
  [ -n "$CTID" ] || die "--ctid is required"
  need_pve
  local conf
  conf=$(pct config "$CTID" | tr '\0' '\n')
  IP=$(printf '%s\n' "$conf" | sed -n 's/^net0: .*ip=\([^,]*\).*/\1/p')
  PANEL_BIND=$(cur_env "$CTID" | sed -n 's/^DISPLAY_MCP_PANEL_BIND=//p')
  printf '  ct        %s (%s)\n' "$CTID" "$(pct status "$CTID" | sed 's/^status: //')"
  printf '  %s\n' "$(printf '%s\n' "$conf" | sed -n 's/^description: //p' | head -1 | sed 's/%3A/:/g; s/%0A//g')"
  HEALTH_CT=$CTID
  printf '  health    %s\n' "$(probe || echo "no answer from $(healthz_url)")"
}

do_set_env() {
  [ -n "$CTID" ] || die "--ctid is required"
  need_pve
  pct status "$CTID" >/dev/null 2>&1 || die "CT $CTID does not exist"
  local env=()
  [ -n "$PANEL_BIND" ] && env+=("DISPLAY_MCP_PANEL_BIND=$PANEL_BIND")
  [ "$SERVER_HOST_SET" = 1 ] && env+=("DISPLAY_MCP_SERVER_HOST=$SERVER_HOST")
  env+=(${EXTRA_ENV[@]+"${EXTRA_ENV[@]}"})
  [ "${#env[@]}" -gt 0 ] || die "nothing to set: give --env KEY=VALUE, --panel-bind or --server-host"
  set_env "$CTID" "${env[@]}"
  run pct reboot "$CTID"
}

# --- args -----------------------------------------------------------------

usage() {
  awk 'NR>2 && /^#/ { sub(/^#[[:space:]]?/, ""); print; next } NR>2 { exit }' "${BASH_SOURCE[0]}"
  cat <<'EOF'

Commands:
  install     pull the image and create, configure and start a new container
  upgrade     move a container's state onto a new one from a new image
  status      the container's state and its /healthz
  set-env     change settings on a container (--env KEY=VALUE, --panel-bind, --server-host), then reboot it

Flags:
  --image REF                 ghcr.io/<owner>/display-mcp:<tag> (install, upgrade)
  --ctid N                    install: the new CT's id (default: next free);
                              upgrade/status: the existing CT
  --new-ctid N                upgrade: the replacement CT's id (default: next free)
  --net SPEC                  a NIC: bridge=vmbr0,ip=10.0.20.5/24[,gw=10.0.20.1][,tag=20]
                              (ip=dhcp is fine: add hwaddr=BC:24:11:.. to pin the MAC,
                              reserve it in DHCP, and give --panel-bind that address)
                              repeatable; the first is eth0, the second eth1.
                              At most one carries gw=. (install)
  --ip CIDR --gw IP           shorthand for a first --net on --bridge (install)
  --bridge NAME               default: vmbr0 (for --ip/--gw)
  --nameserver IP             default: the host's
  --storage NAME              root disk and state volume storage (default: local-lvm)
  --template-storage NAME     where the image is pulled to (default: local)
  --state-size GB             default: 1
  --hostname NAME             default: display-mcp
  --cores N / --memory MB     default: 1 / 512
  --panel-bind LIST           default: "<eth0's ip>,127.0.0.1"; list every address
                              the panel should answer on
  --server-host LIST          MCP bind (default: 127.0.0.1)
  --access-team-domain URL    Cloudflare Access team domain
  --access-aud TAG            Cloudflare Access AUD tag
  --env KEY=VALUE             any other variable; repeatable
  --state-from FILE.tar       install: unpack an old state directory into the volume
  --dry-run                   print the plan, change nothing
EOF
}

CMD=${1:-}
[ $# -gt 0 ] && shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --image) IMAGE=${2:?}; shift 2 ;;
    --ctid) CTID=${2:?}; shift 2 ;;
    --new-ctid) NEW_CTID=${2:?}; shift 2 ;;
    --ip) IP=${2:?}; shift 2 ;;
    --gw) GW=${2:?}; shift 2 ;;
    --bridge) BRIDGE=${2:?}; shift 2 ;;
    --net) NETS+=("${2:?}"); shift 2 ;;
    --nameserver) NAMESERVER=${2:?}; shift 2 ;;
    --storage) STORAGE=${2:?}; shift 2 ;;
    --template-storage) TEMPLATE_STORAGE=${2:?}; shift 2 ;;
    --state-size) STATE_SIZE=${2:?}; shift 2 ;;
    --hostname) HOSTNAME_=${2:?}; shift 2 ;;
    --cores) CORES=${2:?}; shift 2 ;;
    --memory) MEMORY=${2:?}; shift 2 ;;
    --panel-bind) PANEL_BIND=${2:?}; shift 2 ;;
    --server-host) SERVER_HOST=${2:?}; SERVER_HOST_SET=1; shift 2 ;;
    --access-team-domain) ACCESS_TEAM_DOMAIN=${2:?}; shift 2 ;;
    --access-aud) ACCESS_AUD=${2:?}; shift 2 ;;
    --env) case "${2:?}" in *=*) EXTRA_ENV+=("$2") ;; *) die "--env wants KEY=VALUE" ;; esac; shift 2 ;;
    --state-from) STATE_FROM=${2:?}; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown flag: $1 (see --help)" ;;
  esac
done

case "$CMD" in
  install) do_install ;;
  upgrade) do_upgrade ;;
  status) do_status ;;
  set-env) do_set_env ;;
  ""|-h|--help|help) usage ;;
  *) die "unknown command: $CMD (see --help)" ;;
esac
