"""Differential tests: the shipped firmware header against the Python renderer.

`firmware/display_list.h` is authoritative (docs/SPEC.md) and
`display_mcp.render` mirrors it, so where the two disagree the Python is the
bug. The wrap/truncate pair has been diffed this way since the port; this
module does the same for the ink-mixing mask.

The C++ is **extracted from the shipped header**, never retyped here — a copy
would only prove that two copies agree. If the header's shape changes enough
that the extraction fails, that is a test failure and not a silent skip.

Needs a host C++ compiler; skips cleanly without one.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from display_mcp.render import BUILTIN_MIXES, DENSITIES, INK, check, mix_on, render

HEADER = Path(__file__).resolve().parents[1] / "firmware" / "display_list.h"

# Only the mix_on tests need a compiler; the table tests are pure data and
# always run, so a machine without a toolchain still catches a drifted table.


def _extract(pattern: str, what: str) -> str:
    src = HEADER.read_text()
    m = re.search(pattern, src, re.MULTILINE)
    assert m, f"could not find {what} in {HEADER.name} — has it been renamed?"
    return m.group(0)


@pytest.fixture(scope="module")
def cpp_mix_on(tmp_path_factory):
    """Compile the header's own mix_on and return a callable front end."""
    if shutil.which("c++") is None:
        pytest.skip("no host C++ compiler")
    matrix = _extract(r"^static const uint8_t B\[2\]\[2\].*;$", "the Bayer matrix")
    fn = _extract(r"^inline bool mix_on\(.*$", "mix_on()")

    d = tmp_path_factory.mktemp("parity")
    src = d / "mix_on.cpp"
    src.write_text(
        textwrap.dedent(
            """\
            #include <cstdint>
            #include <cstdio>
            %s
            %s
            int main() {
              // Every percentage, not just the three legal densities: within
              // {25,50,75,100} a `/ 20` divisor is indistinguishable from
              // `/ 25`, so sweeping the whole range is what actually pins the
              // arithmetic down.
              for (int pct = 0; pct <= 100; pct++)
                for (int y = 0; y < 16; y++)
                  for (int x = 0; x < 16; x++)
                    printf("%%d %%d %%d %%d\\n", pct, x, y,
                           mix_on(x, y, pct) ? 1 : 0);
              return 0;
            }
            """
        )
        % (matrix, fn)
    )
    exe = d / "mix_on"
    subprocess.run(
        ["c++", "-std=c++17", "-O0", "-o", str(exe), str(src)], check=True
    )
    out = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout
    table = {}
    for line in out.splitlines():
        pct, x, y, on = (int(v) for v in line.split())
        table[(pct, x, y)] = bool(on)
    return table


def test_mix_on_matches_the_firmware(cpp_mix_on):
    """Every cell, every density: the two implementations must agree."""
    disagreements = [
        (pct, x, y, want, mix_on(x, y, pct))
        for (pct, x, y), want in cpp_mix_on.items()
        if mix_on(x, y, pct) != want
    ]
    assert not disagreements, f"{len(disagreements)} cells differ, e.g. {disagreements[:4]}"


@pytest.mark.parametrize("pct", DENSITIES)
def test_firmware_densities_are_exact(cpp_mix_on, pct):
    """The compiled mask really does select pct% of a 16x16 field."""
    on = sum(1 for (p, _, _), v in cpp_mix_on.items() if p == pct and v)
    assert on / 256 == pct / 100


def test_firmware_50_percent_is_the_historic_checkerboard(cpp_mix_on):
    """The compatibility claim, checked against the compiled header rather
    than against the comment that asserts it: every shipped document using
    `tone` depends on the 50% mask being exactly `(x + y) % 2 == 0`."""
    assert all(
        v == ((x + y) % 2 == 0)
        for (pct, x, y), v in cpp_mix_on.items()
        if pct == 50
    )


# --------------------------------------------------------------------------
# the built-in mix table — docs/plans/ink-mixing.md decision 10
#
# Twenty-one entries transcribed between C++ and Python is exactly where a
# typo hides and is never noticed: the wrong colour still draws, still
# validates, and only looks slightly off on a wall nobody is measuring. The
# table is a permanent contract, so it is diffed rather than trusted.
#
# This one needs no compiler — it is a data table, not behaviour — so unlike
# the mix_on tests above it always runs.
# --------------------------------------------------------------------------

_ENTRY_RE = re.compile(
    r'^\s*\{"(?P<name>[a-z-]+)",\s*"(?P<c>[a-z]+)",\s*"(?P<c2>[a-z]+)",\s*(?P<mix>\d+)\},\s*$',
    re.MULTILINE,
)


def _firmware_table() -> dict[str, tuple[str, str, int]]:
    src = HEADER.read_text()
    start = src.index("BUILTIN_MIXES[]")
    end = src.index("};", start)
    table = {
        m.group("name"): (m.group("c"), m.group("c2"), int(m.group("mix")))
        for m in _ENTRY_RE.finditer(src[start:end])
    }
    assert table, f"could not extract BUILTIN_MIXES from {HEADER.name}"
    return table


def test_builtin_table_has_no_compiler_dependency():
    """Guard the guard: if the extraction silently matched nothing, every
    comparison below would pass vacuously."""
    assert len(_firmware_table()) == len(BUILTIN_MIXES) > 0


def test_builtin_names_match_the_firmware():
    fw = _firmware_table()
    assert set(fw) == set(BUILTIN_MIXES), (
        f"only in firmware: {sorted(set(fw) - set(BUILTIN_MIXES))}; "
        f"only in python: {sorted(set(BUILTIN_MIXES) - set(fw))}"
    )


@pytest.mark.parametrize("name", sorted(BUILTIN_MIXES))
def test_builtin_recipe_matches_the_firmware(name):
    fw = _firmware_table()
    assert fw[name] == BUILTIN_MIXES[name], (
        f"{name}: firmware says {fw[name]}, python says {BUILTIN_MIXES[name]}"
    )


@pytest.mark.parametrize("name,recipe", sorted(BUILTIN_MIXES.items()))
def test_builtin_recipes_are_well_formed(name, recipe):
    """Every entry names two real, different inks at a legal density."""
    c, c2, mix = recipe
    assert c in INK, f"{name}: unknown base ink {c!r}"
    assert c2 in INK, f"{name}: unknown second ink {c2!r}"
    assert c != c2, f"{name}: c and c2 are the same ink, so it is not a mix"
    assert mix in DENSITIES, f"{name}: density {mix} is not one of {DENSITIES}"


def test_builtin_names_are_documented_in_the_spec():
    """A name the spec does not carry is a name no caller can discover."""
    spec = (HEADER.parent.parent / "docs" / "SPEC.md").read_text()
    missing = [n for n in BUILTIN_MIXES if f"`{n}`" not in spec]
    assert not missing, f"not in docs/SPEC.md: {missing}"


# --------------------------------------------------------------------------
# sprite (docs/plans/dragon-feedback.md B1) -- the op loop must actually
# dispatch on it, so the two sides cannot silently diverge on whether it
# exists at all.
# --------------------------------------------------------------------------


def test_op_loop_has_a_sprite_branch():
    src = HEADER.read_text()
    assert 'strcmp(kind, "sprite")' in src


# --------------------------------------------------------------------------
# sprite, differentially (docs/plans/dragon-feedback.md F5). draw_sprite()
# was factored out of the op loop precisely so it -- and utf8_prev/
# utf8_next/mix_on/struct Ink/MixDisplay, which it's built on -- can be
# extracted verbatim, compiled against a stub Display/ArduinoJson, and
# rasterised, then diffed pixel-for-pixel against
# display_mcp.render.render(). JSON edge cases that never reach the pixels
# (a palette key that isn't one character, a non-string row element, a bad
# mirror value...) are exercised on the Python side in test_render.py;
# this module only has to prove the two sides paint the same thing once an
# op's fields are legal.
#
# Needs a host C++ compiler; skips cleanly without one, like cpp_mix_on
# above.
# --------------------------------------------------------------------------


def _extract_block(pattern: str, what: str) -> str:
    """Like `_extract`, but for a brace-delimited definition (a function
    body, a struct, a class) that a naive `.*?\\}` regex can't safely
    bound -- it would stop at the first `}` a nested block contains.
    Finds the start, then counts braces from the first `{` to its match;
    a trailing `;` (a struct/class definition) is swept in too.
    """
    src = HEADER.read_text()
    m = re.search(pattern, src, re.MULTILINE)
    assert m, f"could not find {what} in {HEADER.name} — has it been renamed?"
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


# A stand-in for the slice of ArduinoJson and ESPHome draw_sprite() actually
# touches: JsonObject/JsonArray/JsonVariant/JsonPair with the same
# `[]`/`|`/`is<T>()`/`as<T>()` surface, and a `display::Display` whose
# `filled_rectangle()` calls `draw_pixel_at()` like the real one.
_STUB_ESPHOME_AND_JSON = r"""
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
  void filled_rectangle(int x1, int y1, int w, int h, Color c) {
    for (int yy = y1; yy < y1 + h; yy++)
      for (int xx = x1; xx < x1 + w; xx++)
        this->draw_pixel_at(xx, yy, c);
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
"""

# draw_sprite()'s resolve_ink(name, palette) is a big alias/built-in walk
# over a real document palette; this stand-in only needs the names the
# scenarios below actually use, and gives them exactly
# display_mcp.render.INK's own RGB triples (the panel's muted inks, not
# primary colours) so a pixel diff means something. "navy" and
# "grey-dark" are BUILTIN_MIXES entries; "flame" is samples/sprite.json's
# own document-palette recipe (red+yellow 50) — real recipes, not
# stand-ins.
_STUB_RESOLVE_INK = r"""
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

# A resizable canvas (draw_pixel_at bounds-checked, like the real panel's
# DisplayBuffer) plus a tiny recursive-descent JSON parser for the harness's
# own stdin payload -- draw_sprite()'s op object, plus "_cw"/"_ch" telling
# main() how big a canvas to raster into. Output on stdout is one byte (did
# it draw) followed by the raw RGB raster; ESP_LOGW above prints to stderr
# so it never corrupts that binary stream.
_HARNESS_MAIN = r"""
class Canvas : public esphome::display::Display {
 public:
  int w, h;
  std::vector<esphome::Color> px;
  // (222, 222, 216) is display_mcp.render.INK["white"] -- every scenario's
  // `bg`, so an untouched (transparent) cell has to start out matching it.
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

int main() {
  std::string body;
  { int c; while ((c = getchar()) != EOF) body += (char) c; }
  P p(body);
  NodePtr root = p.val();
  JsonObject o(root);
  JsonObject palette;  // draw_sprite()'s second arg; unused by the resolve_ink stub above
  const int cw = o["_cw"] | 64;
  const int ch = o["_ch"] | 64;
  Canvas canvas(cw, ch);
  const bool drew = draw_sprite(canvas, o, palette);
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


class _SpriteHarness:
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


@pytest.fixture(scope="module")
def sprite_harness(tmp_path_factory) -> _SpriteHarness:
    """Compile draw_sprite() -- extracted verbatim from the shipped header,
    never retyped -- against the stubs above, once for the module."""
    if shutil.which("c++") is None:
        pytest.skip("no host C++ compiler")

    matrix = _extract(r"^static const uint8_t B\[2\]\[2\].*;$", "the Bayer matrix")
    mix_on_fn = _extract(r"^inline bool mix_on\(.*$", "mix_on()")
    utf8_prev_fn = _extract_block(r"^inline size_t utf8_prev\(", "utf8_prev()")
    utf8_next_fn = _extract_block(r"^inline size_t utf8_next\(", "utf8_next()")
    ink_struct = _extract_block(r"^struct Ink \{", "struct Ink")
    mixdisplay_cls = _extract_block(
        r"^class MixDisplay : public esphome::display::Display \{", "MixDisplay"
    )
    draw_sprite_fn = _extract_block(r"^inline bool draw_sprite\(", "draw_sprite()")

    d = tmp_path_factory.mktemp("sprite_parity")
    src = d / "sprite_harness.cpp"
    src.write_text(
        "// Host-compile harness for draw_sprite(), extracted verbatim from\n"
        "// firmware/display_list.h. ArduinoJson and ESPHome are stubbed.\n"
        "#include <algorithm>\n#include <cctype>\n#include <cstdint>\n"
        "#include <cstdio>\n#include <cstring>\n#include <map>\n"
        "#include <memory>\n#include <set>\n#include <string>\n#include <vector>\n\n"
        + _STUB_ESPHOME_AND_JSON
        + "\n" + matrix + "\n" + mix_on_fn
        + "\n" + utf8_prev_fn + "\n" + utf8_next_fn
        + "\n" + ink_struct + "\n" + mixdisplay_cls
        + "\n" + _STUB_RESOLVE_INK
        + "\n" + draw_sprite_fn
        + "\n" + _HARNESS_MAIN
    )
    exe = d / "sprite_harness"
    subprocess.run(["c++", "-std=c++17", "-O1", "-o", str(exe), str(src)], check=True)
    return _SpriteHarness(exe)


def _sprite_pixels_py(op, cw, ch, font_dir, palette=None):
    doc = {"v": 1, "bg": "white", "ops": [op]}
    if palette:
        doc["palette"] = palette
    img, problems = render(doc, font_dir)
    px = img.load()
    return [[px[x, y] for x in range(cw)] for y in range(ch)], problems


def _sprite_diff(sprite_harness, font_dir, op, cw, ch, palette=None):
    """Run the same op through both renderers and return every
    (x, y, cpp_rgb, py_rgb) where they disagree, plus render()'s own
    problems -- empty diffs is the whole point of the test."""
    _drew, cpp_px, _logs = sprite_harness.run(op, cw, ch)
    py_px, problems = _sprite_pixels_py(op, cw, ch, font_dir, palette)
    diffs = [
        (x, y, cpp_px[y][x], py_px[y][x])
        for y in range(ch)
        for x in range(cw)
        if cpp_px[y][x] != py_px[y][x]
    ]
    return diffs, problems


def test_sprite_multibyte_row_matches_the_firmware(sprite_harness, font_dir):
    """`{"palette": {"█": "black", "▄": "red"}, "rows": ["█▄█"]}` draws
    three cells, not nine (F1) -- the whole point of walking by codepoint,
    on both sides."""
    diffs, problems = _sprite_diff(
        sprite_harness,
        font_dir,
        {
            "op": "sprite", "x": 0, "y": 0, "cell": 10,
            "palette": {"█": "black", "▄": "red"}, "rows": ["█▄█"],
        },
        30, 10,
    )
    assert problems == []
    assert not diffs, diffs[:5]


def test_sprite_abutting_mixed_runs_at_odd_origin_match_the_firmware(sprite_harness, font_dir):
    diffs, problems = _sprite_diff(
        sprite_harness,
        font_dir,
        {
            "op": "sprite", "x": 1, "y": 1, "cell": 6,
            "palette": {"N": "navy", "D": "grey-dark"}, "rows": ["NNDD"],
        },
        30, 10,
    )
    assert problems == []
    assert not diffs, diffs[:5]


def test_sprite_mirrored_ragged_matches_the_firmware(sprite_harness, font_dir):
    diffs, problems = _sprite_diff(
        sprite_harness,
        font_dir,
        {
            "op": "sprite", "x": 0, "y": 0, "cell": 5,
            "palette": {"K": "black", "O": "red"},
            "rows": ["KKKKK", "OK", "KOK"], "mirror": "x",
        },
        30, 20,
    )
    assert len(problems) == 1 and "ragged" in problems[0]
    assert not diffs, diffs[:5]


def test_sprite_3x3_mixed_block_matches_a_rect(sprite_harness, font_dir):
    """A uniform 3x3 grid of one mixed character is, pixel for pixel, the
    same box a single `rect` of the same colour fills -- proof that
    run-merging across several rows costs nothing at the seams, on the
    compiled side as much as the Python's own
    test_sprite_mixed_cell_dithers_identically_to_a_rect does."""
    op = {
        "op": "sprite", "x": 0, "y": 0, "cell": 10,
        "palette": {"K": "navy"}, "rows": ["KKK", "KKK", "KKK"],
    }
    drew, cpp_px, logs = sprite_harness.run(op, 30, 30)
    assert drew and not logs
    rect_doc = {
        "v": 1, "bg": "white",
        "ops": [{"op": "rect", "x": 0, "y": 0, "w": 30, "h": 30, "c": "navy"}],
    }
    img, problems = render(rect_doc, font_dir)
    assert problems == []
    px = img.load()
    diffs = [
        (x, y, cpp_px[y][x], px[x, y])
        for y in range(30)
        for x in range(30)
        if cpp_px[y][x] != px[x, y]
    ]
    assert not diffs, diffs[:5]


def test_sprite_sample_matches_the_firmware(sprite_harness, font_dir, sprite_sample_doc):
    """samples/sprite.json's own sprite op, verbatim but for x=y=0 -- only
    the relative pixels matter for a dithering-phase diff, not where the
    real document places the dragon on the panel."""
    op = dict(next(o for o in sprite_sample_doc["ops"] if o["op"] == "sprite"))
    op["x"] = op["y"] = 0
    cw = max(len(r) for r in op["rows"]) * op["cell"]
    ch = len(op["rows"]) * op["cell"]
    diffs, problems = _sprite_diff(
        sprite_harness, font_dir, op, cw, ch, palette=sprite_sample_doc.get("palette")
    )
    assert problems == []
    assert not diffs, diffs[:5]


def test_sprite_oversized_cell_is_malformed_on_both_sides(sprite_harness, font_dir):
    """F7: the two sides have to agree on the bound, not just each avoid
    overflowing on their own terms."""
    op = {
        "op": "sprite", "x": 0, "y": 0, "cell": 99999,
        "palette": {"K": "black"}, "rows": ["K"],
    }
    drew, _px, logs = sprite_harness.run(op, 10, 10)
    assert not drew
    assert any("cell" in log for log in logs)
    problems = check({"v": 1, "bg": "white", "ops": [op]}, font_dir)
    assert any("nothing to draw, skipped" in p for p in problems)
