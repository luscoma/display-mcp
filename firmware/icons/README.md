# Icon sources and rasters

Eight activity icons, drawn from [lucide](https://lucide.dev) at version
**1.47.0** (pinned), plus `rasterize.py`, the script that turns them into
the committed PNGs both the firmware and the preview consume. Decision 4 of
`docs/plans/fonts-and-icons.md` is the full write-up; this file is the
quick reference.

## Source → artefact

| activity | lucide icon | source | rasters |
|---|---|---|---|
| `school-day` | `book-open` | `src/school-day.svg` | `school-day-{22,28,36,48,84}.png` |
| `daycare` | `baby` | `src/daycare.svg` | `daycare-{22,28,36,48,84}.png` |
| `taekwondo` | `star` | `src/taekwondo.svg` | `taekwondo-{22,28,36,48,84}.png` |
| `swim` | `waves-ladder` | `src/swim.svg` | `swim-{22,28,36,48,84}.png` |
| `helper` | `user-round` | `src/helper.svg` | `helper-{22,28,36,48,84}.png` |
| `appointment` | `stethoscope` | `src/appointment.svg` | `appointment-{22,28,36,48,84}.png` |
| `family-meeting` | `users` | `src/family-meeting.svg` | `family-meeting-{22,28,36,48,84}.png` |
| `closed` | `calendar-off` | `src/closed.svg` | `closed-{22,28,36,48,84}.png` |

`src/<activity>.svg` is the picture's lucide file, renamed for the activity
it stands for (`book-open.svg` → `school-day.svg`) — nothing else about the
SVG is changed. `src/LICENSE` is lucide-static's own ISC licence text,
fetched at the same pinned version.

The five sizes are the font-slot pixel sizes (`xs sm md lg xl` = `22 28 36
48 84`), not a separate icon ladder — see Decision 4.

## Version pin

**lucide-static 1.47.0**, fetched 2026-09-19 from:

(The pixels are fixed by the other end too: `resvg_py` 0.3.4 as shipped in
ESPHome 2026.8.2's Python. A different resvg may rasterise a curve a pixel
differently; the firmware compiles the committed PNG, so that only matters
when this script is re-run.)

Sources:

- `https://cdn.jsdelivr.net/npm/lucide-static@1.47.0/icons/<icon>.svg` for
  each SVG
- `https://cdn.jsdelivr.net/npm/lucide-static@1.47.0/LICENSE` for the
  licence

The same version is recorded in a comment at the top of `rasterize.py`.
Bumping the pin means re-fetching the eight SVGs at the new version,
re-running `rasterize.py`, and updating both places this version number is
written.

## Rasterising

```
/opt/homebrew/Cellar/esphome/2026.8.2/libexec/bin/python firmware/icons/rasterize.py
```

Run under ESPHome's own Python — it has `resvg_py`, which the project's
`.venv` does not have and does not need (Pillow it has already). The script takes no
arguments and locates every path relative to itself. For each of the eight
SVGs and each of the five sizes it:

1. Calls `resvg_py.svg_to_bytes(svg_path=..., width=px, height=px,
   dpi=100)` — the exact call ESPHome's `components/file/image.py` makes
   for an SVG `file:` image.
2. Reproduces `components/image/__init__.py`'s `ImageBinary.convert()`:
   takes the alpha channel and thresholds it at 128 with no dithering
   (`image.convert("1", dither=Image.Dither.NONE)`), which is what a
   `type: BINARY` image with the default `dither: NONE` does to an
   alpha-only source.
3. Writes the result as an RGBA PNG whose RGB is always `(0, 0, 0)` and
   whose alpha is exactly `0` or `255` — the shape
   `is_alpha_only()` recognises, so ESPHome compiles the PNG through the
   same BINARY path an SVG would take.

It prints one line per file, `wrote:` or `unchanged:`, and is deterministic
and idempotent: given the same source SVGs, a second run writes the same
bytes and reports every file `unchanged`.

## What consumes the PNGs

`src/display_mcp/render/icons/<activity>-<px>.png` — forty files, eight
activities at the five slot sizes — are committed, not generated at build
or test time. Both sides read the same file:

- The **firmware** compiles each PNG through an `image:` entry with
  `type: BINARY` (a later batch wires these into
  `firmware/epaper-schedule.yaml`).
- The **preview** (`display_mcp.render`) blits the same PNG in
  `draw_icon()` (also a later batch).

This batch (B4a) only lands the sources and the rasters; nothing reads them
yet.
