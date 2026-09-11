# Frame bezel: the panel in a 12 1/8" × 10 1/8" picture frame

Status: designed and coupon-tested 2026-09-09; first full print the same
evening (decision 7 records what it taught), second set exported after it. Source is `mount/epaper_frame_bezel.scad`; mock-ups and STLs
sit next to it; `mount/README.md` has the print procedure. This replaces the
earlier standalone wall mount (tiled tray, glass clips, French cleat), which
was never printed and is gone; this repo is authoritative for the hardware.

## What we want on the wall

An ordinary picture frame, hung portrait, with the panel showing through a
matte black bezel that reads like a mat. No glazing: the printed bezel and
the panel are the only things in the frame. The ribbon and the driver board
are hidden behind, the battery too, and the frame's own backing board and
turn buttons close it up.

```
frame lip ─┐
           ▼
  ┌────────────────────────┐   bezel face plate, 2 mm, 45° bevel at the window
  │ ┌────────────────────┐ │   overlaps the panel glass so it can't come forward
  │ │                    │ │
  │ │   active area      │ │   window = active area − 1 mm per edge
  │ │   202.8 × 270.4    │ │
  │ │                    │ │
  │ └────────────────────┘ │
  │   ═══ ribbon edge ═══  │   notch in the bottom wall; flex folds behind
  └────────────────────────┘
```

Nothing grabs the glass. The lip presses on the face plate, the face plate
overlaps the glass, the backing board presses on the spacer's back. Every
step of the load path is a push, never a clamp, which is what a 0.85 mm
sheet of glass wants; the ring does the job a mat does in a framed print.

## Decision 1: a bezel ring, not loose spacer strips. (2026-09-09.)

The Ikea-hack builds use side strips behind a glazed frame. Without glazing
the front lip has to be part of the print, so it is one stepped ring: a face
plate that is the visible bezel plus a pocket wall that fills the gap between
the glass and the rabbet. The face plate overlaps the glass by 4 mm on three
edges and 12.3 mm on the ribbon edge; the extra on that edge is the panel's
own dead border, not lost image.

## Decision 2: geometry from the vendor drawing, not the datasheet table.

The 13.3" e-Paper (E) user manual, section 4, settles what the table
doesn't say: the active area is 3.0 mm from the glass on three edges and
11.3 mm on the ribbon edge, so it is off-centre on the glass by 4.15 mm;
the ribbon leaves a short edge in the plane of the glass and must fold
within ~3.4 mm of the edge at R > 0.5; the bonded flex runs about 40 to 176
mm along that edge; the 60-pin tail is 30.5 mm wide, 29.75 mm long, and
starts 40.24 mm from the corner; the fan-out area on the back stands up to
1.2 mm proud. The tail's corner is **bottom-left as seen from the front**,
confirmed on the panel, so `fpc_mirror` stays false.

## Decision 3: centre the image, not the glass.

With the active area off-centre, centring the glass would give a 10 mm
bezel on one short edge and 18 mm on the other. The glass is instead placed
so the *image* is centred, then walked 1 mm back toward the frame centre
(`centre_bias`), which is invisible from the front and leaves 2.9 mm of
wall outside the ribbon notch. Visible bezel with a 5 mm frame lip: 22 mm
sides, 13 mm top, 15 mm bottom.

## Decision 4: the window hides 1 mm of image per edge, and the composer knows.

The lip has to overlap something, and the 3 mm dead border on three edges
is too thin to overlap alone once the panel floats 0.3 mm in its pocket. So
the window is the active area less 1 mm per edge: about 6 px hidden, plus a
couple of pixels of float and the bevel's shadow. On the display-mcp side
`check()` (and so `validate`) warns when a `text`, `fmt` or `icon` anchor
lands inside `BEZEL_MARGIN` = 24 px, and `compose.md` says fills run full
bleed and type stays 24 px in. Judged by the anchor corner only, so the
standard footer at y 1545 stays clean. Warnings never block a publish.

## Decision 5: thickness comes from coupons, and it is 4.85 mm.

The frame has a stepped rabbet. Measured with `part = "coupons"` (40 mm
corners embossed with their thickness, dropped into the frame corner with
the backing board on): the first ladder, 2.9 to 3.35, left 1.6 mm short;
the second, 4.85 to 5.35, closed on **4.85**. The spacer is 2.0 face + 0.85
glass + 0.3 float + 1.7 back = 4.85, and the 2.0 mm behind the glass is where
the ribbon fold (needs ~1.4) and the fan-out bump (1.2) live, inside the
spacer's depth. The backing board needs a hole only where the tail and the
driver board are, roughly 45 × 40 mm at the bottom-left of the glass. The
frame's second step stays free for the board and battery.

## Decision 6: four dovetailed quarters.

A 306 mm ring fits no ordinary bed. `split = "quarters"` gives four L pieces
with 8 mm dovetails at −0.05 mm fit, printed face-down and support-free; the
largest is 216 × 161 mm. The bottom joint sits at x = −88 rather than the
middle so it stays out of the ribbon notch. `halves` (two 255 × 161 mm U
pieces) suits a 256 mm bed. Everything is trapped in compression in the
rabbet, so the joints only have to register, not hold.

## Decision 7: what the first full print changed. (2026-09-09, evening.)

Three things, all now in the defaults:

- **Size.** The ring sat about 1/16" loose in both directions, so the
  rabbet is recorded as 10 1/8" × 12 1/8" and the 0.6 mm clearance stays
  honest rather than going negative.
- **The notch had a wall in it.** The inner end of the notch cut was placed
  1 mm *outside* the pocket edge instead of 1 mm inside, so a 1 mm sliver of
  wall stood between the glass pocket and the recess, and the notch also
  stopped 0.25 mm short of the glass back. Both gone: the wall is simply
  absent from the back of the face plate to the back of the spacer.
- **The notch was 5 mm off.** The flex sat flush against the left end and
  had ~5 mm spare at the right. The bonded-flex extent is now 35 to 174 mm
  from the tail corner (was 40 to 176), notch 4 mm beyond that each end.

The second print (all three fixes in) went together and fits the frame. Its
one finding: the dovetails were loose at 0.15 mm fit in PETG. The fit
ladder (`part = "joints"`: one tab, sockets at 0.10 / 0.05 / 0 / −0.05)
settled it on 2026-09-10: **−0.05** seats right, so `tab_fit` is −0.05.
The socket is cut 0.05 smaller than the tab and the print's own inside
corners take up the rest. That number is specific to PETG on this printer;
the ladder exists so anyone changing either prints it first rather than
trusting the default.

## Decision 8: the electronics carrier is a screwed-down web. (2026-09-10.)

The driver board and battery get a printed part, `mount/epaper_frame_carrier.scad`,
that lies on the back of the backing board in the ribbon corner. Three
drafts in one afternoon: a plate on the frame's second step with the ribbon
routed underneath; a plate flat on the backing hooking into the groove;
and the one that stuck, the user's: a web of ribs rather than a plate,
since on the backing board a plate does nothing, with rails on the two
outer edges that rise to the frame's second step and flange out over it so
the part is screwed to the frame like its own turn buttons are. Ribbon
tail, adapter and FFC stay taped to the backing; the web leaves them alone.
The board screws to counterbored bosses on its standoffs; the battery
straps to a low tray around a cross rib. Measured bottom edge, from the
ribbon corner: turn buttons at 1.5" and 8.5", the backing's ribbon cut-out
from 2" to 8" where neither groove nor ledge can be used, and a 1" strip
along the edge nothing can lie on; so the bottom rail is a 1" corner run
with one screw, the right rail takes three, and the ribs stay above the
strip. After the first full print the board moved above the battery,
placed by a hole measured on the frame (1.5" in, 4.75" up), so the FFC
runs straight up from the adapter; with everything close to the right rail
the arm out to an 8" screw was dropped. Coupons (rail, corner, far window,
board ring, then a 3 × 3 rail ladder) settled the ledge at 9.0 up and a
5.5 flange, and the board holes at 72 × 21.75, before the full print. Power is
battery only; the frame comes down to charge.
Flange undersides are unsupported overhangs in the print and take slicer
supports; nothing can be put under them because the frame's wall is there.

## Still open


- The full print: does the ring drop into the rabbet, does the panel float
  without ticking, does the flex fold clear in the notch. Adjust
  `rabbet_fit`, `panel_fit` or `fpc_notch_out` from what the print says.
- The carrier coupons, then the full print: do the rails seat and the
  flanges suit the ledge, does the far segment fit its window, does the
  board and battery stack clear the moulding.
