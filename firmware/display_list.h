#pragma once
//
// display_list.h — a tiny interpreter for the e-paper display list.
//
// The firmware is a dumb, stable renderer: all layout lives in the JSON, so
// changing the design never needs a reflash. Only the *vocabulary* (fonts,
// icons, ops) is compiled in.
//
// Semantics here are authoritative. The `display_mcp.render` package (the
// preview behind display-mcp-cli and the MCP preview tool) mirrors them;
// where the two disagree, the Python is the bug.
//
// Usage from a display lambda:
//
//     DisplayListAssets a;
//     a.fonts["xl"] = id(font_xl);   // ... etc
//     a.icons["check/sm"] = id(ic_check_sm);
//     a.time = "1:43 PM"; a.time24 = "13:43";   // from the sntp clock, or empty
//     draw_display_list(it, id(dl_body), a);
//
#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include "esphome/components/display/display.h"
#include "esphome/components/font/font.h"
#include "esphome/components/image/image.h"
#include "esphome/components/json/json_util.h"
#include "esphome/core/color.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"

namespace dl {

static const char *const TAG = "display_list";

// The document schema version this firmware implements. `v` is the agreed
// escape hatch for a future breaking change to the compiled vocabulary --
// see docs/plans/ink-mixing.md decision 10 -- so it has to actually be
// checked somewhere or it can never serve that purpose. A mismatch only
// warns and the document still draws: never refuse to draw, a blank or
// stale wall is worse than a slightly-wrong interpretation (see
// draw_display_list).
static const int DOCUMENT_VERSION = 1;

// Device-safety bounds, together: a document field the firmware trusts
// directly as a loop count, a coordinate magnitude or a string length must
// never let an adversarial, or merely wrong, document turn one op into a
// multi-second loop, an out-of-range accumulation or a failed allocation,
// on a panel with no heap to spare and (at kThickMax's original writing) no
// watchdog margin to lose. docs/plans/firmware-bounds.md (D1-D9) is the
// decision record for everything below; docs/plans/wake-sleep-flow.md is
// the sprite-allocation crash that started the audit. Content past any of
// these bounds is skipped with a warning, never drawn wrong and never
// allowed to run long -- CLAUDE.md's "warnings never block a publish" rule
// is what makes skip-not-reject safe here.
//
// Each bound here is mirrored by the same name (kFoo -> FOO) in
// display_mcp.render (mostly render/shapes.py); tests/parity/
// test_limits_and_dispatch.py extracts and diffs every one of them by name.
//
// kThickMax bounds an outline's `t` (line, rect/circle/poly outline):
// thick_line()'s and the rect outline loop's `for (int i = 0; i < t;
// i++)` clamp to it silently; a bad `t` is authoring feedback and stays
// on the Python side (D1).
// kSpriteMaxCell bounds `sprite`'s `cell` so c0*cell/row*cell arithmetic
// can never approach INT32_MAX even for the largest document
// MAX_DOC_BYTES allows; past this bound there is nothing sensible to
// draw, so draw_sprite() rejects the whole op rather than clamping it.
// kMaxCoord (D4) bounds every coordinate and size field of every op --
// x, y, w, h, x2, y2, r, `text`'s `lh`, each poly point, and a sprite's
// pixel box (x + cols*cell, y + rows*cell) -- more than twice the
// 1200x1600 canvas on either axis. It does NOT make every op's cost the
// same: a plain rect fill is clipped to the canvas (D5,
// clipped_filled_rectangle()) and so costs at most the canvas itself
// (~1.92M px); an unclipped filled circle at r == kMaxCoord costs
// ~pi*r^2, ~52.7M px (~2.6s); a rounded rect's four corner circles are
// the same shape at a smaller radius (r <= (min(w,h)-1)/2 <=~2047); a
// sprite whose pixel box spans the full -kMaxCoord..kMaxCoord range on
// both axes costs up to ~8192x8192, ~67M px (~3.4s); a poly outline (D8,
// see thick_line()'s own clip_line_cs()) is clipped to the canvas plus a
// kThickMax margin per segment -- up to kPolyMaxPts edges * kThickMax
// parallel copies * that clipped diagonal (~2000px on the real 1200x1600
// canvas) -- costs the most of any of them, ~87M px (~4.35s); docs/plans/
// firmware-bounds.md's "Review amendments" section has the fuller
// numbers, including how that estimate was checked. The actual safety
// argument is the 20s draw budget (D3) plus every single op finishing
// well under the 30s watchdog (D2), not a
// single uniform per-op ceiling. Supersedes the old `kPolyMaxCoord`
// (1 << 20), which existed only to keep poly_spans()'s int64 crossing
// arithmetic away from overflow -- trivially true at this much smaller
// value, so one name now does both jobs.
// kTextMaxLen bounds `text.s` and `fmt.s` (the template, before expansion):
// past it the whole op is skipped, which is what keeps fit_line()'s
// quadratic cost (~7ms at the bound) and wrap()'s word vector (~6KB at the
// bound) bounded. kTextMaxLines bounds wrapped `lines` the way kThickMax
// bounds `t` -- clamped, not skipped.
// kSpriteMaxCols/kSpriteMaxRows/kSpriteMaxPalette bound the grid a sprite
// can describe; together with kMaxCoord on its pixel box, draw_sprite()'s
// ragged-row walk can never visit more than kSpriteMaxCols * kSpriteMaxRows
// cells.
// kPolyMaxPts bounds how many points a poly's `pts` can push into its own
// vector -- enforced while parsing, so the vector itself never grows past
// it.
static const int kThickMax = 64;
static const int kSpriteMaxCell = 1600;
static const int32_t kMaxCoord = 4096;
static const int kTextMaxLen = 512;
static const int kTextMaxLines = 64;
static const int kSpriteMaxCols = 1200;
static const int kSpriteMaxRows = 1600;
static const int kSpriteMaxPalette = 64;
static const int kPolyMaxPts = 1024;

// D3's backstop: draw_display_list() reads millis() once at entry and
// checks it at the top of every op, stopping (not aborting) the loop once
// this many milliseconds have passed. This is the safety net under the
// per-op bounds above, not a substitute for them -- it protects against
// a *legal* document with simply too many ops, the one shape of slowness
// the per-op bounds can't see. No Python mirror -- there is no device
// clock to mirror against -- see docs/SPEC.md's note on it instead.
static const uint32_t kDrawBudgetMs = 20000;

struct DisplayListAssets {
  // Type scale, keyed by the name the JSON uses: xl, lg, md, sm, xs, mono.
  std::map<std::string, esphome::display::BaseFont *> fonts;
  // Icons keyed "<name>/<size-class>", e.g. "weather-sunny/lg".
  std::map<std::string, esphome::image::Image *> icons;
  // The panel's own clock at draw time, "1:43 PM" and "13:43". Empty when the
  // clock is not valid yet; the fmt op prints "--:--" then.
  std::string time;
  std::string time24;
  // Pack state from the battery ADC, "82%" and "3.9V". Empty when the sensor
  // has no reading yet; the fmt op prints "--%" / "-.-V" then.
  std::string battery;
  std::string battv;
};

// The six inks the panel can actually produce. Anything else is a config bug,
// not something to silently approximate.
inline bool base_color(const std::string &n, esphome::Color &out) {
  if (n == "black") { out = esphome::Color(0, 0, 0); return true; }
  if (n == "white") { out = esphome::Color(255, 255, 255); return true; }
  if (n == "yellow") { out = esphome::Color(255, 255, 0); return true; }
  if (n == "red") { out = esphome::Color(255, 0, 0); return true; }
  if (n == "blue") { out = esphome::Color(0, 0, 255); return true; }
  if (n == "green") { out = esphome::Color(0, 255, 0); return true; }
  return false;
}

// Decision 2 (docs/plans/ink-mixing.md): one 2x2 Bayer mask, three
// densities, absolute (panel-space, never op-relative) phase, so adjacent
// fills reproduce a mixed ground exactly regardless of which op painted it.
//
//     B = | 0 2 |     mix_on(x, y, pct) picks the second ink (c2/b)
//         | 3 1 |     wherever B[y&1][x&1] < pct / 25 (integer division).
//
// Bit-identity check at pct=50 (threshold 2), confirming this matches the
// plain `((px + py) & 1) == 0` checkerboard:
//
//     (x&1,y&1)=(0,0): B=0, 0<2 -> true   | px+py even -> true
//     (x&1,y&1)=(1,0): B=2, 2<2 -> false  | px+py odd  -> false
//     (x&1,y&1)=(0,1): B=3, 3<2 -> false  | px+py odd  -> false
//     (x&1,y&1)=(1,1): B=1, 1<2 -> true   | px+py even -> true
//
// All four phases agree, so mix_on(x, y, 50) == ((x + y) & 1 == 0) exactly.
// At pct=25 (threshold 1) only B==0 survives: one cell in four. At pct=75
// (threshold 3) every cell but B==3 survives: three in four.
static const uint8_t B[2][2] = {{0, 2}, {3, 1}};
inline bool mix_on(int x, int y, int pct) { return B[y & 1][x & 1] < pct / 25; }

/// A resolved ink. `mix` in {25, 50, 75} dithers `a`/`b` by mix_on(); a plain
/// colour is `{a, a, 100}`, so every call site draws through the same path
/// with nothing to branch on (decision 1).
struct Ink {
  esphome::Color a, b;
  int mix;
};

/// The named palette (docs/SPEC.md "The named palette"; docs/plans/
/// ink-mixing.md decision 10): twenty-one tested two-ink mixes, compiled in
/// so `"c": "navy"` resolves with no palette entry in the document at all.
/// Resolution order is base inks -> the document's `palette` -> this table
/// (see resolve_ink/resolve_solid), so a document can still shadow any name
/// here by declaring its own palette entry under the same key.
///
/// This table is diffed against `display_mcp.render`'s copy of it by a
/// differential test that extracts it from the shipped header with a
/// regex, so it has to stay machine-readable: one entry per line, in
/// exactly this `{"name", "c", "c2", mix}` shape, never spread across
/// lines. `c` and `c2` are always base ink names -- never another mix, by
/// construction of this table -- so a lookup here is always a leaf.
struct BuiltinMix { const char *name, *c, *c2; uint8_t mix; };
static const BuiltinMix BUILTIN_MIXES[] = {
    {"navy", "black", "blue", 50},
    {"maroon", "black", "red", 50},
    {"plum", "red", "blue", 50},
    {"forest", "black", "green", 50},
    {"teal", "blue", "green", 50},
    {"brown", "red", "green", 50},
    {"grey-dark", "black", "white", 25},
    {"cream-pale", "yellow", "white", 75},
    {"cream", "yellow", "white", 50},
    {"sage-pale", "green", "white", 75},
    {"slate-pale", "blue", "white", 75},
    {"pink-pale", "red", "white", 75},
    {"grey-light", "black", "white", 75},
    {"sage", "green", "white", 50},
    {"pink", "red", "white", 50},
    {"slate", "blue", "white", 50},
    {"chartreuse", "yellow", "green", 50},
    {"grey-mid", "black", "white", 50},
    {"mustard", "black", "yellow", 50},
    {"orange", "yellow", "red", 50},
    {"olive", "yellow", "blue", 50},
};
static const int N_BUILTIN_MIXES = sizeof(BUILTIN_MIXES) / sizeof(BUILTIN_MIXES[0]);

/// Linear scan of the table above. Only reached once both a base ink name
/// and a document palette lookup have already missed, so the common path
/// (base inks, or a document that supplies its own palette) never pays for
/// this -- and twenty-one short strcmps is cheap even when it is reached,
/// against a ~20 s panel refresh.
inline const BuiltinMix *find_builtin(const std::string &name) {
  for (int i = 0; i < N_BUILTIN_MIXES; i++)
    if (name == BUILTIN_MIXES[i].name)
      return &BUILTIN_MIXES[i];
  return nullptr;
}

/// Build the Ink for a built-in entry. `c`/`c2` are always base ink names
/// (see BuiltinMix above), so this needs no alias chasing or palette --
/// just the same six-name switch every other ink resolves through.
inline Ink resolve_builtin(const BuiltinMix &m) {
  esphome::Color a, b;
  base_color(m.c, a);
  base_color(m.c2, b);
  return Ink{a, b, m.mix};
}

/// Resolve a colour name to a single Color, refusing to land on a palette
/// mix -- used for a mix's own `c`/`c2`, which may not nest ("a mix of
/// mixes is not representable in a 2x2 mask", decision 1). Same alias chain
/// and 8-hop cap as resolve_ink, but a mix found along the way degrades to
/// that entry's own `c` and the walk continues, rather than blending it.
inline esphome::Color resolve_solid(const char *name, JsonObject palette) {
  std::string n = name ? name : "black";
  esphome::Color c;
  for (int hop = 0; hop < 8; hop++) {
    if (base_color(n, c))
      return c;
    if (!palette.isNull()) {
      auto v = palette[n.c_str()];
      if (v.template is<JsonObject>()) {
        ESP_LOGW(TAG, "'%s' is a mix, not a plain colour here; using its base ink", n.c_str());
        n = v.template as<JsonObject>()["c"] | "black";
        continue;
      }
      const char *next = v;
      if (next != nullptr) {
        n = next;
        continue;
      }
    }
    // Base inks and the document's palette both missed this name -- try the
    // built-in table (decision 10's order: base inks -> palette ->
    // built-ins) before giving up. A built-in name is still a mix, so the
    // same "mixes don't nest" rule applies here as to a palette mix object
    // above: degrade to its own base ink and keep chasing, don't blend it.
    const BuiltinMix *bm = find_builtin(n);
    if (bm != nullptr) {
      ESP_LOGW(TAG, "'%s' is a built-in mix, not a plain colour here; using its base ink", n.c_str());
      n = bm->c;
      continue;
    }
    break;
  }
  ESP_LOGW(TAG, "unknown colour '%s', using black", n.c_str());
  return esphome::Color(0, 0, 0);
}

/// Parse a palette object entry ({c, c2, mix}) into an Ink. `name` is the
/// palette key it was found under, for warnings. Every case here is pinned
/// down in docs/plans/ink-mixing.md decision 1's schema table -- the Python
/// renderer implements the same contract independently, so nothing here is
/// left to whichever side was written first.
inline Ink resolve_mix_entry(const char *name, JsonObject entry, JsonObject palette) {
  const char *c_name = entry["c"] | "black";
  const esphome::Color a = resolve_solid(c_name, palette);

  const char *c2_name = entry["c2"];
  if (c2_name == nullptr || !strcmp(c2_name, c_name)) {
    // c2 missing, or equal to c: not a mix (decision 1).
    ESP_LOGW(TAG, "palette '%s' has no distinct c2, drawing solid", name);
    return Ink{a, a, 100};
  }
  const esphome::Color b = resolve_solid(c2_name, palette);

  auto mv = entry["mix"];
  int pct = 50;
  if (!mv.isNull()) {
    if (!mv.template is<int>() && !mv.template is<float>()) {
      ESP_LOGW(TAG, "palette '%s' mix is not a number, using 50", name);
    } else {
      const float f = mv.template as<float>();
      if (f < 0 || f > 100) {
        ESP_LOGW(TAG, "palette '%s' mix %.0f out of range, using 50", name, f);
      } else {
        pct = static_cast<int>(f + 0.5f);
        if (pct != 25 && pct != 50 && pct != 75) {
          const int rounded = pct <= 37 ? 25 : (pct <= 62 ? 50 : 75);
          ESP_LOGW(TAG, "palette '%s' mix %d rounds to %d", name, pct, rounded);
          pct = rounded;
        }
      }
    }
  }
  return Ink{a, b, pct};
}

// Resolve through the document's palette aliases, with a depth cap so a
// self-referential palette can't hang the render. A palette entry is either
// a plain alias string (as before) or a mix object, in which case the whole
// thing resolves through resolve_mix_entry instead of chasing further
// aliases -- a mix is always a leaf.
inline Ink resolve_ink(const char *name, JsonObject palette) {
  std::string n = name ? name : "black";
  esphome::Color c;
  for (int hop = 0; hop < 8; hop++) {
    if (base_color(n, c))
      return Ink{c, c, 100};
    if (!palette.isNull()) {
      auto v = palette[n.c_str()];
      if (v.template is<JsonObject>())
        return resolve_mix_entry(n.c_str(), v.template as<JsonObject>(), palette);
      const char *next = v;
      if (next != nullptr) {
        n = next;
        continue;
      }
    }
    // Base inks and the document's palette both missed this name -- fall
    // through to the built-in named table (decision 10). A document that
    // declares its own palette entry under the same key already returned
    // above, so this is only reached for a name the document never
    // mentions, which is exactly the "no palette entry needed" case the
    // built-in table exists for.
    const BuiltinMix *bm = find_builtin(n);
    if (bm != nullptr)
      return resolve_builtin(*bm);
    break;
  }
  ESP_LOGW(TAG, "unknown colour '%s', using black", name ? name : "(null)");
  return Ink{esphome::Color(0, 0, 0), esphome::Color(0, 0, 0), 100};
}

inline int measure_w(esphome::display::BaseFont *f, const std::string &s) {
  int w = 0, xo = 0, bl = 0, h = 0;
  f->measure(s.c_str(), &w, &xo, &bl, &h);
  return w;
}

inline int font_height(esphome::display::BaseFont *f) {
  int w = 0, xo = 0, bl = 0, h = 0;
  f->measure("Ag", &w, &xo, &bl, &h);
  return h;
}

// Step back to the previous UTF-8 boundary so truncation never splits a
// codepoint — otherwise a clipped "—" or "°" renders as garbage.
inline size_t utf8_prev(const std::string &s, size_t i) {
  if (i == 0)
    return 0;
  i--;
  while (i > 0 && (static_cast<unsigned char>(s[i]) & 0xC0) == 0x80)
    i--;
  return i;
}

// The forward twin of utf8_prev: advance one codepoint from a UTF-8 byte
// index -- skip the lead byte, then any `10xxxxxx` continuation bytes. The
// sprite op walks a row this way, one grid cell per *character*, not per
// byte -- otherwise a multibyte cell character (a box-drawing glyph, say)
// draws as several narrow cells here while the Python, whose strings are
// already codepoints, draws one.
inline size_t utf8_next(const std::string &s, size_t i) {
  if (i >= s.size())
    return s.size();
  i++;
  while (i < s.size() && (static_cast<unsigned char>(s[i]) & 0xC0) == 0x80)
    i++;
  return i;
}

/// Shorten to fit max_w, appending an ellipsis. Returns s unchanged if it fits.
inline std::string fit_line(esphome::display::BaseFont *f, const std::string &s, int max_w) {
  if (max_w <= 0 || measure_w(f, s) <= max_w)
    return s;
  static const char *ELL = "\xE2\x80\xA6";  // U+2026
  size_t cut = s.size();
  while (cut > 0) {
    cut = utf8_prev(s, cut);
    std::string cand = s.substr(0, cut);
    while (!cand.empty() && cand.back() == ' ')
      cand.pop_back();
    if (measure_w(f, cand + ELL) <= max_w)
      return cand + ELL;
  }
  return ELL;
}

/// Greedy word wrap to at most max_lines; the last line is ellipsized if the
/// text runs past it.
inline std::vector<std::string> wrap(esphome::display::BaseFont *f, const std::string &s, int max_w,
                                     int max_lines) {
  std::vector<std::string> words, lines;
  size_t start = 0;
  while (start <= s.size()) {
    size_t sp = s.find(' ', start);
    if (sp == std::string::npos) {
      if (start < s.size())
        words.push_back(s.substr(start));
      break;
    }
    if (sp > start)
      words.push_back(s.substr(start, sp - start));
    start = sp + 1;
  }

  std::string cur;
  size_t used = 0;
  for (size_t i = 0; i < words.size(); i++) {
    std::string trial = cur.empty() ? words[i] : cur + " " + words[i];
    if (cur.empty() || measure_w(f, trial) <= max_w) {
      cur = trial;
      used = i + 1;
    } else {
      lines.push_back(cur);
      cur = words[i];
      used = i + 1;
      if (static_cast<int>(lines.size()) == max_lines)
        break;
    }
  }
  if (static_cast<int>(lines.size()) < max_lines && !cur.empty())
    lines.push_back(cur);

  // Anything left over gets folded into the final line and ellipsized.
  if (static_cast<int>(lines.size()) == max_lines && used < words.size()) {
    std::string tail = lines.back();
    for (size_t i = used; i < words.size(); i++)
      tail += " " + words[i];
    lines.back() = fit_line(f, tail, max_w);
  }
  // A single word longer than the box would otherwise escape unclipped.
  for (auto &l : lines)
    l = fit_line(f, l, max_w);
  return lines;
}

inline esphome::display::TextAlign align_of(const char *a) {
  std::string s = a ? a : "left";
  if (s == "center")
    return esphome::display::TextAlign::TOP_CENTER;
  if (s == "right")
    return esphome::display::TextAlign::TOP_RIGHT;
  return esphome::display::TextAlign::TOP_LEFT;
}

// Sign-correct floor division: C++'s `/` truncates toward zero, but both
// clip_line_cs() below and the even-odd scanline fill further down
// (poly_spans(), docs/plans/dragon-feedback.md D12) need a genuine floor
// so an intersection with a negative numerator or denominator lands on
// the integer both sides agree on. Python's `//` is already floor
// division, so display_mcp.render's mirrors (_clip_line_cs(),
// _poly_spans()) need no helper of their own to match this. Defined here,
// ahead of its first use, rather than left where poly_spans() alone
// needed it.
inline int64_t floor_div(int64_t a, int64_t b) {
  const int64_t q = a / b;
  const int64_t r = a % b;
  return (r != 0 && ((r < 0) != (b < 0))) ? q - 1 : q;
}

// Cohen-Sutherland outcodes for clip_line_cs() below -- which side(s) of
// [xmin,xmax] x [ymin,ymax] a point falls outside on, ORed together (a
// corner point carries two bits).
enum { kCsInside = 0, kCsLeft = 1, kCsRight = 2, kCsBottom = 4, kCsTop = 8 };

inline int cs_outcode(int x, int y, int xmin, int ymin, int xmax, int ymax) {
  int code = kCsInside;
  if (x < xmin)
    code |= kCsLeft;
  else if (x > xmax)
    code |= kCsRight;
  if (y < ymin)
    code |= kCsBottom;
  else if (y > ymax)
    code |= kCsTop;
  return code;
}

/// Cohen-Sutherland line clipping: `(x1,y1)-(x2,y2)` clipped in place to
/// `[xmin,xmax] x [ymin,ymax]` (inclusive). Returns false when the segment
/// misses the rectangle entirely -- draw nothing -- true otherwise, with
/// the endpoints updated to the clipped segment (docs/plans/
/// firmware-bounds.md D4's review amendment).
///
/// This is what keeps thick_line() -- and through it, `line` and `poly`'s
/// outline -- from ever walking a Bresenham line longer than the clip
/// rectangle's own diagonal, however far apart its true endpoints are (up
/// to `2 * kMaxCoord` on a side): without it, a `poly` outline alone could
/// reach `kPolyMaxPts` edges * `kThickMax` parallel copies * a diagonal of
/// millions of pixels, hundreds of millions of pixel writes, well past the
/// watchdog on its own. `line`/`rect` outlines are already documented as
/// eyeball, not pixel, parity with the Python (docs/SPEC.md); moving a
/// clipped endpoint onto the rectangle's own boundary can shift a
/// boundary pixel by one from what an *unclipped* walk would have drawn,
/// which is within that same accepted tolerance -- the two only ever draw
/// the identical segment to the unclipped walk when it doesn't reach the
/// clip rectangle at all, which is the common case for anything actually
/// meant to land on the panel.
///
/// The four intersection expressions use floor_div(), not `/` -- `/`
/// truncates toward zero, and for an edge crossing the clip boundary with
/// a negative numerator or denominator that can round to a different
/// integer than a true floor, which is what `_clip_line_cs()`'s Python
/// mirror already computes (its `//` is a genuine floor). Without
/// floor_div() here, the two implementations disagreed on which pixel a
/// clipped endpoint lands on for a real fraction of off-canvas edges --
/// confirmed by brute force, not assumed -- which would have made
/// `poly`'s outline, the one shape in this file held to pixel-exact
/// parity rather than eyeball parity, wrong exactly where this clip
/// engages.
inline bool clip_line_cs(int &x1, int &y1, int &x2, int &y2, int xmin, int ymin, int xmax,
                         int ymax) {
  int code1 = cs_outcode(x1, y1, xmin, ymin, xmax, ymax);
  int code2 = cs_outcode(x2, y2, xmin, ymin, xmax, ymax);
  while (true) {
    if (!(code1 | code2))
      return true;  // both endpoints inside
    if (code1 & code2)
      return false;  // both outside on the same side -- trivially rejected
    const int code_out = code1 ? code1 : code2;
    int x = 0, y = 0;
    // floor_div(), not `/`: `/` truncates toward zero, and for an edge
    // that crosses the clip boundary with a negative numerator or
    // denominator that lands the intersection on a different integer
    // than a genuine floor would -- confirmed by brute force over legal
    // edges against the production clip box, ~11.5% of off-canvas edges
    // clipped to an endpoint one row/column away from a floor-consistent
    // clip, 369 of them drawing a visibly different pixel set from the
    // Python mirror (docs/plans/firmware-bounds.md's review amendments).
    // int64_t throughout since the products can exceed INT32_MAX even at
    // this clip box's modest size.
    if (code_out & kCsTop) {
      x = x1 + static_cast<int>(floor_div(static_cast<int64_t>(x2 - x1) * (ymax - y1), y2 - y1));
      y = ymax;
    } else if (code_out & kCsBottom) {
      x = x1 + static_cast<int>(floor_div(static_cast<int64_t>(x2 - x1) * (ymin - y1), y2 - y1));
      y = ymin;
    } else if (code_out & kCsRight) {
      y = y1 + static_cast<int>(floor_div(static_cast<int64_t>(y2 - y1) * (xmax - x1), x2 - x1));
      x = xmax;
    } else {  // kCsLeft
      y = y1 + static_cast<int>(floor_div(static_cast<int64_t>(y2 - y1) * (xmin - x1), x2 - x1));
      x = xmin;
    }
    if (code_out == code1) {
      x1 = x;
      y1 = y;
      code1 = cs_outcode(x1, y1, xmin, ymin, xmax, ymax);
    } else {
      x2 = x;
      y2 = y;
      code2 = cs_outcode(x2, y2, xmin, ymin, xmax, ymax);
    }
  }
}

inline void thick_line(esphome::display::Display &it, int x1, int y1, int x2, int y2, int t,
                       esphome::Color c) {
  if (t > kThickMax)
    t = kThickMax;
  // Every segment drawn below is clipped to the canvas expanded by
  // kThickMax on every side before it reaches Bresenham (docs/plans/
  // firmware-bounds.md D4's review amendment; see clip_line_cs() for why
  // this is safe under the existing eyeball-parity rule for line
  // outlines). The margin, not a flush clip to the canvas itself, is what
  // keeps a thick line's parallel copies -- each shifted by up to t-1 px
  // -- from coming up short right at the edge after their own shift.
  const int margin = kThickMax;
  const int xmin = -margin, ymin = -margin;
  const int xmax = it.get_width() - 1 + margin, ymax = it.get_height() - 1 + margin;
  auto clipped_line = [&](int lx1, int ly1, int lx2, int ly2) {
    if (clip_line_cs(lx1, ly1, lx2, ly2, xmin, ymin, xmax, ymax))
      it.line(lx1, ly1, lx2, ly2, c);
  };
  if (t <= 1) {
    clipped_line(x1, y1, x2, y2);
    return;
  }
  const bool vertical = (x1 == x2);
  const bool horizontal = (y1 == y2);
  for (int i = 0; i < t; i++) {
    if (vertical)
      clipped_line(x1 + i, y1, x2 + i, y2);
    else if (horizontal)
      clipped_line(x1, y1 + i, x2, y2 + i);
    else
      clipped_line(x1, y1 + i, x2, y2 + i);  // diagonals thicken vertically only
  }
}

/// Row half-widths of a `filled_circle()` of the given `radius`, indexed by
/// `|dy|` from 0 to `radius` -- the exact rows esphome::display::Display::
/// filled_circle()'s own midpoint loop draws, recorded here instead of
/// drawn, so a ring built from this table shares filled_circle()'s outer
/// boundary pixel for pixel rather than a hand-derived circle equation that
/// could disagree with it here and there. `radius` must be >= 0.
///
/// `-1` means "this row is never drawn at this radius" -- not the same as
/// a width of 0 (a single centre pixel). At `radius == 1` the midpoint loop
/// only ever visits `dy == 0`: it draws one 3px row and nothing at
/// `|dy| == 1`, a real quirk of the algorithm (verified against the actual
/// filled_circle(), not assumed), so `half[1]` has to say "nothing here",
/// not "one pixel here" -- the caller would otherwise ink a centre dot
/// filled_circle() itself never draws.
inline void circle_half_widths(int radius, std::vector<int> &half) {
  half.assign(radius + 1, -1);
  int dx = -radius, dy = 0, err = 2 - 2 * radius, e2;
  do {
    const int w = -dx;
    if (w > half[dy])
      half[dy] = w;
    e2 = err;
    if (e2 < dy) {
      err += ++dy * 2 + 1;
      if (-dx == dy && e2 <= dx)
        e2 = 0;
    }
    if (e2 > dx)
      err += ++dx * 2 + 1;
  } while (dx <= 0);
}

/// The annulus `filled_circle(cx, cy, r)` minus `filled_circle(cx, cy,
/// r - t)`, drawn through `it` as two horizontal runs per row (via
/// filled_rectangle(), height 1 -- the same primitive draw_poly() fills its
/// spans with) rather than `t` concentric circle() outlines, which leave
/// single-pixel background holes near the 45-degree diagonals from `t == 2`
/// up: consecutive midpoint circles' octant boundaries don't land on the
/// same pixels. `t <= 1` is the caller's
/// job, not this function's -- see the `circle` branch below, which keeps
/// calling circle() directly for `t == 1` rather than routing a one-row
/// annulus through here. `r < 0` draws nothing.
///
/// `r` is bound-checked here too (docs/plans/firmware-bounds.md D4's
/// review amendment), not only relied on from the op loop's own `circle: r
/// out of range` check: this function has its own harness
/// (tests/parity/test_rect_circle.py) that calls it directly, bypassing
/// the loop entirely, and circle_half_widths() below allocates two
/// `(radius + 1)`-int vectors -- unbounded, that is two vectors sized to
/// whatever `r` a caller hands it, not merely slow.
inline void draw_circle_ring(esphome::display::Display &it, int cx, int cy, int r, int t,
                             esphome::Color c) {
  if (r < 0 || r > kMaxCoord)
    return;
  std::vector<int> outer;
  circle_half_widths(r, outer);
  const int inner_r = r - t;
  std::vector<int> inner;
  if (inner_r >= 0)
    circle_half_widths(inner_r, inner);
  for (int dy = -r; dy <= r; dy++) {
    const int ady = dy < 0 ? -dy : dy;
    const int ow = outer[ady];
    if (ow < 0)
      continue;  // filled_circle(r) itself draws nothing on this row
    const int y = cy + dy;
    if (inner_r >= 0 && ady <= inner_r && inner[ady] >= 0) {
      const int iw = inner[ady];
      const int run = ow - iw;
      if (run > 0) {
        it.filled_rectangle(cx - ow, y, run, 1, c);
        it.filled_rectangle(cx + iw + 1, y, run, 1, c);
      }
    } else {
      it.filled_rectangle(cx - ow, y, 2 * ow + 1, 1, c);
    }
  }
}

/// Clip a span `[x, x+w)` to `[0, bound)` (docs/plans/firmware-bounds.md
/// D5): `x`/`w` are updated in place; `w` comes back `<= 0` when the span
/// does not intersect `[0, bound)` at all, which the caller treats as
/// "draw nothing on this axis".
inline void clip_span(int &x, int &w, int bound) {
  if (x < 0) {
    w += x;
    x = 0;
  }
  if (x + w > bound)
    w = bound - x;
}

/// `filled_rectangle()`, clipped to `it`'s own canvas first (D5): a fill
/// (and the Bayer mix a mixed one dithers through) is purely position-based,
/// so painting only the box's intersection with `[0, width) x [0, height)`
/// draws pixel-identical output to painting the whole box and letting
/// draw_pixel_at's own bounds check silently drop what falls outside -- just
/// far cheaper once a box reaches well off canvas, which D4 alone still
/// allows up to kMaxCoord on a side. Draws nothing if the box misses the
/// canvas entirely on either axis.
inline void clipped_filled_rectangle(esphome::display::Display &it, int x, int y, int w, int h,
                                     esphome::Color c) {
  clip_span(x, w, it.get_width());
  clip_span(y, h, it.get_height());
  if (w > 0 && h > 0)
    it.filled_rectangle(x, y, w, h, c);
}

/// A filled rect, rounded at the corners when `r > 0`
/// (docs/plans/dragon-feedback.md D10): the middle band, the two side
/// bands and four filled circles, all through the caller's own `mix` (the
/// same proxy a plain fill uses), so a mixed rounded rect still dithers at
/// one absolute phase rather than seven independent draws that could show
/// a seam. `filled_rectangle(x, y, w, h)` covers `[x, x+w) x [y, y+h)`;
/// `filled_circle` is centred on the given pixel. Eyeball, not pixel,
/// parity with the Python's PIL ellipse -- see render/shapes.py's
/// `_draw_rounded_rect()` for which pixels may differ.
///
/// The plain fill (`r <= 0`) and each of the rounded fill's straight bands
/// go through `clipped_filled_rectangle()` (D5), so a box that straddles
/// or sits well off the canvas costs no more than the visible canvas
/// itself. The four corner circles are left as plain `filled_circle()`
/// calls -- D4 alone already bounds a filled circle's cost to `O(r^2) <=
/// kMaxCoord^2`, which is fine on its own (docs/plans/firmware-bounds.md).
///
/// `r <= 0` draws a plain fill and nothing else. The caller is expected to
/// have already clamped `r` to `(min(w, h) - 1) / 2` -- this function
/// trusts that bound rather than re-deriving it, since the op loop is the
/// only caller and already has `w`/`h` in scope to do it with.
inline void draw_rounded_rect(esphome::display::Display &mix, int x, int y, int w, int h, int r,
                               esphome::Color c) {
  if (r <= 0) {
    clipped_filled_rectangle(mix, x, y, w, h, c);
    return;
  }
  if (w - 2 * r > 0)
    clipped_filled_rectangle(mix, x + r, y, w - 2 * r, h, c);
  if (h - 2 * r > 0) {
    clipped_filled_rectangle(mix, x, y + r, r, h - 2 * r, c);
    clipped_filled_rectangle(mix, x + w - r, y + r, r, h - 2 * r, c);
  }
  mix.filled_circle(x + r, y + r, r, c);
  mix.filled_circle(x + w - 1 - r, y + r, r, c);
  mix.filled_circle(x + r, y + h - 1 - r, r, c);
  mix.filled_circle(x + w - 1 - r, y + h - 1 - r, r, c);
}

/// A proxy `display::Display` that dithers by rewriting colour inside
/// draw_pixel_at() (decision 6). `line`, `rectangle`, `filled_rectangle`,
/// `circle`, `filled_circle` and `image` are non-virtual members of Display
/// that call `this->draw_pixel_at`, and so does the font's glyph loop via
/// `print()` -- so invoking any of them *on* this proxy dithers rect, line,
/// circle, text, fmt and icon uniformly, with no separate fill-then-overlay
/// path for shapes and glyphs.
///
/// Up to two inks can be registered, each keyed by the literal Color a call
/// site draws with (conventionally that ink's own `a`) -- one ink covers
/// rect/line/circle/text/fmt, two covers icon's color_on/color_off. A colour
/// that matches no registered key passes through unchanged, which keeps an
/// opaque icon's untouched half sane when only one side is mixed.
///
/// Subclasses `display::Display`, not `DisplayBuffer` -- the latter adds a
/// pure `draw_absolute_pixel_internal` this proxy has no use for. It is
/// never registered with `App` and never polled (`update()` is a stub to
/// satisfy PollingComponent's pure virtual), and it never touches its own
/// clipping or rotation: draw_pixel_at forwards raw (x, y) into the real
/// display's own DisplayBuffer::draw_pixel_at, which is what actually
/// applies the panel's clipping and rotation.
class MixDisplay : public esphome::display::Display {
 public:
  explicit MixDisplay(esphome::display::Display &real) : real_(real) {}

  void add_ink(esphome::Color key, Ink ink) {
    if (n_ < 2) {
      keys_[n_] = key;
      inks_[n_] = ink;
      n_++;
    }
  }

  void draw_pixel_at(int x, int y, esphome::Color color) override {
    for (int i = 0; i < n_; i++) {
      if (keys_[i] == color) {
        real_.draw_pixel_at(x, y, mix_on(x, y, inks_[i].mix) ? inks_[i].b : inks_[i].a);
        return;
      }
    }
    real_.draw_pixel_at(x, y, color);  // unregistered colour: pass through
  }

  int get_width() override { return real_.get_width(); }
  int get_height() override { return real_.get_height(); }

  // fill() is the one primitive that does NOT reach draw_pixel_at on the
  // real panel -- EpaperSpectra6133 overrides it with a framebuffer memset
  // -- so it can't be dithered through this proxy; a mixed bg is handled at
  // the call site instead (fill the base ink, then overlay the second).
  // Both fill() and clear() must forward straight to the real display
  // rather than fall through to Display's own fill() -> filled_rectangle()
  // -> draw_pixel_at loop, which would paint the whole panel (~1.92M
  // pixels) one pixel at a time.
  void fill(esphome::Color color) override { real_.fill(color); }
  void clear() override { real_.clear(); }

  esphome::display::DisplayType get_display_type() override { return real_.get_display_type(); }
  void update() override {}  // never polled: nothing self-registers this with App

 protected:
  int get_width_internal() override { return real_.get_width(); }
  int get_height_internal() override { return real_.get_height(); }

 private:
  esphome::display::Display &real_;
  esphome::Color keys_[2]{};
  Ink inks_[2]{};
  int n_ = 0;
};

/// Pixel art as rows of characters (docs/plans/dragon-feedback.md D9).
/// Each row string is one grid row, one
/// `cell`x`cell` square per *character* -- walked with utf8_next, not
/// strlen, so a multibyte character is one cell -- coloured by `palette`,
/// keyed on the full UTF-8 sequence rather than a single byte. `.` and
/// space are always transparent. A run of equal characters draws as one
/// filled_rectangle through its own MixDisplay, the same proxy `rect`
/// draws through, so a mixed cell dithers identically.
///
/// Factored out of the op loop so a host build can extract, compile and
/// differentially test this one function against the Python without
/// bringing in the whole op loop or a real ArduinoJson.
///
/// Returns false when the op can't be drawn at all -- `cell` isn't a
/// sane integer, `rows` isn't a list of strings, or `palette` isn't an
/// object -- the one place a bad op skips instead of drawing something
/// wrong, mirroring the Python and logging why. Nothing is drawn before
/// this check passes.
inline bool draw_sprite(esphome::display::Display &it, JsonObject o, JsonObject palette) {
  // Read as double, not `o["x"] | 0` (docs/plans/firmware-bounds.md D4's
  // review amendment): ArduinoJson's typed default operator returns the
  // default for ANY value that isn't exactly an in-range JSON integer --
  // a JSON float included -- so `"x": 1e10` would silently read as 0
  // rather than being rejected. Checked here, not only relied on from the
  // op loop's own x/y bound, so draw_sprite() stays a self-contained parse
  // the same way draw_poly() is -- this function has its own harness
  // (tests/parity/test_sprite.py) that calls it directly, bypassing the
  // loop entirely.
  const double x_d = o["x"] | 0.0, y_d = o["y"] | 0.0;
  if (x_d < -kMaxCoord || x_d > kMaxCoord) {
    ESP_LOGW(TAG, "sprite: x=%g out of range (|v| <= %d); skipped", x_d, kMaxCoord);
    return false;
  }
  if (y_d < -kMaxCoord || y_d > kMaxCoord) {
    ESP_LOGW(TAG, "sprite: y=%g out of range (|v| <= %d); skipped", y_d, kMaxCoord);
    return false;
  }
  const int x = static_cast<int>(x_d), y = static_cast<int>(y_d);
  const int cell = o["cell"] | 0;
  JsonArray sprite_rows = o["rows"];
  JsonObject sprite_palette = o["palette"];

  bool rows_ok = !sprite_rows.isNull();
  if (rows_ok) {
    for (JsonVariant rv : sprite_rows) {
      const char *s = rv;
      if (s == nullptr) {
        rows_ok = false;  // a non-string element -- bail before drawing anything
        break;
      }
    }
  }
  if (cell < 1 || cell > kSpriteMaxCell || !rows_ok || sprite_palette.isNull()) {
    ESP_LOGW(TAG,
             "sprite needs an integer cell >= 1 and <= %d, rows (a list of "
             "strings) and palette (an object); skipped",
             kSpriteMaxCell);
    return false;
  }

  // Grid dimensions and palette size, bounded independently of `cell`
  // (docs/plans/firmware-bounds.md D7): together with kMaxCoord on the
  // pixel box below, these keep the ragged-row walk further down to at
  // most kSpriteMaxCols * kSpriteMaxRows cell visits, however small `cell`
  // itself is.
  const int n_rows = static_cast<int>(sprite_rows.size());
  if (n_rows > kSpriteMaxRows) {
    ESP_LOGW(TAG, "sprite has %d rows, more than %d; skipped", n_rows, kSpriteMaxRows);
    return false;
  }
  const int n_palette = static_cast<int>(sprite_palette.size());
  if (n_palette > kSpriteMaxPalette) {
    ESP_LOGW(TAG, "sprite palette has %d entries, more than %d; skipped", n_palette,
             kSpriteMaxPalette);
    return false;
  }

  // The widest row, in codepoints, decides the grid's column count, and a
  // short row reads as transparent past its own length -- the drawing half
  // of the Python's "ragged rows are padded"; the warning about it is
  // authoring feedback and stays on that side. Padding happens before
  // mirroring, exactly as the Python pads then reverses, so a ragged
  // mirrored row pads on what becomes its leading edge.
  //
  // Rows stay as the UTF-8 strings ArduinoJson already holds; only ONE row's
  // cell boundaries are materialised at a time. An earlier cut kept every
  // cell as its own std::string -- 8,448 of them for a 96x88 sprite, some
  // 200 KB of internal heap on a chip that has about that much free after
  // Wi-Fi -- and operator new aborted the panel on every wake until safe
  // mode caught it (docs/plans/wake-sleep-flow.md).
  size_t cols = 0;
  for (JsonVariant rv : sprite_rows) {
    const char *s = rv;
    const std::string row = s != nullptr ? s : "";
    size_t n_cp = 0;
    for (size_t i = 0; i < row.size(); i = utf8_next(row, i))
      n_cp++;
    cols = std::max(cols, n_cp);
  }
  if (static_cast<int>(cols) > kSpriteMaxCols) {
    ESP_LOGW(TAG, "sprite is %d columns wide, more than %d; skipped", static_cast<int>(cols),
             kSpriteMaxCols);
    return false;
  }

  // The far edge of the pixel box this sprite would actually occupy
  // (docs/plans/firmware-bounds.md D4) -- `x`/`y` themselves are already
  // bound-checked above; this is the sprite-specific arithmetic no other
  // op does. int64_t so cols/rows * cell can never overflow before the
  // comparison runs.
  const int64_t x_edge = static_cast<int64_t>(x) + static_cast<int64_t>(cols) * cell;
  const int64_t y_edge = static_cast<int64_t>(y) + static_cast<int64_t>(n_rows) * cell;
  if (std::abs(x_edge) > kMaxCoord || std::abs(y_edge) > kMaxCoord) {
    ESP_LOGW(TAG, "sprite pixel box out of range (|v| <= %d); skipped", kMaxCoord);
    return false;
  }

  const bool mirror = !strcmp(o["mirror"] | "", "x");
  // Any other non-null mirror value is a Python-side ("x" is the only
  // legal one) authoring warning; the firmware just doesn't mirror, as it
  // always has.

  // Resolve each character once, not per cell, keyed on its full UTF-8
  // sequence rather than a single byte. A palette key that isn't exactly
  // one codepoint can't identify a cell at all and is skipped with a
  // warning; a row that uses it then falls into the "no
  // palette entry" path below, same as any other unknown character. A
  // palette value that isn't a plain colour name (missing, or an inline
  // mix object) reads as "black" the same way `o["c"] | "black"`
  // degrades one anywhere else in this file.
  std::map<std::string, Ink> char_ink;
  for (JsonPair kv : sprite_palette) {
    const std::string key = kv.key().c_str();
    size_t n_cp = 0;
    for (size_t i = 0; i < key.size(); i = utf8_next(key, i))
      n_cp++;
    if (n_cp != 1) {
      ESP_LOGW(TAG, "sprite palette key '%s' is not one character; ignored", key.c_str());
      continue;
    }
    if (key == "." || key == " ")
      continue;  // always transparent; cannot be redefined
    const char *cname = kv.value() | "black";
    char_ink[key] = resolve_ink(cname, palette);
  }

  const Ink black_ink{esphome::Color(0, 0, 0), esphome::Color(0, 0, 0), 100};
  std::set<std::string> warned;
  // The "no palette entry" warning set is capped (docs/plans/
  // firmware-bounds.md D7): eight distinct offending characters get their
  // own line, a ninth gets one more "...and more" line, and nothing after
  // that logs at all -- a sprite with hundreds of stray characters must not
  // turn a single wake's log into hundreds of ESP_LOGW calls.
  static const size_t kMaxWarnedChars = 8;
  bool warned_overflow = false;
  size_t r = 0;
  for (JsonVariant rv : sprite_rows) {
    const char *s = rv;
    const std::string row = s != nullptr ? s : "";
    // (offset, length) of each codepoint in this row: a few hundred bytes
    // for the widest sensible row, freed before the next one.
    std::vector<std::pair<size_t, size_t>> cps;
    for (size_t i = 0; i < row.size();) {
      const size_t j = utf8_next(row, i);
      cps.emplace_back(i, j - i);
      i = j;
    }
    // Grid column -> the (offset, length) span of the codepoint drawn
    // there in `row`, or `npos` past the row's own length (transparent); a
    // mirrored row reads its codepoints from the far end, which is where
    // the padding then lands. Returning a span instead of a std::string
    // means the run-merge loop below can walk a whole row without
    // allocating one string per cell -- the hot loop this file's crash was
    // in (docs/plans/wake-sleep-flow.md) -- and only ever builds a string
    // for the single winning span of each run.
    auto span_at = [&](size_t c) -> std::pair<size_t, size_t> {
      const size_t idx = mirror ? cols - 1 - c : c;
      return idx < cps.size() ? cps[idx] : std::pair<size_t, size_t>(std::string::npos, 0);
    };
    auto span_eq = [&](const std::pair<size_t, size_t> &a, const std::pair<size_t, size_t> &b) {
      if (a.first == std::string::npos || b.first == std::string::npos)
        return a.first == b.first;  // both "past the row" -- the same transparent cell
      return a.second == b.second && !row.compare(a.first, a.second, row, b.first, b.second);
    };
    size_t c0 = 0;
    while (c0 < cols) {
      const auto sp0 = span_at(c0);
      size_t c1 = c0 + 1;
      while (c1 < cols && span_eq(span_at(c1), sp0))
        c1++;
      const size_t run = c1 - c0;
      const std::string ch =
          sp0.first == std::string::npos ? "." : row.substr(sp0.first, sp0.second);
      if (ch != "." && ch != " ") {
        Ink cell_ink = black_ink;
        auto entry = char_ink.find(ch);
        if (entry != char_ink.end()) {
          cell_ink = entry->second;
        } else if (warned.count(ch)) {
          // Already reported -- a repeat of a character that made the
          // first eight must not fall into the overflow branch below just
          // because the set happens to be full by now (review amendment
          // to docs/plans/firmware-bounds.md D7: without this check first,
          // e.g. rows ["ABCDEFGHA"] with an empty palette logged "A" as
          // the overflow line on its second occurrence instead of nothing
          // at all, disagreeing with the Python mirror).
        } else if (warned.size() < kMaxWarnedChars) {
          // Checked, then inserted -- not the other way around: inserting
          // first and capping only the LOG lines left `warned` itself
          // unbounded, so a sprite with thousands of distinct offending
          // characters would still grow the set (and heap-allocate one
          // std::string per entry) without limit, even though only eight
          // lines were ever printed.
          warned.insert(ch);
          // The UTF-8 sequence, printed with %s -- %c would only show its
          // first byte.
          ESP_LOGW(TAG, "sprite: no palette entry for '%s'; drawing black", ch.c_str());
        } else if (!warned_overflow) {
          warned_overflow = true;
          ESP_LOGW(TAG, "sprite: ...and more characters with no palette entry");
        }
        MixDisplay smix(it);
        smix.add_ink(cell_ink.a, cell_ink);
        smix.filled_rectangle(x + static_cast<int>(c0) * cell, y + static_cast<int>(r) * cell,
                               static_cast<int>(run) * cell, cell, cell_ink.a);
      }
      c0 = c1;
    }
    r++;
  }
  return true;
}

/// Even-odd scanline fill (D12): for each integer scanline `y` from `ymin`
/// to `ymax` inclusive -- already clamped by the caller to the visible
/// range `[0, height)`, so this loop can never scale with how far outside
/// the canvas `pts` reaches -- an edge
/// `(x0,y0)-(x1,y1)` of the closed point list with `y0 != y1` contributes a
/// crossing when `y` is in `[min(y0,y1), max(y0,y1))` -- half-open, so a
/// vertex shared by two edges is counted on exactly one of them -- at
/// `x = x0 + floor_div((y - y0) * (x1 - x0), y1 - y0)`. Crossings are
/// sorted, paired up, each pair clamped to `[0, width)` -- a span whose
/// true extent runs off either edge of the canvas is trimmed to it before
/// `emit` ever sees it -- and `emit(y, xa, xb)` is called directly on
/// what survives -- no vector of spans is ever materialised.
///
/// A free function, not folded into draw_poly(), so the parity harness
/// (tests/parity/test_poly.py) can extract and diff it on its own
/// against display_mcp.render's `_poly_spans()` -- the one place the two
/// renderers could genuinely disagree, per D12. Products go through
/// `int64_t` even though `kMaxCoord` (docs/plans/firmware-bounds.md D4) is
/// now small enough that `(y - y0) * (x1 - x0)` fits comfortably in an
/// int32 -- there is no cost to keeping the wider type, and it stays
/// correct if the bound ever moves.
///
/// `xs` is declared once, outside the scanline loop, and `clear()`ed at the
/// top of each iteration (docs/plans/firmware-bounds.md D8) rather than
/// redeclared per `y` -- one heap allocation reused `ymax - ymin + 1`
/// times instead of that many fresh ones.
inline void poly_spans(const std::vector<std::pair<int, int>> &pts, int ymin, int ymax, int width,
                       const std::function<void(int, int, int)> &emit) {
  const int n = static_cast<int>(pts.size());
  std::vector<int64_t> xs;
  for (int y = ymin; y <= ymax; y++) {
    xs.clear();
    for (int i = 0; i < n; i++) {
      const int64_t x0 = pts[i].first, y0 = pts[i].second;
      const int64_t x1 = pts[(i + 1) % n].first, y1 = pts[(i + 1) % n].second;
      if (y0 == y1)
        continue;  // horizontal edges never cross a scanline
      const int64_t lo = std::min(y0, y1), hi = std::max(y0, y1);
      if (y >= lo && y < hi)
        xs.push_back(x0 + floor_div((static_cast<int64_t>(y) - y0) * (x1 - x0), y1 - y0));
    }
    std::sort(xs.begin(), xs.end());
    for (size_t i = 0; i + 1 < xs.size(); i += 2) {
      const int64_t xa = std::max<int64_t>(0, xs[i]);
      const int64_t xb = std::min<int64_t>(width - 1, xs[i + 1]);
      if (xa <= xb)
        emit(y, static_cast<int>(xa), static_cast<int>(xb));
    }
  }
}

/// A point list, filled by the shared even-odd scanline above or outlined
/// edge by edge (docs/plans/dragon-feedback.md D12). `c` is the op's own
/// ink -- already resolved and registered on `it` (a MixDisplay) by the
/// caller before dispatch, the same way rect/line/circle receive it -- so
/// unlike draw_sprite() this needs no palette of its own: a poly has one
/// colour for the whole shape, not one per character.
///
/// `pts` must be a JsonArray of at least three, and at most `kPolyMaxPts`,
/// `[x, y]` integer pairs, each within `kMaxCoord` of the origin; anything
/// else -- too few points, too many, an element that isn't exactly a
/// two-number pair, a coordinate past the bound -- is malformed and the
/// whole op is abandoned before anything is drawn, mirroring
/// draw_sprite()'s all-or-nothing parse. `pair.size()` proves a JsonArray
/// has exactly two elements. The `kPolyMaxPts` check runs *while* parsing
/// (docs/plans/firmware-bounds.md D8), so `pts` itself never grows past
/// it -- a document with a million-point array costs one bounded parse,
/// not a bounded parse plus an unbounded vector.
///
/// Filled: every span poly_spans() finds, each one `filled_rectangle` of
/// height 1 through `it`, so a mixed fill dithers with absolute phase
/// exactly like a `rect` fill does -- the scanline range is clamped to
/// `[0, height)` first, so a polygon whose points sit far outside the
/// canvas costs no more than one that doesn't. Outlined (`fill: false`):
/// every edge, including the closing one, through the file's own
/// thick_line() -- the same primitive and the same thickness rule the
/// `line` op uses.
///
/// Returns false -- with the caller doing `skipped++` -- when `pts` is
/// malformed; true otherwise, whether filled or outlined.
inline bool draw_poly(esphome::display::Display &it, JsonObject o, const Ink &c) {
  JsonArray raw_pts = o["pts"];
  std::vector<std::pair<int, int>> pts;
  bool ok = !raw_pts.isNull();
  bool too_many = false;
  if (ok) {
    for (JsonVariant pv : raw_pts) {
      if (pts.size() >= static_cast<size_t>(kPolyMaxPts)) {
        // Checked before parsing the next element, not after -- pts itself
        // never grows past kPolyMaxPts (D8).
        too_many = true;
        break;
      }
      JsonArray pair = pv;
      if (pair.isNull() || pair.size() != 2) {
        ok = false;
        break;
      }
      JsonVariant xv = pair[0], yv = pair[1];
      if (!xv.template is<int>() || !yv.template is<int>()) {
        ok = false;  // not both integers
        break;
      }
      pts.emplace_back(xv.template as<int>(), yv.template as<int>());
    }
  }
  if (too_many) {
    ESP_LOGW(TAG, "poly has more than %d points; nothing to draw, skipped", kPolyMaxPts);
    return false;
  }
  if (!ok || pts.size() < 3) {
    ESP_LOGW(TAG, "poly needs at least three [x, y] points; nothing to draw, skipped");
    return false;
  }
  for (const auto &p : pts) {
    if (std::abs(p.first) > kMaxCoord || std::abs(p.second) > kMaxCoord) {
      ESP_LOGW(TAG, "poly point out of range (|x|,|y| <= %d); nothing to draw, skipped",
               kMaxCoord);
      return false;
    }
  }

  if (o["fill"] | true) {
    const int width = it.get_width(), height = it.get_height();
    int ymin = pts[0].second, ymax = pts[0].second;
    for (const auto &p : pts) {
      ymin = std::min(ymin, p.second);
      ymax = std::max(ymax, p.second);
    }
    ymin = std::max(0, ymin);
    ymax = std::min(height - 1, ymax);
    if (ymin <= ymax) {
      poly_spans(pts, ymin, ymax, width, [&](int y, int xa, int xb) {
        it.filled_rectangle(xa, y, xb - xa + 1, 1, c.a);
      });
    }
  } else {
    const int t = o["t"] | 1;
    const int n = static_cast<int>(pts.size());
    for (int i = 0; i < n; i++) {
      const auto &p0 = pts[i];
      const auto &p1 = pts[(i + 1) % n];
      thick_line(it, p0.first, p0.second, p1.first, p1.second, t, c.a);
    }
  }
  return true;
}

inline void replace_all(std::string &s, const char *key, const std::string &val) {
  const size_t klen = strlen(key);
  size_t pos = 0;
  while ((pos = s.find(key, pos)) != std::string::npos) {
    s.replace(pos, klen, val);
    pos += val.size();
  }
}

/// Expand the system fields of a `fmt` template: {hash} (last 5 of
/// meta.hash) {hash16} {time} {time24} {battery} {battv}. Unknown {fields} stay
/// literal, which is the versioning story: a document written for a newer
/// firmware still draws, just with the placeholder showing.
inline std::string expand_fmt(const std::string &tpl, const std::string &doc_hash,
                              const DisplayListAssets &a) {
  std::string s = tpl;
  const std::string h16 = doc_hash.empty() ? "no hash" : doc_hash;
  const std::string h5 =
      doc_hash.empty() ? "no hash" : (doc_hash.size() > 5 ? doc_hash.substr(doc_hash.size() - 5) : doc_hash);
  replace_all(s, "{hash16}", h16);
  replace_all(s, "{hash}", h5);
  replace_all(s, "{time24}", a.time24.empty() ? "--:--" : a.time24);
  replace_all(s, "{time}", a.time.empty() ? "--:--" : a.time);
  replace_all(s, "{battery}", a.battery.empty() ? "--%" : a.battery);
  replace_all(s, "{battv}", a.battv.empty() ? "-.-V" : a.battv);
  return s;
}

/// Identity of what a document *draws*, or empty if it carries none.
///
/// meta.hash covers bg + palette + ops only, so a fresh `meta.generated`
/// timestamp on an otherwise identical document costs nothing. There is
/// deliberately no fallback: a document without a hash is a server bug, and
/// silently papering over it with a raw-byte hash would hide the fact that
/// every wake is now doing a full refresh.
inline std::string document_id(const std::string &body) {
  std::string out;
  esphome::json::parse_json(body, [&](JsonObject root) -> bool {
    const char *h = root["meta"]["hash"];
    if (h != nullptr)
      out = h;
    return true;
  });
  return out;
}

// D4's bound, applied uniformly in the op loop below: every coordinate and
// size field the loop itself reads (as opposed to the ones draw_sprite()/
// draw_poly() already bound on their own, being self-contained parses with
// their own harnesses) goes through this one check.
//
// Takes a double, not an int: `o["x"] | 0` (ArduinoJson's typed default
// operator) returns the default for ANY value that isn't exactly an
// in-range JSON integer -- including a JSON float, and including an
// integer literal too large for int32 -- so `"x": 1e10` would silently
// read as 0 and draw at the origin instead of being rejected. Reading
// every such field as `o["field"] | 0.0` instead accepts any JSON number
// (int or float) as its true value, bound-checked here before the caller
// truncates it (review amendment to docs/plans/firmware-bounds.md D4).
inline bool coord_ok(double v) { return v >= -static_cast<double>(kMaxCoord) && v <= static_cast<double>(kMaxCoord); }

/// Execute a display list against `it`. Returns false if the JSON did not parse
/// or carried no ops — the caller should then draw its own fallback.
inline bool draw_display_list(esphome::display::Display &it, const std::string &body,
                              const DisplayListAssets &assets) {
  if (body.empty()) {
    ESP_LOGW(TAG, "empty body");
    return false;
  }

  bool drew = false;

  esphome::json::parse_json(body, [&](JsonObject root) -> bool {
    // `v` is the agreed escape hatch for a future breaking change to the
    // compiled vocabulary (the named table above included) -- see
    // docs/plans/ink-mixing.md decision 10. Missing or unrecognised only
    // warns, naming both the value seen and the version this firmware
    // implements; the document is drawn regardless, per the rule that
    // warnings never block a publish.
    const int doc_v = root["v"] | 0;
    if (doc_v != DOCUMENT_VERSION)
      ESP_LOGW(TAG, "document v=%d, firmware implements v=%d; drawing anyway", doc_v, DOCUMENT_VERSION);

    JsonObject palette = root["palette"];
    const char *bg_name = root["bg"] | "white";
    const Ink bg_ink = resolve_ink(bg_name, palette);
    it.fill(bg_ink.a);
    if (bg_ink.mix != 100) {
      // fill() can't be dithered through the proxy (see MixDisplay), so a
      // mixed bg is the base ink from the fast fill() above, plus an
      // explicit overlay of the second ink wherever mix_on() says so.
      const int w = it.get_width(), h = it.get_height();
      for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++)
          if (mix_on(x, y, bg_ink.mix))
            it.draw_pixel_at(x, y, bg_ink.b);
    }
    // For the `hash` op: the identity of this document, drawn on the wall so
    // you can read off which version the panel shows. Empty when the server
    // forgot to stamp it, which the wake cycle already logs as a bug.
    const std::string doc_hash = root["meta"]["hash"] | "";

    JsonArray ops = root["ops"];
    if (ops.isNull()) {
      ESP_LOGW(TAG, "no ops array");
      return false;
    }

    // D3's backstop, read once here: a legal document with too many ops
    // must not run the loop task past the watchdog, however far under
    // budget each individual op is. Checked at the top of every iteration,
    // not just once, so the budget is what actually stops the loop.
    const uint32_t t0 = esphome::millis();
    int n = 0, skipped = 0;
    for (JsonObject o : ops) {
      if (esphome::millis() - t0 > kDrawBudgetMs) {
        const int remaining = static_cast<int>(ops.size()) - n - skipped;
        ESP_LOGW(TAG, "draw budget exceeded after %d ops; %d skipped", n, remaining);
        skipped += remaining;
        break;
      }

      const char *kind = o["op"] | "";
      // D4's coordinate bound, applied to every op's x/y up front: poly has
      // no x/y field of its own, so `o["x"] | 0.0` here is always 0.0 and
      // the check always passes for it, same as omitting x/y from any op
      // that doesn't use them. sprite double-checks this itself (see
      // draw_sprite()'s own x/y and pixel-box bounds), since it has its own
      // harness that calls it directly, bypassing this loop entirely.
      //
      // Read as double, not `o["x"] | 0` (review amendment): ArduinoJson's
      // typed default operator returns the default for ANY value that
      // isn't exactly an in-range JSON integer -- a JSON float included --
      // so `"x": 1e10` would silently read as 0 and draw at the origin
      // instead of being rejected. `coord_ok()` runs on the double, before
      // truncation, so a huge value is caught rather than laundered into a
      // small in-range one first.
      const double ox_d = o["x"] | 0.0, oy_d = o["y"] | 0.0;
      if (!coord_ok(ox_d)) {
        ESP_LOGW(TAG, "%s: x=%g out of range (|v| <= %d); skipped", kind, ox_d, kMaxCoord);
        skipped++;
        continue;
      }
      if (!coord_ok(oy_d)) {
        ESP_LOGW(TAG, "%s: y=%g out of range (|v| <= %d); skipped", kind, oy_d, kMaxCoord);
        skipped++;
        continue;
      }
      const int ox = static_cast<int>(ox_d), oy = static_cast<int>(oy_d);
      const Ink c = resolve_ink(o["c"] | "black", palette);
      // Every shape and glyph op below draws through this proxy instead of
      // `it` directly, which is what makes a mixed `c` dither (decision 6);
      // solid ink (mix == 100) draws pixel-identical either way.
      MixDisplay mix(it);
      mix.add_ink(c.a, c);

      if (!strcmp(kind, "rect")) {
        const double w_d = o["w"] | 0.0, h_d = o["h"] | 0.0;
        if (!coord_ok(w_d)) {
          ESP_LOGW(TAG, "rect: w=%g out of range (|v| <= %d); skipped", w_d, kMaxCoord);
          skipped++;
          continue;
        }
        if (!coord_ok(h_d)) {
          ESP_LOGW(TAG, "rect: h=%g out of range (|v| <= %d); skipped", h_d, kMaxCoord);
          skipped++;
          continue;
        }
        const int x = ox, y = oy, w = static_cast<int>(w_d), h = static_cast<int>(h_d);
        if (o["fill"] | true) {
          // Corner radius (docs/plans/dragon-feedback.md D10). Clamped to
          // (min(w, h) - 1) / 2 the same way the Python is -- silently
          // here, with a warning there, since a document is authored on
          // that side. The bound is min(w, h) - 1, not min(w, h): a corner
          // disc is 2r+1 px across, so r == min(w, h) / 2 on an even
          // dimension would ink one row/column past the box.
          // std::max(0, ...) guards a zero-size box.
          int r = o["r"] | 0;
          const int max_r = std::max(0, (std::min(w, h) - 1) / 2);
          if (r > max_r) r = max_r;
          draw_rounded_rect(mix, x, y, w, h, r, c.a);
        } else {
          int t = o["t"] | 1;
          if (t > kThickMax)
            t = kThickMax;
          for (int i = 0; i < t; i++)
            mix.rectangle(x + i, y + i, w - 2 * i, h - 2 * i, c.a);
        }

      } else if (!strcmp(kind, "line")) {
        const double x2_d = o["x2"] | 0.0, y2_d = o["y2"] | 0.0;
        if (!coord_ok(x2_d)) {
          ESP_LOGW(TAG, "line: x2=%g out of range (|v| <= %d); skipped", x2_d, kMaxCoord);
          skipped++;
          continue;
        }
        if (!coord_ok(y2_d)) {
          ESP_LOGW(TAG, "line: y2=%g out of range (|v| <= %d); skipped", y2_d, kMaxCoord);
          skipped++;
          continue;
        }
        const int x2 = static_cast<int>(x2_d), y2 = static_cast<int>(y2_d);
        thick_line(mix, ox, oy, x2, y2, o["t"] | 1, c.a);

      } else if (!strcmp(kind, "circle")) {
        const double r_d = o["r"] | 0.0;
        if (!coord_ok(r_d)) {
          ESP_LOGW(TAG, "circle: r=%g out of range (|v| <= %d); skipped", r_d, kMaxCoord);
          skipped++;
          continue;
        }
        const int x = ox, y = oy, r = static_cast<int>(r_d);
        if (o["fill"] | true) {
          mix.filled_circle(x, y, r, c.a);
        } else {
          // An unfilled circle honours `t` (SPEC.md), matching the
          // Python. `t == 1`, the common case, is the plain circle()
          // outline below. `t >= 2` goes through draw_circle_ring()
          // instead of stacking `t` concentric circle() rings, which
          // would leave single-pixel holes near the diagonals;
          // draw_circle_ring() fills the annulus by rows instead, matching
          // filled_circle(r) - filled_circle(r - t) exactly.
          const int t = o["t"] | 1;
          if (t <= 1)
            mix.circle(x, y, r, c.a);
          else
            draw_circle_ring(mix, x, y, r, t, c.a);
        }

      } else if (!strcmp(kind, "text")) {
        auto fit = assets.fonts.find(o["f"] | "md");
        if (fit == assets.fonts.end()) {
          ESP_LOGW(TAG, "unknown font '%s'", o["f"] | "md");
          skipped++;
          continue;
        }
        esphome::display::BaseFont *font = fit->second;
        // Length checked on the raw C string, before a std::string copies
        // it -- `o["s"] | ""` on a field the document controls can be up
        // to MAX_DOC_BYTES itself; constructing the std::string first
        // would already have paid the copy this check exists to avoid
        // (docs/plans/firmware-bounds.md D6).
        const char *s_ptr = o["s"] | "";
        const size_t s_len = strlen(s_ptr);
        if (s_len > static_cast<size_t>(kTextMaxLen)) {
          // The quadratic fit_line()/wrap() cost this protects: ~7ms and a
          // ~6KB word vector at the bound.
          ESP_LOGW(TAG, "text: s is %d bytes, more than %d; skipped",
                   static_cast<int>(s_len), kTextMaxLen);
          skipped++;
          continue;
        }
        const std::string s(s_ptr, s_len);
        const int x = ox, y = oy;
        const int max_w = o["w"] | 0;
        const auto align = align_of(o["a"] | "left");

        if ((o["wrap"] | false) && max_w > 0) {
          int lines = o["lines"] | 2;
          if (lines > kTextMaxLines)
            lines = kTextMaxLines;
          // lh joins the bound too (review amendment to D4/D6): with
          // `lines` up to kTextMaxLines, `y + i * lh` in the print loop
          // below is exactly the kind of size-field arithmetic D4 already
          // covers for every other op -- a `lh` of, say, 2e9 would
          // overflow that multiply long before it ever reached a sane
          // print() call. Same double-read-then-bound-check shape as
          // every other coordinate field; the default is itself a double
          // so a document that omits `lh` never has to pass through this
          // check at all in spirit, only in code shape.
          const double lh_default = font_height(font) * 1.24;
          const double lh_d = o["lh"] | lh_default;
          if (!coord_ok(lh_d)) {
            ESP_LOGW(TAG, "text: lh=%g out of range (|v| <= %d); skipped", lh_d, kMaxCoord);
            skipped++;
            continue;
          }
          const int lh = static_cast<int>(lh_d);
          auto out = wrap(font, s, max_w, lines);
          for (size_t i = 0; i < out.size(); i++) {
            const int ly = y + static_cast<int>(i) * lh;
            mix.print(x, ly, font, c.a, align, out[i].c_str());
          }
        } else {
          const std::string line = fit_line(font, s, max_w);
          mix.print(x, y, font, c.a, align, line.c_str());
        }

      } else if (!strcmp(kind, "fmt")) {
        // `text` without wrap whose `s` is a template: {hash} {hash16} {time}
        // {time24}. The values are never in the document (meta.hash covers
        // where this is drawn, not what it says), so a clock tick never
        // costs a refresh and the hash cannot be circular.
        auto fit = assets.fonts.find(o["f"] | "xs");
        if (fit == assets.fonts.end()) {
          ESP_LOGW(TAG, "unknown font '%s'", o["f"] | "xs");
          skipped++;
          continue;
        }
        esphome::display::BaseFont *font = fit->second;
        // Same as `text`: length checked on the raw C string before a
        // std::string copies it (docs/plans/firmware-bounds.md D6).
        const char *s_raw_ptr = o["s"] | "";
        const size_t s_raw_len = strlen(s_raw_ptr);
        if (s_raw_len > static_cast<size_t>(kTextMaxLen)) {
          ESP_LOGW(TAG, "fmt: s is %d bytes, more than %d; skipped",
                   static_cast<int>(s_raw_len), kTextMaxLen);
          skipped++;
          continue;
        }
        const std::string s_raw(s_raw_ptr, s_raw_len);
        const std::string s = expand_fmt(s_raw, doc_hash, assets);
        const int x = ox, y = oy;
        const auto align = align_of(o["a"] | "left");
        mix.print(x, y, font, c.a, align, s.c_str());

      } else if (!strcmp(kind, "icon")) {
        std::string key = std::string(o["n"] | "") + "/" + std::string(o["z"] | "sm");
        auto iit = assets.icons.find(key);
        if (iit == assets.icons.end()) {
          ESP_LOGW(TAG, "icon '%s' is not compiled in", key.c_str());
          skipped++;
          continue;
        }
        // color_off only matters for opaque binary images; with
        // transparency: chroma_key the off pixels are skipped entirely.
        const Ink off = resolve_ink(o["bgc"] | bg_name, palette);
        mix.add_ink(off.a, off);
        const int ix = ox, iy = oy;
        iit->second->draw(ix, iy, &mix, c.a, off.a);

      } else if (!strcmp(kind, "sprite")) {
        // draw_sprite() takes the raw `it`, not this loop's `mix`: a
        // sprite has its own palette of colours, one `Ink` per character,
        // not the loop's single resolved `c` -- it builds and registers a
        // fresh MixDisplay per run of equal characters instead. draw_poly()
        // has exactly one colour for the whole shape, the same as
        // rect/line/circle, so it reuses the caller's `mix` like they do.
        if (!draw_sprite(it, o, palette)) {
          skipped++;
          continue;
        }

      } else if (!strcmp(kind, "poly")) {
        if (!draw_poly(mix, o, c)) {
          skipped++;
          continue;
        }

      } else {
        ESP_LOGW(TAG, "unknown op '%s'", kind);
        skipped++;
        continue;
      }
      n++;
    }

    ESP_LOGI(TAG, "drew %d ops (%d skipped)", n, skipped);
    drew = n > 0;
    return true;
  });

  return drew;
}

}  // namespace dl
