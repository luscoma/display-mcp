#!/usr/bin/env bash
#
# Redeploy: have the host pull from GitHub and run setup.sh there. Two moving
# parts on purpose: no push hooks, no sudoers carve-out, and the thing that
# runs as root is setup.sh, which you have already read.
#
#   ./deploy.sh              code change: pull, sync into the venv, restart
#   ./deploy.sh --install    unit, drop-in, dependency, tunnel or Access change
#   ./deploy.sh status       what is running, what is published, is the tunnel up
#
# Anything after the command is handed to setup.sh on the host, which is how
# the edge gets configured. The three that matter:
#
#   ./deploy.sh --install --with-tunnel
#       install cloudflared and bring the tunnel up. Pass --with-tunnel with
#       no token and setup.sh prompts for it with echo off; that keeps the
#       token out of your shell history and out of the host's process list,
#       which is where --tunnel-token TOKEN would put it.
#
#   ./deploy.sh --install --access-team-domain https://<team>.cloudflareaccess.com \
#                         --access-aud <aud tag>
#       verify the Cloudflare Access JWT on every MCP request. Without both,
#       the MCP endpoint verifies nothing and `status` says so under
#       `mcp auth` — fine while it is loopback-only, not once the tunnel is
#       up and the endpoint is reachable from the internet.
#
#   ./deploy.sh --install --domain mcp.example.com
#       the tunnel's public hostname, so setup.sh can print it back to you.
#       Routing lives in the Cloudflare dashboard; this only records it.
#
# `setup.sh --help` on the host has the rest. This script never pushes: the
# host's checkout has an `origin` pointing at GitHub and pulls from there, so
# commit and push before running it.
#
# Set DISPLAY_MCP_HOST to the machine running the service (user@host form
# works); DISPLAY_MCP_DIR overrides the checkout path, which is otherwise
# taken relative to the login home directory.

set -euo pipefail

HOST=${DISPLAY_MCP_HOST:-}
DIR=${DISPLAY_MCP_DIR:-display-mcp}

case ${1:-} in
  ""|sync|--sync)    CMD=sync ;;
  install|--install) CMD=install ;;
  status|--status)   CMD=status ;;
  -h|--help) sed -n '3,38p' "$0" | sed 's/^#//; s/^ //'; exit 0 ;;
  *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
esac
[ $# -gt 0 ] && shift || true

# Whatever is left is setup.sh's business, not ours: forwarding it verbatim
# means this script needs no update when setup.sh grows a flag. %q quotes each
# argument for the remote shell.
EXTRA=""
if [ $# -gt 0 ]; then EXTRA=$(printf ' %q' "$@"); fi

[ -n "$HOST" ] || {
  echo "set DISPLAY_MCP_HOST to the host running the service, e.g." >&2
  echo "  DISPLAY_MCP_HOST=user@host ./deploy.sh" >&2
  exit 2
}

# The host pulls from GitHub, so an unpushed commit is one the deploy cannot
# see. Checking the local ref is enough to catch the common mistake and costs
# no network; a stale origin/main only ever makes this warn late, never early.
if git rev-parse --verify --quiet origin/main >/dev/null; then
  ahead=$(git rev-list --count origin/main..HEAD)
  if [ "$ahead" -gt 0 ]; then
    echo "$ahead commit(s) are not on origin/main — push first, the host pulls from there" >&2
    git --no-pager log --oneline origin/main..HEAD >&2
    exit 1
  fi
else
  echo "no origin/main to compare against; deploying whatever the host can pull" >&2
fi

# status needs no privileges; install and sync write to /opt and restart units.
SUDO=sudo
if [ "$CMD" = status ]; then SUDO=""; fi

# -t so setup.sh can prompt: for sudo, and for the tunnel token.
ssh -t "$HOST" "set -e
  cd '$DIR'
  git pull --ff-only
  $SUDO ./deploy/setup.sh $CMD$EXTRA"
