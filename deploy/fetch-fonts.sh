#!/usr/bin/env bash
#
# fetch-fonts.sh <dir> — put the preview's seven font files (one per family
# per slant; mono has no italic) in <dir>.
#
# One implementation, two callers: setup.sh on the host, and local development
# on whatever you're reading this on:
#
#   deploy/fetch-fonts.sh ./fonts
#
# Google Fonts ships every weight of a family in one upright variable font
# and, for an italic style, a second variable font — never separate files
# per weight. That is why each of Petrona, Instrument Sans and Karla is two
# files here (an upright one and an `-Italic` one) rather than one: the
# renderer picks the weight it wants out of whichever of the two it loaded.
# JetBrains Mono has no italic in this vocabulary, so it is a single file.
#
# Exits 0 with all seven fetched files in place and looking like fonts.
# Exits 1, with a warning explaining the manual fallback, if something
# downloadable did not pan out. Leaves ownership alone — the caller chowns
# if it needs to.

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
# "tmp: unbound variable" -- exit 1 after every face had installed fine,
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

# The seven fetched destinations.
FONT_PETRONA="Petrona.ttf"
FONT_PETRONA_ITALIC="Petrona-Italic.ttf"
FONT_INSTRUMENT="InstrumentSans.ttf"
FONT_INSTRUMENT_ITALIC="InstrumentSans-Italic.ttf"
FONT_KARLA="Karla.ttf"
FONT_KARLA_ITALIC="Karla-Italic.ttf"
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

# GitHub's listing of one ofl/<slug> directory, fetched at most once per
# slug even though up to two destinations (an upright and an italic) pull
# from it -- four slugs, not seven API calls, against GitHub's unauthenticated
# 60/hour limit. Called lazily, only when at least one of that slug's
# destinations still needs fetching, from family_listing below. Prints
# nothing (and does not fail the script) on a rate limit or a network
# hiccup; the caller falls back to $fallback_url either way.
list_ofl() {
  local slug=$1
  curl -fsSL --max-time 20 \
    "https://api.github.com/repos/google/fonts/contents/ofl/$slug" 2>/dev/null || true
}

# The shared listing for a slug's destination(s): skips the API call
# entirely when every one of them is already a real font, same as
# fetch_if_missing used to do per-file before the listing was shared.
family_listing() {
  local slug=$1; shift
  local dest
  for dest in "$@"; do
    is_font "$dest" || { list_ofl "$slug"; return 0; }
  done
  printf ''
}

# The pure filter, factored out of fetch_one so it can be driven offline
# (see tests/test_deploy.py) with a captured listing on stdin instead of a
# live API call. Reads a GitHub directory listing (one JSON object per
# `ofl/<slug>` entry, `list_ofl`'s output) and prints the candidate download
# URLs, in listing order: 0 keeps the non-italic ones, 1 keeps only the
# italic ones. Either way the filename must contain the escaped `[` a
# variable font's axis-tag suffix always has (`Petrona%5Bwght%5D.ttf`) -- a
# static `Petrona-Regular.ttf` sitting in the same directory must not be
# able to win the upright slot over `Petrona[wght].ttf`.
select_urls() {
  local italic=$1
  local grep_opts=(-vi)
  [ "$italic" = 1 ] && grep_opts=(-i)
  sed -n 's/.*"download_url": *"\([^"]*\.ttf\)".*/\1/p' \
    | grep "${grep_opts[@]}" 'italic' \
    | grep '%5B' || true
}

# One family/slant, fetched into one destination file from an
# already-fetched directory $listing (see list_ofl/family_listing).
# $fallback_url is the fixed URL used when the API is rate limited or
# select_urls finds nothing (an empty $listing, or a directory that has
# been reorganised).
fetch_one() {
  local label=$1 listing=$2 italic=$3 fallback_url=$4 dest=$5
  log "fetching $label"
  local urls=() u
  cleanup; TMP=$(mktemp)

  while read -r u; do [ -n "$u" ] && urls+=("$u"); done < <(
    printf '%s' "$listing" | select_urls "$italic"
  )
  urls+=("$fallback_url")

  for u in "${urls[@]}"; do
    if curl -fsSL --retry 2 --max-time 60 -o "$TMP" "$u" && is_font "$TMP"; then
      # mktemp made $TMP 0600; the service user has to be able to read these.
      # Guarded, not a bare statement: under `set -e` an install failure here
      # (e.g. an unwritable $DIR) would otherwise abort the whole script
      # before the manual-fallback warning below ever ran.
      if install -m 0644 "$TMP" "$dest"; then
        ok "$label installed from ${u##*/}"
        return 0
      fi
      warn "downloaded $label but could not install it to $dest."
      return 1
    fi
  done

  warn "could not download a usable $label."
  return 1
}

# Skips the fetch (and the network round trip) when the destination already
# looks like a font, same as fetch_one's caller used to do inline. This is
# also the whole "is everything already here" check now (C9, final review):
# a separate all_present() pre-check calling is_font() a second time on
# every destination just to print one combined "fonts already present"
# line was folded into this -- family_listing() below already skips its
# own API call per slug when every one of that slug's destinations passes
# is_font(), so a fully-populated $DIR still does zero network work, it
# just says so per file (seven "already present" lines) rather than once.
fetch_if_missing() {
  local label=$1 listing=$2 italic=$3 fallback_url=$4 dest=$5
  if is_font "$dest"; then
    ok "$label already present in $DIR"
    return 0
  fi
  fetch_one "$label" "$listing" "$italic" "$fallback_url" "$dest"
}

main() {
  mkdir -p "$DIR"
  local petrona="$DIR/$FONT_PETRONA" petrona_i="$DIR/$FONT_PETRONA_ITALIC"
  local instrument="$DIR/$FONT_INSTRUMENT" instrument_i="$DIR/$FONT_INSTRUMENT_ITALIC"
  local karla="$DIR/$FONT_KARLA" karla_i="$DIR/$FONT_KARLA_ITALIC"
  local mono="$DIR/$FONT_MONO"

  local failed=0
  local listing

  listing=$(family_listing petrona "$petrona" "$petrona_i")
  fetch_if_missing "Petrona" "$listing" 0 \
    'https://raw.githubusercontent.com/google/fonts/main/ofl/petrona/Petrona%5Bwght%5D.ttf' \
    "$petrona" || failed=1
  fetch_if_missing "Petrona Italic" "$listing" 1 \
    'https://raw.githubusercontent.com/google/fonts/main/ofl/petrona/Petrona-Italic%5Bwght%5D.ttf' \
    "$petrona_i" || failed=1

  listing=$(family_listing instrumentsans "$instrument" "$instrument_i")
  fetch_if_missing "Instrument Sans" "$listing" 0 \
    'https://raw.githubusercontent.com/google/fonts/main/ofl/instrumentsans/InstrumentSans%5Bwdth,wght%5D.ttf' \
    "$instrument" || failed=1
  fetch_if_missing "Instrument Sans Italic" "$listing" 1 \
    'https://raw.githubusercontent.com/google/fonts/main/ofl/instrumentsans/InstrumentSans-Italic%5Bwdth,wght%5D.ttf' \
    "$instrument_i" || failed=1

  listing=$(family_listing karla "$karla" "$karla_i")
  fetch_if_missing "Karla" "$listing" 0 \
    'https://raw.githubusercontent.com/google/fonts/main/ofl/karla/Karla%5Bwght%5D.ttf' \
    "$karla" || failed=1
  fetch_if_missing "Karla Italic" "$listing" 1 \
    'https://raw.githubusercontent.com/google/fonts/main/ofl/karla/Karla-Italic%5Bwght%5D.ttf' \
    "$karla_i" || failed=1

  listing=$(family_listing jetbrainsmono "$mono")
  fetch_if_missing "JetBrains Mono" "$listing" 0 \
    'https://raw.githubusercontent.com/google/fonts/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf' \
    "$mono" || failed=1

  if [ "$failed" = 1 ]; then
    warn "Put the missing file(s) in $DIR by hand -- Petrona.ttf,"
    warn "Petrona-Italic.ttf, InstrumentSans.ttf, InstrumentSans-Italic.ttf,"
    warn "Karla.ttf, Karla-Italic.ttf and/or JetBrainsMono-Regular.ttf --"
    warn "and/or re-run once the network/API rate limit clears."
    return 1
  fi
  return 0
}

# Guarded so tests/test_deploy.py can `source` this file (to drive
# select_urls offline, with a captured listing) without also running main()
# against whatever $1 the sourcing shell happens to have.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  main "$@"
fi
