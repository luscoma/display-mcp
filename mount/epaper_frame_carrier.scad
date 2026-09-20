// =====================================================================
// Electronics carrier — a web of ribs that lies on the back of the
// backing board, is screwed to the frame's second step, and carries the
// ESP32-S3 driver board on its standoffs, the battery and the speaker.
//
// Seen from BEHIND, bottom-right corner (where the ribbon tail comes out).
// Profile behind the backing board, measured by hand:
//
//   backing board back face ........ z = 0          the web lies on this
//   groove, all four sides ......... ~2 mm tall, centred ~3/16" (4.8) above
//                                    the backing (not used by this design)
//   ledge (second rabbet) .......... 10.0 above the backing with the backing pushed
//                                    forward against the panel stack (it has 2-3 mm of
//                                    play); flange 5.5 wide: the flange sits here
//   opening at the backing ......... same as the backing: 10 1/8" x 12 1/8"
//
// Rails along the right and bottom edges stand from the backing up to the
// ledge and turn outward into a flange that lies on the ledge, with plain
// holes for small wood screws — the same step the frame's own
// turn buttons are screwed into. The part drops straight in from behind
// and is screwed down; nothing slides or hooks.
//
// Inside, 4 mm ribs: a ring through the driver board's four holes with a
// counterbored boss at each (the board stands on its 6 mm standoffs,
// screwed from underneath), a ring around the battery, and ties to the
// rails. The tail area is left open: the adapter board and the FFC stay
// taped to the backing as now. The bottom rail has gaps for the tail and
// for the turn button.
//
// Second draft (2026-09-18), after living with the first print:
//   - Battery: lies on the backing inside its ring (no cross rib) and is
//     held like a phone battery: a fixed lip along the rail-side wall it
//     tilts in under, and two snap fingers on the far side it presses
//     down past. Thumb tabs above the finger lips release it.
//   - FFC: a bridge level with the battery's centre that the ribbon slides
//     under on its run from the adapter to the board, so it lies flat and
//     cannot lever a connector. (A second one near the board left the
//     ribbon no run to climb to the connector; dropped.)
//   - Speaker: a slide pocket over the middle of the board's top edge (its
//     lead is short), open upward so gravity keeps it seated when the
//     frame hangs.
//   - Tilt: the far end of the web lifted off the backing, and there is
//     visible space under the rail's foot on the first print. So the rail
//     is SHORT of the ledge: the part hangs from the flange screws alone,
//     the web never bears on the backing, and every rib is a floating
//     cantilever that flexes. The backing has 2-3 mm of play between the
//     panel stack and the turn buttons; the ladder measured it one way,
//     the print met it the other. Build the rail to the forward position
//     plus a little preload, so the foot holds the backing against the
//     stack and the play is gone (ledge_z 9.0 -> 10.0). Tape tabs off the
//     board ring and the bridge hold the far end down as well.
//
//   part = "assembly"      frame corner + backing + carrier + board, battery, speaker
//        | "plan"          true-scale plan over the measured no-go zones, labelled
//        | "section"       cut through the board's lower holes (section_of = "board")
//                          or through a snap finger (section_of = "battery")
//        | "detail"        the battery pocket and the FFC bridge, close up
//        | "carrier"       the part alone, as printed (bottom on the bed)
//        | "rail_ladder"   rail stubs at ladder_heights x ladder_widths, labelled
//        | "coupons_v2"    battery clip, speaker pocket and the FFC bridge
//        | "clip_ladder"   battery clips at clip_lips x clip_thicks, labelled
//        | "speaker_coupon" the speaker pocket alone
//
// Print order for a new frame: rail_ladder (set ledge_z to the tallest stub
// whose flange still seats with the backing pushed forward), then coupons_v2
// against the real battery, speaker and ribbon (clip_ladder if the snap is
// wrong), then carrier. Bottom-down, PETG, supports under the flanges only;
// the FFC bar is a ~39 mm bridge 2 mm off the bed and the snap fingers are
// thin free-standing walls, both print without support.
//
// Coordinates: x to the right and y up as seen from behind; the opening's
// right wall is x = 0 (wood at x > 0), its bottom wall is y = 0 (wood at
// y < 0); z = 0 is the back face of the backing board.
// =====================================================================

/* [What to render] */
part = "assembly";   // assembly | plan | section | detail | carrier | rail_ladder | coupons_v2 | clip_ladder | speaker_coupon
section_of = "board";       // section: "board" cuts through the board's lower holes, "battery" through a snap finger
plan_labels = true;         // captions on the plan view

/* [Rail ladder: short rail coupons at every height x flange width, labelled] */
ladder_heights = [9.4, 9.8, 10.2, 10.6];     // the ladder that settled ledge_z = 10.0 (9.0 floated; 11.0 and up were all too tall)
ladder_widths  = [5.5];                      // flange, settled by the first ladder (5.5 / 6.5 / 7.5)
ladder_len     = 20;

/* [Frame, behind the backing board — measured] */
ledge_z       = 10.0;   // backing to the flange underside, with the backing pushed FORWARD against the panel stack.
                        // The first ladder picked 8.9 with the backing resting the other way; the 9.0 print floated,
                        // 11.0 and up were too tall, the v3 ladder (9.4..10.6) settled 10.0 on 2026-09-19.
ledge_w       = 6.0;    // flange = ledge_w - ledge_fit = 5.5, the ladder's pick
groove_c      = 4.8;    // mock-up only
groove_h      = 2.0;    // mock-up only
groove_d      = 1.0;    // mock-up only
frame_back    = 12;     // mock-up only: moulding beyond the ledge
opening_w_in  = 10.125;
opening_h_in  = 12.125;

/* [Bottom edge, measured from the corner (seen from behind, the ribbon corner)] */
button_x      = -1.5 * 25.4;   // first turn button, centre
button2_x     = -8.5 * 25.4;   // second turn button (beyond this part; drawn in the plan)
button_gap    = 24;            // gap in the bottom rail and flange around a button
ribbon_from   = -2.0 * 25.4;   // the backing's ribbon cut-out: nothing can use the groove or ledge here
ribbon_to     = -8.0 * 25.4;
no_lie_h      = 25.4;          // nothing lies on the backing within this of the bottom edge (button tabs, flex)

/* [Rails and flange] */
rail_t     = 3.0;    // rail thickness (stands inside the opening wall)
wall_fit   = 0.3;    // rail clearance to the opening wall
flange_t   = 2.0;    // flange thickness on the ledge
ledge_fit  = 0.5;    // flange stops this short of the moulding beyond the ledge
screw_d    = 2.4;    // #2 wood screw, plain hole: a pan head sits proud on the flange, nothing is above it.
                     // No countersink: a 5 mm one would cut through both edges of a 5.5 mm flange.
ext_w      = 150;    // how far the carrier reaches from the right wall
ext_h      = 170;    // how far up from the bottom wall (the speaker pocket sits above the board)

/* [Ribbon tail, for the plan view] */
glass_inset  = (opening_w_in * 25.4 - 208.8) / 2;   // glass edge from the opening wall, 24.2
tail_from    = 40.24;
tail_w       = 30.5;

/* [Web] */
web_t      = 3.5;    // rib height: a 1.5 mm M2 counterbore leaves a 2.0 mm web at the bosses
rib_w      = 6.0;

/* [Driver board — Waveshare ESP32-S3-ePaper-Driver-Board] */
board_w     = 75.5;
board_h     = 25.4;
board_t     = 1.6;
hole_dx     = 72.0;   // first coupon at 71 was 1 mm short
hole_dy     = 21.75;  // first coupon at 20.75 was 1 mm short
// The board takes M2, not M2.5. Each boss is recessed on both faces: a
// collar on top with a socket the standoff's foot sits in, a shallow
// counterbore underneath for the screw head.
hole_d      = 2.3;    // M2 clearance
head_d      = 4.2;    // M2 pan head (3.8 dia, 1.3 tall) counterbore, from underneath
head_h      = 1.5;
standoff_d  = 3.46;   // hex M2 standoff, 3 mm across flats, across corners
socket_d    = 3.8;    // the socket in the collar the standoff sits in (0.17 a side over the corners)
socket_h    = 1.5;    // how far the standoff sits down into the collar
boss_d      = 9.0;
standoff_h  = 6.0;
// placed by the board's bottom-right hole, measured on the frame: 1.5" in from the
// right wall, 4.75" up from the bottom; the board sits above the battery so the
// FFC runs straight up from the adapter
board_br_x_in = 1.5;
board_br_y_in = 4.75;
board_cx    = -board_br_x_in * 25.4 - hole_dx / 2;
board_cy    =  board_br_y_in * 25.4 + hole_dy / 2;

/* [Battery — JLJLUP 3000 mAh, measured 65 x 35.5 x 10. Lies on the backing inside its ring, held by lips] */
batt_w      = 35.5;   // at its widest: the cell bulges at mid-height, and the walls must clear that
batt_w_top  = 34.5;   // across the top and bottom faces, where the lips engage (the edges are rounded)
batt_h      = 65;
batt_t      = 10;
batt_fit    = 0.05;   // a side, at the bulge: 36.1 mostly worked, the user asked for 0.5 tighter (35.6)
batt_cx     = -34;
batt_cy     = 72;
tray_wall_t = 1.6;
tray_end_h  = 5.0;    // the low end walls, and the low run of the finger side, above the web
lead_notch_w = 8;     // notch for the battery lead: top end wall, left corner (the lead leaves the cell at that corner)
lip_z       = batt_t + 0.5;   // underside of both lips above the backing: the battery is 10, plus slop
// fixed lip on the rail-side wall: the battery's edge tilts in under it
lip_fixed   = 2.0;    // overhang over the battery's edge
lip_flat    = 1.0;    // of which this much is flat underneath; the rest rises at 45 deg so it prints
lip_t       = 2.0;    // thickness above lip_z
// snap fingers on the far side: the battery presses down past them
finger_ys   = [-14, 14];   // along the battery, from its centre
finger_w    = 10;
finger_t    = 1.2;    // the clip ladder picked 1.5/1.2 on 2026-09-19 (lip/thickness)
finger_lip  = 1.5;    // overhang from the wall; catches the rounded edge by ~0.95. Clip ladder pick.
finger_top  = 14.5;   // finger tip above the backing: the thumb tab above the lip, pushed outward to release
finger_gap  = 0.6;    // the low wall stops this short of each finger so the finger can flex

/* [Battery clip ladder: one clip coupon per finger lip x finger thickness, labelled "lip/thickness"] */
clip_lips   = [0.9, 1.2, 1.5];
clip_thicks = [1.0, 1.2];

/* [FFC bridges: bars the ribbon slides under, on its run from the adapter up to the board] */
ffc_w         = 31;          // measured 2026-09-19
bridge_ys     = [batt_cy];   // one bridge, level with the battery's centre: a second one near the board left the ribbon no run to climb to the connector
bridge_clear  = 2.0;         // under the bar; the FFC is 0.3
bridge_bar_t  = 2.5;
bridge_leg    = 4;
bridge_margin = 4;           // clear span beyond each edge of the FFC

/* [Tape tabs: thin tongues that reach out over the backing and get taped down] */
tab_t   = 1.2;
tab_w   = 12;
tab_len = 22;

/* [Speaker — the driver board's little speaker, 10.5 x 14.5, slides into a pocket open upward] */
spk_w      = 10.5;   // across the slot
spk_l      = 14.5;   // along the slide
spk_t      = 4.8;    // measured 2026-09-19 (the 3.0 guess was too thin)
spk_fit    = 0.8;    // total, so 0.4 a side: an easy slide, gravity does the rest
spk_wall   = 1.6;
spk_roof_t = 1.6;
spk_roof_l = 9;      // the roof covers this much of the pocket from its closed end; the rest stays open to grip
spk_cx     = board_cx;   // over the middle of the board, just above its top edge: the speaker's lead is short
spk_lead_w = 4;      // notch in the closed end for the lead

/* [Mock-up] */
adapter_w   = 45;
adapter_h   = 26;
backing_t   = 3.0;
plate_color = [0.22, 0.23, 0.25];

$fa = 2; $fs = 0.4; eps = 0.01; BIG = 1000; in = 25.4;

// ---------------------------------------------------------------------
// Derived
// ---------------------------------------------------------------------
x_wall   = -wall_fit;                 // rail outer face
y_wall   =  wall_fit;
x_in     = x_wall - rail_t;           // rail inner face
y_in     = y_wall + rail_t;
x_far    = -ext_w;                    // far end of the carrier
y_far    =  ext_h;
tail_cx  = -(glass_inset + tail_from + tail_w/2);
hole_pts = [for (sx = [-1, 1], sy = [-1, 1]) [board_cx + sx*hole_dx/2, board_cy + sy*hole_dy/2]];
bw = batt_w + 2*batt_fit; bh = batt_h + 2*batt_fit;
bx_l = batt_cx - bw/2; bx_r = batt_cx + bw/2; by_b = batt_cy - bh/2; by_t = batt_cy + bh/2;   // the battery pocket

ffc_cx  = tail_cx;                                   // the FFC runs straight up from the tail
bx0 = ffc_cx - ffc_w/2 - bridge_margin;              // a bridge's clear span
bx1 = ffc_cx + ffc_w/2 + bridge_margin;

spk_x0 = spk_cx - spk_w/2 - spk_fit/2 - spk_wall;    // the speaker pocket's outside
spk_x1 = spk_cx + spk_w/2 + spk_fit/2 + spk_wall;
spk_y0 = hole_pts[3][1] + rib_w/2 + spk_wall;        // closed end: its wall stands on the board's top tie
spk_y1 = spk_y0 + spk_l + spk_fit + 1;               // open end
spk_z_roof = web_t + spk_t + spk_fit;                // roof underside

// tape tabs: [root on the web, free end]. Two off the board's far end; the bridges add their own.
tabs = [for (k = [0, 1]) [hole_pts[k], [hole_pts[k][0] - tab_len, hole_pts[k][1]]]];

echo(str("bottom rail: corner run x ", button_x + button_gap/2, "..0; ribbon cut-out ", ribbon_to, "..", ribbon_from, " rules the ledge out beyond it"));
part_x0 = min(hole_pts[0][0], bx0 - bridge_leg + 1) - tab_len - tab_w/2;   // the tape tabs reach furthest
part_z  = max(finger_top, spk_z_roof + spk_roof_t, ledge_z + flange_t);
echo(str("carrier: ", round(10 * (ledge_w - ledge_fit - part_x0)) / 10, " x ", round(10 * (y_far + ledge_w - ledge_fit)) / 10, " mm, ", part_z, " tall (", ledge_z + flange_t, " at the rails)"));
echo(str("board top face ", web_t + standoff_h + board_t, " mm above the backing (standoff foot at ", web_t, ", collar top at ", web_t + socket_h, "); rails ", ledge_z + flange_t, " tall"));
edge_in = (bw - batt_w_top) / 2;   // the top face's edge, in from the wall, battery centred
finger_flex = max(0, finger_lip - (bw - batt_w) + 0);   // the bulge passing the finger lip tip, battery pressed to the fixed wall
echo(str("battery pocket ", bw, " wide; top face edges ", edge_in, " in from the walls; fixed lip engages ", lip_fixed - edge_in, ", finger lip ", finger_lip - edge_in, " (centred); finger bends ", finger_flex, " on the way in, strain ~", round(1000 * 1.5 * finger_t * finger_flex / pow(lip_z - web_t, 2)) / 10, "%"));
echo(str("FFC bridges at y ", bridge_ys, ", clear span x ", bx0, "..", bx1, " (", bx1 - bx0, " mm bridge, ", bridge_clear, " off the bed)"));
echo(str("speaker pocket x ", spk_x0, "..", spk_x1, " y ", spk_y0, "..", spk_y1, ", roof ", spk_z_roof + spk_roof_t, " tall; part reaches y ", y_far));

section_y = section_of == "battery" ? batt_cy + finger_ys[1] : board_cy - hole_dy/2;   // a finger, or the board's lower holes
module clip() {
  if (part == "section")
    linear_extrude(1) projection(cut = true) rotate([-90, 0, 0]) translate([0, -section_y, 0]) children();
  else children();
}
module box(x0, x1, y0, y1, z0, z1) {
  translate([min(x0,x1), min(y0,y1), min(z0,z1)]) cube([abs(x1-x0), abs(y1-y0), abs(z1-z0)]);
}
module rrect(w, h, r) { hull() for (sx=[-1,1], sy=[-1,1]) translate([sx*(w/2-r), sy*(h/2-r)]) circle(r); }
module rib(p, q, w = rib_w) { hull() { translate(p) circle(d = w); translate(q) circle(d = w); } }
// a profile drawn in (x, z) and run along y from y0 to y1
module along_y(y0, y1) { translate([0, max(y0, y1), 0]) rotate([90, 0, 0]) linear_extrude(abs(y1 - y0)) children(); }

// ---------------------------------------------------------------------
// Rails: a wall from the backing to the ledge, a flange out over the
// ledge, a 45° fill under the flange so it prints without support
// ---------------------------------------------------------------------
// The flange's underside is a bare overhang in the print (the frame's wall
// is under it in use, so nothing can be added there): print bottom-down
// with slicer supports under the flanges only. They are 3.5 mm wide.
module rail_x(y0, y1) {            // right rail, spanning y0..y1
  fx = ledge_w - ledge_fit;        // flange outer edge
  box(x_in, x_wall, y0, y1, 0, ledge_z + flange_t);
  box(x_in, fx, y0, y1, ledge_z, ledge_z + flange_t);
}
module rail_y(x0, x1) {            // bottom rail, spanning x0..x1
  fy = -(ledge_w - ledge_fit);
  box(x0, x1, y_wall, y_in, 0, ledge_z + flange_t);
  box(x0, x1, fy, y_in, ledge_z, ledge_z + flange_t);
}
module rails() {
  rail_x(y_wall, y_far);
  // bottom rail: only the corner run, between the wall and the first turn button.
  // Beyond the button the backing's ribbon cut-out (2" to 8") rules the ledge out.
  rail_y(button_x + button_gap/2, x_wall);
}
flange_screws = [[ledge_w/2 - ledge_fit/2, 34], [ledge_w/2 - ledge_fit/2, (34 + y_far - 12) / 2],
                 [ledge_w/2 - ledge_fit/2, y_far - 12],
                 [(button_x + button_gap/2) / 2, -(ledge_w/2 - ledge_fit/2)]];


// ---------------------------------------------------------------------
// The web
// ---------------------------------------------------------------------
module web2d() {
  // ring through the board's holes
  rib(hole_pts[0], hole_pts[1]); rib(hole_pts[2], hole_pts[3]);   // short sides
  rib(hole_pts[0], hole_pts[2]); rib(hole_pts[1], hole_pts[3]);   // long sides
  // battery ring: open inside, the battery lies on the backing
  difference() { translate([batt_cx, batt_cy]) rrect(bw + 2*rib_w, bh + 2*rib_w, 3); translate([batt_cx, batt_cy]) rrect(bw, bh, 2); }
  // board ring -> right rail, at both right-hand holes
  for (k = [2, 3]) rib(hole_pts[k], [x_in + 1, hole_pts[k][1]]);
  // board ring -> battery ring, straight down, clear of the FFC's path from the adapter
  rib([board_cx + hole_dx/2 - 6, board_cy - hole_dy/2], [board_cx + hole_dx/2 - 6, by_t + rib_w/2]);
  // battery ring -> right rail
  rib([bx_r + rib_w/2, batt_cy + 20], [x_in + 1, batt_cy + 20]);
  rib([bx_r + rib_w/2, batt_cy - 20], [x_in + 1, batt_cy - 20]);
  // battery ring -> the corner run of the bottom rail, landing right of the button gap
  rib([bx_r - 2, by_b - rib_w/2], [(button_x + button_gap/2) / 2, y_in - 1]);
  // FFC bridges: the right foot ties to the battery ring
  for (y = bridge_ys) rib([bx1 + bridge_leg - 1, y], [bx_l - 1, y]);
  // speaker pocket -> right rail
  rib([spk_x1 - 1, (spk_y0 + spk_y1) / 2], [x_in + 1, (spk_y0 + spk_y1) / 2]);
}

// a boss: collar on top with a socket for the standoff foot, counterbore below for the head
module boss_solid(p) { translate([p[0], p[1], 0]) cylinder(d = boss_d, h = web_t + socket_h); }
module boss_cuts(p) translate([p[0], p[1], 0]) {
  translate([0, 0, -1]) cylinder(d = hole_d, h = web_t + socket_h + 2);   // M2 through
  translate([0, 0, -1]) cylinder(d = head_d, h = head_h + 1);             // head, from underneath
  translate([0, 0, web_t]) cylinder(d = socket_d, h = socket_h + 1);      // standoff socket, from the top
}

// ---------------------------------------------------------------------
// Battery: fixed lip on the rail side, snap fingers on the far side,
// low end walls with a notch for the lead
// ---------------------------------------------------------------------
module battery_tray(fl = finger_lip, ft = finger_t) {
  // rail-side wall, full height, with the fixed lip along its inner face
  box(bx_r, bx_r + tray_wall_t, by_b - tray_wall_t, by_t + tray_wall_t, web_t - eps, lip_z + lip_t);
  translate([bx_r, 0, 0]) along_y(by_b, by_t)
    polygon([[eps, lip_z], [-lip_flat, lip_z], [-lip_fixed, lip_z + (lip_fixed - lip_flat)], [-lip_fixed, lip_z + lip_t], [eps, lip_z + lip_t]]);
  // far-side wall: low, and cut back around each finger so the finger flexes alone
  difference() {
    box(bx_l - tray_wall_t, bx_l, by_b - tray_wall_t, by_t + tray_wall_t, web_t - eps, web_t + tray_end_h);
    for (fy = finger_ys) box(bx_l - tray_wall_t - 1, bx_l + 1, batt_cy + fy - finger_w/2 - finger_gap, batt_cy + fy + finger_w/2 + finger_gap, web_t + eps, BIG);
  }
  // the fingers: a plate up from the ring, a small lip with a lead-in, a thumb tab above
  for (fy = finger_ys) translate([bx_l, 0, 0]) along_y(batt_cy + fy - finger_w/2, batt_cy + fy + finger_w/2)
    polygon([[-ft, web_t - eps], [0, web_t - eps], [0, lip_z], [fl, lip_z], [fl, lip_z + 0.4],
             [0, lip_z + 0.4 + 1.25 * fl], [0, finger_top], [-ft, finger_top]]);
  // end walls, low; the top one notched at its left corner for the lead
  box(bx_l - tray_wall_t, bx_r + tray_wall_t, by_b - tray_wall_t, by_b, web_t - eps, web_t + tray_end_h);
  difference() {
    box(bx_l - tray_wall_t, bx_r + tray_wall_t, by_t, by_t + tray_wall_t, web_t - eps, web_t + tray_end_h);
    box(bx_l - tray_wall_t - 1, bx_l + lead_notch_w, by_t - 1, by_t + tray_wall_t + 1, web_t + eps, BIG);
  }
}

// ---------------------------------------------------------------------
// FFC bridge: two legs on the backing and a bar the ribbon slides under.
// The bar is a ~30 mm bridge 2 mm off the bed in the print.
// ---------------------------------------------------------------------
module ffc_bridge(y) {
  box(bx0 - bridge_leg, bx0, y - rib_w/2, y + rib_w/2, 0, bridge_clear + bridge_bar_t);
  box(bx1, bx1 + bridge_leg, y - rib_w/2, y + rib_w/2, 0, bridge_clear + bridge_bar_t);
  box(bx0 - eps, bx1 + eps, y - rib_w/2, y + rib_w/2, bridge_clear, bridge_clear + bridge_bar_t);
}

// a tape tab: a thin tongue from a point on the web out over the backing
module tab(p, q, w = tab_w) { linear_extrude(tab_t) hull() { translate(p) circle(d = w); translate(q) circle(d = w); } }

// ---------------------------------------------------------------------
// Speaker pocket: floor on the backing, two side walls, a closed end
// standing on the board's top tie, a roof over the closed half; open at
// the top so the speaker slides in from above and gravity keeps it there
// ---------------------------------------------------------------------
module speaker_slot() {
  difference() {
    union() {
      box(spk_x0, spk_x1, hole_pts[3][1], spk_y1, 0, web_t);                                                // floor, lapping onto the board's top rib
      for (xx = [spk_x0, spk_x1 - spk_wall]) box(xx, xx + spk_wall, spk_y0 - spk_wall, spk_y1, 0, spk_z_roof + spk_roof_t);   // sides
      box(spk_x0, spk_x1, spk_y0 - spk_wall, spk_y0, 0, spk_z_roof + spk_roof_t);                          // closed end
      box(spk_x0, spk_x1, spk_y0 - eps, spk_y0 + spk_roof_l, spk_z_roof, spk_z_roof + spk_roof_t);         // roof
    }
    box(spk_cx - spk_lead_w/2, spk_cx + spk_lead_w/2, spk_y0 - spk_wall - 1, spk_y0 + 1, web_t, spk_z_roof + eps);   // lead notch
  }
}

module carrier() {
  difference() {
    union() {
      // the web, clipped to the opening so no rib end pokes into the wall
      linear_extrude(web_t) intersection() { web2d(); translate([x_far - 30, y_wall]) square([-x_far + 30 + x_wall, y_far]); }
      for (p = hole_pts) boss_solid(p);
      battery_tray();
      for (y = bridge_ys) { ffc_bridge(y); tab([bx0 - bridge_leg + 1, y], [bx0 - bridge_leg - tab_len, y]); }
      for (t = tabs) tab(t[0], t[1]);
      speaker_slot();
      rails();
    }
    for (p = hole_pts) boss_cuts(p);
    // flange screws, plain holes
    for (p = flange_screws) translate([p[0], p[1], -1]) cylinder(d = screw_d, h = BIG);
  }
}

// ---------------------------------------------------------------------
// Mock-ups
// ---------------------------------------------------------------------
module frame_mock() {
  L = 245; T = 145;
  color([0.33, 0.22, 0.14]) clip() difference() {
    union() { box(0, 30, -30, T + 30, -backing_t - 2, frame_back); box(-L, 30, -30, 0, -backing_t - 2, frame_back); }
    box(-BIG, ledge_w, -ledge_w, BIG, ledge_z, BIG);
    box(-BIG, groove_d, -groove_d, BIG, groove_c - groove_h/2, groove_c + groove_h/2);
  }
  color([0.15, 0.15, 0.16]) clip() box(-L, 0, 0, T + 30, -backing_t, 0);
  // turn buttons: tab on the backing, screw into the ledge
  color([0.75, 0.75, 0.78]) clip() for (bx = [button_x, button2_x]) { box(bx - 6, bx + 6, -2, 14, 0, 1); translate([bx, -2, ledge_z]) cylinder(d = 5, h = 2); }
  // the backing's ribbon cut-out, the flex, the adapter and the FFC
  color([0.35, 0.28, 0.2]) clip() box(ribbon_to, ribbon_from, -1, 8, -backing_t, 0.01);
  color([0.85, 0.55, 0.15]) clip() box(ribbon_to + 4, ribbon_from - 4, -6, 6, 0, 0.3);
  color([0.85, 0.55, 0.15]) clip() box(tail_cx - tail_w/2, tail_cx + tail_w/2, -6, 14, 0, 0.3);
  color([0.2, 0.35, 0.7]) clip() box(tail_cx - adapter_w/2, tail_cx + adapter_w/2, 12, 12 + adapter_h, 0, 1.6);
  color([0.92, 0.92, 0.88]) clip() box(tail_cx - ffc_w/2, tail_cx + ffc_w/2, 12 + adapter_h, board_cy - board_h/2 + 4, 0, 0.3);
}
module board_mock() {
  z0 = web_t;                       // standoff foot sits on the socket floor
  color([0.75, 0.65, 0.3]) clip() for (p = hole_pts) translate([p[0], p[1], z0]) cylinder(d = standoff_d, h = standoff_h);
  color([0.2, 0.35, 0.7]) clip() translate([board_cx, board_cy, z0 + standoff_h]) linear_extrude(board_t) square([board_w, board_h], center = true);
  zt = z0 + standoff_h + board_t;
  color([0.8, 0.8, 0.8]) clip() box(board_cx + 12, board_cx + 32, board_cy - 9, board_cy + 9, zt, zt + 3);
  color([0.8, 0.8, 0.8]) clip() box(board_cx - board_w/2 - 1, board_cx - board_w/2 + 8, board_cy - 4.5, board_cy + 4.5, zt, zt + 3.2);
  color([0.92, 0.92, 0.88]) clip() box(board_cx - 17, board_cx + 17, board_cy - board_h/2 + 1, board_cy - board_h/2 + 6, zt, zt + 2.5);
  color([0.95, 0.95, 0.9]) clip() box(board_cx - 24, board_cx - 16, board_cy + board_h/2 - 6, board_cy + board_h/2 - 1, zt, zt + 4);
}
module battery_mock() {   // lies on the backing; bulges to batt_w at mid-height, batt_w_top at the faces
  color([0.55, 0.55, 0.6]) clip() translate([batt_cx, batt_cy, 0]) hull() {
    translate([0, 0, 3]) linear_extrude(batt_t - 6) rrect(batt_w, batt_h, 3);
    linear_extrude(batt_t) rrect(batt_w_top, batt_h - 1, 2);
  }
}
module speaker_mock() {
  color([0.3, 0.3, 0.32]) clip() box(spk_cx - spk_w/2, spk_cx + spk_w/2, spk_y0 + 0.2, spk_y0 + 0.2 + spk_l, web_t, web_t + spk_t);
}
module assembly() { frame_mock(); color(plate_color) clip() carrier(); board_mock(); battery_mock(); speaker_mock(); }

// plan: the carrier's footprint over the measured no-go zones, true scale
module plan() {
  L = 8.5 * 25.4 + 30;
  color([0.15, 0.15, 0.16]) translate([-L, 0, -3]) cube([L + 0.3, opening_h_in * 25.4, 1]);   // backing board
  color([0.33, 0.22, 0.14]) { translate([0, -30, -3]) cube([30, 400, 1]); translate([-L - 30, -30, -3]) cube([L + 60, 30, 1]); }
  color([0.55, 0.25, 0.2, 0.8]) translate([ribbon_to, 0, -2]) cube([ribbon_from - ribbon_to, 8, 1]);     // ribbon cut-out
  color([0.9, 0.3, 0.3, 0.35]) translate([-L, 0, -2]) cube([L, no_lie_h, 1]);                             // no-lie strip
  color([0.85, 0.55, 0.15]) translate([tail_cx - tail_w/2, -6, -1.5]) cube([tail_w, 20, 1]);              // tail
  color([0.2, 0.35, 0.7]) translate([tail_cx - adapter_w/2, 12, -1.5]) cube([adapter_w, adapter_h, 1]);   // adapter
  color([0.7, 0.7, 0.65]) translate([tail_cx - ffc_w/2, 12 + adapter_h, -1.2]) cube([ffc_w, board_cy - board_h/2 + 4 - 12 - adapter_h, 1]);   // FFC
  color([0.75, 0.75, 0.78]) for (bx = [button_x, button2_x]) translate([bx - 6, -2, -1.5]) cube([12, 16, 1]);  // buttons
  color(plate_color) carrier();
  board_mock(); battery_mock(); speaker_mock();
  if (plan_labels) color([1, 0.85, 0.3]) translate([0, 0, 20]) {
    cap("bottom-right corner, seen from behind, true scale", [-190, y_far + 6], 5);
    cap("right rail: three screws into the ledge", [x_in - 4, y_far + 6], 3.5, "right");
    cap("driver board on M2 standoffs; tape tabs off its far end", [hole_pts[1][0] - tab_len - 6, hole_pts[1][1] + 26], 3.5);
    cap("speaker pocket, open upward", [spk_x0 - 4, spk_y1 - 4], 3.5, "right");
    cap("FFC bridge", [bx0 - bridge_leg - tab_len - 6, bridge_ys[0] + 6], 3.5);
    cap("lead notch", [bx_l - rib_w, by_t + rib_w + 1.5], 3);
    cap("battery: fixed lip on the rail side, snap fingers opposite", [bx_l - rib_w - 4, batt_cy - 16], 3.5, "right");
    cap("corner run, one screw", [button_x + button_gap/2 - 4, y_in + 4], 3.5, "right");
    cap("turn buttons at 1.5\" and 8.5\"; the backing's ribbon cut-out 2\" to 8\"; nothing lies within 1\" of this edge", [-190, 18], 3.5);
  }
}
module cap(txt, at, size = 4, align = "left") { translate(at) text(txt, size = size, halign = align, font = "Liberation Sans"); }

// a 0.4 mm embossed label on a flat top face at height z
module label(txt, x, y, z, rot = 0, size = 3) { translate([x, y, z - eps]) linear_extrude(0.4) rotate(rot) text(txt, size = size, halign = "center", valign = "center", font = "Liberation Sans:style=Bold"); }

// Battery clip coupon: 30 mm of the pocket's cross-section around one finger, ends open so
// the battery slides in sideways, on a 1.2 mm floor that stands in for the backing board
// (the ring is open inside, so without it the two sides are loose pieces). Does the
// battery tilt in under the fixed lip, does the finger snap over it and hold it flat,
// can a thumb release it. Origin at the coupon's bottom-left corner.
module clip_coupon(fl = finger_lip, ft = finger_t, txt = "BATT") {
  fy = batt_cy + finger_ys[0];
  translate([-(bx_l - rib_w), -(fy - 15), 0]) {
    box(bx_l - rib_w, bx_r + rib_w, fy - 15, fy + 15, 0, tab_t);
    translate([0, 0, tab_t]) intersection() {
      union() {
        linear_extrude(web_t) difference() { translate([batt_cx, batt_cy]) rrect(bw + 2*rib_w, bh + 2*rib_w, 3); translate([batt_cx, batt_cy]) rrect(bw, bh, 2); }
        battery_tray(fl, ft);
      }
      box(bx_l - rib_w - 1, bx_r + rib_w + 1, fy - 15, fy + 15, -1, BIG);
    }
    label(txt, bx_r + tray_wall_t + 2.2, fy, tab_t + web_t, 90, 2.6);   // on the ring rib outside the fixed wall
  }
}
clip_w = (bx_r + rib_w) - (bx_l - rib_w);   // a clip coupon's footprint in x; 30 in y
module clip_ladder() {
  for (i = [0 : len(clip_lips) - 1], j = [0 : len(clip_thicks) - 1])
    translate([i * (clip_w + 6), j * 36, 0]) clip_coupon(clip_lips[i], clip_thicks[j], str(clip_lips[i], "/", clip_thicks[j]));
}

// Second-draft coupons: the three new things, before the whole part is reprinted.
module coupons_v2() {
  // 1. battery clip (see clip_coupon)
  translate([10, 0, 0]) clip_coupon();
  // 2. the speaker pocket alone
  translate([-spk_x0 + 70, -(spk_y0 - spk_wall), 0]) { speaker_slot(); label("SPK", spk_cx, spk_y0 + spk_roof_l/2, spk_z_roof + spk_roof_t, 0, 3); }
  // 3. one FFC bridge with its tab and a stub of rib: does the 30 mm bar print, does the FFC slide under
  translate([-(bx0 - bridge_leg - tab_len) + 5, -bridge_ys[0] + 50, 0]) {
    ffc_bridge(bridge_ys[0]);
    tab([bx0 - bridge_leg + 1, bridge_ys[0]], [bx0 - bridge_leg - tab_len, bridge_ys[0]]);
    linear_extrude(web_t) rib([bx1 + bridge_leg - 1, bridge_ys[0]], [bx1 + bridge_leg + 10, bridge_ys[0]]);
    label("FFC", bx0 - bridge_leg - tab_len/2 - 2, bridge_ys[0], tab_t, 0, 3);   // on the tape tab
  }
}
module speaker_coupon() { translate([-spk_x0, -(spk_y0 - spk_wall), 0]) { speaker_slot(); label("SPK", spk_cx, spk_y0 + spk_roof_l/2, spk_z_roof + spk_roof_t, 0, 3); } }

// one short rail with its flange, at a given ledge height and flange width, labelled on top
module rail_coupon(h, fw, len = ladder_len) {
  difference() {
    union() {
      box(x_in, x_wall, 0, len, 0, h + flange_t);
      box(x_in, fw, 0, len, h, h + flange_t);
      translate([(x_in + fw) / 2, len / 2, h + flange_t - eps]) linear_extrude(0.4)
        rotate(90) text(str(h, " ", fw), size = 2.6, halign = "center", valign = "center");
    }
    translate([fw / 2, len / 2, -1]) cylinder(d = screw_d, h = BIG);
  }
}
module rail_ladder() {
  for (i = [0 : len(ladder_heights) - 1], j = [0 : len(ladder_widths) - 1])
    translate([j * 16 + 6, i * (ladder_len + 6), 0]) rail_coupon(ladder_heights[i], ladder_widths[j]);
}

// detail: the battery pocket and the lower FFC bridge, carrier and mock-ups, nothing else
module detail() {
  intersection() {
    union() { color(plate_color) carrier(); battery_mock(); }
    box(-110, 0, 30, 115, -1, BIG);
  }
  color([0.15, 0.15, 0.16]) box(-110, 0, 30, 115, -backing_t, 0);
  color([0.92, 0.92, 0.88]) box(tail_cx - ffc_w/2, tail_cx + ffc_w/2, 30, 115, 0, 0.3);
}

if (part == "assembly" || part == "section") assembly();
else if (part == "coupons_v2") color(plate_color) coupons_v2();
else if (part == "speaker_coupon") color(plate_color) speaker_coupon();
else if (part == "clip_ladder") color(plate_color) clip_ladder();
else if (part == "rail_ladder") color(plate_color) rail_ladder();
else if (part == "carrier") color(plate_color) carrier();
else if (part == "plan") plan();
else if (part == "detail") detail();
