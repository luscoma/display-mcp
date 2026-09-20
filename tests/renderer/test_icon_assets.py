"""The committed lucide icon rasters (docs/plans/fonts-and-icons.md,
Decision 4, batches B4a/B4b).

`render/icons/` has no `__init__.py` (B4a's note) and holds one PNG per
activity/slot -- `firmware/icons/rasterize.py`'s output (run under ESPHome's
own Python, which this project's venv does not have). This module holds
that output to the shape it promises: for every activity at every font-slot
size, an RGBA PNG that is exactly `px` by `px`, whose RGB is always zero,
and whose alpha is exactly 0 or 255 (the shape ESPHome's
`is_alpha_only()`/`type: BINARY` path expects), with some ink actually on
the canvas -- plus (B4b) that this file set and `ICONS`/`ICON_SIZES`, the
renderer's own tables, agree on what a lucide activity icon is and what
sizes it comes in.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from display_mcp.render import ICON_SIZES, ICONS
from display_mcp.render.firmware_yaml import _MDI_SLUGS

ROOT = Path(__file__).resolve().parents[2]
ICONS_DIR = ROOT / "src" / "display_mcp" / "render" / "icons"

# The eight activities named in the plan, independent of `ICONS`/`ICON_SIZES`
# so a change to either table's *shape* can't quietly make this module stop
# checking what it says it checks -- `test_activities_are_exactly_the_lucide_icons`
# below is what proves the two actually agree.
ACTIVITIES = (
    "school-day",
    "daycare",
    "taekwondo",
    "swim",
    "helper",
    "appointment",
    "family-meeting",
    "closed",
)

# The five font slots' pixel sizes (Decision 4: icons share the font ladder),
# also independent of `ICON_SIZES` for the same reason -- see
# `test_sizes_are_exactly_the_icon_slot_pixel_counts` below.
SIZES = (22, 28, 36, 48, 84)


def _expected_names() -> set[str]:
    return {f"{activity}-{px}.png" for activity in ACTIVITIES for px in SIZES}


def test_every_activity_and_size_has_a_png():
    missing = [name for name in sorted(_expected_names()) if not (ICONS_DIR / name).is_file()]
    assert missing == []


def test_no_other_files_in_icons_dir():
    # Dotfiles (.DS_Store) are ignored: macOS drops them and .gitignore hides
    # them, so they are not a stray asset.
    actual = {p.name for p in ICONS_DIR.iterdir() if p.is_file() and not p.name.startswith(".")}
    assert actual == _expected_names()


def _load(activity: str, px: int) -> Image.Image:
    return Image.open(ICONS_DIR / f"{activity}-{px}.png")


def test_pngs_are_rgba_and_exactly_their_slot_size():
    for activity in ACTIVITIES:
        for px in SIZES:
            img = _load(activity, px)
            assert img.mode == "RGBA", f"{activity}-{px}.png is {img.mode}, not RGBA"
            assert img.size == (px, px), f"{activity}-{px}.png is {img.size}, not ({px}, {px})"


def test_rgb_is_always_zero():
    for activity in ACTIVITIES:
        for px in SIZES:
            img = _load(activity, px)
            r, g, b, _a = img.split()
            for channel, label in ((r, "R"), (g, "G"), (b, "B")):
                lo, hi = channel.getextrema()
                assert (lo, hi) == (0, 0), (
                    f"{activity}-{px}.png has non-zero {label} (extrema {(lo, hi)}); "
                    "ESPHome's is_alpha_only() requires every colour channel to be 0"
                )


def test_alpha_is_only_0_or_255():
    for activity in ACTIVITIES:
        for px in SIZES:
            img = _load(activity, px)
            alpha = img.split()[-1]
            values = set(alpha.tobytes())
            extra = values - {0, 255}
            assert not extra, f"{activity}-{px}.png has intermediate alpha values {extra}"


def test_alpha_extrema_are_exactly_0_and_255():
    """Both ends, not just "some ink": ESPHome's `is_alpha_only()` returns
    False for an image whose alpha is 255 everywhere, and then compiles the
    (all-black) colour data instead -- a blank icon on the wall while the
    preview blits a solid square from the same file. `(0, 255)` is exactly
    the shape that guarantees the BINARY path takes the alpha channel."""
    for activity in ACTIVITIES:
        for px in SIZES:
            img = _load(activity, px)
            alpha = img.split()[-1]
            assert alpha.getextrema() == (0, 255), (
                f"{activity}-{px}.png alpha extrema {alpha.getextrema()}: "
                "needs both a transparent and an inked pixel"
            )


# --------------------------------------------------------------------------
# This file's asset shape against the renderer's own tables (B4b): the two
# must agree on which names are lucide activity icons and which pixel sizes
# exist, or `draw_icon()`'s PNG path and the firmware's `image:` block could
# silently name a file neither this file nor `ICONS` actually has an entry
# for.
# --------------------------------------------------------------------------


def test_activities_are_exactly_the_lucide_icons():
    """Every `ICONS` name that isn't one of the eleven MDI icons is one of
    this file's eight activities, and vice versa -- `_MDI_SLUGS`
    (firmware_yaml.py) is the one place that table of eleven lives."""
    lucide_names = set(ICONS) - set(_MDI_SLUGS)
    assert lucide_names == set(ACTIVITIES)


def test_sizes_are_exactly_the_icon_slot_pixel_counts():
    assert set(SIZES) == set(ICON_SIZES.values())


def test_every_activity_size_pair_is_an_icons_entry():
    """Every PNG this file expects has an `ICONS` entry naming its slot --
    the renderer side of the icon parity test; the YAML/firmware side is
    `tests/parity/test_limits_and_dispatch.py`'s
    `test_a_icons_keys_are_exactly_icons_and_slots`."""
    px_to_slot = {px: slot for slot, px in ICON_SIZES.items()}
    for activity in ACTIVITIES:
        for px in SIZES:
            assert px_to_slot[px] in ICONS[activity], (
                f"{activity}-{px}.png has no ICONS[{activity!r}] slot for {px}px"
            )


def test_every_lucide_icons_slot_has_a_png_and_vice_versa():
    """The reverse direction: every slot `ICONS` lists for a lucide
    activity icon has a committed PNG, and no lucide icon claims a slot
    this file doesn't expect a PNG for."""
    for activity in ACTIVITIES:
        expected = {f"{activity}-{ICON_SIZES[slot]}.png" for slot in ICONS[activity]}
        assert expected == {f"{activity}-{px}.png" for px in SIZES}


# The eleven MDI icons' name -> mdi: slug, read off the hand-written YAML
# before B4b's generator replaced it (docs/plans/fonts-and-icons.md B4b
# review item 8) -- a literal, independent of `firmware_yaml._MDI_SLUGS`,
# so an accidental slug edit there (a typo, a rename) fails loudly instead
# of both copies silently agreeing on the wrong thing.
_PRE_B4B_MDI_SLUGS = {
    "weather-sunny": "weather-sunny",
    "weather-partly-cloudy": "weather-partly-cloudy",
    "weather-cloudy": "weather-cloudy",
    "weather-rainy": "weather-rainy",
    "weather-snowy": "weather-snowy",
    "weather-night": "weather-night",
    "check": "check",
    "map-marker": "map-marker",
    "clock": "clock-outline",
    "alert": "alert",
    "battery": "battery",
}


def test_mdi_slugs_match_the_pre_b4b_yaml():
    assert _MDI_SLUGS == _PRE_B4B_MDI_SLUGS
