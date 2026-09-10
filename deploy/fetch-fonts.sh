#!/usr/bin/env bash
#
# fetch-fonts.sh <dir> — put the Instrument Sans Regular/Bold pair in <dir>.
#
# One implementation, two callers: setup.sh on the host, and local development
# on whatever you're reading this on:
#
#   deploy/fetch-fonts.sh ./fonts
#
# Google Fonts ships Instrument Sans as a single variable font, which is why
# Regular and Bold end up byte-identical here — the renderer selects the Bold
# instance itself at render time. Any static Regular + Bold pair works too,
# so long as it's the same family the firmware compiles in; drop them in
# <dir> by hand instead of running this script if you'd rather.
#
# Exits 0 with both files in place and looking like a font. Exits 1, with a
# warning explaining the manual fallback, if nothing downloadable panned out.
# Leaves ownership alone — the caller chowns if it needs to.

set -euo pipefail

if [ -t 1 ]; then B=$'\e[1m'; Y=$'\e[33m'; G=$'\e[32m'; Z=$'\e[0m'
else B=""; Y=""; G=""; Z=""; fi

log()  { printf '%s==>%s %s\n' "$B" "$Z" "$*"; }
ok()   { printf '    %s+%s %s\n' "$G" "$Z" "$*"; }
warn() { printf '    %s!%s %s\n' "$Y" "$Z" "$*" >&2; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

DIR=${1:?"usage: $0 <dir>"}

FONT_REGULAR="InstrumentSans-Regular.ttf"
FONT_BOLD="InstrumentSans-Bold.ttf"

# A real font, not the few hundred bytes of JSON GitHub hands back for a 404
# or a rate limit. Checks size and the first four magic bytes rather than
# trusting the HTTP status, which curl -f already filters but the API
# listing's URLs have not been fetched yet when we build the list.
is_font() {
  local f=$1 size magic
  [ -s "$f" ] || return 1
  size=$(wc -c <"$f" | tr -d ' ')
  [ "$size" -gt 20000 ] || return 1
  magic=$(od -An -tx1 -N4 "$f" | tr -d ' \n')
  case "$magic" in
    00010000|4f54544f|74746366|74727565) return 0 ;;
    *) return 1 ;;
  esac
}

main() {
  mkdir -p "$DIR"
  local reg="$DIR/$FONT_REGULAR" bold="$DIR/$FONT_BOLD"

  if is_font "$reg" && is_font "$bold"; then
    ok "fonts already present in $DIR"
    return 0
  fi

  log "fetching Instrument Sans"
  local tmp urls=() u
  tmp=$(mktemp)
  trap 'rm -f "$tmp"' RETURN

  # Ask GitHub what is actually in that directory rather than guessing a
  # filename — upstream renames variable fonts from time to time. The
  # listing also contains the Italic variable font, which must not win: the
  # firmware compiles the upright face. The hardcoded URL is the fallback
  # for when the API is rate limited.
  while read -r u; do [ -n "$u" ] && urls+=("$u"); done < <(
    curl -fsSL --max-time 20 \
      https://api.github.com/repos/google/fonts/contents/ofl/instrumentsans 2>/dev/null \
      | sed -n 's/.*"download_url": *"\([^"]*\.ttf\)".*/\1/p' \
      | grep -vi 'italic' || true
  )
  urls+=('https://raw.githubusercontent.com/google/fonts/main/ofl/instrumentsans/InstrumentSans%5Bwdth,wght%5D.ttf')

  for u in "${urls[@]}"; do
    if curl -fsSL --retry 2 --max-time 60 -o "$tmp" "$u" && is_font "$tmp"; then
      # mktemp made $tmp 0600; the service user has to be able to read these.
      install -m 0644 "$tmp" "$reg"
      install -m 0644 "$tmp" "$bold"
      ok "fonts installed from ${u##*/}"
      return 0
    fi
  done

  warn "could not download a usable font."
  warn "Put any Regular+Bold pair in $DIR as $FONT_REGULAR and $FONT_BOLD,"
  warn "or re-run once the network/API rate limit clears."
  return 1
}

main "$@"
