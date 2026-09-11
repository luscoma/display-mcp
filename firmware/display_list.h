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
#include <cstring>
#include <map>
#include <string>
#include <vector>

#include "esphome/components/display/display.h"
#include "esphome/components/font/font.h"
#include "esphome/components/image/image.h"
#include "esphome/components/json/json_util.h"
#include "esphome/core/color.h"
#include "esphome/core/log.h"

namespace dl {

static const char *const TAG = "display_list";

struct DisplayListAssets {
  // Type scale, keyed by the name the JSON uses: xl, lg, md, sm, xs.
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
// fills and knockouts tile seamlessly and a tone knockout can reproduce a
// mixed ground exactly.
//
//     B = | 0 2 |     mix_on(x, y, pct) picks the second ink (c2/b)
//         | 3 1 |     wherever B[y&1][x&1] < pct / 25 (integer division).
//
// Bit-identity check at pct=50 (threshold 2), which every existing document
// depends on via lighten_rect's `((px + py) & 1) == 0`:
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
    if (palette.isNull())
      break;
    auto v = palette[n.c_str()];
    if (v.template is<JsonObject>()) {
      ESP_LOGW(TAG, "'%s' is a mix, not a plain colour here; using its base ink", n.c_str());
      n = v.template as<JsonObject>()["c"] | "black";
      continue;
    }
    const char *next = v;
    if (next == nullptr)
      break;
    n = next;
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
    if (palette.isNull())
      break;
    auto v = palette[n.c_str()];
    if (v.template is<JsonObject>())
      return resolve_mix_entry(n.c_str(), v.template as<JsonObject>(), palette);
    const char *next = v;
    if (next == nullptr)
      break;
    n = next;
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

inline void thick_line(esphome::display::Display &it, int x1, int y1, int x2, int y2, int t,
                       esphome::Color c) {
  if (t <= 1) {
    it.line(x1, y1, x2, y2, c);
    return;
  }
  const bool vertical = (x1 == x2);
  const bool horizontal = (y1 == y2);
  for (int i = 0; i < t; i++) {
    if (vertical)
      it.line(x1 + i, y1, x2 + i, y2, c);
    else if (horizontal)
      it.line(x1, y1 + i, x2, y2 + i, c);
    else
      it.line(x1, y1 + i, x2, y2 + i, c);  // diagonals thicken vertically only
  }
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

/// `tone: "light"`: the panel has six inks and no grey, so a lighter text
/// weight is a 1 px checkerboard of the local background knocked out of the
/// glyphs -- always at a fixed 50% (decision 5: tone is sugar for "mix with
/// bgc at 50%", not a separate density). `bg` may itself be a mix, in which
/// case each knocked-out pixel takes whichever of bg's two inks its own
/// mix_on() would have painted there; absolute phase means that reproduces
/// the mixed ground exactly instead of speckling. get_text_bounds() does the
/// TextAlign and x_offset math the way print() does, so the box lands on the
/// ink for any alignment.
inline void lighten_rect(esphome::display::Display &it, int x1, int y1, int w, int h, Ink bg) {
  const int x0 = std::max(x1, 0), y0 = std::max(y1, 0);
  const int xe = std::min(x1 + w, it.get_width()), ye = std::min(y1 + h, it.get_height());
  for (int py = y0; py < ye; py++)
    for (int px = x0; px < xe; px++)
      if (mix_on(px, py, 50))
        it.draw_pixel_at(px, py, mix_on(px, py, bg.mix) ? bg.b : bg.a);
}

inline void lighten_box(esphome::display::Display &it, int x, int y, const char *text,
                        esphome::display::BaseFont *font, esphome::display::TextAlign align,
                        Ink bg) {
  int x1 = 0, y1 = 0, w = 0, h = 0;
  it.get_text_bounds(x, y, text, font, align, &x1, &y1, &w, &h);
  lighten_rect(it, x1, y1, w, h, bg);
}

/// `tone` attribute -> should the glyphs be lightened. Unknown values warn
/// and draw at full ink; never a skipped op.
inline bool tone_is_light(const char *tone) {
  if (tone == nullptr || *tone == '\0')
    return false;
  if (!strcmp(tone, "light"))
    return true;
  ESP_LOGW(TAG, "unknown tone '%s', drawing full ink", tone);
  return false;
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

    int n = 0, skipped = 0;
    for (JsonObject o : ops) {
      const char *kind = o["op"] | "";
      const Ink c = resolve_ink(o["c"] | "black", palette);
      // Every shape and glyph op below draws through this proxy instead of
      // `it` directly, which is what makes a mixed `c` dither (decision 6);
      // solid ink (mix == 100) draws pixel-identical either way.
      MixDisplay mix(it);
      mix.add_ink(c.a, c);

      if (!strcmp(kind, "rect")) {
        const int x = o["x"] | 0, y = o["y"] | 0, w = o["w"] | 0, h = o["h"] | 0;
        if (o["fill"] | true) {
          mix.filled_rectangle(x, y, w, h, c.a);
        } else {
          const int t = o["t"] | 1;
          for (int i = 0; i < t; i++)
            mix.rectangle(x + i, y + i, w - 2 * i, h - 2 * i, c.a);
        }

      } else if (!strcmp(kind, "line")) {
        thick_line(mix, o["x"] | 0, o["y"] | 0, o["x2"] | 0, o["y2"] | 0, o["t"] | 1, c.a);

      } else if (!strcmp(kind, "circle")) {
        const int x = o["x"] | 0, y = o["y"] | 0, r = o["r"] | 0;
        if (o["fill"] | true)
          mix.filled_circle(x, y, r, c.a);
        else
          mix.circle(x, y, r, c.a);

      } else if (!strcmp(kind, "text")) {
        auto fit = assets.fonts.find(o["f"] | "md");
        if (fit == assets.fonts.end()) {
          ESP_LOGW(TAG, "unknown font '%s'", o["f"] | "md");
          skipped++;
          continue;
        }
        esphome::display::BaseFont *font = fit->second;
        const std::string s = o["s"] | "";
        const int x = o["x"] | 0, y = o["y"] | 0;
        const int max_w = o["w"] | 0;
        const auto align = align_of(o["a"] | "left");

        const bool light = tone_is_light(o["tone"] | "");
        const Ink local_bg = resolve_ink(o["bgc"] | bg_name, palette);

        if ((o["wrap"] | false) && max_w > 0) {
          const int lines = o["lines"] | 2;
          const int lh = o["lh"] | static_cast<int>(font_height(font) * 1.24f);
          auto out = wrap(font, s, max_w, lines);
          for (size_t i = 0; i < out.size(); i++) {
            const int ly = y + static_cast<int>(i) * lh;
            mix.print(x, ly, font, c.a, align, out[i].c_str());
            if (light)
              lighten_box(it, x, ly, out[i].c_str(), font, align, local_bg);
          }
        } else {
          const std::string line = fit_line(font, s, max_w);
          mix.print(x, y, font, c.a, align, line.c_str());
          if (light)
            lighten_box(it, x, y, line.c_str(), font, align, local_bg);
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
        const std::string s = expand_fmt(o["s"] | "", doc_hash, assets);
        const int x = o["x"] | 0, y = o["y"] | 0;
        const auto align = align_of(o["a"] | "left");
        mix.print(x, y, font, c.a, align, s.c_str());
        if (tone_is_light(o["tone"] | ""))
          lighten_box(it, x, y, s.c_str(), font, align, resolve_ink(o["bgc"] | bg_name, palette));

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
        const int ix = o["x"] | 0, iy = o["y"] | 0;
        iit->second->draw(ix, iy, &mix, c.a, off.a);
        if (tone_is_light(o["tone"] | ""))
          lighten_rect(it, ix, iy, iit->second->get_width(), iit->second->get_height(), off);

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
