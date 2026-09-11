// =====================================================================
// Electronics carrier — a web of ribs that lies on the back of the
// backing board, is screwed to the frame's second step, and carries the
// ESP32-S3 driver board on its standoffs and the battery.
//
// Seen from BEHIND, bottom-right corner (where the ribbon tail comes out).
// Profile behind the backing board, measured by hand:
//
//   backing board back face ........ z = 0          the web lies on this
//   groove, all four sides ......... ~2 mm tall, centred ~3/16" (4.8) above
//                                    the backing (not used by this design)
//   ledge (second rabbet) .......... 9.0 above the backing; flange 5.5 wide
//                                    (rail ladder, 2026-09-10): the flange sits here
//   opening at the backing ......... same as the backing: 10 1/8" x 12 1/8"
//
// Rails along the right and bottom edges stand from the backing up to the
// ledge and turn outward into a flange that lies on the ledge, with
// countersunk holes for small wood screws — the same step the frame's own
// turn buttons are screwed into. The part drops straight in from behind
// and is screwed down; nothing slides or hooks.
//
// Inside, 4 mm ribs: a ring through the driver board's four holes with a
// counterbored boss at each (the board stands on its 6 mm standoffs,
// screwed from underneath), a tray for the battery with a cross rib the
// velcro strap wraps around, and ties to the rails. The tail area is left
// open: the adapter board and the FFC stay taped to the backing as now.
// The bottom rail has gaps for the tail and for the turn button.
//
//   part = "assembly"  frame corner + backing + carrier + board + battery
//        | "section"   2D cut through the right rail: rail, flange, ledge
//        | "carrier"   the part alone, as printed (bottom on the bed)
//
// Coordinates: x to the right and y up as seen from behind; the opening's
// right wall is x = 0 (wood at x > 0), its bottom wall is y = 0 (wood at
// y < 0); z = 0 is the back face of the backing board.
// =====================================================================

/* [What to render] */
part = "assembly";   // assembly | section | carrier | plan | coupons | rail_ladder
coupon_board_ring = true;   // include the board-ring coupon on the coupon plate

/* [Rail ladder: short rail coupons at every height x flange width, labelled] */
ladder_heights = [8.9, 9.9, 10.9];   // backing to the underside of the flange
ladder_widths  = [5.5, 6.5, 7.5];    // flange, measured out from the opening wall
ladder_len     = 20;

/* [Frame, behind the backing board — measured] */
ledge_z       = 9.0;    // backing to the flange underside: the rail ladder picked 8.9, rounded up
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
far_rail      = false;         // the arm to the 8" window: not needed once the board sits by the right rail
far_seg_len   = 8;             // that rail segment's length; it ends at the cut-out and the screw sits mid-segment
arm_w         = 8;             // the arm along the top of the 1" strip

/* [Rails and flange] */
rail_t     = 3.0;    // rail thickness (stands inside the opening wall)
wall_fit   = 0.3;    // rail clearance to the opening wall
flange_t   = 2.0;    // flange thickness on the ledge
ledge_fit  = 0.5;    // flange stops this short of the moulding beyond the ledge
screw_d    = 2.4;    // #2 wood screw, plain hole: a pan head sits proud on the flange, nothing is above it
flange_countersink = false;   // a 5 mm countersink would cut through both edges of a 3.5 mm flange
screw_head = 5.0;
ext_w      = 150;    // how far the carrier reaches from the right wall
ext_h      = 160;    // how far up from the bottom wall (the board now sits above the battery)

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

/* [Battery — JLJLUP 3000 mAh, 65 x 36 x 10] */
batt_w      = 36;
batt_h      = 65;
batt_t      = 10;
batt_fit    = 1.0;
batt_cx     = -34;
batt_cy     = 72;
tray_wall_h = 5.0;    // low walls around the battery
tray_wall_t = 1.6;
strap_w     = 22;     // the strap passes either side of the cross rib

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

far_x1 = ribbon_to - 0.3;           // far rail segment: from just past the cut-out ...
far_x0 = far_x1 - far_seg_len;      // ... toward the second button
far_sx = (far_x0 + far_x1) / 2;     // its screw, and the arm's post
echo(str("bottom rail: corner run x ", button_x + button_gap/2, "..0; ribbon zone ", ribbon_to, "..", ribbon_from, "; far segment ", far_x0, "..", far_x1, " screw at ", far_sx, " (", -far_sx/25.4, "\")"));
echo(str("board top face ", web_t + standoff_h + board_t, " mm above the backing (standoff foot at ", web_t, ", collar top at ", web_t + socket_h, "); rails ", ledge_z + flange_t, " tall"));

section_y = board_cy - hole_dy/2;   // through the board's lower holes: boss, socket, counterbore
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
  if (far_rail) rail_y(far_x0, far_x1);
}
flange_screws = concat([[ledge_w/2 - ledge_fit/2, 34], [ledge_w/2 - ledge_fit/2, (34 + y_far - 12) / 2],
                        [ledge_w/2 - ledge_fit/2, y_far - 12],
                        [(button_x + button_gap/2) / 2, -(ledge_w/2 - ledge_fit/2)]],
                       far_rail ? [[far_sx, -(ledge_w/2 - ledge_fit/2)]] : []);


// ---------------------------------------------------------------------
// The web
// ---------------------------------------------------------------------
module web2d() {
  // ring through the board's holes
  rib(hole_pts[0], hole_pts[1]); rib(hole_pts[2], hole_pts[3]);   // short sides
  rib(hole_pts[0], hole_pts[2]); rib(hole_pts[1], hole_pts[3]);   // long sides
  // battery tray ring and cross rib
  difference() { translate([batt_cx, batt_cy]) rrect(bw + 2*rib_w, bh + 2*rib_w, 3); translate([batt_cx, batt_cy]) rrect(bw, bh, 2); }
  rib([batt_cx - bw/2, batt_cy], [batt_cx + bw/2, batt_cy]);
  // board ring -> right rail, at both right-hand holes
  for (k = [2, 3]) rib(hole_pts[k], [x_in + 1, hole_pts[k][1]]);
  // board ring -> battery tray, straight down, clear of the FFC's path from the adapter
  rib([board_cx + hole_dx/2 - 6, board_cy - hole_dy/2], [board_cx + hole_dx/2 - 6, batt_cy + bh/2 + rib_w/2]);
  // battery tray -> right rail
  rib([batt_cx + bw/2 + rib_w/2, batt_cy + 20], [x_in + 1, batt_cy + 20]);
  rib([batt_cx + bw/2 + rib_w/2, batt_cy - 20], [x_in + 1, batt_cy - 20]);
  // battery tray -> the corner run of the bottom rail, landing right of the button gap
  rib([batt_cx + bw/2 - 2, batt_cy - bh/2 - rib_w/2], [(button_x + button_gap/2) / 2, y_in - 1]);
  // arm to the far screw (off by default now)
  if (far_rail) {
    rib([board_cx - hole_dx/2, board_cy - hole_dy/2], [far_sx, no_lie_h + 6], arm_w);
    rib([far_sx, no_lie_h + 6], [far_sx, y_in - 1]);
  }
}

// a boss: collar on top with a socket for the standoff foot, counterbore below for the head
module boss_solid(p) { translate([p[0], p[1], 0]) cylinder(d = boss_d, h = web_t + socket_h); }
module boss_cuts(p) translate([p[0], p[1], 0]) {
  translate([0, 0, -1]) cylinder(d = hole_d, h = web_t + socket_h + 2);   // M2 through
  translate([0, 0, -1]) cylinder(d = head_d, h = head_h + 1);             // head, from underneath
  translate([0, 0, web_t]) cylinder(d = socket_d, h = socket_h + 1);      // standoff socket, from the top
}

module carrier() {
  difference() {
    union() {
      // the web, clipped to the opening so no rib end pokes into the wall
      linear_extrude(web_t) intersection() { web2d(); translate([far_x0 - 30, y_wall]) square([-far_x0 + 30 + x_wall, y_far]); }
      for (p = hole_pts) boss_solid(p);
      // battery tray walls, outside the battery footprint, open where the strap passes
      translate([batt_cx, batt_cy, web_t - eps]) linear_extrude(tray_wall_h) difference() {
        rrect(bw + 2*tray_wall_t, bh + 2*tray_wall_t, 2.5); rrect(bw, bh, 2);
        for (sx = [-1, 1]) translate([sx*(bw/2 + tray_wall_t/2), 0]) square([tray_wall_t + 2, strap_w + 4], center = true);
      }
      rails();
    }
    for (p = hole_pts) boss_cuts(p);
    // flange screws, plain holes (countersink optional, see above)
    for (p = flange_screws) translate([p[0], p[1], 0]) {
      translate([0, 0, -1]) cylinder(d = screw_d, h = BIG);
      if (flange_countersink) translate([0, 0, ledge_z + flange_t - 1.2]) cylinder(d1 = screw_d, d2 = screw_head, h = 1.2 + eps);
    }
  }
}

// ---------------------------------------------------------------------
// Mock-ups
// ---------------------------------------------------------------------
module frame_mock() {
  L = 245; T = 145;
  color([0.33, 0.22, 0.14]) clip() difference() {
    union() { box(0, 30, -30, T, -backing_t - 2, frame_back); box(-L, 30, -30, 0, -backing_t - 2, frame_back); }
    box(-BIG, ledge_w, -ledge_w, BIG, ledge_z, BIG);
    box(-BIG, groove_d, -groove_d, BIG, groove_c - groove_h/2, groove_c + groove_h/2);
  }
  color([0.15, 0.15, 0.16]) clip() box(-L, 0, 0, T, -backing_t, 0);
  // turn buttons: tab on the backing, screw into the ledge
  color([0.75, 0.75, 0.78]) clip() for (bx = [button_x, button2_x]) { box(bx - 6, bx + 6, -2, 14, 0, 1); translate([bx, -2, ledge_z]) cylinder(d = 5, h = 2); }
  // the backing's ribbon cut-out, the flex, the adapter and the FFC
  color([0.35, 0.28, 0.2]) clip() box(ribbon_to, ribbon_from, -1, 8, -backing_t, 0.01);
  color([0.85, 0.55, 0.15]) clip() box(ribbon_to + 4, ribbon_from - 4, -6, 6, 0, 0.3);
  color([0.85, 0.55, 0.15]) clip() box(tail_cx - tail_w/2, tail_cx + tail_w/2, -6, 14, 0, 0.3);
  color([0.2, 0.35, 0.7]) clip() box(tail_cx - adapter_w/2, tail_cx + adapter_w/2, 12, 12 + adapter_h, 0, 1.6);
  color([0.92, 0.92, 0.88]) clip() box(tail_cx - 11, tail_cx + 11, 12 + adapter_h, board_cy - board_h/2 + 4, 0, 0.3);
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
module battery_mock() {
  color([0.55, 0.55, 0.6]) clip() translate([batt_cx, batt_cy, web_t]) linear_extrude(batt_t) rrect(batt_w, batt_h, 3);
}
module assembly() { frame_mock(); color(plate_color) clip() carrier(); board_mock(); battery_mock(); }

// plan: the carrier's footprint over the measured no-go zones, true scale
module plan() {
  L = 8.5 * 25.4 + 30;
  color([0.15, 0.15, 0.16]) translate([-L, 0, -3]) cube([L + 0.3, opening_h_in * 25.4, 1]);   // backing board
  color([0.33, 0.22, 0.14]) { translate([0, -30, -3]) cube([30, 400, 1]); translate([-L - 30, -30, -3]) cube([L + 60, 30, 1]); }
  color([0.55, 0.25, 0.2, 0.8]) translate([ribbon_to, 0, -2]) cube([ribbon_from - ribbon_to, 8, 1]);     // ribbon cut-out
  color([0.9, 0.3, 0.3, 0.35]) translate([-L, 0, -2]) cube([L, no_lie_h, 1]);                             // no-lie strip
  color([0.85, 0.55, 0.15]) translate([tail_cx - tail_w/2, -6, -1.5]) cube([tail_w, 20, 1]);              // tail
  color([0.75, 0.75, 0.78]) for (bx = [button_x, button2_x]) translate([bx - 6, -2, -1.5]) cube([12, 16, 1]);  // buttons
  color(plate_color) carrier();
  board_mock(); battery_mock();
}

// Coupons: the parts of the shape that meet the frame, and the hole pattern,
// with almost no plastic. Lay them out flat, bottom-down like the real part.
module coupons() {
  // 1. right-rail coupon: 30 mm of rail + flange + one screw hole
  translate([10, 0, 0]) difference() {
    rail_x(0, 30);
    translate([ledge_w/2 - ledge_fit/2, 15, -1]) cylinder(d = screw_d, h = BIG);
    if (flange_countersink) translate([ledge_w/2 - ledge_fit/2, 15, ledge_z + flange_t - 1.2]) cylinder(d1 = screw_d, d2 = screw_head, h = 1.2 + eps);
  }
  // 2. corner coupon: the corner run and the bottom 30 mm of the right rail, with the corner screw
  translate([60, 0, 0]) difference() {
    union() { rail_x(y_wall, 30); rail_y(button_x + button_gap/2, x_wall); }
    translate([(button_x + button_gap/2) / 2, -(ledge_w/2 - ledge_fit/2), -1]) cylinder(d = screw_d, h = BIG);
    if (flange_countersink) translate([(button_x + button_gap/2) / 2, -(ledge_w/2 - ledge_fit/2), ledge_z + flange_t - 1.2]) cylinder(d1 = screw_d, d2 = screw_head, h = 1.2 + eps);
  }
  // 3. far-window coupon: the 8" segment with its screw and 20 mm of arm and post
  translate([-far_x0 + 110, 0, 0]) difference() {
    union() {
      rail_y(far_x0, far_x1);
      // clipped to the opening like the real web, so the post ends inside the rail
      linear_extrude(web_t) intersection() {
        union() { rib([far_sx, no_lie_h + 6], [far_sx, y_in - 1]); rib([far_sx - 20, no_lie_h + 6], [far_sx, no_lie_h + 6], arm_w); }
        translate([far_x0 - 40, y_wall]) square([60, 60]);
      }
    }
    translate([far_sx, -(ledge_w/2 - ledge_fit/2), -1]) cylinder(d = screw_d, h = BIG);
    if (flange_countersink) translate([far_sx, -(ledge_w/2 - ledge_fit/2), ledge_z + flange_t - 1.2]) cylinder(d1 = screw_d, d2 = screw_head, h = 1.2 + eps);
  }
  // 4. board ring alone: the hole pattern against the real board and standoffs
  if (coupon_board_ring) translate([-board_cx + 40, -board_cy + 60, 0]) difference() {
    union() {
      linear_extrude(web_t) { rib(hole_pts[0], hole_pts[1]); rib(hole_pts[2], hole_pts[3]); rib(hole_pts[0], hole_pts[2]); rib(hole_pts[1], hole_pts[3]); }
      for (p = hole_pts) boss_solid(p);
    }
    for (p = hole_pts) boss_cuts(p);
  }
}

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

if (part == "assembly" || part == "section") assembly();
else if (part == "coupons") color(plate_color) coupons();
else if (part == "rail_ladder") color(plate_color) rail_ladder();
else if (part == "carrier") color(plate_color) carrier();
else if (part == "plan") plan();
