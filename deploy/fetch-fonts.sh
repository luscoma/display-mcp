#!/usr/bin/env bash
#
# fetch-fonts.sh <dir> — put the Instrument Sans Regular/Bold pair and the
# JetBrains Mono Regular face in <dir>.
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
# <dir> by hand instead of running this script if you'd rather. JetBrains
# Mono is fetched the same way, as a variable font too — the renderer
# selects its Regular instance the same way it selects Instrument Sans's
# Bold one.
#
# Exits 0 with all three files in place and looking like a font. Exits 1, with
# a warning explaining the manual fallback, if nothing downloadable panned out.
# Leaves ownership alone — the caller chowns if it needs to.

set -euo pipefail

if [ -t 1 ]; then B=$'\e[1m'; Y=$'\e[33m'; G=$'\e[32m'; Z=$'\e[0m'
else B=""; Y=""; G=""; Z=""; fi

log()  { printf '%s==>%s %s\n' "$B" "$Z" "$*"; }
ok()   { printf '    %s+%s %s\n' "$G" "$Z" "$*"; }
warn() { printf '    %s!%s %s\n' "$Y" "$Z" "$*" >&2; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

DIR=${1:?"usage: $0 <dir>"}

# $TMP is the download in flight, cleaned up on exit. Deliberately not a
# `local` with a RETURN trap: a RETURN trap set inside a function is global
# and fires on *every* later function return, so it ran again when main()
# returned with $tmp already out of scope, and `set -u` turned that into
# "tmp: unbound variable" -- exit 1 after both faces had installed fine,
# which made setup.sh discard the scratch dir it had just filled.
#
# on_exit re-raises the status it was entered with: an EXIT trap that falls
# off the end hands the script the trap's own status instead. It is armed
# below the usage check on purpose -- a ${1:?} abort is already past $? by
# the time a trap could see it, and would exit 0.
TMP=""
cleanup() { if [ -n "$TMP" ]; then rm -f "$TMP"; TMP=""; fi; }
on_exit() { local rc=$?; cleanup; exit "$rc"; }
trap on_exit EXIT

FONT_REGULAR="InstrumentSans-Regular.ttf"
FONT_BOLD="InstrumentSans-Bold.ttf"
FONT_MONO="JetBrainsMono-Regular.ttf"

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

# One family, installed to one or more destination paths (Instrument Sans
# writes the same downloaded file to both its Regular and Bold names — the
# renderer and the firmware both select the Bold instance out of the one
# variable font; JetBrains Mono has a single destination). Ask GitHub what
# is actually in that ofl/<slug> directory rather than guessing a filename
# — upstream renames variable fonts from time to time. The listing also
# contains the Italic variable font, which must not win: the firmware
# compiles the upright face. $fallback_url is the fixed URL used when the
# API is rate limited.
fetch_family() {
  local label=$1 slug=$2 fallback_url=$3; shift 3
  local dests=("$@")
  log "fetching $label"
  local urls=() u
  cleanup; TMP=$(mktemp)

  while read -r u; do [ -n "$u" ] && urls+=("$u"); done < <(
    curl -fsSL --max-time 20 \
      "https://api.github.com/repos/google/fonts/contents/ofl/$slug" 2>/dev/null \
      | sed -n 's/.*"download_url": *"\([^"]*\.ttf\)".*/\1/p' \
      | grep -vi 'italic' || true
  )
  urls+=("$fallback_url")

  for u in "${urls[@]}"; do
    if curl -fsSL --retry 2 --max-time 60 -o "$TMP" "$u" && is_font "$TMP"; then
      # mktemp made $TMP 0600; the service user has to be able to read these.
      local d
      for d in "${dests[@]}"; do install -m 0644 "$TMP" "$d"; done
      ok "$label installed from ${u##*/}"
      return 0
    fi
  done

  warn "could not download a usable $label."
  return 1
}

main() {
  mkdir -p "$DIR"
  local reg="$DIR/$FONT_REGULAR" bold="$DIR/$FONT_BOLD" mono="$DIR/$FONT_MONO"

  if is_font "$reg" && is_font "$bold" && is_font "$mono"; then
    ok "fonts already present in $DIR"
    return 0
  fi

  local failed=0
  if is_font "$reg" && is_font "$bold"; then
    ok "Instrument Sans already present in $DIR"
  else
    fetch_family "Instrument Sans" instrumentsans \
      'https://raw.githubusercontent.com/google/fonts/main/ofl/instrumentsans/InstrumentSans%5Bwdth,wght%5D.ttf' \
      "$reg" "$bold" || failed=1
  fi
  if is_font "$mono"; then
    ok "JetBrains Mono already present in $DIR"
  else
    fetch_family "JetBrains Mono" jetbrainsmono \
      'https://raw.githubusercontent.com/google/fonts/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf' \
      "$mono" || failed=1
  fi

  if [ "$failed" = 1 ]; then
    warn "Put a Regular+Bold pair in $DIR as $FONT_REGULAR and $FONT_BOLD,"
    warn "and/or a Regular face as $FONT_MONO, by hand, or re-run once the"
    warn "network/API rate limit clears."
    return 1
  fi
  return 0
}

main "$@"
