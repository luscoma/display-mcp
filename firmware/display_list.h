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

// Resolve through the document's palette aliases, with a depth cap so a
// self-referential palette can't hang the render.
inline esphome::Color resolve_color(const char *name, JsonObject palette) {
  std::string n = name ? name : "black";
  esphome::Color c;
  for (int hop = 0; hop < 8; hop++) {
    if (base_color(n, c))
      return c;
    if (palette.isNull())
      break;
    const char *next = palette[n.c_str()];
    if (next == nullptr)
      break;
    n = next;
  }
  ESP_LOGW(TAG, "unknown colour '%s', using black", name ? name : "(null)");
  return esphome::Color(0, 0, 0);
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
/// glyphs. get_text_bounds() does the TextAlign and x_offset math the way
/// print() does, so the box lands on the ink for any alignment.
inline void lighten_rect(esphome::display::Display &it, int x1, int y1, int w, int h, esphome::Color bg) {
  const int x0 = std::max(x1, 0), y0 = std::max(y1, 0);
  const int xe = std::min(x1 + w, it.get_width()), ye = std::min(y1 + h, it.get_height());
  for (int py = y0; py < ye; py++)
    for (int px = x0; px < xe; px++)
      if (((px + py) & 1) == 0)
        it.draw_pixel_at(px, py, bg);
}

inline void lighten_box(esphome::display::Display &it, int x, int y, const char *text,
                        esphome::display::BaseFont *font, esphome::display::TextAlign align,
                        esphome::Color bg) {
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
    esphome::Color bg = resolve_color(bg_name, palette);
    it.fill(bg);
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
      esphome::Color c = resolve_color(o["c"] | "black", palette);

      if (!strcmp(kind, "rect")) {
        const int x = o["x"] | 0, y = o["y"] | 0, w = o["w"] | 0, h = o["h"] | 0;
        if (o["fill"] | true) {
          it.filled_rectangle(x, y, w, h, c);
        } else {
          const int t = o["t"] | 1;
          for (int i = 0; i < t; i++)
            it.rectangle(x + i, y + i, w - 2 * i, h - 2 * i, c);
        }

      } else if (!strcmp(kind, "line")) {
        thick_line(it, o["x"] | 0, o["y"] | 0, o["x2"] | 0, o["y2"] | 0, o["t"] | 1, c);

      } else if (!strcmp(kind, "circle")) {
        const int x = o["x"] | 0, y = o["y"] | 0, r = o["r"] | 0;
        if (o["fill"] | true)
          it.filled_circle(x, y, r, c);
        else
          it.circle(x, y, r, c);

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
        const esphome::Color local_bg = resolve_color(o["bgc"] | bg_name, palette);

        if ((o["wrap"] | false) && max_w > 0) {
          const int lines = o["lines"] | 2;
          const int lh = o["lh"] | static_cast<int>(font_height(font) * 1.24f);
          auto out = wrap(font, s, max_w, lines);
          for (size_t i = 0; i < out.size(); i++) {
            const int ly = y + static_cast<int>(i) * lh;
            it.print(x, ly, font, c, align, out[i].c_str());
            if (light)
              lighten_box(it, x, ly, out[i].c_str(), font, align, local_bg);
          }
        } else {
          const std::string line = fit_line(font, s, max_w);
          it.print(x, y, font, c, align, line.c_str());
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
        it.print(x, y, font, c, align, s.c_str());
        if (tone_is_light(o["tone"] | ""))
          lighten_box(it, x, y, s.c_str(), font, align, resolve_color(o["bgc"] | bg_name, palette));

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
        esphome::Color off = resolve_color(o["bgc"] | bg_name, palette);
        const int ix = o["x"] | 0, iy = o["y"] | 0;
        iit->second->draw(ix, iy, &it, c, off);
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
