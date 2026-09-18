"""The compiled-harness machinery every parity test in this package shares:
header extraction, one `_STUB` C++ prelude (a stand-in `esphome::Color`/
`esphome::display::Display` with every primitive `display_list.h`'s
free functions call -- `draw_pixel_at`, `filled_rectangle`, `line`,
`circle`, `filled_circle`, `horizontal_line`, transcribed from the real
esphome package, not reinvented -- plus a minimal ArduinoJson stand-in
with `size()`, a bounds-checked `Canvas`, a tiny recursive-descent JSON
parser, and the `run_harness()` glue that reads an op from stdin and
writes a drew-byte plus the raw RGB raster to stdout), one `_compile()`
that turns a harness's own header fragments and `main()` into an
executable, and one `_OpHarness` that runs it.

Every harness needs a host C++ compiler; every fixture here skips
cleanly (`pytest.skip`) without one, so the pure-data tests elsewhere in
this package (the mix table, the device-safety limits, the glyph/YAML
checks) still run on a machine with no toolchain.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HEADER = Path(__file__).resolve().parents[2] / "firmware" / "display_list.h"
YAML = HEADER.parent / "epaper-schedule.yaml"


def _extract(pattern: str, what: str) -> str:
    """One line (or a few, for a multi-line declaration a `$` anchors the
    end of) extracted verbatim from the shipped header -- never retyped,
    so a copy here can only prove two copies agree with each other, not
    with the firmware."""
    src = HEADER.read_text()
    m = re.search(pattern, src, re.MULTILINE)
    assert m, f"could not find {what} in {HEADER.name} -- has it been renamed?"
    return m.group(0)


def _extract_block(pattern: str, what: str) -> str:
    """Like `_extract`, but for a brace-delimited definition (a function
    body, a struct, a class) that a naive `.*?\\}` regex can't safely
    bound -- it would stop at the first `}` a nested block contains.
    Finds the start, then counts braces from the first `{` to its match;
    a trailing `;` (a struct/class definition) is swept in too."""
    src = HEADER.read_text()
    m = re.search(pattern, src, re.MULTILINE)
    assert m, f"could not find {what} in {HEADER.name} -- has it been renamed?"
    start = m.start()
    i = src.index("{", m.start())
    depth = 0
    j = i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                j += 1
                break
        j += 1
    end = j
    k = end
    while k < len(src) and src[k] in " \t":
        k += 1
    if k < len(src) and src[k] == ";":
        end = k + 1
    return src[start:end]


def _firmware_const_value(name: str) -> int:
    """A namespace-scope `static const int[32_t] <name> = <expr>;` from the
    header, evaluated as Python -- a C++ integer-literal expression like
    `1 << 20` is also a valid Python one, and this only ever runs against
    our own header, not untrusted input. Pure text, no compiler needed."""
    src = HEADER.read_text()
    m = re.search(rf"^static const int(?:32_t)? {name} = (?P<value>.+);$", src, re.MULTILINE)
    assert m, f"could not find {name} in {HEADER.name} -- has it been renamed?"
    return eval(m.group("value"), {"__builtins__": {}})  # noqa: S307 - our own header


def _branch(src: str, start_marker: str, end_marker: str) -> str:
    """The slice of `src` between two markers -- used to check a field is
    read, or a helper called, inside the *right* op-dispatch branch, not
    just somewhere in the file."""
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


# --------------------------------------------------------------------------
# _STUB: the C++ prelude every compiled harness shares. ArduinoJson and
# ESPHome are stubbed to the slice `display_list.h`'s free functions
# actually touch; Color/Display's shape primitives are transcribed from the
# real esphome package (pip downloaded to check this, not reinvented), not
# reimplemented from scratch, so a match against them is a match against
# the panel's own rasteriser.
# --------------------------------------------------------------------------

_STUB = r"""
#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace esphome {
struct Color {
  uint8_t r = 0, g = 0, b = 0;
  Color() = default;
  Color(int r_, int g_, int b_) : r(r_), g(g_), b(b_) {}
  bool operator==(const Color &o) const { return r == o.r && g == o.g && b == o.b; }
};
namespace display {
enum class DisplayType { DISPLAY_TYPE_COLOR };
class Display {
 public:
  virtual ~Display() = default;
  virtual void draw_pixel_at(int x, int y, Color color) = 0;
  virtual int get_width() { return get_width_internal(); }
  virtual int get_height() { return get_height_internal(); }
  virtual void fill(Color c) {}
  virtual void clear() {}
  virtual DisplayType get_display_type() = 0;
  virtual void update() {}
  void horizontal_line(int x, int y, int width, Color c) {
    for (int i = x; i < x + width; i++) this->draw_pixel_at(i, y, c);
  }
  void filled_rectangle(int x1, int y1, int w, int h, Color c) {
    for (int i = y1; i < y1 + h; i++) this->horizontal_line(x1, i, w, c);
  }
  // line()/circle()/filled_circle(), transcribed verbatim from
  // esphome/components/display/display.cpp -- what thick_line() (line),
  // draw_circle_ring() and draw_rounded_rect() (filled_circle) call on the
  // real panel; a from-scratch reimplementation risks disagreeing with the
  // real one at some tie-break, this doesn't, because it isn't one.
  void line(int x1, int y1, int x2, int y2, Color color) {
    const int32_t dx = std::abs(x2 - x1), sx = x1 < x2 ? 1 : -1;
    const int32_t dy = -std::abs(y2 - y1), sy = y1 < y2 ? 1 : -1;
    int32_t err = dx + dy;
    while (true) {
      this->draw_pixel_at(x1, y1, color);
      if (x1 == x2 && y1 == y2)
        break;
      int32_t e2 = 2 * err;
      if (e2 >= dy) {
        err += dy;
        x1 += sx;
      }
      if (e2 <= dx) {
        err += dx;
        y1 += sy;
      }
    }
  }
  void circle(int cx, int cy, int radius, Color c) {
    int dx = -radius, dy = 0, err = 2 - 2 * radius, e2;
    do {
      this->draw_pixel_at(cx - dx, cy + dy, c);
      this->draw_pixel_at(cx + dx, cy + dy, c);
      this->draw_pixel_at(cx + dx, cy - dy, c);
      this->draw_pixel_at(cx - dx, cy - dy, c);
      e2 = err;
      if (e2 < dy) { err += ++dy * 2 + 1; if (-dx == dy && e2 <= dx) e2 = 0; }
      if (e2 > dx) { err += ++dx * 2 + 1; }
    } while (dx <= 0);
  }
  void filled_circle(int cx, int cy, int radius, Color c) {
    int dx = -radius, dy = 0, err = 2 - 2 * radius, e2;
    do {
      int hw = 2 * (-dx) + 1;
      this->horizontal_line(cx + dx, cy + dy, hw, c);
      this->horizontal_line(cx + dx, cy - dy, hw, c);
      e2 = err;
      if (e2 < dy) { err += ++dy * 2 + 1; if (-dx == dy && e2 <= dx) e2 = 0; }
      if (e2 > dx) { err += ++dx * 2 + 1; }
    } while (dx <= 0);
  }
 protected:
  virtual int get_width_internal() = 0;
  virtual int get_height_internal() = 0;
};
}  // namespace display
}  // namespace esphome

#define ESP_LOGW(tag, fmt, ...) std::fprintf(stderr, "W " fmt "\n", ##__VA_ARGS__)
static const char *const TAG = "display_list";

struct Node;
using NodePtr = std::shared_ptr<Node>;
struct Node {
  enum Type { NUL, INT, FLT, BOOL, STR, ARR, OBJ } t = NUL;
  long long i = 0;
  double f = 0;
  bool b = false;
  std::string s;
  std::vector<NodePtr> arr;
  std::vector<std::pair<std::string, NodePtr>> obj;
};
class JsonArray;
class JsonObject;
class JsonVariant {
 public:
  NodePtr n;
  JsonVariant() = default;
  explicit JsonVariant(NodePtr p) : n(p) {}
  bool isNull() const { return !n || n->t == Node::NUL; }
  template <typename T> bool is() const;
  template <typename T> T as() const;
  operator const char *() const { return (n && n->t == Node::STR) ? n->s.c_str() : nullptr; }
  operator JsonArray() const;
  operator JsonObject() const;
  template <typename T> T operator|(T def) const;
};
class JsonString {
 public:
  std::string v;
  const char *c_str() const { return v.c_str(); }
};
class JsonPair {
 public:
  std::string k;
  NodePtr v;
  JsonString key() const { return JsonString{k}; }
  JsonVariant value() const { return JsonVariant(v); }
};
class JsonArray {
 public:
  NodePtr n;
  JsonArray() = default;
  explicit JsonArray(NodePtr p) : n(p) {}
  bool isNull() const { return !n || n->t != Node::ARR; }
  // Real ArduinoJson's JsonArray has both of these; draw_poly() proves a
  // two-element array with plain indexing and .size() instead of a manual
  // begin()/end() walk (docs/plans/dragon-feedback.md D12).
  size_t size() const { return n ? n->arr.size() : 0; }
  JsonVariant operator[](size_t i) const {
    return (n && i < n->arr.size()) ? JsonVariant(n->arr[i]) : JsonVariant();
  }
  struct iterator {
    const std::vector<NodePtr> *v;
    size_t i;
    bool operator!=(const iterator &o) const { return i != o.i; }
    void operator++() { i++; }
    JsonVariant operator*() const { return JsonVariant((*v)[i]); }
  };
  iterator begin() const { return iterator{n ? &n->arr : nullptr, 0}; }
  iterator end() const { return iterator{n ? &n->arr : nullptr, n ? n->arr.size() : 0}; }
};
class JsonObject {
 public:
  NodePtr n;
  JsonObject() = default;
  explicit JsonObject(NodePtr p) : n(p) {}
  bool isNull() const { return !n || n->t != Node::OBJ; }
  JsonVariant operator[](const char *k) const {
    if (n && n->t == Node::OBJ)
      for (auto &kv : n->obj)
        if (kv.first == k)
          return JsonVariant(kv.second);
    return JsonVariant();
  }
  struct iterator {
    const std::vector<std::pair<std::string, NodePtr>> *v;
    size_t i;
    bool operator!=(const iterator &o) const { return i != o.i; }
    void operator++() { i++; }
    JsonPair operator*() const { return JsonPair{(*v)[i].first, (*v)[i].second}; }
  };
  iterator begin() const { return iterator{n ? &n->obj : nullptr, 0}; }
  iterator end() const { return iterator{n ? &n->obj : nullptr, n ? n->obj.size() : 0}; }
};
inline JsonVariant::operator JsonArray() const {
  return JsonArray(n && n->t == Node::ARR ? n : nullptr);
}
inline JsonVariant::operator JsonObject() const {
  return JsonObject(n && n->t == Node::OBJ ? n : nullptr);
}
template <> inline bool JsonVariant::is<int>() const {
  return n && n->t == Node::INT && n->i >= INT32_MIN && n->i <= INT32_MAX;
}
template <> inline bool JsonVariant::is<float>() const {
  return n && (n->t == Node::FLT || n->t == Node::INT);
}
template <> inline bool JsonVariant::is<const char *>() const { return n && n->t == Node::STR; }
template <> inline bool JsonVariant::is<JsonObject>() const { return n && n->t == Node::OBJ; }
template <> inline int JsonVariant::as<int>() const { return n ? (int) n->i : 0; }
template <> inline float JsonVariant::as<float>() const {
  return n ? (n->t == Node::FLT ? (float) n->f : (float) n->i) : 0;
}
template <> inline JsonObject JsonVariant::as<JsonObject>() const { return JsonObject(n); }
template <> inline int JsonVariant::operator|<int>(int def) const {
  return is<int>() ? as<int>() : def;
}
template <> inline const char *JsonVariant::operator|<const char *>(const char *def) const {
  const char *s = *this;
  return s ? s : def;
}
template <> inline bool JsonVariant::operator|<bool>(bool def) const {
  return n && n->t == Node::BOOL ? n->b : def;
}

// A resizable canvas (draw_pixel_at bounds-checked, like the real panel's
// DisplayBuffer), shared by every harness: its RGB raster is diffed pixel
// for pixel against the Python renderer, or against another op run through
// this same harness (an independent oracle -- e.g. Display::filled_circle
// for draw_circle_ring). (222, 222, 216) is display_mcp.render.INK["white"]
// -- every scenario's `bg`, so an untouched (transparent) cell has to start
// out matching it.
class Canvas : public esphome::display::Display {
 public:
  int w, h;
  std::vector<esphome::Color> px;
  Canvas(int w_, int h_) : w(w_), h(h_), px(w_ * h_, esphome::Color(222, 222, 216)) {}
  void draw_pixel_at(int x, int y, esphome::Color c) override {
    if (x >= 0 && y >= 0 && x < w && y < h) px[y * w + x] = c;
  }
  esphome::display::DisplayType get_display_type() override {
    return esphome::display::DisplayType::DISPLAY_TYPE_COLOR;
  }
 protected:
  int get_width_internal() override { return w; }
  int get_height_internal() override { return h; }
};

// A tiny recursive-descent JSON parser for the harness's own stdin
// payload -- an op object, plus "_cw"/"_ch" telling run_harness() how big
// a canvas to raster into.
struct P {
  const std::string &s;
  size_t i = 0;
  P(const std::string &s) : s(s) {}
  void ws() { while (i < s.size() && isspace((unsigned char) s[i])) i++; }
  NodePtr val() {
    ws();
    char c = s[i];
    if (c == '{') return objv();
    if (c == '[') return arrv();
    if (c == '"') {
      auto n = std::make_shared<Node>();
      n->t = Node::STR;
      n->s = str();
      return n;
    }
    if (!strncmp(s.c_str() + i, "true", 4)) {
      i += 4;
      auto n = std::make_shared<Node>();
      n->t = Node::BOOL;
      n->b = true;
      return n;
    }
    if (!strncmp(s.c_str() + i, "false", 5)) {
      i += 5;
      auto n = std::make_shared<Node>();
      n->t = Node::BOOL;
      n->b = false;
      return n;
    }
    if (!strncmp(s.c_str() + i, "null", 4)) {
      i += 4;
      return std::make_shared<Node>();
    }
    size_t start = i;
    bool flt = false;
    while (i < s.size() &&
           (isdigit((unsigned char) s[i]) || s[i] == '-' || s[i] == '+' ||
            s[i] == '.' || s[i] == 'e' || s[i] == 'E')) {
      if (s[i] == '.' || s[i] == 'e' || s[i] == 'E') flt = true;
      i++;
    }
    auto n = std::make_shared<Node>();
    std::string num = s.substr(start, i - start);
    if (flt) {
      n->t = Node::FLT;
      n->f = atof(num.c_str());
    } else {
      n->t = Node::INT;
      n->i = atoll(num.c_str());
    }
    return n;
  }
  std::string str() {
    i++;
    std::string out;
    while (s[i] != '"') {
      if (s[i] == '\\') {
        i++;
        if (s[i] == 'u') {
          unsigned cp = strtoul(s.substr(i + 1, 4).c_str(), nullptr, 16);
          i += 5;
          if (cp < 0x80) {
            out += (char) cp;
          } else if (cp < 0x800) {
            out += (char) (0xC0 | (cp >> 6));
            out += (char) (0x80 | (cp & 0x3F));
          } else {
            out += (char) (0xE0 | (cp >> 12));
            out += (char) (0x80 | ((cp >> 6) & 0x3F));
            out += (char) (0x80 | (cp & 0x3F));
          }
          continue;
        }
        out += s[i++];
        continue;
      }
      out += s[i++];
    }
    i++;
    return out;
  }
  NodePtr arrv() {
    auto n = std::make_shared<Node>();
    n->t = Node::ARR;
    i++;
    ws();
    if (s[i] == ']') { i++; return n; }
    while (true) {
      n->arr.push_back(val());
      ws();
      if (s[i] == ',') { i++; continue; }
      i++;
      break;
    }
    return n;
  }
  NodePtr objv() {
    auto n = std::make_shared<Node>();
    n->t = Node::OBJ;
    i++;
    ws();
    if (s[i] == '}') { i++; return n; }
    while (true) {
      ws();
      std::string k = str();
      ws();
      i++;
      n->obj.push_back({k, val()});
      ws();
      if (s[i] == ',') { i++; continue; }
      i++;
      break;
    }
    return n;
  }
};

// The harness's own stdin/stdout protocol, shared by every op: read the op
// JSON (plus "_cw"/"_ch") from stdin, build a Canvas, hand both to `draw`,
// then write one byte (did it draw) followed by the raw RGB raster on
// stdout -- ESP_LOGW above prints to stderr so it never corrupts that
// binary stream.
template <typename F>
int run_harness(F draw) {
  std::string body;
  { int c; while ((c = getchar()) != EOF) body += (char) c; }
  P p(body);
  NodePtr root = p.val();
  JsonObject o(root);
  const int cw = o["_cw"] | 64;
  const int ch = o["_ch"] | 64;
  Canvas canvas(cw, ch);
  const bool drew = draw(canvas, o);
  const unsigned char drew_byte = drew ? 1 : 0;
  std::fwrite(&drew_byte, 1, 1, stdout);
  for (auto &c : canvas.px) {
    std::fwrite(&c.r, 1, 1, stdout);
    std::fwrite(&c.g, 1, 1, stdout);
    std::fwrite(&c.b, 1, 1, stdout);
  }
  return 0;
}
"""

# draw_*()'s resolve_ink(name, palette) is a big alias/built-in walk over a
# real document palette; this stand-in only needs the names the scenarios
# below actually use, and gives them exactly display_mcp.render.INK's own
# RGB triples (the panel's muted inks, not primary colours) so a pixel diff
# means something. "navy" and "grey-dark" are BUILTIN_MIXES entries;
# "flame" is samples/sprite.json's own document-palette recipe
# (red+yellow 50) -- real recipes, not stand-ins.
_RESOLVE_INK = r"""
inline Ink resolve_ink(const char *name, JsonObject) {
  std::string n = name ? name : "black";
  auto BLACK = esphome::Color(32, 32, 32);
  auto WHITE = esphome::Color(222, 222, 216);
  auto YELLOW = esphome::Color(206, 172, 44);
  auto RED = esphome::Color(156, 46, 42);
  auto BLUE = esphome::Color(46, 62, 128);
  auto GREEN = esphome::Color(72, 108, 66);
  if (n == "black") return Ink{BLACK, BLACK, 100};
  if (n == "white") return Ink{WHITE, WHITE, 100};
  if (n == "red") return Ink{RED, RED, 100};
  if (n == "blue") return Ink{BLUE, BLUE, 100};
  if (n == "yellow") return Ink{YELLOW, YELLOW, 100};
  if (n == "green") return Ink{GREEN, GREEN, 100};
  if (n == "navy") return Ink{BLACK, BLUE, 50};
  if (n == "grey-dark") return Ink{BLACK, WHITE, 25};
  if (n == "flame") return Ink{RED, YELLOW, 50};
  std::fprintf(stderr, "W unknown colour '%s', using black\n", n.c_str());
  return Ink{BLACK, BLACK, 100};
}
"""

WHITE = (222, 222, 216)  # display_mcp.render.INK["white"]; every Canvas's own background


def _compile(
    tmp_dir: Path, name: str, extracted_parts: str, main_src: str, *, sanitize: bool = False
) -> Path:
    """Compile one harness executable: `_STUB`, then this harness's own
    header fragments (extracted verbatim, never retyped) and `main()`.

    `sanitize` adds `-fsanitize=undefined -fno-sanitize-recover=all` --
    only draw_poly()'s harness needs it (poly_spans()'s int64_t crossing
    arithmetic is exactly the kind of thing UBSan catches that a plain
    -O1 build wouldn't, and -fno-sanitize-recover=all makes any such
    finding a hard failure here rather than a quiet stderr line the
    other harnesses would miss too).
    """
    src = tmp_dir / f"{name}.cpp"
    src.write_text(
        "// Host-compile harness for " + name + "(), extracted verbatim from\n"
        "// firmware/display_list.h. ArduinoJson and ESPHome are stubbed.\n"
        + _STUB + "\n" + extracted_parts + "\n" + main_src
    )
    exe = tmp_dir / name
    cmd = ["c++", "-std=c++17", "-O1"]
    if sanitize:
        cmd += ["-fsanitize=undefined", "-fno-sanitize-recover=all"]
    cmd += ["-o", str(exe), str(src)]
    subprocess.run(cmd, check=True)
    return exe


class _OpHarness:
    """One compiled executable, run once per op: encode `op` (plus the
    canvas size) as JSON on stdin, decode a drew-byte and the raw RGB
    raster off stdout. The same shape for sprite, poly, the rounded rect
    and the circle ring -- a harness whose `main()` needs to pick between
    more than one header function (the ring harness, `outer`/`inner`
    against `filled_circle` as well as the ring itself) reads that choice
    from an extra op field (`_shape`) rather than needing a second
    protocol.
    """

    def __init__(self, exe: Path):
        self.exe = exe

    def run(
        self, op: dict, cw: int, ch: int
    ) -> tuple[bool, list[list[tuple[int, int, int]]], list[str]]:
        payload = dict(op)
        payload["_cw"] = cw
        payload["_ch"] = ch
        out = subprocess.run(
            [str(self.exe)],
            input=json.dumps(payload).encode(),
            capture_output=True,
            check=True,
        )
        data = out.stdout
        drew = bool(data[0])
        raster = data[1:]
        assert len(raster) == cw * ch * 3, "harness printed the wrong number of bytes"
        pixels = [
            [tuple(raster[(y * cw + x) * 3 : (y * cw + x) * 3 + 3]) for x in range(cw)]
            for y in range(ch)
        ]
        logs = out.stderr.decode(errors="replace").splitlines()
        return drew, pixels, logs


def _pixels_py(op: dict, cw: int, ch: int, font_dir, palette: dict | None = None):
    """render() a one-op document and read back the same `cw`x`ch` window
    `_OpHarness.run()` returns -- the Python half of every diff below."""
    from display_mcp.render import render

    doc = {"v": 1, "bg": "white", "ops": [op]}
    if palette:
        doc["palette"] = palette
    img, problems = render(doc, font_dir)
    px = img.load()
    return [[px[x, y] for x in range(cw)] for y in range(ch)], problems


def _diff(harness: _OpHarness, font_dir, op: dict, cw: int, ch: int, palette: dict | None = None):
    """Run the same op through both renderers and return every
    (x, y, cpp_rgb, py_rgb) where they disagree, plus render()'s own
    problems -- empty diffs is the whole point of every test that calls
    this."""
    _drew, cpp_px, _logs = harness.run(op, cw, ch)
    py_px, problems = _pixels_py(op, cw, ch, font_dir, palette)
    diffs = [
        (x, y, cpp_px[y][x], py_px[y][x])
        for y in range(ch)
        for x in range(cw)
        if cpp_px[y][x] != py_px[y][x]
    ]
    return diffs, problems


# --------------------------------------------------------------------------
# Fixtures. Each skips cleanly without a host C++ compiler.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cpp_mix_on(tmp_path_factory):
    """Compile the header's own mix_on() and return a callable front end,
    as a full sweep of every (pct, x, y) in a 16x16 field."""
    if shutil.which("c++") is None:
        pytest.skip("no host C++ compiler")
    matrix = _extract(r"^static const uint8_t B\[2\]\[2\].*;$", "the Bayer matrix")
    fn = _extract(r"^inline bool mix_on\(.*$", "mix_on()")

    d = tmp_path_factory.mktemp("mix_on")
    src = d / "mix_on.cpp"
    src.write_text(
        "#include <cstdint>\n#include <cstdio>\n" + matrix + "\n" + fn
        + r"""
int main() {
  // Every percentage, not just the three legal densities: within
  // {25,50,75,100} a `/ 20` divisor is indistinguishable from `/ 25`, so
  // sweeping the whole range is what actually pins the arithmetic down.
  for (int pct = 0; pct <= 100; pct++)
    for (int y = 0; y < 16; y++)
      for (int x = 0; x < 16; x++)
        printf("%d %d %d %d\n", pct, x, y, mix_on(x, y, pct) ? 1 : 0);
  return 0;
}
"""
    )
    exe = d / "mix_on"
    subprocess.run(["c++", "-std=c++17", "-O0", "-o", str(exe), str(src)], check=True)
    out = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout
    table = {}
    for line in out.splitlines():
        pct, x, y, on = (int(v) for v in line.split())
        table[(pct, x, y)] = bool(on)
    return table


@pytest.fixture(scope="module")
def sprite_harness(tmp_path_factory) -> _OpHarness:
    """Compile draw_sprite() -- extracted verbatim, never retyped."""
    if shutil.which("c++") is None:
        pytest.skip("no host C++ compiler")
    parts = "\n".join([
        _extract(r"^static const uint8_t B\[2\]\[2\].*;$", "the Bayer matrix"),
        _extract(r"^inline bool mix_on\(.*$", "mix_on()"),
        _extract(r"^static const int kSpriteMaxCell = \d+;$", "kSpriteMaxCell"),
        _extract_block(r"^inline size_t utf8_prev\(", "utf8_prev()"),
        _extract_block(r"^inline size_t utf8_next\(", "utf8_next()"),
        _extract_block(r"^struct Ink \{", "struct Ink"),
        _extract_block(
            r"^class MixDisplay : public esphome::display::Display \{", "MixDisplay"
        ),
        _RESOLVE_INK,
        _extract_block(r"^inline bool draw_sprite\(", "draw_sprite()"),
    ])
    main_src = r"""
int main() {
  JsonObject palette;  // draw_sprite()'s second arg; unused by the resolve_ink stub above
  return run_harness([&](Canvas &canvas, JsonObject o) {
    return draw_sprite(canvas, o, palette);
  });
}
"""
    exe = _compile(tmp_path_factory.mktemp("sprite_parity"), "sprite_harness", parts, main_src)
    return _OpHarness(exe)


@pytest.fixture(scope="module")
def poly_harness(tmp_path_factory) -> _OpHarness:
    """Compile draw_poly() -- extracted verbatim, never retyped -- with
    -fsanitize=undefined (the fill's int64_t crossing arithmetic is exactly
    the kind of thing UBSan catches that a plain -O1 build wouldn't)."""
    if shutil.which("c++") is None:
        pytest.skip("no host C++ compiler")
    parts = "\n".join([
        _extract(r"^static const uint8_t B\[2\]\[2\].*;$", "the Bayer matrix"),
        _extract(r"^inline bool mix_on\(.*$", "mix_on()"),
        _extract_block(r"^struct Ink \{", "struct Ink"),
        _extract_block(
            r"^class MixDisplay : public esphome::display::Display \{", "MixDisplay"
        ),
        _extract(r"^static const int kThickMax = \d+;$", "kThickMax"),
        _extract_block(r"^inline void thick_line\(", "thick_line()"),
        _RESOLVE_INK,
        _extract_block(r"^inline int64_t floor_div\(", "floor_div()"),
        _extract(r"^static const int32_t kPolyMaxCoord = .*;$", "kPolyMaxCoord"),
        _extract_block(r"^inline void poly_spans\(", "poly_spans()"),
        _extract_block(r"^inline bool draw_poly\(", "draw_poly()"),
    ])
    main_src = r"""
int main() {
  JsonObject palette;  // draw_poly() takes none; the resolve_ink stub ignores it too
  return run_harness([&](Canvas &canvas, JsonObject o) {
    const Ink ink = resolve_ink(o["c"] | "black", palette);
    MixDisplay mix(canvas);
    mix.add_ink(ink.a, ink);
    return draw_poly(mix, o, ink);
  });
}
"""
    exe = _compile(
        tmp_path_factory.mktemp("poly_parity"), "poly_harness", parts, main_src, sanitize=True
    )
    return _OpHarness(exe)


@pytest.fixture(scope="module")
def rect_harness(tmp_path_factory) -> _OpHarness:
    """Compile draw_rounded_rect() -- extracted verbatim, never retyped.
    Op shape: {x, y, w, h, r, c}."""
    if shutil.which("c++") is None:
        pytest.skip("no host C++ compiler")
    parts = "\n".join([
        _extract_block(r"^struct Ink \{", "struct Ink"),
        _RESOLVE_INK,
        _extract_block(r"^inline void draw_rounded_rect\(", "draw_rounded_rect()"),
    ])
    main_src = r"""
int main() {
  JsonObject palette;
  return run_harness([&](Canvas &canvas, JsonObject o) {
    const Ink ink = resolve_ink(o["c"] | "black", palette);
    const int x = o["x"] | 0, y = o["y"] | 0, w = o["w"] | 0, h = o["h"] | 0, r = o["r"] | 0;
    draw_rounded_rect(canvas, x, y, w, h, r, ink.a);
    return true;
  });
}
"""
    exe = _compile(tmp_path_factory.mktemp("rect_parity"), "rect_harness", parts, main_src)
    return _OpHarness(exe)


@pytest.fixture(scope="module")
def circle_ring_harness(tmp_path_factory) -> _OpHarness:
    """Compile circle_half_widths()/draw_circle_ring() -- extracted
    verbatim, never retyped. Op shape: {x, y, r, t, c}, plus an op-only
    `_shape` field ("ring", the default, or "filled_circle") so the same
    executable can also stand in for the independent oracle
    (Display::filled_circle) the ring is diffed against -- calling
    Canvas::filled_circle directly, not through draw_circle_ring, so that
    diff stays against an independent primitive rather than the ring
    checking itself."""
    if shutil.which("c++") is None:
        pytest.skip("no host C++ compiler")
    parts = "\n".join([
        _extract_block(r"^struct Ink \{", "struct Ink"),
        _RESOLVE_INK,
        _extract_block(r"^inline void circle_half_widths\(", "circle_half_widths()"),
        _extract_block(r"^inline void draw_circle_ring\(", "draw_circle_ring()"),
    ])
    main_src = r"""
int main() {
  JsonObject palette;
  return run_harness([&](Canvas &canvas, JsonObject o) {
    const Ink ink = resolve_ink(o["c"] | "black", palette);
    const char *shape = o["_shape"] | "ring";
    const int x = o["x"] | 0, y = o["y"] | 0, r = o["r"] | 0;
    if (!strcmp(shape, "filled_circle")) {
      if (r >= 0) canvas.filled_circle(x, y, r, ink.a);
    } else {
      const int t = o["t"] | 1;
      draw_circle_ring(canvas, x, y, r, t, ink.a);
    }
    return true;
  });
}
"""
    exe = _compile(
        tmp_path_factory.mktemp("circle_ring_parity"), "circle_ring_harness", parts, main_src
    )
    return _OpHarness(exe)
