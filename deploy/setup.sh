#!/usr/bin/env bash
#
# setup.sh — install or remove the display-mcp server on a Debian host.
# Nothing here is Pi-specific.
#
# Everything it touches, it can put back. Run it twice and nothing changes; run
# `uninstall` and the machine looks like it did before, except for packages you
# may want for other things (apt is left alone).
#
#   sudo ./setup.sh install                 # detects the LAN address itself
#   sudo ./setup.sh install --with-tunnel --tunnel-token TOKEN \
#                            --access-team-domain URL --access-aud TAG
#   sudo ./setup.sh status
#   sudo ./setup.sh uninstall               # keeps /var/lib/display-mcp
#   sudo ./setup.sh uninstall --purge       # takes it too, and the user
#
# --dry-run prints the plan and changes nothing. Use it first.
#
# What it deliberately does NOT do, because it cannot: create the tunnel and
# its Access application in the Cloudflare dashboard, open any hole a router
# needs so the panel can reach this host, or reflash the panel. `install`
# lists those at the end.

set -euo pipefail

# --- where things go ------------------------------------------------------

PREFIX=/opt/display-mcp
STATE=/var/lib/display-mcp
SVC_USER=display-mcp
UNIT=/etc/systemd/system/display-mcp.service
DROPIN_DIR=/etc/systemd/system/display-mcp.service.d
DROPIN=$DROPIN_DIR/10-local.conf

# The public hostname the tunnel serves. Informational only — the tunnel's
# routing lives in the Cloudflare dashboard, not here — so the placeholder is
# harmless until you pass --domain.
DOMAIN=${DISPLAY_MCP_DOMAIN:-<your-mcp-hostname>}
BIND=""
PORT=8080
FONTS_FROM=""
ACCESS_TEAM_DOMAIN=""
ACCESS_AUD=""
WITH_TUNNEL=0
TUNNEL_TOKEN=${DISPLAY_MCP_TUNNEL_TOKEN:-}
CF_UNIT=/etc/systemd/system/cloudflared.service
WITH_FONTS=1
PURGE=0
DRY=0

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd -- "$HERE/.." && pwd)
SAMPLE=$REPO/samples/display.json

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

# Write a file through a temp so a half-written unit never gets loaded, and so
# --dry-run can show the destination without touching it.
write_file() {
  local dest=$1 mode=${2:-0644} owner=${3:-root:root}
  if [ "$DRY" = 1 ]; then
    printf '    would write: %s (%s %s)\n' "$dest" "$mode" "$owner"
    cat >/dev/null
    return 0
  fi
  local tmp
  tmp=$(mktemp "${dest}.XXXXXX")
  cat >"$tmp"
  chmod "$mode" "$tmp"
  chown "$owner" "$tmp"
  mv -f "$tmp" "$dest"
}

# --- pieces ---------------------------------------------------------------

need_root() {
  [ "${DISPLAY_MCP_SETUP_ALLOW_NONROOT:-0}" = 1 ] && return 0
  [ "$(id -u)" = 0 ] || die "run this with sudo"
}

# We are already root, so this is a drop, not an escalation. runuser ships with
# util-linux; sudo is merely usual.
as_svc() {
  if command -v runuser >/dev/null 2>&1; then runuser -u "$SVC_USER" -- "$@"
  else sudo -u "$SVC_USER" "$@"; fi
}

# The address the host actually uses to reach the rest of the network — which is
# the one the panel can reach it on. Not 0.0.0.0: the panel endpoint should not
# be able to appear on an interface you forgot about.
detect_bind() {
  local ip=""
  if command -v ip >/dev/null 2>&1; then
    ip=$(ip -4 -o route get 1.1.1.1 2>/dev/null \
         | sed -n 's/.* src \([0-9.]*\).*/\1/p') || true
  fi
  if [ -z "$ip" ] && command -v hostname >/dev/null 2>&1; then
    ip=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -m1 '^[0-9]' ) || true
  fi
  [ -n "$ip" ] || die "could not detect a LAN address; pass --bind <ip>"
  printf '%s' "$ip"
}

ensure_pkgs() {
  local want=(python3-venv curl ca-certificates) missing=()
  for p in "${want[@]}"; do
    if command -v dpkg >/dev/null 2>&1; then
      dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
    else
      missing+=("$p")
    fi
  done
  if [ ${#missing[@]} -eq 0 ]; then skip "packages already present"; return 0; fi
  log "installing: ${missing[*]}"
  run apt-get update -qq
  run env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing[@]}"
}

ensure_user() {
  if id -u "$SVC_USER" >/dev/null 2>&1; then
    skip "user $SVC_USER exists"
  else
    log "creating system user $SVC_USER"
    run adduser --system --group --no-create-home --home "$PREFIX" "$SVC_USER"
  fi
  run install -d -o "$SVC_USER" -g "$SVC_USER" -m 0755 "$PREFIX" "$PREFIX/fonts"
}

# Same check fetch-fonts.sh makes: a real font, not GitHub's JSON for a 404.
is_font() {
  local f=$1 magic
  [ -s "$f" ] || return 1
  [ "$(wc -c <"$f" | tr -d ' ')" -gt 20000 ] || return 1
  magic=$(od -An -tx1 -N4 "$f" | tr -d ' \n')
  case "$magic" in 00010000|4f54544f|74746366|74727565) return 0 ;; *) return 1 ;; esac
}

install_fonts() {
  if [ "$WITH_FONTS" = 0 ]; then skip "fonts skipped (--no-fonts)"; return 0; fi

  local reg="$PREFIX/fonts/InstrumentSans-Regular.ttf" bold="$PREFIX/fonts/InstrumentSans-Bold.ttf"

  if [ -n "$FONTS_FROM" ]; then
    log "copying fonts from $FONTS_FROM"
    local src
    src=$(find "$FONTS_FROM" -maxdepth 1 -iname '*.ttf' -o -maxdepth 1 -iname '*.otf' | sort | head -1)
    [ -n "$src" ] || die "no .ttf/.otf found in $FONTS_FROM"
    run install -o "$SVC_USER" -g "$SVC_USER" -m 0644 "$src" "$reg"
    run install -o "$SVC_USER" -g "$SVC_USER" -m 0644 "$src" "$bold"
    ok "fonts from $(basename "$src")"
    return 0
  fi

  if [ "$DRY" = 1 ]; then
    printf '    would fetch Instrument Sans into %s (deploy/fetch-fonts.sh)\n' "$PREFIX/fonts"
    return 0
  fi

  if is_font "$reg" && is_font "$bold"; then
    skip "fonts already installed"
    return 0
  fi

  # Download as root into a scratch dir, then install with the service
  # user's ownership. Not as the service user: it cannot read this repo when
  # it lives under a 0700 home directory, which on Debian 13 it does.
  local scratch
  scratch=$(mktemp -d)
  if "$HERE/fetch-fonts.sh" "$scratch"; then
    run install -o "$SVC_USER" -g "$SVC_USER" -m 0644 "$scratch/InstrumentSans-Regular.ttf" "$reg"
    run install -o "$SVC_USER" -g "$SVC_USER" -m 0644 "$scratch/InstrumentSans-Bold.ttf" "$bold"
  else
    warn "the service will not render previews until fonts are in place;"
    warn "the panel endpoint is unaffected. Re-run install once it works, or"
    warn "use --fonts-from <dir> with a Regular+Bold pair."
  fi
  rm -rf "$scratch"
}

# The dependency list between "= [" and the closing "]", so a sync can tell
# you it changed without caring about version pins elsewhere in the file.
deps_of() {
  sed -n '/^dependencies = \[/,/^\]/p' "$1" 2>/dev/null || true
}

# Copies the repo's Python package into $PREFIX/app and (re)installs it into
# the venv, non-editable. Shared by install and sync: install creates the
# venv first time round, sync just re-runs pip, which is fast when only the
# source changed. Neither touches system packages, the tunnel, fonts or the
# service user — those are install's other steps, sync does not call them.
sync_app() {
  # docs/SPEC.md and samples/ are not cargo: pyproject force-includes them into
  # the package at build time, so pip needs them present in $PREFIX/app. Without
  # them the wheel builds fine and display://spec then fails at read time on the
  # host, which is a miserable way to find out. Hence the checks below.
  local f
  for f in "$REPO/pyproject.toml" "$REPO/README.md" "$REPO/docs/SPEC.md"; do
    [ -f "$f" ] || die "missing from the repo: $f"
  done
  local d
  for d in "$REPO/src" "$REPO/samples"; do
    [ -d "$d" ] || die "missing from the repo: $d"
  done

  local new_deps old_deps=""
  new_deps=$(deps_of "$REPO/pyproject.toml")
  [ -f "$PREFIX/app/pyproject.toml" ] && old_deps=$(deps_of "$PREFIX/app/pyproject.toml")
  if [ -n "$old_deps" ] && [ "$old_deps" != "$new_deps" ]; then
    warn "pyproject.toml's dependency list changed since the last install/sync."
    warn "pip will pick it up below; nothing special to do."
  fi

  log "copying the app into $PREFIX/app"
  if [ "$DRY" = 1 ]; then
    printf '    would copy pyproject.toml, README.md, src/, samples/, docs/SPEC.md into %s\n' "$PREFIX/app"
  else
    rm -rf "$PREFIX/app"
    install -d -o "$SVC_USER" -g "$SVC_USER" -m 0755 "$PREFIX/app" "$PREFIX/app/docs"
    cp "$REPO/pyproject.toml" "$REPO/README.md" "$PREFIX/app/"
    cp "$REPO/docs/SPEC.md" "$PREFIX/app/docs/"
    cp -R "$REPO/src" "$PREFIX/app/src"
    cp -R "$REPO/samples" "$PREFIX/app/samples"
    chown -R "$SVC_USER:$SVC_USER" "$PREFIX/app"
  fi

  if [ -x "$PREFIX/venv/bin/python" ]; then
    skip "venv exists"
  else
    log "creating the venv"
    run as_svc python3 -m venv "$PREFIX/venv"
  fi

  log "installing the package into the venv"
  if ! run as_svc "$PREFIX/venv/bin/pip" install --quiet --upgrade \
         --timeout 60 --retries 3 "$PREFIX/app"; then
    die "pip could not install $PREFIX/app.
       Usually a transient PyPI or DNS problem. Nothing else was changed —
       fix the network and re-run: $0 install"
  fi
}

install_unit() {
  log "installing the systemd unit"
  [ -f "$HERE/display-mcp.service" ] || die "missing from the repo: display-mcp.service"
  # The shipped unit is written for the default paths; retarget it if asked.
  sed -e "s#/opt/display-mcp#$PREFIX#g" \
      -e "s#/var/lib/display-mcp#$STATE#g" \
      -e "s#^User=display-mcp#User=$SVC_USER#" \
      -e "s#^Group=display-mcp#Group=$SVC_USER#" \
      -e "s#^StateDirectory=display-mcp\$#StateDirectory=$(basename "$STATE")#" \
      "$HERE/display-mcp.service" | write_file "$UNIT" 0644

  # Local settings go in a drop-in, not in the unit. Nothing to hand-edit, and
  # `uninstall` removes the whole directory rather than trying to un-edit a file.
  run install -d -m 0755 "$DROPIN_DIR"
  local body
  body=$(cat <<EOF
# Written by setup.sh. Re-run it to change these, or edit and
# \`systemctl daemon-reload && systemctl restart display-mcp\`.
[Service]
Environment=DISPLAY_MCP_PANEL_BIND=$BIND,127.0.0.1
Environment=DISPLAY_MCP_PANEL_PORT=$PORT
EOF
)
  if [ -n "$ACCESS_TEAM_DOMAIN" ] && [ -n "$ACCESS_AUD" ]; then
    body="$body
Environment=DISPLAY_MCP_CF_ACCESS_TEAM_DOMAIN=$ACCESS_TEAM_DOMAIN
Environment=DISPLAY_MCP_CF_ACCESS_AUD=$ACCESS_AUD"
  fi
  printf '%s\n' "$body" | write_file "$DROPIN" 0644
  ok "panel endpoint will bind $BIND:$PORT (and 127.0.0.1:$PORT for you)"
  if [ -n "$ACCESS_TEAM_DOMAIN" ] && [ -n "$ACCESS_AUD" ]; then
    ok "Cloudflare Access configured for the MCP endpoint"
  else
    warn "Cloudflare Access not configured — the MCP endpoint is authless."
    warn "Pass --access-team-domain URL --access-aud TAG once you have an"
    warn "Access application in front of it (see docs/RUNBOOK.md step 7)."
  fi
}

seed_state() {
  run install -d -o "$SVC_USER" -g "$SVC_USER" -m 0755 "$STATE"
  if [ "$DRY" != 1 ] && [ -f "$STATE/default.json" ]; then
    skip "$STATE/default.json exists, leaving it"
  elif [ -f "$SAMPLE" ]; then
    # samples/display.json ships pre-stamped with meta.hash, which is what
    # makes copying it straight into the state dir safe. It is the one
    # sanctioned way to write there by hand — every other document must go
    # through set_display, which is the only code path that stamps the hash.
    run install -o "$SVC_USER" -g "$SVC_USER" -m 0644 "$SAMPLE" "$STATE/default.json"
    ok "seeded the sample document so the panel has something to draw"
  fi
}

install_tunnel() {
  if [ "$WITH_TUNNEL" = 0 ]; then skip "Cloudflare Tunnel skipped (pass --with-tunnel)"; return 0; fi

  if ! command -v cloudflared >/dev/null 2>&1; then
    log "adding the Cloudflare apt repository and installing cloudflared"
    if [ "$DRY" != 1 ]; then
      curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
        -o /usr/share/keyrings/cloudflare-main.gpg
      echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
        >/etc/apt/sources.list.d/cloudflared.list
      apt-get update -qq
      DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends cloudflared
    else
      printf '    would add the Cloudflare repo and install cloudflared\n'
    fi
  else
    skip "cloudflared already installed"
  fi

  # Cloudflare's own installer: writes and enables cloudflared.service from
  # the token. The token is the tunnel's credential; it is never echoed here.
  if [ -f "$CF_UNIT" ] && [ -z "$TUNNEL_TOKEN" ]; then
    skip "cloudflared service already installed (pass --tunnel-token to replace it)"
  else
    if [ -z "$TUNNEL_TOKEN" ] && [ -t 0 ] && [ "$DRY" != 1 ]; then
      printf 'Tunnel token (Zero Trust -> Networks -> Tunnels; input hidden): '
      read -rs TUNNEL_TOKEN; echo
    fi
    if [ -z "$TUNNEL_TOKEN" ] && [ "$DRY" != 1 ]; then
      die "no tunnel token: pass --tunnel-token TOKEN or set DISPLAY_MCP_TUNNEL_TOKEN"
    fi
    if [ "$DRY" = 1 ]; then
      [ -f "$CF_UNIT" ] && printf '    would run: cloudflared service uninstall\n'
      printf '    would run: cloudflared service install <token>\n'
    else
      if [ -f "$CF_UNIT" ]; then
        cloudflared service uninstall >/dev/null 2>&1 || true
      fi
      cloudflared service install "$TUNNEL_TOKEN" >/dev/null
      sleep 2
      systemctl is-active --quiet cloudflared \
        || die "cloudflared did not start. journalctl -u cloudflared -n 40"
    fi
    ok "tunnel service installed"
  fi
  ok "https://$DOMAIN/mcp -> http://localhost:8001 (set that public hostname in the dashboard)"
}

# --- commands -------------------------------------------------------------

do_install() {
  need_root
  [ -n "$BIND" ] || BIND=$(detect_bind)

  ensure_pkgs
  ensure_user
  install_fonts
  sync_app
  install_unit
  seed_state
  install_tunnel

  log "starting the service"
  run systemctl daemon-reload
  # enable --now does nothing to a service that is already running, and the
  # drop-in may have just changed (bind, Access settings): restart, always.
  run systemctl enable display-mcp
  run systemctl restart display-mcp
  if [ "$DRY" != 1 ]; then
    sleep 1
    systemctl is-active --quiet display-mcp \
      || die "display-mcp did not start. journalctl -u display-mcp -n 40"
  fi

  do_check || true
  echo
  log "installed."
  do_status || true
  cat <<EOF

${B}Still yours to do — none of this can be done from this host:${Z}

  1. Point the panel at it. In firmware/epaper-schedule.yaml:
         dl_url: "http://$BIND:$PORT/display.json"
     then reflash.
  2. Make sure the panel can reach $BIND:$PORT. If the panel and this host
     share a network segment there is nothing to open. If they do not, add
     one rule sourced to the panel's address (give it a DHCP reservation
     first), destination this host on $PORT, and narrow it to that one pair.
  3. $(if [ "$WITH_TUNNEL" = 1 ]; then
         echo "Zero Trust dashboard: the tunnel's public hostname $DOMAIN must"
         echo "     route to http://localhost:8001, and an Access application must"
         echo "     sit on $DOMAIN (docs/RUNBOOK.md step 6)."
       else
         echo "Edge: re-run with --with-tunnel to reach the MCP endpoint from"
         echo "     outside this network (docs/RUNBOOK.md step 6). Until then it"
         echo "     listens on loopback only, which is fine for local testing."
       fi)
  4. Add https://$DOMAIN/mcp as a connector in Claude, with Access in front.
     setup.sh install --access-team-domain URL --access-aud TAG once you
     know them (docs/RUNBOOK.md step 7) — until then the endpoint is authless.

  Full runbook, with the gate for each step: docs/RUNBOOK.md
EOF
}

do_uninstall() {
  need_root
  log "stopping the service"
  run systemctl disable --now display-mcp 2>/dev/null || true
  run rm -f "$UNIT"
  run rm -rf "$DROPIN_DIR"
  run systemctl daemon-reload
  run systemctl reset-failed display-mcp 2>/dev/null || true
  ok "unit removed"

  log "removing the tunnel"
  if [ -f "$CF_UNIT" ] && command -v cloudflared >/dev/null 2>&1; then
    run cloudflared service uninstall
    ok "cloudflared service removed (the package is left alone)"
  else
    skip "no cloudflared service"
  fi

  if [ "$PURGE" = 1 ]; then
    log "purging"
    run rm -rf "$PREFIX" "$STATE"
    ok "$PREFIX and $STATE are gone"
    if id -u "$SVC_USER" >/dev/null 2>&1; then
      # deluser fails if anything is still running as the user, and quietly
      # claiming otherwise would be worse than saying so.
      if run deluser --system "$SVC_USER" >/dev/null 2>&1; then
        getent group "$SVC_USER" >/dev/null 2>&1 \
          && { run delgroup "$SVC_USER" >/dev/null 2>&1 || true; }
        ok "the $SVC_USER user is gone"
      else
        warn "could not remove the $SVC_USER user — usually a process is still"
        warn "running as it. Check: pgrep -u $SVC_USER ; then: deluser --system $SVC_USER"
      fi
    fi
  else
    run rm -rf "$PREFIX/venv" "$PREFIX/app" "$PREFIX/__pycache__"
    ok "kept $STATE (your published documents) and $PREFIX/fonts"
    skip "add --purge to remove those too"
  fi

  echo
  log "uninstalled. apt packages were left alone."
  cat <<EOF

  Left for you, since removing them could break something else:
    - any firewall rule you added so the panel could reach this host
    - the connector in Claude
    - the cloudflared and python3-venv packages
    - the tunnel and the Access application in the Zero Trust dashboard
EOF
}

# Code-only redeploy: copy the app into $PREFIX/app, reinstall it into the
# venv, and restart. Deliberately does NOT touch system packages, the service
# user, fonts or the tunnel — those are `install`, and they should be a
# decision rather than a side effect of a deploy.
do_sync() {
  need_root
  [ -x "$PREFIX/venv/bin/python" ] || die "not installed yet — run: $0 install"
  log "syncing the application"
  sync_app
  run systemctl restart display-mcp
  if [ "$DRY" != 1 ]; then
    sleep 1
    systemctl is-active --quiet display-mcp || die "display-mcp did not restart. journalctl -u display-mcp -n 40"
  fi
  ok "restarted"
  do_status || true
}

do_check() {
  local cli="$PREFIX/venv/bin/display-mcp-cli"
  [ -x "$cli" ] || { warn "no venv at $cli"; return 1; }
  # The copy under $PREFIX/app, not $SAMPLE in the repo: this runs as the
  # service user, which cannot read a repo that lives in a 0700 home dir.
  local sample="$PREFIX/app/samples/display.json"
  [ -f "$sample" ] || { skip "no sample document to check"; return 0; }
  log "checking the renderer"
  if as_svc "$cli" check "$sample" --font-dir "$PREFIX/fonts"; then
    ok "fonts load, document validates"
  else
    warn "the renderer could not process the sample — usually the fonts."
    warn "The panel endpoint still works; only preview() is affected."
    return 1
  fi
}

do_status() {
  local bind port url
  bind=$(sed -n 's/^Environment=DISPLAY_MCP_PANEL_BIND=//p' "$DROPIN" 2>/dev/null | tail -1 || true)
  port=$(sed -n 's/^Environment=DISPLAY_MCP_PANEL_PORT=//p' "$DROPIN" 2>/dev/null | tail -1 || true)
  bind=${bind:-$BIND}; port=${port:-$PORT}
  [ -n "$bind" ] || { warn "not installed"; return 1; }
  # The drop-in holds "<lan-ip>,127.0.0.1"; the first entry is the panel's.
  bind=${bind%%,*}
  url="http://$bind:$port/display.json"

  printf '  service   %s\n' "$(systemctl is-active display-mcp 2>/dev/null || echo inactive)"
  printf '  endpoint  %s\n' "$url"

  local health_code
  health_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
                "http://127.0.0.1:$port/healthz" 2>/dev/null || true)
  health_code=${health_code:-000}
  if [ "$health_code" = 200 ]; then
    printf '  healthz  %s 200 ok%s\n' "$G" "$Z"
  else
    printf '  healthz  %s %s — is the service up?%s\n' "$Y" "$health_code" "$Z"
  fi

  if [ -f "$CF_UNIT" ]; then
    printf '  tunnel    %s\n' "$(systemctl is-active cloudflared 2>/dev/null || echo inactive)"
  else
    printf '  tunnel    not installed (--with-tunnel)\n'
  fi

  local team aud
  team=$(sed -n 's/^Environment=DISPLAY_MCP_CF_ACCESS_TEAM_DOMAIN=//p' "$DROPIN" 2>/dev/null | tail -1 || true)
  aud=$(sed -n 's/^Environment=DISPLAY_MCP_CF_ACCESS_AUD=//p' "$DROPIN" 2>/dev/null | tail -1 || true)
  if [ -n "$team" ] && [ -n "$aud" ]; then
    printf '  mcp auth  %sCloudflare Access configured (%s)%s\n' "$G" "$team" "$Z"
  else
    printf '  mcp auth  %snot configured — the MCP endpoint is authless%s\n' "$Y" "$Z"
  fi

  local etag code
  etag=$(curl -sI --max-time 5 "$url" 2>/dev/null \
         | sed -n 's/.*[Ee][Tt]ag: *"\([^"]*\)".*/\1/p' | tr -d '\r' || true)
  if [ -z "$etag" ]; then
    printf '  document  %s\n' "none published yet (503 is expected until then)"
    return 0
  fi
  printf '  document  hash %s\n' "$etag"
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
         -H "If-None-Match: \"$etag\"" "$url" 2>/dev/null || true)
  code=${code:-000}
  if [ "$code" = 304 ]; then
    printf '  revalidate%s 304 — an unchanged wake costs the panel nothing%s\n' "$G" "$Z"
  else
    printf '  revalidate%s %s — expected 304; the panel will refresh every wake%s\n' "$Y" "$code" "$Z"
  fi
}

# --- args -----------------------------------------------------------------

usage() {
  sed -n '3,22p' "${BASH_SOURCE[0]}" | sed 's/^#//; s/^ //'
  cat <<'EOF'

Commands:
  install     idempotent; safe to re-run after changing a flag
  sync        code-only redeploy: copy the app into the venv and restart
  uninstall   removes everything install added
  status      is it up, what is published, does revalidation work, is Access on
  check       can the renderer load the fonts and the sample document

Flags:
  --bind IP                  panel endpoint address (default: detected LAN address)
  --port N                   panel endpoint port (default: 8080)
  --domain HOST              public MCP hostname the tunnel serves (or DISPLAY_MCP_DOMAIN)
  --with-tunnel              run a Cloudflare Tunnel to the MCP endpoint
  --tunnel-token TOKEN       the tunnel's token (or DISPLAY_MCP_TUNNEL_TOKEN; prompted on a tty)
  --fonts-from DIR           copy fonts from DIR instead of downloading
  --no-fonts                 skip fonts entirely (preview() will not work)
  --access-team-domain URL   Cloudflare Access team domain, e.g. https://x.cloudflareaccess.com
  --access-aud TAG           Cloudflare Access application's AUD tag
  --prefix DIR               install root (default: /opt/display-mcp)
  --state DIR                state directory, must be under /var/lib (default: /var/lib/display-mcp)
  --user NAME                service user (default: display-mcp)
  --purge                    uninstall only: also remove state, fonts and the user
  --dry-run                  print the plan, change nothing
EOF
}

CMD=${1:-}
[ $# -gt 0 ] && shift || true
while [ $# -gt 0 ]; do
  case $1 in
    --bind) BIND=${2:?}; shift 2 ;;
    --port) PORT=${2:?}; shift 2 ;;
    --domain) DOMAIN=${2:?}; shift 2 ;;
    --prefix) PREFIX=${2:?}; shift 2 ;;
    --state) STATE=${2:?}; shift 2 ;;
    --user) SVC_USER=${2:?}; shift 2 ;;
    --fonts-from) FONTS_FROM=${2:?}; shift 2 ;;
    --access-team-domain) ACCESS_TEAM_DOMAIN=${2:?}; shift 2 ;;
    --access-aud) ACCESS_AUD=${2:?}; shift 2 ;;
    --with-tunnel) WITH_TUNNEL=1; shift ;;
    --tunnel-token) TUNNEL_TOKEN=${2:?}; shift 2 ;;
    --no-fonts) WITH_FONTS=0; shift ;;
    --purge) PURGE=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

case "$STATE" in
  /var/lib/?*) : ;;
  *) die "--state must be a directory under /var/lib (systemd StateDirectory)" ;;
esac

case "${CMD:-}" in
  install)   do_install ;;
  sync)      do_sync ;;
  uninstall) do_uninstall ;;
  status)    do_status ;;
  check)     need_root; do_check ;;
  ""|-h|--help|help) usage ;;
  *) die "unknown command: $CMD (try --help)" ;;
esac
