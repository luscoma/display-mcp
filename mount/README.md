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
`part = "coupons"` prints (the test plates are not committed; render them,
they land in `stl/` where the ignore rules keep them out of git):

- **Corner coupons** at `coupon_thicks`, each a 40 mm top-left corner of the
  real part with the thickness embossed on the back, `coupon_cols` per row. Drop one in the frame's top-left rabbet corner, fit the
  backing board, close a turn button: the right one is the thickest that
  still lets the button close and doesn't rock. Below 3.15 the face plate
  gets thinner to keep the 0.3 mm glass float; above it the extra goes on the
  back. Set `face_t` / `back_t` to match and print the real thing.
- **A joint pair** (`part = "joint"`): the two
  halves of the top dovetail at the current `tab_fit`.
- **A fit ladder** (`part = "joints"`, 76 × 120 mm): one tab half and a socket half at each value in `joint_fits`
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
- The glass has 0.3 mm of float behind the face plate and 0.8 mm a side in
  the pocket (raised from 0.3 once the -0.05 dovetails closed the ring up). The spacer's back is
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
standoffs, the battery and the speaker. `carrier_plan.png` is a labelled
true-scale plan over the measured no-go zones (`part = "plan"`),
`carrier_assembly.png` and `carrier_print.png` the mock-ups, `carrier_boss.png`
the section through a boss (`part = "section"`); `stl/carrier.stl` is the
part. This is the second draft (2026-09-19); the first one taught most of
what follows.

## How it holds on

Rails along the right and bottom edges stand from the backing board up to
the frame's second step (the ledge) and turn outward into a 5.5 mm flange
that lies on it, with four plain holes for #2 pan-head wood screws (a
countersink would cut through the edges of a flange that narrow) — the
same step the frame's own turn buttons are screwed into. The part drops
straight in from behind and is screwed down; nothing slides or hooks.

The rail height, `ledge_z` = 10.0, is the distance from the ledge to the
backing board **with the backing pushed forward against the panel
stack**. The backing has 2–3 mm of play between the stack and the turn
buttons; the first print was built to the other end of that play (9.0),
floated off the backing, and the heavy board end sagged. Built to the
forward position with a little preload, the rail's foot holds the backing
against the stack and the web has something to bear on. Four thin tape
tabs (1.2 mm tongues off the board ring's far end and the FFC bridge's
far foot) get taped to the backing and hold the far end of the web down.

The bottom edge, measured from the ribbon corner: a turn button at 1.5",
the backing's ribbon cut-out from 2" to 8" (no groove or ledge usable
there), another button at 8.5", and nothing can lie on the backing within
1" of that edge. So the bottom rail is the corner run, 0 to 1", with one
screw; the right rail carries three; and every rib stays above the 1"
strip. Nothing screws into the backing board itself.

## Coupons first

None of the test plates are committed; render them from the SCAD and print
in this order. Each is a few grams.

1. **Rail ladder** (`part = "rail_ladder"`): 20 mm rail stubs at every
   `ladder_heights` × `ladder_widths`, labelled "height width" on top.
   Push the backing board forward against the panel stack and hold it,
   stand each stub in the right-hand opening with its flange on the
   ledge, and take the tallest whose flange still seats under firm hand
   pressure. Set `ledge_z` to it. (Here: 9.0 floated, 11.0 and up were all
   too tall, a 9.4–10.6 ladder settled 10.0.)
2. **Feature coupons** (`part = "coupons_v2"`), labelled BATT / SPK / FFC:
   - *Battery clip*: 30 mm of the pocket around one snap finger on a
     floor that stands in for the backing, ends open so the battery
     slides in sideways. Does it tilt in under the fixed lip, does the
     finger click over it and hold it flat, can a thumb release it.
   - *Speaker pocket*: does the speaker slide in and stop.
   - *FFC bridge*: does the ribbon pass under the bar, did the bar print.
3. **Clip ladder** (`part = "clip_ladder"`), only if the snap is wrong: one
   battery clip per `clip_lips` × `clip_thicks`, labelled "lip/thickness".
   Set `finger_lip` and `finger_t` to the winner. (Here: 1.5/1.2.)

## What sits on it

- The **battery** (JLJLUP 3000 mAh, measured 65 × 35.5 × 10; the listing's
  36 was the bulge rounded up) lies directly on the backing inside an open
  ring and is held like a phone battery. A fixed 2.0 mm lip runs along the
  rail-side wall; two snap fingers with a 1.5 mm lip stand on the far side,
  each with a thumb tab above the lip. Press the battery against the fixed
  wall, tilt that edge under its lip, lower the other edge: the fingers
  click over. To remove, push both tabs outward and lift. The cell bulges
  at mid-height, so `batt_w` (35.5) sizes the walls and `batt_w_top` (34.5)
  is what the lips engage. The lead leaves the cell at a corner; the notch
  is at the pocket's top-left (seen from behind).
- The **ribbon tail** and the **adapter board** stay on the backing under
  tape. The **FFC** (31 mm wide) runs straight up from the adapter to the
  board and passes under one bridge, level with the battery's centre, 2 mm
  clear, so it lies flat and can't lever a connector. A second bridge near
  the board was tried and dropped: the ribbon had no run left to climb to
  the connector.
- The **driver board** sits above the battery, next to the rail. It is
  placed by its bottom-right hole, measured on the frame: 1.5" in from the
  right wall, 4.75" up from the bottom (`board_br_x_in`, `board_br_y_in`). It
  takes M2, not M2.5. It stands on its 6 mm standoffs over a ring of ribs
  with a 9 mm boss at each of the four holes (72 × 21.75 mm pattern; the
  first coupon at 71 × 20.75 was 1 mm short each way). Each boss is
  recessed on both faces: a 1.5 mm collar on top with a 3.8 mm socket the
  standoff's foot drops into, so it can't walk sideways, and a 4.2 × 1.5 mm
  counterbore underneath so the M2 pan head sits flush. Ribs are 3.5 mm;
  the web between socket floor and head is 2.0 mm. The standoffs are 3 mm
  across-flats hex (3.46 across corners), hence the 3.8 socket.
- The board's little **speaker** (10.5 × 14.5 × 4.8) slides into a pocket
  just above the middle of the board's top edge, open upward so gravity
  keeps it seated when the frame hangs; the roof covers the lower half and
  the lead leaves through a notch in the closed end. It sits there because
  its lead is short.

Board top face ends up 11.1 mm behind the backing plus components, the
rails 12.0, the snap-finger tabs 14.5; the moulding must be deeper than
that beyond the ledge.

## Printing

144 × 176 mm, 14.5 mm tall at the finger tabs, 12.0 at the rails. Print
bottom-down as exported, PETG like the bezel. The flange undersides are
bare 5.5 mm overhangs (in use the frame's wall is under them, so nothing
can be added there): enable slicer supports for overhangs only, they land
under the flanges and snap off. The FFC bar is a ~39 mm bridge 2 mm off
the bed and the snap fingers are 1.2 mm free-standing walls; both print
without support.

```bash
openscad --export-format binstl -o stl/carrier.stl -D 'part="carrier"' epaper_frame_carrier.scad
```
