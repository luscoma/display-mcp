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

import importlib.util
from pathlib import Path

from PIL import Image

from display_mcp.render import ICON_SIZES, ICONS, LUCIDE_ICONS
from display_mcp.render.firmware_yaml import _MDI_NAMES, _MDI_SLUG_OVERRIDES
from display_mcp.render.fonts import SLOTS

ROOT = Path(__file__).resolve().parents[2]
ICONS_DIR = ROOT / "src" / "display_mcp" / "render" / "icons"


def _load_rasterize():
    """`firmware/icons/rasterize.py` as a module, without going through
    `firmware/icons/` as a package (it isn't one) -- importable from this
    venv now that its `resvg_py` import moved inside `rasterize_one()`
    (C9, final review), so `ACTIVITIES`/`SIZES` can be cross-checked here
    without ESPHome's own Python."""
    path = ROOT / "firmware" / "icons" / "rasterize.py"
    spec = importlib.util.spec_from_file_location("rasterize", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rasterize_activities_and_sizes_match_the_renderer():
    rasterize = _load_rasterize()
    assert set(rasterize.ACTIVITIES) == LUCIDE_ICONS
    assert rasterize.SIZES == tuple(SLOTS.values())

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


def test_icons_dir_is_exactly_the_expected_pngs():
    """Set equality both ways: every activity/size pair has a committed
    PNG, and nothing else is in the directory. (A separate
    `test_every_activity_and_size_has_a_png` asserting only the "nothing
    missing" half was removed as strictly subsumed by this one.)

    Dotfiles (.DS_Store) are ignored: macOS drops them and .gitignore hides
    them, so they are not a stray asset.
    """
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
    this file's eight activities, and vice versa -- `_MDI_NAMES`
    (firmware_yaml.py) is the one place that table of eleven lives, and
    `LUCIDE_ICONS` (shapes.py) is the shared source `firmware_yaml.py`'s
    MDI-vs-PNG decision and `shapes.py`'s own PNG-vs-stand-in decision
    both read (C9, final review) -- this file's own `ACTIVITIES` stays an
    independent literal (see its own comment) so this test is a real
    cross-check, not two names for the same list."""
    lucide_names = set(ICONS) - _MDI_NAMES
    assert lucide_names == set(ACTIVITIES) == LUCIDE_ICONS


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


# `test_every_lucide_icons_slot_has_a_png_and_vice_versa`, a per-activity
# restatement of `test_every_activity_and_size_has_a_png` +
# `test_no_other_files_in_icons_dir` above (same two sets, sliced by
# activity instead of compared whole), was removed here as a duplicate
# (C8, final review) rather than made to open the files -- it never did,
# and the two tests above already prove the full set on both sides.

# `clock` -> `mdi:clock-outline`, read off the hand-written YAML before
# B4b's generator replaced it (docs/plans/fonts-and-icons.md B4b review
# item 8) -- a literal, independent of `firmware_yaml._MDI_SLUG_OVERRIDES`
# (C9 shrank the eleven-entry self-mapping table this used to check in
# full to just its one real override), so an accidental edit there (a
# typo, a rename) fails loudly instead of both copies silently agreeing on
# the wrong thing.
_PRE_B4B_CLOCK_SLUG = {"clock": "clock-outline"}


def test_mdi_slug_override_matches_the_pre_b4b_yaml():
    assert _MDI_SLUG_OVERRIDES == _PRE_B4B_CLOCK_SLUG
