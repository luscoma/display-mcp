"""`normalize_size_alias()`/`normalize_font_key()` (docs/plans/
fonts-and-icons.md Decision 4, B4b), differentially against the shipped
header: every font and icon spelling the renderer accepts, fed through the
C++ normaliser exactly as `display_list.h`'s `text`/`fmt`/`icon` branches do
before consulting `assets.fonts`/`assets.icons`, must land on a key that
map actually holds -- the same canonical name (or, for a bare legacy font
alias, the same literal spelling) `resolve_font()`/`resolve_icon_size()`
already computed on the Python side. A spelling the renderer *rejects*
either comes back unchanged (an off-ladder size, a bare name the table
doesn't know) or lands on a string that is provably absent from the
firmware's own key set -- either way the map lookup still misses and the op
still skips, exactly as it did before this batch added the normaliser.

Needs a host C++ compiler; skips cleanly without one (see conftest.py).
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from display_mcp.render import FONT_ALIASES, FONTS, ICON_SIZES, ICONS, SLOTS, resolve_font

from .conftest import _compile, _extract_block


def _bare_font_aliases() -> dict[str, str]:
    """The five legacy bare names -- the only `FONT_ALIASES` entries the
    YAML still carries as their own `a.fonts[...]` line (B4b); the other
    fifty (a face's own pixel-count spelling) are resolved by
    `normalize_font_key()` instead. Mirrors `firmware_yaml._bare_font_aliases()`
    exactly (that one isn't imported here to keep this file's only
    dependency on the generator the fence text itself, not its internals)."""
    return {alias: target for alias, target in FONT_ALIASES.items() if "/" not in alias}


# The firmware's own font key set after B4b: 110 canonical names plus the
# five bare aliases -- exactly what `render_fonts_lines()` emits and what
# `assets.fonts` is populated with on the real panel.
_FIRMWARE_FONT_KEYS: set[str] = set(FONTS) | set(_bare_font_aliases())

# The firmware's own icon key set: canonical `name/slot` only -- no bare or
# pixel-count alias (Decision 4).
_FIRMWARE_ICON_KEYS: set[str] = {
    f"{name}/{slot}" for name, slots in ICONS.items() for slot in slots
}


@pytest.fixture(scope="module")
def normalise_harness(tmp_path_factory):
    """Compile `normalize_size_alias()`/`normalize_font_key()` -- extracted
    verbatim, never retyped -- behind a tiny line protocol: `F <spelling>`
    normalises a full font key, `Z <spelling>` normalises a bare size
    token (what the icon branch feeds it, and what `normalize_font_key()`
    feeds it internally). One line per case, read with `getline` rather
    than `scanf("%s", ...)` so the empty-string case (a genuinely present
    but empty spelling) round-trips instead of being unreadable as a
    whitespace-delimited token."""
    if shutil.which("c++") is None:
        pytest.skip("no host C++ compiler")
    parts = "#include <cstring>\n#include <string>\n" + _extract_block(
        r"^inline const char \*normalize_size_alias\(", "normalize_size_alias()"
    ) + "\n" + _extract_block(
        r"^inline std::string normalize_font_key\(", "normalize_font_key()"
    )
    main_src = r"""
#include <cstdio>
#include <iostream>
#include <string>
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    const char kind = line.empty() ? '?' : line[0];
    const std::string rest = line.size() > 2 ? line.substr(2) : "";
    if (kind == 'F') {
      std::printf("%s\n", normalize_font_key(rest.c_str()).c_str());
    } else {
      std::printf("%s\n", normalize_size_alias(rest.c_str()));
    }
  }
  return 0;
}
"""
    return _compile(
        tmp_path_factory.mktemp("size_normalise_parity"), "normalise_harness", parts, main_src
    )


def _run(harness, lines: list[str]) -> list[str]:
    out = subprocess.run(
        [str(harness)], input=("\n".join(lines) + "\n").encode(), capture_output=True, check=True
    ).stdout.decode()
    return out.splitlines()


# One line per case (`_run`'s `"\n".join(lines)`), read with `getline` on
# the harness side -- a spelling containing a literal newline never appears
# in this vocabulary, so that's the one character this protocol can't
# round-trip; everything else, including a leading/trailing space or a
# non-ASCII byte, comes back exactly as sent.


def test_normalize_size_alias_matches_the_slot_table(normalise_harness):
    """The five real mappings, plus what must NOT trigger one: the slot
    names themselves (already canonical, not a pixel count), an off-ladder
    pixel count that is a real compiled size for one family
    (`petrona-italic/40`'s `40`), a decimal spelling of a real size
    (`"36.0"`), a negative or zero-padded one, and the empty string."""
    cases = [(str(px), slot) for slot, px in SLOTS.items()] + [
        (slot, slot) for slot in SLOTS  # a slot name is left alone, not "normalised" again
    ] + [
        (bad, bad)
        for bad in ("40", "18", "12", "36.0", "-36", "036", "", "XL", "Md", "check")
    ]
    lines = [f"Z {z}" for z, _want in cases]
    got = _run(normalise_harness, lines)
    assert got == [want for _z, want in cases]


def test_normalize_font_key_edge_cases(normalise_harness):
    """Boundary and malformed spellings a fuzzer would try before a real
    document would (docs/plans/fonts-and-icons.md B4b review, nit 12):
    no slash at all, a slash with nothing on one side or the other, more
    than one slash (only the last one is the size half), every near-miss
    spelling of a real pixel count, a non-ASCII byte where a digit would
    be, and a handful of real canonical/alias spellings already covered
    individually elsewhere in this file but not as part of one batch
    exercising `normalize_font_key()` (rather than `normalize_size_alias()`
    alone) end to end."""
    cases = [
        ("", ""),
        ("/", "/"),
        ("petrona/", "petrona/"),
        ("a/b/36", "a/b/md"),  # only the LAST slash's tail is the size half
        ("petrona/048", "petrona/048"),  # zero-padded -- not the exact string "48"
        ("petrona/48.0", "petrona/48.0"),  # decimal spelling of a real size
        ("petrona/48 ", "petrona/48 "),  # trailing space
        ("petrona/4800", "petrona/4800"),  # a real prefix, wrong count
        ("x/é", "x/é"),  # non-ASCII byte where a digit would be
        ("md", "md"),  # bare legacy alias -- no slash, nothing to normalise
        ("instrument/26", "instrument/26"),  # canonical: 26 isn't a slot's px
        ("mono/24", "mono/24"),  # canonical
        ("petrona-italic/40", "petrona-italic/40"),  # canonical, off-ladder px
        # A key at exactly kNameMaxLen (64) bytes -- the caller's own bound
        # in display_list.h, not this function's, but the harness's fixed
        # `std::string` + `getline` and `std::string` construction must still handle
        # it without truncation.
        ("petrona/" + "3" * 56, "petrona/" + "3" * 56),
    ]
    assert len(cases[-1][0]) == 64
    lines = [f"F {name}" for name, _want in cases]
    got = _run(normalise_harness, lines)
    assert got == [want for _name, want in cases]


def test_every_accepted_font_spelling_normalises_onto_a_firmware_key(normalise_harness):
    """Every spelling `resolve_font()` accepts -- 110 canonical names plus
    all 55 `FONT_ALIASES` entries -- normalised through `normalize_font_key()`
    lands on a key `_FIRMWARE_FONT_KEYS` actually holds, and that key
    resolves (via `resolve_font()`, since a firmware key is always either
    already canonical or one of the five bare aliases) to the exact same
    face `resolve_font()` computed for the original spelling."""
    spellings = sorted(set(FONTS) | set(FONT_ALIASES))
    lines = [f"F {spelling}" for spelling in spellings]
    got = _run(normalise_harness, lines)
    assert len(got) == len(spellings)
    for spelling, normalised in zip(spellings, got, strict=True):
        assert normalised in _FIRMWARE_FONT_KEYS, (
            f"{spelling!r} normalised to {normalised!r}, not a firmware key"
        )
        assert resolve_font(normalised) == resolve_font(spelling), (
            f"{spelling!r} -> {normalised!r} resolves to a different face"
        )


# A representative sample of spellings the renderer rejects: a bad family
# with a real-looking size, a real family with an off-ladder size, a bad
# family with a bad size, a bare name that almost matches a legacy alias,
# and the empty string.
_REJECTED_FONT_SPELLINGS = (
    "bogus/36",
    "karla/41",
    "bogus/41",
    "xl2",
    "",
    "petrona-italic/40x",
)


def test_rejected_font_spellings_still_miss_the_firmware_map(normalise_harness):
    """Every spelling above is genuinely unknown (`resolve_font()` is
    `None` for it), so it must not land on a real firmware key by
    accident -- the normaliser is only supposed to collapse a *known*
    family's pixel-count size onto its slot, never manufacture a hit for
    an unknown one."""
    for spelling in _REJECTED_FONT_SPELLINGS:
        assert resolve_font(spelling) is None, f"{spelling!r} is not actually rejected"
    lines = [f"F {spelling}" for spelling in _REJECTED_FONT_SPELLINGS]
    got = _run(normalise_harness, lines)
    for spelling, normalised in zip(_REJECTED_FONT_SPELLINGS, got, strict=True):
        assert normalised not in _FIRMWARE_FONT_KEYS, (
            f"{spelling!r} normalised to {normalised!r}, which IS a firmware key"
        )


def test_every_icon_slot_and_px_spelling_normalises_onto_a_firmware_key(normalise_harness):
    """Every `name/slot` pair `ICONS` actually has, addressed by both its
    slot spelling and its pixel-count spelling (Decision 4: `z` takes
    either, exactly as `f` does) -- both must land on the one canonical
    `name/slot` key the firmware's `a.icons` map holds."""
    pairs = sorted((name, slot) for name, slots in ICONS.items() for slot in slots)
    lines = []
    for _name, slot in pairs:
        lines.append(f"Z {slot}")
        lines.append(f"Z {ICON_SIZES[slot]}")
    got = _run(normalise_harness, lines)
    assert len(got) == 2 * len(pairs)
    for i, (name, slot) in enumerate(pairs):
        from_slot, from_px = got[2 * i], got[2 * i + 1]
        assert from_slot == slot
        assert from_px == slot
        key = f"{name}/{slot}"
        assert key in _FIRMWARE_ICON_KEYS


_REJECTED_ICON_SIZES = ("40", "18", "", "XL", "sm.", "48.0")


def test_rejected_icon_sizes_are_left_unchanged(normalise_harness):
    """Every size string above isn't one of the five compiled pixel counts,
    so `normalize_size_alias()` must leave it exactly as given -- composing
    `name + "/" + result` for any real icon `name` then can never collide
    with a real `_FIRMWARE_ICON_KEYS` entry, since every one of those ends
    in a slot name, not one of these."""
    lines = [f"Z {z}" for z in _REJECTED_ICON_SIZES]
    got = _run(normalise_harness, lines)
    assert got == list(_REJECTED_ICON_SIZES)
    for name in ICONS:
        for z in _REJECTED_ICON_SIZES:
            assert f"{name}/{z}" not in _FIRMWARE_ICON_KEYS
