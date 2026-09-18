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

from display_mcp.render import (
    BUILTIN_MIXES,
    DENSITIES,
    HEIGHT,
    INK,
    POLY_MAX_COORD,
    SPRITE_MAX_CELL,
    THICK_MAX,
    WIDTH,
    check,
    mix_on,
    render,
)

HEADER = Path(__file__).resolve().parents[1] / "firmware" / "display_list.h"

# Only the mix_on tests need a compiler; the table tests are pure data and
# always run, so a machine without a toolchain still catches a drifted table.


def _extract(pattern: str, what: str) -> str:
    src = HEADER.read_text()
    m = re.search(pattern, src, re.MULTILINE)
    assert m, f"could not find {what} in {HEADER.name} — has it been renamed?"
    return m.group(0)


def _firmware_const_value(name: str) -> int:
    """A namespace-scope `static const int[32_t] <name> = <expr>;` from the
    header, evaluated as Python -- a C++ integer-literal expression like
    `1 << 20` is also a valid Python one, and this only ever runs against
    our own header, not untrusted input. Pure text, no compiler needed."""
    src = HEADER.read_text()
    m = re.search(rf"^static const int(?:32_t)? {name} = (?P<value>.+);$", src, re.MULTILINE)
    assert m, f"could not find {name} in {HEADER.name} — has it been renamed?"
    return eval(m.group("value"), {"__builtins__": {}})  # noqa: S307 - our own header


def test_device_safety_limits_match_the_firmware():
    """THICK_MAX/SPRITE_MAX_CELL/POLY_MAX_COORD (docs/plans/dragon-feedback.md
    D9/D12) are the same bound on both sides -- kThickMax, kSpriteMaxCell and
    kPolyMaxCoord sit together at namespace scope in the header the same way
    these three do here. Pure data, no compiler needed."""
    assert _firmware_const_value("kThickMax") == THICK_MAX
    assert _firmware_const_value("kSpriteMaxCell") == SPRITE_MAX_CELL
    assert _firmware_const_value("kPolyMaxCoord") == POLY_MAX_COORD


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


def test_builtin_mixes_match_the_firmware():
    """The firmware's table is the same 21 names with the same recipes as
    Python's, and every recipe names two real, different inks at a legal
    density -- the SPEC-table parser test (test_render.py) is the stronger
    check that every name is documented, so this stays firmware-focused."""
    fw = _firmware_table()
    diff = sorted(n for n in fw.keys() & BUILTIN_MIXES.keys() if fw[n] != BUILTIN_MIXES[n])
    assert fw == BUILTIN_MIXES, (
        f"only in firmware: {sorted(set(fw) - set(BUILTIN_MIXES))}; "
        f"only in python: {sorted(set(BUILTIN_MIXES) - set(fw))}; "
        f"differing recipes: {diff}"
    )
    for name, (c, c2, mix) in BUILTIN_MIXES.items():
        assert c in INK, f"{name}: unknown base ink {c!r}"
        assert c2 in INK, f"{name}: unknown second ink {c2!r}"
        assert c != c2, f"{name}: c and c2 are the same ink, so it is not a mix"
        assert mix in DENSITIES, f"{name}: density {mix} is not one of {DENSITIES}"


# --------------------------------------------------------------------------
# Compiled glyph set (docs/plans/dragon-feedback.md D11): epaper-schedule.yaml
# is what actually tells the ESPHome build which code points to compile in,
# so it -- not display_list.h -- is the oracle here. No compiler needed:
# this is a data comparison, like the BUILTIN_MIXES table above.
# --------------------------------------------------------------------------

YAML = HEADER.parent / "epaper-schedule.yaml"


def _yaml_font_entries() -> list[str]:
    """One block of text per `font:` list entry, id to id, so each font's
    own `glyphsets:`/`glyphs:` lines can be checked in isolation."""
    src = YAML.read_text()
    start = src.index("\nfont:\n")
    end = src.index("\n\n", start + 1)
    block = src[start:end]
    ids = [m.start() for m in re.finditer(r"^\s*- file:", block, re.MULTILINE)]
    ids.append(len(block))
    return [block[a:b] for a, b in zip(ids, ids[1:], strict=False)]


def test_every_font_entry_lists_gf_latin_core():
    entries = _yaml_font_entries()
    assert len(entries) == 6, f"expected six font entries, found {len(entries)}"
    missing = [e.splitlines()[1] for e in entries if "glyphsets: [GF_Latin_Core]" not in e]
    assert not missing, f"entries missing 'glyphsets: [GF_Latin_Core]': {missing}"


def test_mono_extra_glyph_range_matches_the_yaml():
    """`font_mono`'s `glyphs:` string, decoded back to code points, must be
    exactly `Face("mono").extra_glyphs` -- the YAML and the Python table
    are two independent statements of the same range, and either one
    drifting silently un-compiles or over-promises glyphs."""
    from display_mcp.render import FONTS

    entries = _yaml_font_entries()
    mono_entry = next(e for e in entries if "font_mono" in e)
    m = re.search(r'glyphs: "(.*?)"', mono_entry)
    assert m, "font_mono entry has no glyphs: string"
    yaml_codepoints = {ord(c) for c in m.group(1)}

    (extra_range,) = FONTS["mono"].extra_glyphs
    assert yaml_codepoints == set(extra_range), (
        f"yaml has {len(yaml_codepoints)} code points, "
        f"Face('mono').extra_glyphs has {len(set(extra_range))}"
    )


# --------------------------------------------------------------------------
# sprite (docs/plans/dragon-feedback.md B1) -- the op loop must actually
# dispatch on it, so the two sides cannot silently diverge on whether it
# exists at all.
# --------------------------------------------------------------------------


def test_op_loop_dispatches_every_compiled_op():
    """The op loop must actually dispatch on sprite and poly, so the two
    sides cannot silently diverge on whether either op exists at all; and
    the rect/circle branches must read the field the plan says (D10, B2)
    and hand off to the right helper, not just contain the field name
    somewhere in the file. These harnesses test the functions the branches
    call, not the dispatch itself -- this is the one test of the dispatch."""
    src = HEADER.read_text()
    assert 'strcmp(kind, "sprite")' in src
    assert 'strcmp(kind, "poly")' in src

    rect_block = _branch(src, 'strcmp(kind, "rect")', 'strcmp(kind, "line")')
    assert 'o["r"]' in rect_block
    assert "draw_rounded_rect(" in rect_block

    circle_block = _branch(src, 'strcmp(kind, "circle")', 'strcmp(kind, "text")')
    assert 'o["t"]' in circle_block
    assert "draw_circle_ring(" in circle_block


# --------------------------------------------------------------------------
# sprite, differentially. draw_sprite() is factored out of the op loop
# precisely so it -- and utf8_prev/
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
  // esphome::display::Display::line(), transcribed verbatim from
  // esphome/components/display/display.cpp (the real package, pip
  // downloaded to check this, not reinvented) -- what draw_poly()'s
  // thick_line() calls on the real panel, and the one primitive this
  // module's own stub had never needed before poly's outline (line/rect
  // outline thickness is eyeball parity, not diffed here). A from-scratch
  // Bresenham risks disagreeing with the real one at some tie-break;
  // this doesn't, because it isn't one.
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
  // Real ArduinoJson's JsonArray has both of these; this stub needs them
  // too, so draw_poly() can prove a two-element array with plain indexing
  // and .size() instead of a manual begin()/end() walk
  // (docs/plans/dragon-feedback.md D12).
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
    sprite_max_cell_const = _extract(
        r"^static const int kSpriteMaxCell = \d+;$", "kSpriteMaxCell"
    )
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
        "#include <cstdio>\n#include <cstdlib>\n#include <cstring>\n#include <map>\n"
        "#include <memory>\n#include <set>\n#include <string>\n#include <vector>\n\n"
        + _STUB_ESPHOME_AND_JSON
        + "\n" + matrix + "\n" + mix_on_fn
        + "\n" + sprite_max_cell_const
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
    three cells, not nine -- the whole point of walking by codepoint,
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
    """The two sides have to agree on the bound, not just each avoid
    overflowing on their own terms -- including the bound itself, which the
    message states so the two tables (here and in draw_sprite()) can't
    silently drift."""
    op = {
        "op": "sprite", "x": 0, "y": 0, "cell": 99999,
        "palette": {"K": "black"}, "rows": ["K"],
    }
    drew, _px, logs = sprite_harness.run(op, 10, 10)
    assert not drew
    assert any("cell" in log for log in logs)
    problems = check({"v": 1, "bg": "white", "ops": [op]}, font_dir)
    assert any("nothing to draw, skipped" in p for p in problems)
    assert any(f"<= {max(WIDTH, HEIGHT)}" in p for p in problems)


# --------------------------------------------------------------------------
# rect r / circle t (docs/plans/dragon-feedback.md D10, B2) -- both fields
# must actually be read where the plan says, extracted the same crude way
# the sprite-branch test above is: the field name has to appear inside the
# right branch of the op dispatch, not just anywhere in the file.
# --------------------------------------------------------------------------


def _branch(src: str, start_marker: str, end_marker: str) -> str:
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


# --------------------------------------------------------------------------
# draw_rounded_rect, differentially (docs/plans/dragon-feedback.md D10) --
# extracted verbatim from the header, compiled against a minimal Display
# stub (filled_rectangle/filled_circle only; draw_rounded_rect calls
# nothing else), and compared against the Python's own
# `_draw_rounded_rect()` for a handful of sizes.
#
# Eyeball, not pixel, parity is the standard here (both docstrings say so):
# PIL's ellipse and ESPHome's midpoint filled_circle round their arcs
# slightly differently, so the diff below checks what the two sides
# actually promise to agree on -- the overall bounding box and the three
# straight bands (the middle band and the two side bands) -- rather than
# the handful of corner-arc pixels that are allowed to differ.
#
# Needs a host C++ compiler; skips cleanly without one, like the other
# compiled parity fixtures in this module.
# --------------------------------------------------------------------------

_ROUNDED_RECT_STUB = r"""
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
namespace esphome {
struct Color {
  uint8_t r = 0, g = 0, b = 0;
  Color() = default;
  Color(int r_, int g_, int b_) : r(r_), g(g_), b(b_) {}
};
namespace display {
class Display {
 public:
  virtual ~Display() = default;
  virtual void draw_pixel_at(int x, int y, Color c) = 0;
  void horizontal_line(int x, int y, int width, Color c) {
    for (int i = x; i < x + width; i++) this->draw_pixel_at(i, y, c);
  }
  void filled_rectangle(int x1, int y1, int w, int h, Color c) {
    for (int i = y1; i < y1 + h; i++) this->horizontal_line(x1, i, w, c);
  }
  // Transcribed from esphome::display::Display (esphome/components/display/
  // display.cpp), the same midpoint routine display_list.h's own
  // filled_circle() calls -- not reinvented here, so draw_rounded_rect()'s
  // circles match the panel's own rasteriser.
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
};
}  // namespace display
}  // namespace esphome
"""

_ROUNDED_RECT_MAIN = r"""
class Canvas : public esphome::display::Display {
 public:
  int w, h;
  std::vector<uint8_t> px;
  Canvas(int w_, int h_) : w(w_), h(h_), px(w_ * h_, 0) {}
  void draw_pixel_at(int x, int y, esphome::Color c) override {
    if (x >= 0 && y >= 0 && x < w && y < h) px[y * w + x] = 1;
  }
};
// argv: x y w h r pad -- prints one (w + 2*pad) * (h + 2*pad) raster
// ('#'/'.'), drawn at (pad, pad) so a corner circle centred off the
// nominal box (there isn't one here) still has room to show up.
int main(int argc, char **argv) {
  int x = atoi(argv[1]), y = atoi(argv[2]), w = atoi(argv[3]), h = atoi(argv[4]);
  int r = atoi(argv[5]), pad = atoi(argv[6]);
  int cw = w + 2 * pad, ch = h + 2 * pad;
  Canvas canvas(cw, ch);
  esphome::Color c(1, 1, 1);
  draw_rounded_rect(canvas, x + pad, y + pad, w, h, r, c);
  for (auto v : canvas.px) putchar(v ? '#' : '.');
  return 0;
}
"""


@pytest.fixture(scope="module")
def rounded_rect_harness(tmp_path_factory):
    """Compile draw_rounded_rect() -- extracted verbatim from the shipped
    header, never retyped -- against the stand-in Display above, once for
    the module."""
    if shutil.which("c++") is None:
        pytest.skip("no host C++ compiler")
    fn = _extract_block(r"^inline void draw_rounded_rect\(", "draw_rounded_rect()")

    d = tmp_path_factory.mktemp("rounded_rect_parity")
    src = d / "rounded_rect_harness.cpp"
    src.write_text(_ROUNDED_RECT_STUB + "\n" + fn + "\n" + _ROUNDED_RECT_MAIN)
    exe = d / "rounded_rect_harness"
    subprocess.run(["c++", "-std=c++17", "-O1", "-o", str(exe), str(src)], check=True)
    return exe


def _cpp_rounded_rect(rounded_rect_harness, x, y, w, h, r, pad=4):
    cw, ch = w + 2 * pad, h + 2 * pad
    out = subprocess.run(
        [str(rounded_rect_harness), str(x), str(y), str(w), str(h), str(r), str(pad)],
        capture_output=True, check=True, text=True,
    )
    data = out.stdout
    assert len(data) == cw * ch, "harness printed the wrong number of pixels"
    return [[data[yy * cw + xx] == "#" for xx in range(cw)] for yy in range(ch)], pad


def _python_rounded_rect(x, y, w, h, r, pad=4):
    from PIL import Image, ImageDraw

    from display_mcp.render import _draw_rounded_rect

    cw, ch = w + 2 * pad, h + 2 * pad
    img = Image.new("L", (cw, ch), 0)
    dr = ImageDraw.Draw(img)
    _draw_rounded_rect(dr, x + pad, y + pad, w, h, r, 1)
    px = img.load()
    return [[bool(px[xx, yy]) for xx in range(cw)] for yy in range(ch)]


#  even, odd, wide, tiny -- one of each shape this construction treats
# differently, not the full cross product.
_ROUNDED_RECT_SIZES = [(40, 40, 10), (41, 41, 20), (60, 30, 14), (7, 7, 3)]


@pytest.mark.parametrize("w,h,r", _ROUNDED_RECT_SIZES)
def test_rounded_rect_bounding_box_matches_the_python(rounded_rect_harness, w, h, r):
    """Both sides fill the same `[x, x+w) x [y, y+h)` box overall, whatever
    the corner arcs look like pixel for pixel."""
    x = y = 0
    cpp, pad = _cpp_rounded_rect(rounded_rect_harness, x, y, w, h, r)
    py = _python_rounded_rect(x, y, w, h, r, pad)

    def bbox(grid):
        xs = [xx for row in grid for xx, v in enumerate(row) if v]
        ys = [yy for yy, row in enumerate(grid) for v in row if v]
        return min(xs), min(ys), max(xs), max(ys)

    assert bbox(cpp) == bbox(py) == (x + pad, y + pad, x + pad + w - 1, y + pad + h - 1)


@pytest.mark.parametrize("w,h,r", _ROUNDED_RECT_SIZES)
def test_rounded_rect_straight_bands_match_the_python_exactly(rounded_rect_harness, w, h, r):
    """The middle band and the two side bands are plain rectangles on both
    sides -- no arc rasterisation involved -- so unlike the corners, these
    must be pixel-identical."""
    x = y = 0
    cpp, pad = _cpp_rounded_rect(rounded_rect_harness, x, y, w, h, r)
    py = _python_rounded_rect(x, y, w, h, r, pad)

    bands = []
    if w - 2 * r > 0:
        bands.append((x + r, y, x + w - r, y + h))  # middle band
    if h - 2 * r > 0:
        bands.append((x, y + r, x + r, y + h - r))  # left band
        bands.append((x + w - r, y + r, x + w, y + h - r))  # right band

    for bx0, by0, bx1, by1 in bands:
        for yy in range(by0 + pad, by1 + pad):
            for xx in range(bx0 + pad, bx1 + pad):
                assert cpp[yy][xx] == py[yy][xx], (xx - pad, yy - pad)


# --------------------------------------------------------------------------
# circle t, differentially. Stacking concentric filled circles of radius
# r, r-1, ... would leave single-pixel holes near the diagonals from t == 2
# up; circle_half_widths()/draw_circle_ring() -- extracted verbatim from
# the header -- draw an annulus scanline instead. The oracle here is the
# *compiled* filled_circle()/circle(), not
# a Python reimplementation of the midpoint algorithm (which could itself
# disagree with ESPHome's by a pixel): the harness computes
# filled_circle(r) and filled_circle(r - t) itself and hands both rasters
# back alongside the ring's, so the diff in Python is pixel equality, not
# geometry.
#
# Needs a host C++ compiler; skips cleanly without one, like sprite_harness.
# --------------------------------------------------------------------------

_CIRCLE_RING_STUB = r"""
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
namespace esphome {
struct Color {
  uint8_t r = 0, g = 0, b = 0;
  Color() = default;
  Color(int r_, int g_, int b_) : r(r_), g(g_), b(b_) {}
};
namespace display {
enum class DisplayType { DISPLAY_TYPE_COLOR };
class Display {
 public:
  virtual ~Display() = default;
  virtual void draw_pixel_at(int x, int y, Color c) = 0;
  void horizontal_line(int x, int y, int width, Color c) {
    for (int i = x; i < x + width; i++) this->draw_pixel_at(i, y, c);
  }
  void filled_rectangle(int x1, int y1, int w, int h, Color c) {
    for (int i = y1; i < y1 + h; i++) this->horizontal_line(x1, i, w, c);
  }
  // Transcribed from esphome::display::Display (esphome/components/display/
  // display.cpp) -- the real midpoint routines display_list.h's own
  // filled_circle()/circle() calls, not reinvented here, so a match
  // against these is a match against the panel's own rasteriser.
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
};
}  // namespace display
}  // namespace esphome
static const char *const TAG = "dl";
"""

_CIRCLE_RING_MAIN = r"""
class Canvas : public esphome::display::Display {
 public:
  int w, h;
  std::vector<uint8_t> px;
  Canvas(int w_, int h_) : w(w_), h(h_), px(w_ * h_, 0) {}
  void draw_pixel_at(int x, int y, esphome::Color c) override {
    if (x >= 0 && y >= 0 && x < w && y < h) px[y * w + x] = 1;
  }
};
// argv: r t pad -- prints three w*h rasters back to back ('#'/'.'): the
// ring draw_circle_ring() actually draws, then the outer filled_circle(r)
// and the inner filled_circle(r - t) (blank, all '.', when r - t < 0) --
// so the diff against "outer minus inner" happens in Python, not here.
int main(int argc, char **argv) {
  int r = atoi(argv[1]), t = atoi(argv[2]), pad = atoi(argv[3]);
  int n = 2 * r + 2 * pad + 1;
  int cx = r + pad, cy = r + pad;
  esphome::Color c(1, 1, 1);
  Canvas ring(n, n), outer(n, n), inner(n, n);
  draw_circle_ring(ring, cx, cy, r, t, c);
  outer.filled_circle(cx, cy, r, c);
  int inner_r = r - t;
  if (inner_r >= 0) inner.filled_circle(cx, cy, inner_r, c);
  for (auto &canvas : {&ring, &outer, &inner})
    for (auto v : canvas->px) putchar(v ? '#' : '.');
  return 0;
}
"""


@pytest.fixture(scope="module")
def circle_ring_harness(tmp_path_factory):
    """Compile circle_half_widths()/draw_circle_ring() -- extracted
    verbatim from the shipped header, never retyped -- against the
    stand-in Display above, once for the module."""
    if shutil.which("c++") is None:
        pytest.skip("no host C++ compiler")
    half_widths_fn = _extract_block(r"^inline void circle_half_widths\(", "circle_half_widths()")
    ring_fn = _extract_block(r"^inline void draw_circle_ring\(", "draw_circle_ring()")

    d = tmp_path_factory.mktemp("circle_ring_parity")
    src = d / "circle_ring_harness.cpp"
    src.write_text(
        _CIRCLE_RING_STUB + "\n" + half_widths_fn + "\n" + ring_fn + "\n" + _CIRCLE_RING_MAIN
    )
    exe = d / "circle_ring_harness"
    subprocess.run(["c++", "-std=c++17", "-O1", "-o", str(exe), str(src)], check=True)
    return exe


def _ring_vs_filled_circles(circle_ring_harness, r: int, t: int, pad: int = 4):
    """(ring pixels, outer pixels, inner pixels), each an n*n bool grid, n
    the harness's own square canvas side."""
    n = 2 * r + 2 * pad + 1
    out = subprocess.run(
        [str(circle_ring_harness), str(r), str(t), str(pad)],
        capture_output=True, check=True, text=True,
    )
    data = out.stdout
    assert len(data) == 3 * n * n, "harness printed the wrong number of pixels"
    grids = []
    for k in range(3):
        chunk = data[k * n * n : (k + 1) * n * n]
        grids.append([[chunk[y * n + x] == "#" for x in range(n)] for y in range(n)])
    ring, outer, inner = grids
    return ring, outer, inner, n


@pytest.mark.parametrize("r", [0, 1, 2, 3, 6, 20, 60])
@pytest.mark.parametrize("t_offset", [2, 5])  # t relative to nothing; see below
def test_circle_ring_matches_filled_circle_difference(circle_ring_harness, r, t_offset):
    """The annulus equals filled_circle(r) minus filled_circle(r - t),
    pixel for pixel, for every t from 2 up to well past r (where there is
    no inner circle at all)."""
    t = t_offset
    ring, outer, inner, n = _ring_vs_filled_circles(circle_ring_harness, r, t)
    diffs = [
        (x, y)
        for y in range(n)
        for x in range(n)
        if ring[y][x] != (outer[y][x] and not inner[y][x])
    ]
    assert not diffs, diffs[:5]


@pytest.mark.parametrize("r", [5, 40])
def test_circle_ring_past_the_radius_equals_a_plain_filled_circle(circle_ring_harness, r):
    """t >= r + 1 leaves no inner circle at all -- the ring degenerates to
    exactly filled_circle(r), the same identity a t == 1 circle() call is
    kept exact to by not going through the ring at all."""
    t = r + 5
    ring, outer, inner, n = _ring_vs_filled_circles(circle_ring_harness, r, t)
    assert not any(any(row) for row in inner)
    assert ring == outer


@pytest.mark.parametrize("r,t", [(10, 2), (20, 3), (15, 4)])
def test_circle_ring_has_no_diagonal_holes(circle_ring_harness, r, t):
    """The bug this whole fix is for: stacking concentric filled circles of
    shrinking radius left single-pixel background holes near the 45-degree
    diagonals from t == 2 up. Walk the annulus's own outer edge (the
    outermost ring of the disc, taken from filled_circle(r) itself minus
    one step in) and check every one of those pixels is actually lit --
    a hole would show up here first, in the annulus's own boundary."""
    ring, outer, _inner, n = _ring_vs_filled_circles(circle_ring_harness, r, t)
    cx = cy = n // 2
    # Sample the ring at every angle along its own outer radius: this is
    # exactly the outer boundary of filled_circle(r), which the annulus
    # must fully cover (its outer half is that same boundary).
    import math

    holes = []
    for deg in range(360):
        th = math.radians(deg)
        x = cx + round(r * math.cos(th))
        y = cy + round(r * math.sin(th))
        if outer[y][x] and not ring[y][x]:
            holes.append((deg, x, y))
    assert not holes, holes[:8]


# --------------------------------------------------------------------------
# poly, differentially (docs/plans/dragon-feedback.md D12/B4). draw_poly()
# and its own poly_spans() -- plus thick_line() (already in the header) and
# this module's own Display::line() (see _STUB_ESPHOME_AND_JSON) -- are
# extracted verbatim, compiled, and diffed pixel-for-pixel against
# display_mcp.render.render(). Unlike sprite, poly's fill is the one place
# the two renderers could genuinely disagree (D12), and its outline is
# diffed too, since display_mcp.render draws it with the same Bresenham
# walk the header uses rather than PIL's `width=` (see
# render._bresenham_points's own docstring for why that distinction only
# matters here).
#
# Needs a host C++ compiler; skips cleanly without one, like sprite_harness.
# --------------------------------------------------------------------------


# Everything sprite_harness's main() needs before `int main() {` -- the
# Canvas and the tiny JSON parser -- reused rather than retyped, so the two
# harnesses can't drift on how they read stdin or bounds-check a pixel.
_CANVAS_AND_PARSER = _HARNESS_MAIN.split("int main() {")[0]

# draw_poly()'s own harness main(): resolve `c` through the same
# resolve_ink() stub sprite_harness uses (so "navy", "grey-dark" etc. work
# here too), build the MixDisplay the real op loop builds before dispatch
# -- draw_poly() receives that proxy already carrying `c`, not a bare
# Display, so the harness has to hand it the same thing -- and call
# draw_poly() exactly as the loop does.
_POLY_HARNESS_MAIN = (
    _CANVAS_AND_PARSER
    + r"""int main() {
  std::string body;
  { int c; while ((c = getchar()) != EOF) body += (char) c; }
  P p(body);
  NodePtr root = p.val();
  JsonObject o(root);
  JsonObject palette;  // draw_poly() takes none; the resolve_ink stub ignores it too
  const int cw = o["_cw"] | 64;
  const int ch = o["_ch"] | 64;
  Canvas canvas(cw, ch);
  const Ink ink = resolve_ink(o["c"] | "black", palette);
  MixDisplay mix(canvas);
  mix.add_ink(ink.a, ink);
  const bool drew = draw_poly(mix, o, ink);
  const unsigned char drew_byte = drew ? 1 : 0;
  std::fwrite(&drew_byte, 1, 1, stdout);
  for (auto &px : canvas.px) {
    std::fwrite(&px.r, 1, 1, stdout);
    std::fwrite(&px.g, 1, 1, stdout);
    std::fwrite(&px.b, 1, 1, stdout);
  }
  return 0;
}
"""
)


class _PolyHarness:
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
def poly_harness(tmp_path_factory) -> _PolyHarness:
    """Compile draw_poly() -- extracted verbatim from the shipped header,
    never retyped -- against the same stubs sprite_harness uses, plus
    floor_div()/poly_spans()/thick_line(), once for the module."""
    if shutil.which("c++") is None:
        pytest.skip("no host C++ compiler")

    matrix = _extract(r"^static const uint8_t B\[2\]\[2\].*;$", "the Bayer matrix")
    mix_on_fn = _extract(r"^inline bool mix_on\(.*$", "mix_on()")
    ink_struct = _extract_block(r"^struct Ink \{", "struct Ink")
    mixdisplay_cls = _extract_block(
        r"^class MixDisplay : public esphome::display::Display \{", "MixDisplay"
    )
    thick_max_const = _extract(r"^static const int kThickMax = \d+;$", "kThickMax")
    thick_line_fn = _extract_block(r"^inline void thick_line\(", "thick_line()")
    floor_div_fn = _extract_block(r"^inline int64_t floor_div\(", "floor_div()")
    poly_max_coord_const = _extract(
        r"^static const int32_t kPolyMaxCoord = .*;$", "kPolyMaxCoord"
    )
    poly_spans_fn = _extract_block(r"^inline void poly_spans\(", "poly_spans()")
    draw_poly_fn = _extract_block(r"^inline bool draw_poly\(", "draw_poly()")

    d = tmp_path_factory.mktemp("poly_parity")
    src = d / "poly_harness.cpp"
    src.write_text(
        "// Host-compile harness for draw_poly(), extracted verbatim from\n"
        "// firmware/display_list.h. ArduinoJson and ESPHome are stubbed.\n"
        "#include <algorithm>\n#include <cctype>\n#include <cstdint>\n"
        "#include <cstdio>\n#include <cstdlib>\n#include <cstring>\n#include <functional>\n"
        "#include <map>\n#include <memory>\n#include <set>\n#include <string>\n"
        "#include <tuple>\n#include <utility>\n#include <vector>\n\n"
        + _STUB_ESPHOME_AND_JSON
        + "\n" + matrix + "\n" + mix_on_fn
        + "\n" + ink_struct + "\n" + mixdisplay_cls
        + "\n" + thick_max_const + "\n" + thick_line_fn
        + "\n" + _STUB_RESOLVE_INK
        + "\n" + floor_div_fn
        + "\n" + poly_max_coord_const + "\n" + poly_spans_fn + "\n" + draw_poly_fn
        + "\n" + _POLY_HARNESS_MAIN
    )
    exe = d / "poly_harness"
    # -fsanitize=undefined: the fill's int64_t crossing
    # arithmetic is exactly the kind of thing UBSan catches that a plain
    # -O1 build wouldn't -- signed overflow, an out-of-range cast -- and
    # -fno-sanitize-recover=all makes any such finding a hard failure here
    # rather than a quiet stderr line every other harness would miss too.
    subprocess.run(
        [
            "c++", "-std=c++17", "-O1", "-fsanitize=undefined", "-fno-sanitize-recover=all",
            "-o", str(exe), str(src),
        ],
        check=True,
    )
    return _PolyHarness(exe)


def _poly_pixels_py(op, cw, ch, font_dir):
    doc = {"v": 1, "bg": "white", "ops": [op]}
    img, problems = render(doc, font_dir)
    px = img.load()
    return [[px[x, y] for x in range(cw)] for y in range(ch)], problems


def _poly_diff(poly_harness, font_dir, op, cw, ch):
    """Run the same op through both renderers and return every
    (x, y, cpp_rgb, py_rgb) where they disagree, plus render()'s own
    problems -- empty diffs is the whole point of the test."""
    _drew, cpp_px, _logs = poly_harness.run(op, cw, ch)
    py_px, problems = _poly_pixels_py(op, cw, ch, font_dir)
    diffs = [
        (x, y, cpp_px[y][x], py_px[y][x])
        for y in range(ch)
        for x in range(cw)
        if cpp_px[y][x] != py_px[y][x]
    ]
    return diffs, problems


def test_poly_triangle_matches_the_firmware(poly_harness, font_dir):
    op = {"op": "poly", "pts": [[5, 5], [55, 5], [30, 45]], "c": "black"}
    diffs, problems = _poly_diff(poly_harness, font_dir, op, 60, 50)
    assert problems == []
    assert not diffs, diffs[:5]


def test_poly_concave_chevron_matches_the_firmware(poly_harness, font_dir):
    """A concave "V"-notch chevron -- the case a naive bounding-box fill
    would get wrong but the even-odd scanline gets right on both sides."""
    op = {
        "op": "poly",
        "pts": [[0, 0], [20, 0], [35, 20], [20, 40], [0, 40], [15, 20]],
        "c": "navy",
    }
    diffs, problems = _poly_diff(poly_harness, font_dir, op, 40, 45)
    assert problems == []
    assert not diffs, diffs[:5]


def test_poly_bowtie_matches_the_firmware(poly_harness, font_dir):
    """Two triangles sharing a vertex, drawn as one self-touching path --
    the half-open crossing rule has to land the shared vertex on exactly
    one row without leaving a gap, on both sides identically."""
    op = {"op": "poly", "pts": [[0, 0], [40, 40], [0, 40], [40, 0]], "c": "red"}
    diffs, problems = _poly_diff(poly_harness, font_dir, op, 45, 45)
    assert problems == []
    assert not diffs, diffs[:5]


def test_poly_horizontal_edge_matches_the_firmware(poly_harness, font_dir):
    """A pentagon with one flat top edge -- horizontal edges contribute no
    crossings on either side, so this pins that they're skipped the same
    way rather than one side tripping over a zero-length edge."""
    op = {
        "op": "poly",
        "pts": [[10, 0], [30, 0], [40, 20], [20, 35], [0, 20]],
        "c": "blue",
    }
    diffs, problems = _poly_diff(poly_harness, font_dir, op, 45, 40)
    assert problems == []
    assert not diffs, diffs[:5]


def test_poly_negative_and_offcanvas_coords_matches_the_firmware(poly_harness, font_dir):
    """A triangle straddling the top-left corner, partly off-canvas on
    negative coordinates -- both sides have to clip it to the same
    pixels, not merely avoid crashing on it."""
    op = {"op": "poly", "pts": [[-100, -100], [30, -10], [10, 30]], "c": "green"}
    diffs, problems = _poly_diff(poly_harness, font_dir, op, 40, 40)
    assert any("off-canvas" in p for p in problems)
    assert not diffs, diffs[:5]


def test_poly_mixed_fill_at_odd_origin_matches_a_rect(poly_harness, font_dir):
    """An axis-aligned poly at an odd (x, y) with a mixed ink, diffed
    against the C++ raster directly -- proof that poly_spans()'s fill
    dithers with the same absolute phase a `rect` fill does, the way
    test_sprite_3x3_mixed_block_matches_a_rect proves it for sprite.

    This is also the asymmetry docs/SPEC.md "poly" states: x is inclusive of both
    ends (the right edge sits at `x + w - 1`, same as a rect's own
    `[x, x+w-1]`), but the scanline that fills a row is half-open
    (`[min(y0,y1), max(y0,y1))`), so the bottom edge here is `y + h`, not
    `y + h - 1` -- one *past* where a rect's `h`th row would be -- and the
    fill still lands on exactly the same `h` rows a rect of this box would,
    because that last scanline (`y + h`) never gets a crossing.
    """
    x, y, w, h = 7, 11, 20, 14
    op = {
        "op": "poly",
        "pts": [[x, y], [x + w - 1, y], [x + w - 1, y + h], [x, y + h]],
        "c": "navy",
    }
    drew, cpp_px, logs = poly_harness.run(op, 40, 40)
    assert drew and not logs
    rect_doc = {
        "v": 1, "bg": "white",
        "ops": [{"op": "rect", "x": x, "y": y, "w": w, "h": h, "c": "navy"}],
    }
    img, problems = render(rect_doc, font_dir)
    assert problems == []
    px = img.load()
    diffs = [
        (xx, yy, cpp_px[yy][xx], px[xx, yy])
        for yy in range(40)
        for xx in range(40)
        if cpp_px[yy][xx] != px[xx, yy]
    ]
    assert not diffs, diffs[:5]


def test_poly_outline_t3_matches_the_firmware(poly_harness, font_dir):
    """`fill: false` with `t: 3`, including the closing edge."""
    op = {
        "op": "poly",
        "pts": [[10, 10], [50, 10], [50, 40], [10, 40]],
        "c": "black", "fill": False, "t": 3,
    }
    diffs, problems = _poly_diff(poly_harness, font_dir, op, 60, 50)
    assert problems == []
    assert not diffs, diffs[:5]


def test_poly_two_point_pts_warns_and_skips_on_both_sides(poly_harness, font_dir):
    op = {"op": "poly", "pts": [[1, 1], [2, 2]], "c": "black"}
    drew, _px, logs = poly_harness.run(op, 10, 10)
    assert not drew
    assert any("at least three" in log for log in logs)
    problems = check({"v": 1, "bg": "white", "ops": [op]}, font_dir)
    assert any("nothing to draw, skipped" in p for p in problems)


def test_poly_point_out_of_range_warns_and_skips_on_both_sides(poly_harness, font_dir):
    """A point past `kPolyMaxCoord` / `POLY_MAX_COORD`
    (docs/plans/dragon-feedback.md D12) is malformed on both sides, not
    merely off-canvas, so a point millions of units away is rejected
    outright rather than making poly_spans() walk millions of scanlines."""
    op = {"op": "poly", "pts": [[10, -5000000], [20, 5000000], [0, 0]], "c": "black"}
    drew, _px, logs = poly_harness.run(op, 10, 10)
    assert not drew
    assert any("out of range" in log for log in logs)
    problems = check({"v": 1, "bg": "white", "ops": [op]}, font_dir)
    assert any("out of range" in p for p in problems)


def test_poly_canvas_spanning_pts_matches_the_firmware(poly_harness, font_dir):
    """The scanline-range and span-x clamp -- to `[0, height)` and
    `[0, width)`, applied *before* the loop on both sides -- must land on
    exactly the same visible pixels a naive, unclamped fill would have.
    Points well outside the harness's own small canvas (but inside
    `kPolyMaxCoord`) exercise the clamp on both sides identically: the
    firmware's `it.get_width()`/`get_height()` here is the harness's own
    small canvas, while the Python's clamp is always the real 1200x1600 --
    but since the fill is solid well past this window in every direction,
    the two must still agree on every sampled pixel."""
    op = {
        "op": "poly",
        "pts": [[-9000, -9000], [9000, -9000], [9000, 9000], [-9000, 9000]],
        "c": "black",
    }
    diffs, problems = _poly_diff(poly_harness, font_dir, op, 80, 80)
    assert any("off-canvas" in p for p in problems)
    assert not diffs, diffs[:5]


def test_poly_fill_false_0_matches_the_firmware(poly_harness, font_dir):
    """`"fill": 0` is not a JSON bool, so ArduinoJson's `o["fill"] |
    true` reads the default (fills), and the Python side does the same,
    instead of `0`'s truthiness reading it as `fill: false`."""
    op = {
        "op": "poly",
        "pts": [[5, 5], [55, 5], [30, 45]],
        "c": "black",
        "fill": 0,
    }
    diffs, problems = _poly_diff(poly_harness, font_dir, op, 60, 50)
    assert any("fill=0" in p and "using true" in p for p in problems)
    assert not diffs, diffs[:5]
