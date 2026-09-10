# Picture-frame bezel — `epaper_frame_bezel.scad`

The panel hangs in an ordinary picture frame behind this printed bezel:
a **12 1/8" × 10 1/8" rabbet, 4.85 mm deep** (both measured against
prints: the first ring at 12 1/16 × 10 1/16 sat 1/16" loose, the coupons
gave the depth), hung portrait, no glazing. Decisions and open items are in
`docs/plans/frame-bezel.md`. `bezel_front.png`, `bezel_back.png`,
`bezel_exploded.png`, `bezel_cutaway.png`, `bezel_section.png`,
`bezel_notch.png`, `bezel_notch_tail.png`, `bezel_pieces.png` and
`bezel_coupons.png` are the mock-ups; `stl/bezel_*.stl` are the printable pieces at the defaults.

## What it does

A stepped ring that drops into the rabbet in front of the panel. The front
**face plate** (2 mm, 45° mat-style bevel at the window) is the visible
bezel; it overlaps the glass by 4 mm on three edges and 12.3 mm on the ribbon
edge, so the panel cannot come forward. Behind it a **pocket wall** fills the
gap between the glass and the rabbet, so the panel cannot slide. The frame's
lip presses on the face plate; the frame's backing board presses everything
forward. Nothing grabs the glass: every step of the load path is a push,
and the ring does the job a mat would do in a framed print.

The ribbon leaves the glass on a **short edge** in the plane of the glass and
has to fold 180° behind the panel within ~3.4 mm of the edge (vendor drawing:
bending area, R > 0.5). On that edge the wall is **absent**: from the back of
the face plate through to the back of the spacer, 4.5 mm past the glass, over
the bonded flex plus 4 mm each side (35 to 174 mm from the tail corner; the
first print showed the flex flush at 40 and 5 mm spare at 176).

The frame has a stepped rabbet; the backing board sits on the first step,
**4.85 mm** behind the lip (the coupon ladder settled it: 3.35 left 1.6 mm
short, 4.85 closed). The spacer fills that exactly: 2.0 face + 0.85 glass +
2.0 behind. The 2.0 behind the glass is where the ribbon folds (R > 0.5
needs about 1.4) and where the 1.2 mm fan-out bump sits, so both live inside
the spacer's depth. The backing board needs a hole only where the tail and
the driver board are, roughly 45 mm wide by 40 mm up from the bottom-left of
the glass. The second step stays free for the board and battery. The fold, the 1.2 mm fan-out bump on the back of
the glass and the driver board all stand proud of the spacer's back, and the
frame's backing board needs a **cut-out along the ribbon edge** for them:
roughly the width of the notch (150 mm) from just below the glass edge to
about 40 mm above it, merging with whatever hole the driver board needs.

## Numbers at the defaults

| | |
|---|---|
| Rabbet (as hung) | 257.2 × 308.0 mm, spacer 0.6 mm smaller |
| Window at the back of the face | 200.8 × 268.4 (active area minus 1 mm per edge) |
| Front opening incl. bevel | 204.0 × 271.6 |
| Wall thickness | sides 22.8, top 13.4, ribbon edge 7.1 (2.9 left outside the notch) |
| Visible bezel with a 5 mm frame lip | sides 22.4, top 13.0, bottom 15.0 |
| Thickness | 2.0 face + 0.85 glass + 0.3 float + 1.7 back = 4.85, the measured rabbet |

The active area is off-centre on the glass (3.0 mm border on three edges,
11.3 mm on the ribbon edge). `centre_on = "active"` centres the *image* in
the frame; `centre_bias = 1` then walks the glass 1 mm back toward the frame
centre, which is invisible on the front and buys wall outside the notch.

## Printing

A 306 mm ring fits no ordinary bed, so `split = "quarters"` (default) cuts it
into four L pieces with dovetail joints, 0.15 mm fit, all face-down and
support-free:

| Piece | Where | Bounding box |
|---|---|---|
| `bezel_quarter_0.stl` | top-left | 135 × 153 mm |
| `bezel_quarter_1.stl` | top-right | 128 × 153 mm |
| `bezel_quarter_2.stl` | bottom-left | 48 × 161 mm |
| `bezel_quarter_3.stl` | bottom-right | 216 × 161 mm |

The bottom joint sits at x = −88 rather than the middle so it stays out of
the ribbon notch. `split = "halves"` gives two 255 × 161 mm U pieces
(`bezel_half_0/1.stl`, a 256 mm bed), `split = "none"` the one-piece ring.
PETG, black, 0.2 mm layers, 3 perimeters; the face is the visible surface, so
print it on a smooth sheet.

## Coupons: dial the thickness in first

Already done for this frame (answer: 4.85 mm), but for another frame:
`part = "coupons"` (`stl/bezel_coupons.stl`; `bezel_coupons_tall.stl` is the
second ladder) prints:

- **Corner coupons** at `coupon_thicks`, each a 40 mm top-left corner of the
  real part with the thickness embossed on the back, `coupon_cols` per row. Drop one in the frame's top-left rabbet corner, fit the
  backing board, close a turn button: the right one is the thickest that
  still lets the button close and doesn't rock. Below 3.15 the face plate
  gets thinner to keep the 0.3 mm glass float; above it the extra goes on the
  back. Set `face_t` / `back_t` to match and print the real thing.
- **A joint pair** (`part = "joint"`, `stl/bezel_joint_test.stl`): the two
  halves of the top dovetail, to check `tab_fit` (0.15) on your printer.
- **A notch slice**: 50 mm of the bottom wall through the ribbon tail, to
  offer up to the panel's ribbon edge and check the notch clears the flex.

## Check before printing

- The tail is nearest the **bottom-left** corner seen from the front
  (confirmed on the panel); `fpc_mirror` stays false.
- **Which frame edge the ribbon edge sits on.** `fpc_side` — bottom by
  default; left/right swap the rabbet dimensions for a landscape hang.
- **Your frame's lip overhang** only changes the visible bezel widths, not
  the part; `frame_lip` is mock-up only.
- The glass has 0.3 mm of float behind the face plate. The spacer's back is
  2.0 mm behind the glass, so nothing presses on the panel; if it ticks, a
  strip of 2 mm foam tape on the backing board over the top dead border
  (not the ribbon edge) settles it.

```
openscad -o stl/bezel_coupons.stl -D 'part="coupons"' epaper_frame_bezel.scad
openscad -o stl/bezel_quarter_0.stl -D 'part="piece"' -D piece_id=0 epaper_frame_bezel.scad
openscad -o front.png --camera=0,0,1000,0,0,0 --projection=o --imgsize=1400,1600 epaper_frame_bezel.scad
```
