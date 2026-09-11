// =====================================================================
// Picture-frame bezel spacer — Waveshare 13.3" Spectra 6 (E6) panel in a
// 12 1/16" x 10 1/16" rabbet, hung portrait, no glazing.
//
// What it is
// ----------
// A stepped ring that drops into the frame's rabbet in front of the panel:
//
//   front  ┌──────────────┐   face plate: the visible bezel, 45° mat-style
//          │  ┌────────┐  │   bevel on the window edge; overlaps the glass
//   wall ──┤  │ window │  │   so the panel cannot come forward.
//          │  └────────┘  │
//   back   └──────────────┘   pocket wall: fills the gap between the glass
//                              and the rabbet, so the panel cannot slide.
//
// The frame's own lip presses on the face plate; the frame's backing board
// presses everything forward. Nothing grabs the glass: every step of the
// load path is a push. See docs/plans/frame-bezel.md.
//
// The FPC leaves one SHORT edge of the glass (the 208.8 mm edge) in the
// plane of the glass, from its back surface, and must fold 180° behind the
// panel within ~3.4 mm of the glass edge (vendor drawing: "bending area
// R>0.5"). On that edge the pocket wall is simply absent from the back of the
// face plate through to the back of the spacer, outward past the glass by
// fpc_notch_out, over the whole width of the bonded flex.
//
// The rabbet depth was measured with printed coupons (part = "coupons"):
// 4.85 mm from the back of the lip to where the backing board sits. That is
// face + glass + 2.0 mm, and the 2.0 mm behind the glass is where the
// ribbon folds (R > 0.5 needs ~1.4) and where the 1.2 mm fan-out bump sits,
// so both live inside the spacer's depth. The backing board only needs a
// hole where the tail and the driver board are.
//
// Numbers come from the vendor drawing in the 13.3inch e-Paper (E) user
// manual, section 4:  OD 208.80 x 284.70 x 0.85, AA 202.80 x 270.40,
// AA is 3.00 from the glass on three edges and 11.30 on the FPC edge;
// the 60-pin tail is 30.5 wide, 29.75 long, its near edge 40.24 from the
// glass corner; the bonded flex runs ~40 to ~176 mm along that edge; the
// fan-out area on the back near that edge stands up to 1.2 mm proud.
//
//   part = "assembly"   frame + spacer + panel + FPC, viewed from the front
//        | "back"       spacer + panel + FPC only, meant to be viewed from behind
//        | "exploded"   frame, spacer, panel pulled apart along Z
//        | "section"    assembly cut through the FPC tail, half kept
//        | "profile"    a 1 mm slice through the tail, incl. backing board: the true section
//        | "calib"      a 200 mm square, for calibrating an orthographic render
//        | "ring"       the spacer alone, one piece, as installed
//        | "pieces"     the split spacer, face-down, laid out for printing
//        | "piece"      one piece (piece_id), face-down, for STL export
//        | "coupons"    test plate: corner samples at coupon_thicks, a joint pair, a notch slice
//        | "joint"      the dovetail pair alone, well separated, for a fit test
//        | "joints"     fit ladder: one tab half and a socket half per value in joint_fits
//        | "notch"      the ribbon-edge piece from behind with the glass ghosted: the notch area
//
// Frame coordinates: origin at the rabbet centre, X across, Y up, viewer
// at +Z. The spacer's front face is z = 0 and it extends to z = -thick.
// Print parts are mirrored so the front face lies on the bed.
// =====================================================================

/* [What to render] */
part     = "assembly";   // assembly | back | section | ring | pieces | piece
piece_id = 0;            // for part="piece": 0 top-left, 1 top-right, 2 bottom-left, 3 bottom-right (halves: 0 top, 1 bottom)

/* [Frame rabbet — measured, as hung] */
rabbet_w_in = 10.125;    // width of the rabbet opening, inches (first print at 10 1/16 sat 1/16 loose)
rabbet_h_in = 12.125;    // height, inches (same)
rabbet_fit  = 0.6;       // total clearance to the rabbet (0.3 per side)
rabbet_depth_in = 4.85 / 25.4;  // back of the lip to where the backing board sits: measured with coupons, 4.85 mm
outer_r     = 1.0;       // outer corner radius (routed rabbets are rarely dead sharp)
frame_lip   = 5.0;       // mock-up only: how far the moulding overhangs the rabbet
frame_face  = 28;        // mock-up only: moulding width

/* [Panel — vendor drawing] */
panel_w    = 208.8;      // glass, short axis
panel_h    = 284.7;      // glass, long axis (FPC on one end of this axis)
panel_t    = 0.85;
aa_w       = 202.8;
aa_h       = 270.4;
aa_off     = 3.0;        // glass edge to active area, three edges
aa_off_fpc = 11.3;       // glass edge to active area, FPC edge
panel_fit  = 0.6;        // total pocket clearance around the glass
bump_t     = 1.2;        // fan-out area stands this far off the BACK of the glass
bump_w     = 11.0;       // ... over this strip along the FPC edge (mock-up)
fpc_fold_t = 1.8;        // the folded flex stands this far off the back of the glass (mock-up)

/* [FPC — vendor drawing] */
fpc_side       = "bottom";  // bottom | top | left | right : which frame edge the ribbon edge of the glass sits on
fpc_mirror     = false;     // set true if the tail is nearest the OTHER corner of that edge than the mock-up shows
fpc_bond_from  = 35.0;      // bonded flex, along the FPC edge, from the tail-side glass corner (first print: flex flush at 40, so 5 mm more)
fpc_bond_to    = 174.0;     // (first print had ~5 mm spare here)
fpc_tail_from  = 40.24;     // tail near edge from the same corner
fpc_tail_w     = 30.5;
fpc_tail_len   = 29.75;     // beyond the glass edge before folding, i.e. behind the panel after
fpc_notch_out  = 4.5;       // notch reaches this far past the glass edge (bend zone is ~3.4)
fpc_notch_ext  = 4.0;       // notch runs this much past the bonded flex at each end
// The notch is the full wall: from the pocket floor (back of the face plate)
// through to the back of the spacer. The first print stopped it 0.25 mm short
// of the glass back and left a 0.6 mm sliver of wall standing between the
// pocket and the recess, which served nothing.

/* [Bezel] */
face_t         = 2.0;    // visible face plate thickness
image_hidden   = 1.0;    // image lost under the lip, per edge (lip = dead border + this)
bevel          = 1.6;    // 45° bevel on the window edge, measured into the face (< face_t)
pocket_clear_z = 0.3;    // depth float for the glass behind the face plate
back_t         = 1.7;    // body behind that: fills the rabbet to 4.85 and gives the fold its room

/* [Panel placement] */
centre_on      = "active";  // active | glass : what sits centred in the rabbet
centre_bias    = 1.0;       // mm to move the glass back toward the rabbet centre from the "active" position (buys FPC-side wall)

/* [Split for printing] */
split          = "quarters";  // none | halves | quarters
joint_top_x    = 0;      // joint position along the top edge (frame X)
joint_bottom_x = -88;    // along the bottom edge — kept clear of the FPC notch
joint_side_y   = 0;      // joint position on the left and right edges (frame Y); halves split here too
tab_depth      = 8;
tab_neck       = 7;
tab_head       = 10;
// Fit values below were dialled in by test print on one printer in PETG.
// Another material or printer will land elsewhere: PLA shrinks less, so
// -0.05 may be tight; ABS/ASA shrink more, so it may be loose. Print
// part = "joints" first and set tab_fit to the socket that seats with light
// friction. The same goes for rabbet_fit and panel_fit, less critically.
tab_fit        = -0.05;  // PETG, this printer: 0.15 and 0.05 loose, -0.05 right
plate_gap      = 8;      // spacing between pieces in the print layout

/* [Sample coupons] */
coupon_thicks  = [4.85, 4.95, 5.05, 5.15, 5.25, 5.35];  // total thickness ladder (first set 2.9..3.35 left 1.6 mm short of the rabbet floor at 3.35)
coupon_size    = 40;                       // corner coupon edge length
coupon_gap     = 8;
coupon_cols    = 3;                        // corners per row on the plate
coupon_extras  = true;                     // also print the joint pair and the notch slice
joint_fits     = [0.10, 0.05, 0.0, -0.05]; // socket clearance ladder for part = "joints" (0.15 was loose in PETG)

/* [Mock-up] */
show_backing   = true;   // in the profile: the frame's backing board with its ribbon-edge cut-out
backing_t      = 3.0;
backing_relief = 40;     // hole in the backing board for the tail and driver board reaches this far up from the glass edge
aa_key         = false;  // paint the active area magenta so a real screen image can be keyed in
explode        = 60;     // z separation in the exploded view
spacer_color   = [0.22, 0.23, 0.25];
frame_color    = [0.33, 0.22, 0.14];

/* [Rendering] */
$fa = 2;
$fs = 0.4;
eps = 0.01;

// ---------------------------------------------------------------------
// Derived — internal coordinates put the FPC edge at -Y; the whole model
// is rotated at the end for left/right/top.
// ---------------------------------------------------------------------
in = 25.4;
vertical_fpc = (fpc_side == "bottom" || fpc_side == "top");
Wr = (vertical_fpc ? rabbet_w_in : rabbet_h_in) * in;   // internal X
Hr = (vertical_fpc ? rabbet_h_in : rabbet_w_in) * in;   // internal Y
Wout = Wr - rabbet_fit;
Hout = Hr - rabbet_fit;

pocket_w = panel_w + panel_fit;
pocket_h = panel_h + panel_fit;
aa_shift = (aa_off_fpc - aa_off) / 2;                    // AA centre is this far from glass centre, away from the FPC
glass_cy = (centre_on == "active") ? -(aa_shift - centre_bias) : 0;
aa_cy    = glass_cy + aa_shift;

win_w = aa_w - 2 * image_hidden;                         // opening at the back of the face plate
win_h = aa_h - 2 * image_hidden;
thick = face_t + panel_t + pocket_clear_z + back_t;
pocket_d = thick - face_t;
rabbet_depth = rabbet_depth_in * in;

glass_bot = glass_cy - panel_h / 2;
glass_top = glass_cy + panel_h / 2;
gap_bot   = Hout / 2 + glass_bot;                        // wall thickness below the glass (before the notch)
gap_top   = Hout / 2 - glass_top;
gap_side  = (Wout - panel_w) / 2;

lip_side = (panel_w - win_w) / 2;                        // face plate overlap onto the glass
lip_top  = glass_top - (aa_cy + win_h / 2);
lip_bot  = (aa_cy - win_h / 2) - glass_bot;

// Along-edge coordinate u (vendor drawing, from the tail-side corner) -> internal X
function ux(u) = fpc_mirror ? (panel_w / 2 - u) : (-panel_w / 2 + u);
notch_x0 = min(ux(fpc_bond_from - fpc_notch_ext), ux(fpc_bond_to + fpc_notch_ext));
notch_x1 = max(ux(fpc_bond_from - fpc_notch_ext), ux(fpc_bond_to + fpc_notch_ext));
tail_x0  = min(ux(fpc_tail_from), ux(fpc_tail_from + fpc_tail_w));
tail_x1  = max(ux(fpc_tail_from), ux(fpc_tail_from + fpc_tail_w));
tail_cx  = (tail_x0 + tail_x1) / 2;
z_panel_front = -face_t;
z_panel_back  = -face_t - panel_t;

final_rot = (fpc_side == "bottom") ? 0 : (fpc_side == "top") ? 180 : (fpc_side == "right") ? 90 : -90;

echo(str("rabbet ", Wr, " x ", Hr, " mm; spacer outer ", Wout, " x ", Hout, " x ", thick));
echo(str("window (back) ", win_w, " x ", win_h, "; front opening ", win_w + 2*bevel, " x ", win_h + 2*bevel));
echo(str("lip over glass: sides ", lip_side, " top ", lip_top, " fpc ", lip_bot));
echo(str("wall: sides ", gap_side - panel_fit/2, " top ", gap_top - panel_fit/2, " fpc ", gap_bot - panel_fit/2, " (", gap_bot - fpc_notch_out, " left outside the notch)"));
echo(str("visible bezel with ", frame_lip, " mm lip: sides ", gap_side + lip_side - frame_lip + rabbet_fit/2, " top ", gap_top + lip_top - frame_lip + rabbet_fit/2, " fpc ", gap_bot + lip_bot - frame_lip + rabbet_fit/2));
echo(str("notch x ", notch_x0, " .. ", notch_x1, "; tail x ", tail_x0, " .. ", tail_x1));
if (thick > rabbet_depth + 0.05)
  echo(str("WARNING: spacer is ", thick, " thick but the rabbet is only ", rabbet_depth, " deep"));

// ---------------------------------------------------------------------
// Primitives
// ---------------------------------------------------------------------
module rrect(w, h, r) {
  if (r <= 0) square([w, h], center = true);
  else hull() for (sx = [-1, 1], sy = [-1, 1])
    translate([sx * (w/2 - r), sy * (h/2 - r)]) circle(r = r);
}
module box(x0, x1, y0, y1, z0, z1) {
  translate([min(x0,x1), min(y0,y1), min(z0,z1)])
    cube([abs(x1-x0), abs(y1-y0), abs(z1-z0)]);
}

// ---------------------------------------------------------------------
// The spacer ring, internal coordinates, as installed (front face z=0)
// ---------------------------------------------------------------------
module fpc_notch(ft = face_t, th = thick) {
  // inner end reaches 1 mm INTO the pocket so the two cuts merge; the first
  // print had this sign wrong and left a 1 mm wall between pocket and notch
  box(notch_x0, notch_x1,
      glass_bot + 1, glass_bot - fpc_notch_out,
      -th - 1, -ft + eps);
}

// ft = face plate thickness, th = total; defaults are the real part
module ring(ft = face_t, th = thick) {
  bv = min(bevel, ft - 0.4);
  difference() {
    translate([0, 0, -th]) linear_extrude(th) rrect(Wout, Hout, outer_r);
    // panel pocket, open to the back
    translate([0, glass_cy, -th - 1])
      linear_extrude(th - ft + 1) square([pocket_w, pocket_h], center = true);
    // window
    translate([0, aa_cy, -ft - 1])
      linear_extrude(ft + 2) square([win_w, win_h], center = true);
    // mat-style bevel: wider at the front face
    hull() {
      translate([0, aa_cy, -bv]) linear_extrude(eps) square([win_w, win_h], center = true);
      translate([0, aa_cy, 0]) linear_extrude(1) square([win_w + 2*bv, win_h + 2*bv], center = true);
    }
    fpc_notch(ft, th);
  }
}

// ---------------------------------------------------------------------
// Coupons: small samples to try in the real frame before printing 300 mm
// of PETG. Corner coupons drop into the top-left rabbet corner; put the
// backing board on and feel which thickness the turn buttons close on.
// ---------------------------------------------------------------------
function coupon_face(th) = min(face_t, th - panel_t - pocket_clear_z);

module corner_coupon(th) {
  ft = coupon_face(th);
  mirror([0, 0, 1]) intersection() {
    ring(ft, th);
    box(-BIG, -Wout/2 + coupon_size, Hout/2 - coupon_size, BIG, -BIG, BIG);
  }
  // thickness embossed on the back (up, when printed face-down), on the side wall
  translate([-Wout/2 + gap_side/2 + 1, Hout/2 - coupon_size + 4, th - eps])
    linear_extrude(0.4) rotate(90) text(str(th), size = 5, halign = "left", valign = "center");
}

module joint_coupon(sep = coupon_gap) {
  for (i = [0, 1])
    translate([i == 0 ? -sep/2 : sep/2, 0, 0])
      mirror([0, 0, 1]) intersection() {
        spacer_piece(i);
        box(joint_top_x - 26, joint_top_x + 26, Hout/2 - 30, BIG, -BIG, BIG);
      }
}

// fit ladder: the tab half of the top joint once, and the socket half at each
// clearance in joint_fits, labelled on the back. Try the one tab in every socket.
module tab_half() {
  mirror([0, 0, 1]) intersection() {
    spacer_piece(0);
    box(joint_top_x - 26, joint_top_x + 12, Hout/2 - 30, BIG, -BIG, BIG);
  }
}
module socket_half(fit) {
  mirror([0, 0, 1]) intersection() {
    spacer_piece(1, fit);
    box(joint_top_x, joint_top_x + 26, Hout/2 - 30, BIG, -BIG, BIG);
  }
  translate([joint_top_x + 14, Hout/2 - 8, thick - eps])
    linear_extrude(0.4) text(str(fit), size = 4, halign = "left", valign = "center");
}

module notch_coupon() {
  mirror([0, 0, 1]) intersection() {
    ring();
    box(tail_cx - 25, tail_cx + 25, -BIG, glass_bot + 22, -BIG, BIG);
  }
}

// ---------------------------------------------------------------------
// Splitting. A joint is a dovetail on one piece, the matching socket on
// its neighbour. Tabs live on the leg's material, centred on the wall
// where the wall is wide enough, otherwise on the face plate.
// ---------------------------------------------------------------------
BIG = 1000;

// dovetail pointing +X from x=0, centred on y=0
module dovetail2d(grow = 0) {
  polygon([[-2*grow - (grow > 0 ? 1 : 0), -tab_neck/2 - grow],
           [tab_depth + grow,              -tab_head/2 - grow],
           [tab_depth + grow,               tab_head/2 + grow],
           [-2*grow - (grow > 0 ? 1 : 0),   tab_neck/2 + grow]]);
}

// leg centrelines for the tabs
function leg_centre_top()    = (gap_top - panel_fit/2 >= tab_head + 3)
                                 ? (glass_top + panel_fit/2 + Hout/2) / 2
                                 : (aa_cy + win_h/2 + Hout/2) / 2;
function leg_centre_bottom() = (gap_bot - panel_fit/2 >= tab_head + 3)
                                 ? (glass_bot - panel_fit/2 - Hout/2) / 2
                                 : (aa_cy - win_h/2 - Hout/2) / 2;
function leg_centre_side()   = (pocket_w/2 + Wout/2) / 2;

// joint = [x, y, direction(deg)]: tab points along direction from (x,y)
top_joint    = [joint_top_x,    leg_centre_top(),     0];    // tab from the left piece, points +X
bottom_joint = [joint_bottom_x, leg_centre_bottom(),  0];
left_joint   = [-leg_centre_side(), joint_side_y,    90];    // tab from the bottom piece, points +Y
right_joint  = [ leg_centre_side(), joint_side_y,    90];

module tab3d(j, grow = 0) {
  translate([j[0], j[1], -thick - 1]) linear_extrude(thick + 2)
    rotate(j[2]) dovetail2d(grow);
}

// piece = ring ∩ region, plus its tabs, minus the sockets its neighbours' tabs need
module piece(region_pts, tabs, sockets, fit = tab_fit) {
  difference() {
    intersection() {
      ring();
      union() {
        translate([0, 0, -thick - 1]) linear_extrude(thick + 2) polygon(region_pts);
        for (j = tabs) tab3d(j);
      }
    }
    for (j = sockets) tab3d(j, fit);
  }
}

function rect_pts(x0, x1, y0, y1) = [[x0,y0],[x1,y0],[x1,y1],[x0,y1]];

// region polygons: the split lines are x=joint_top_x above y=joint_side_y,
// x=joint_bottom_x below it, and y=joint_side_y on the sides.
function region(i) =
  split == "quarters" ? (
    i == 0 ? rect_pts(-BIG, joint_top_x,    joint_side_y,  BIG) :
    i == 1 ? rect_pts(joint_top_x,  BIG,    joint_side_y,  BIG) :
    i == 2 ? rect_pts(-BIG, joint_bottom_x, -BIG, joint_side_y) :
             rect_pts(joint_bottom_x, BIG,  -BIG, joint_side_y)) :
  split == "halves" ? (
    i == 0 ? rect_pts(-BIG, BIG, joint_side_y, BIG) :
             rect_pts(-BIG, BIG, -BIG, joint_side_y)) :
  rect_pts(-BIG, BIG, -BIG, BIG);

function tabs(i) =
  split == "quarters" ? (
    i == 0 ? [top_joint] : i == 1 ? [] : i == 2 ? [bottom_joint, left_joint] : [right_joint]) :
  split == "halves" ? (i == 0 ? [] : [left_joint, right_joint]) : [];

function sockets(i) =
  split == "quarters" ? (
    i == 0 ? [left_joint] : i == 1 ? [top_joint, right_joint] : i == 2 ? [] : [bottom_joint]) :
  split == "halves" ? (i == 0 ? [left_joint, right_joint] : []) : [];

n_pieces = split == "quarters" ? 4 : split == "halves" ? 2 : 1;

module spacer_piece(i, fit = tab_fit) { piece(region(i), tabs(i), sockets(i), fit); }

// face-down for printing: front face on z=0, body in +Z
module printable(i) { mirror([0, 0, 1]) spacer_piece(i); }

// spread the pieces apart so they read as separate parts
function spread(i) =
  split == "quarters" ? [ (i % 2 == 0 ? -1 : 1) * plate_gap/2, (i < 2 ? 1 : -1) * plate_gap/2 ] :
  split == "halves"   ? [ 0, (i == 0 ? 1 : -1) * plate_gap/2 ] : [0, 0];

// ---------------------------------------------------------------------
// Mock-up geometry. clip() cuts the section views; it sits inside the
// color() calls because preview drops colours set inside an intersection.
// ---------------------------------------------------------------------
clip_x0 = (part == "profile") ? tail_cx - 0.5 : (part == "section") ? tail_cx : -BIG;
clip_x1 = (part == "profile") ? tail_cx + 0.5 : BIG;
// profile: a true 2D section on the plane x = tail_cx, laid out with the
// frame's front at the top and the frame edge on the left (2D keeps colours)
module clip() {
  if (part == "profile")
    linear_extrude(1) rotate(-90) projection(cut = true)
      rotate([0, -90, 0]) translate([-tail_cx, 0, 0]) children();
  else if (part == "section")
    intersection() { children(); box(clip_x0, clip_x1, -BIG, BIG, -BIG, BIG); }
  else children();
}
module panel_mock() {
  // glass
  color([0.82, 0.84, 0.86, 1]) clip()
    translate([0, glass_cy, z_panel_back]) linear_extrude(panel_t)
      square([panel_w, panel_h], center = true);
  // active area, a hair proud so it renders on top (magenta when keying a real image in)
  color(aa_key ? [1, 0, 1] : [0.97, 0.97, 0.95]) clip()
    translate([0, aa_cy, z_panel_front - 0.02]) linear_extrude(0.03)
      square([aa_w, aa_h], center = true);
  // fan-out strip on the back, FPC edge
  color([0.10, 0.30, 0.16]) clip()
    box(-panel_w/2 + 2, panel_w/2 - 2, glass_bot, glass_bot + bump_w, z_panel_back, z_panel_back - bump_t);
}

module fpc_mock() {
  t = 0.2;
  r = (fpc_fold_t - t) / 2;                    // fold radius (vendor: R > 0.5, bend zone ends ~3.4 past the glass)
  f0 = 1.8;                                    // flat run past the glass before the bend starts
  bond_x0 = min(ux(fpc_bond_from), ux(fpc_bond_to));
  bond_x1 = max(ux(fpc_bond_from), ux(fpc_bond_to));
  color([0.85, 0.55, 0.15]) clip() {
    // bonded flex on the back of the glass, running out past the edge to the fold
    box(bond_x0, bond_x1, glass_bot + 6, glass_bot - f0, z_panel_back, z_panel_back - t);
    // the fold: half a tube, bulging outward (-Y)
    translate([bond_x0, glass_bot - f0, z_panel_back - r])
      rotate([0, 90, 0]) mirror([0, 1, 0])
        rotate_extrude(angle = 180) translate([r - t, 0]) square([t, bond_x1 - bond_x0]);
    // back behind the panel: full width for a few mm, then the tail
    box(bond_x0, bond_x1, glass_bot - f0, glass_bot + 3, z_panel_back - 2*r, z_panel_back - 2*r + t);
    box(tail_x0, tail_x1, glass_bot - f0, glass_bot + fpc_tail_len - 3.4, z_panel_back - 2*r, z_panel_back - 2*r + t);
    // 60-pin fingers
    color([0.9, 0.75, 0.2]) clip()
      box(tail_cx - 14.75, tail_cx + 14.75, glass_bot + fpc_tail_len - 7.4, glass_bot + fpc_tail_len - 3.4,
          z_panel_back - 2*r, z_panel_back - 2*r - 0.05);
  }
}

module frame_mock() {
  sight_w = Wr - 2 * frame_lip;
  sight_h = Hr - 2 * frame_lip;
  color(frame_color) clip() {
    // lip
    difference() {
      linear_extrude(6) rrect(Wr + 2*frame_face, Hr + 2*frame_face, 2);
      translate([0, 0, -1]) linear_extrude(8) square([sight_w, sight_h], center = true);
    }
    // rabbet walls
    difference() {
      translate([0, 0, -rabbet_depth]) linear_extrude(rabbet_depth) rrect(Wr + 2*frame_face, Hr + 2*frame_face, 2);
      translate([0, 0, -rabbet_depth - 1]) linear_extrude(rabbet_depth + 2) square([Wr, Hr], center = true);
    }
  }
}

module backing_mock() {
  zb = -thick;                                  // backing board sits on the spacer's back face
  color([0.55, 0.45, 0.35, 0.55]) clip()
    difference() {
      translate([0, 0, zb - backing_t]) linear_extrude(backing_t) square([Wr - 1, Hr - 1], center = true);
      // hole for the tail and the driver board (the fold itself is inside the spacer's depth)
      box(tail_x0 - 6, tail_x1 + 6, glass_bot - 2, glass_bot + backing_relief, zb + 1, zb - backing_t - 1);
    }
}

module spacer_colored() { color(spacer_color) clip() for (i = [0 : n_pieces - 1]) spacer_piece(i); }

module assembly(with_frame = true, with_backing = false) {
  if (with_frame) frame_mock();
  spacer_colored();
  panel_mock();
  fpc_mock();
  if (with_backing && show_backing) backing_mock();
}

// ---------------------------------------------------------------------
// Dispatch
// ---------------------------------------------------------------------
rotate(final_rot) {
  if (part == "assembly") assembly();
  else if (part == "back") assembly(false, false);
  else if (part == "exploded") {
    translate([0, 0, explode]) frame_mock();
    spacer_colored();
    translate([0, 0, -explode]) { panel_mock(); fpc_mock(); }
  }
  else if (part == "section" || part == "profile") assembly(true, true);   // clip() does the cutting
  else if (part == "calib") color([0, 0, 0]) linear_extrude(1) square(200, center = true);
  else if (part == "ring") color(spacer_color) ring();
  else if (part == "pieces")
    for (i = [0 : n_pieces - 1]) color(i % 2 == 0 ? spacer_color : spacer_color + [0.2, 0.2, 0.2])
      translate(spread(i)) printable(i);
  else if (part == "piece") color(spacer_color) printable(piece_id);
  else if (part == "notch") {
    color(spacer_color) for (i = [0 : n_pieces - 1]) spacer_piece(i);
    color([0.75, 0.80, 0.85, 0.45])
      translate([0, glass_cy, z_panel_back]) linear_extrude(panel_t) square([panel_w, panel_h], center = true);
    fpc_mock();
  }
  else if (part == "joint") color(spacer_color) translate([0, -Hout/2, 0]) joint_coupon(30);
  else if (part == "joints") color(spacer_color) {
    translate([-(joint_top_x - 26), -(Hout/2 - 30), 0]) tab_half();
    for (i = [0 : len(joint_fits) - 1])
      translate([50 - joint_top_x, -(Hout/2 - 30) + i * 34, 0]) socket_half(joint_fits[i]);
  }
  else if (part == "coupons") color(spacer_color) {
    // corner coupons in rows of coupon_cols, thinnest first; then the joint pair and the notch slice
    rows = ceil(len(coupon_thicks) / coupon_cols);
    pitch = coupon_size + coupon_gap;
    for (i = [0 : len(coupon_thicks) - 1])
      translate([Wout/2 + (i % coupon_cols) * pitch, -Hout/2 + floor(i / coupon_cols) * pitch, 0])
        corner_coupon(coupon_thicks[i]);
    if (coupon_extras) {
      translate([30, -Hout/2 - 30 - coupon_gap, 0]) joint_coupon();
      translate([-tail_cx - 25 + 76 + coupon_gap, -glass_bot - 22 - 30 - coupon_gap, 0]) notch_coupon();
    }
  }
}
