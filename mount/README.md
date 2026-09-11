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
into four L pieces with dovetail joints at −0.05 mm fit (the ladder's pick
in PETG; 0.15 and 0.05 were loose), all face-down and support-free:

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
  halves of the top dovetail at the current `tab_fit`.
- **A fit ladder** (`part = "joints"`, `stl/bezel_joint_ladder.stl`, 76 × 120
  mm): one tab half and a socket half at each value in `joint_fits`
  (0.10, 0.05, 0, −0.05), labelled on the back. Try the one tab in every
  socket; the right one seats with light friction and doesn't rattle. Set
  `tab_fit` to it. On this printer, in PETG, that was −0.05. **Every fit
  number here was found by test print in PETG on one printer.** PLA shrinks
  less, so −0.05 may bind; ABS/ASA shrink more, so it may rattle. Print the
  ladder before the quarters if you change material or printer.
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

---

# Electronics carrier — `epaper_frame_carrier.scad`

A web of ribs that lies on the back of the backing board in the
bottom-right corner (seen from behind, where the ribbon tail is), is
screwed to the frame, and carries the ESP32-S3 driver board on its
standoffs and the battery. `carrier_plan.png` (true-scale plan over the
measured no-go zones), `carrier_assembly.png`, `carrier_print.png` and
`carrier_coupons.png` are the mock-ups, `carrier_boss.png` the section
through a boss; `stl/carrier.stl` is the part, `stl/carrier_coupons.stl`
the test plate.

## How it holds on

Rails along the right and bottom edges stand from the backing board up to
the frame's second step (the ledge, 9.0 mm behind the backing; the rail
ladder picked 8.9 × 5.5) and turn outward into a 5.5 mm flange that lies
on it, with four plain holes for
#2 pan-head wood screws (a countersink would cut through the edges of a
flange that narrow) — the same step the frame's own turn buttons are
screwed into. The part drops straight in from behind and is screwed down;
nothing slides or hooks.

The bottom edge, measured from the ribbon corner: a turn button at 1.5",
the backing's ribbon cut-out from 2" to 8" (no groove or ledge usable
there), another button at 8.5", and nothing can lie on the backing within
1" of that edge. So the bottom rail is the corner run, 0 to 1", with one
screw; the right rail carries three; and every rib stays above the 1"
strip. Everything hangs close to the right rail, so that is enough: the
earlier arm out to an 8" screw is still in the file (`far_rail`) but off.
Nothing screws into the backing board itself.

## Coupons first

`stl/carrier_coupons.stl` (~118 × 78 mm, a few grams) prints the four
things that have to be right before the whole part is worth its plastic;
`stl/carrier_coupons_ledge.stl` is the same plate without the board ring,
for re-testing the rails alone; `stl/carrier_rail_ladder.stl` (`part =
"rail_ladder"`) is nine 20 mm rail stubs at every combination of
`ladder_heights` (8.9 / 9.9 / 10.9 to the flange) and `ladder_widths`
(5.5 / 6.5 / 7.5 flange), each labelled "height width" on top, to pick
`ledge_z` and `ledge_w` directly:

- **Rail coupon**: 30 mm of the right rail with its flange and a screw
  hole. Does it stand in the opening with the flange flat on the ledge, is
  the flange the right width, does the overhang print.
- **Corner coupon**: the corner run and the bottom of the right rail.
  Does it seat in the corner, does it clear the 1.5" button.
- **Far-window coupon**: the 8" segment with its screw, post and 20 mm of
  arm. Does the segment fit between the cut-out and the 8.5" button.
- **Board ring**: the four bosses alone. Do the standoffs land, do the
  M2.5 heads sit in the counterbores.

## What sits on it

- The **ribbon tail**, the **adapter board** and the **FFC** (the flat
  flexible cable to the driver board) stay on the backing board under tape
  exactly as now; the web leaves that area open.
- The **driver board** sits above the battery, next to the rail, so the
  FFC runs straight up from the adapter with no fold. It is placed by its
  bottom-right hole, measured on the frame: 1.5" in from the right wall,
  4.75" up from the bottom (`board_br_x_in`, `board_br_y_in`). It takes M2, not
  M2.5. It stands on its 6 mm standoffs over a ring of ribs with a 9 mm
  boss at each of the four holes (72 × 21.75 mm pattern; the first coupon
  at 71 × 20.75 was 1 mm short each way). Each boss is recessed on both
  faces: a 1.5 mm collar on top with a 3.8 mm socket the standoff's foot
  drops into, so it can't walk sideways, and a 4.2 × 1.5 mm counterbore
  underneath so the M2 pan head sits flush. Ribs are 3.5 mm; the web
  between socket floor and head is 2.0 mm. The standoffs are 3 mm
  across-flats hex (3.46 across corners), hence the 3.8 socket.

Board top face ends up 11.1 mm behind the backing plus components, the
rails 11.0; the moulding must be deeper than that beyond the ledge.

## Printing

120 × 166 mm, 11.0 mm tall at the rails. Print bottom-down as exported. The
flange undersides are bare 5.5 mm overhangs (in use the frame's wall is
under them, so nothing can be added there): enable slicer supports for
overhangs only, they land under the flanges and snap off. PETG like the
bezel.
