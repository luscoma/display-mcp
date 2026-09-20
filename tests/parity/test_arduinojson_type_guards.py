"""`parse_deco()` and the `f`/`a`/`z` type-guard idiom, extracted verbatim
from display_list.h and compiled against the *real*, vendored ArduinoJson
7.4.3 header -- not `conftest.py`'s own hand-written `_STUB` JsonVariant,
which every other parity harness in this package uses. The stub's `is<T>()`/
`isNull()` are a close reimplementation, not the library the firmware
actually links; this is the one test in the suite that proves the type
guard's `!o[field].isNull() && !o[field].is<const char *>()` idiom means the
same thing against ArduinoJson itself as it does against the stub, for the
value shapes a document can actually carry (docs/plans/fonts-and-icons.md,
final review, "Firmware safety").

Skips cleanly, like every other host-compiled parity test, without a host
C++ compiler; also skips without the vendored header, which only exists
once `esphome compile`/`esphome config` has populated
`firmware/.esphome/`'s managed-components cache (a fresh checkout has
neither) -- the same "needs a build once" caveat A4's brief calls out.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from .conftest import HEADER, _extract, _extract_block

# Every place `esphome compile`/`esphome config` might have cached the
# vendored ArduinoJson source -- the managed-components dir under a build,
# or the espressif service cache a component manager download lands in
# first. Sorted so this is deterministic if more than one is ever present.
_SEARCH_ROOTS = (
    HEADER.parent / ".esphome" / "build",
    HEADER.parent / ".esphome" / ".espressif",
)


def _find_arduinojson_include_dir() -> Path | None:
    for root in _SEARCH_ROOTS:
        if not root.is_dir():
            continue
        for candidate in sorted(root.glob("**/bblanchon__arduinojson*/src/ArduinoJson.h")):
            return candidate.parent
        for candidate in sorted(root.glob("**/bblanchon__arduinojson*/ArduinoJson.h")):
            return candidate.parent
    return None


# The eleven cases the brief names: a `deco`/`z` key absent from the object
# entirely (distinct from an explicit JSON `null` -- both are `isNull()`,
# but only one has no entry at all), then ten JSON literals covering every
# shape `parse_deco()` and the type guard branch on: null, a number (int and
# float), a bool, an array, an object, and four strings (empty, the two
# legal `deco` values, and one that parses as a string but isn't one of
# them).
_CASES: dict[str, str | None] = {
    "absent": None,  # sentinel: omit the key from the JSON object entirely
    "null": "null",
    "int": "7",
    "float": "1.5",
    "bool": "true",
    "array": "[]",
    "object": "{}",
    "empty_string": '""',
    "underline": '"underline"',
    "strike": '"strike"',
    "bogus": '"bogus"',
}

# parse_deco()'s outcome, matching display_mcp.render._parse_deco()'s return
# value (None/"underline"/"strike") -- the C++ side reports its enum by name
# so the harness output is self-describing rather than a bare int.
_EXPECTED_DECO = {
    "absent": None,
    "null": None,
    "int": None,
    "float": None,
    "bool": None,
    "array": None,
    "object": None,
    "empty_string": None,
    "underline": "underline",
    "strike": "strike",
    "bogus": None,
}

# The type guard's skip/no-skip decision, matching
# _op_optional_field_type_problem()'s `value is None or isinstance(value, str)`
# (never a skip) vs anything else (skip) -- independent of whether the
# *string* is one of deco's two legal values, which is a separate check on
# both sides.
_EXPECTED_SKIP = {
    "absent": False,
    "null": False,
    "int": True,
    "float": True,
    "bool": True,
    "array": True,
    "object": True,
    "empty_string": False,
    "underline": False,
    "strike": False,
    "bogus": False,
}


@pytest.fixture(scope="module")
def type_guard_harness(tmp_path_factory):
    if shutil.which("c++") is None:
        pytest.skip("no host C++ compiler")
    include_dir = _find_arduinojson_include_dir()
    if include_dir is None:
        pytest.skip(
            "vendored ArduinoJson not found under firmware/.esphome -- "
            "run `esphome compile`/`esphome config` from firmware/ once"
        )

    parse_deco_src = _extract_block(r"^inline Deco parse_deco\(", "parse_deco()")
    deco_enum_src = _extract(r"^enum class Deco \{.*\};$", "the Deco enum")
    # The icon branch's `z` guard -- one instance of the three-line idiom
    # that also appears (with a different field/message) for text/fmt's
    # `f` and `a`; all three share the exact same two-clause condition, so
    # this one instance is what's compiled and driven here.
    guard_src = _extract_block(
        r'^\s*if \(!o\["z"\]\.isNull\(\) && !o\["z"\]\.is<const char \*>\(\)\) \{',
        "the icon `z` type-guard idiom",
    )

    main_src = r"""
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    JsonDocument doc;
    if (deserializeJson(doc, line)) {
      std::printf("ERR\n");
      continue;
    }
    JsonObject o = doc.as<JsonObject>();

    const Deco d = parse_deco(o["deco"]);
    const char *deco_name = d == Deco::kUnderline ? "underline"
                             : d == Deco::kStrike  ? "strike"
                                                    : "none";

    int skipped = 0;
    for (int _i = 0; _i < 1; _i++) {
""" + guard_src + r"""
    }
    std::printf("%s %d\n", deco_name, skipped);
  }
  return 0;
}
"""
    src = (
        "#include <ArduinoJson.h>\n"
        "#include <cstdio>\n"
        "#include <cstring>\n"
        "#include <iostream>\n"
        "#include <string>\n"
        '#define ESP_LOGW(tag, fmt, ...) std::fprintf(stderr, "W " fmt "\\n", ##__VA_ARGS__)\n'
        'static const char *const TAG = "t";\n\n'
        + deco_enum_src
        + "\n\n"
        + parse_deco_src
        + "\n"
        + main_src
    )
    d = tmp_path_factory.mktemp("arduinojson_type_guards")
    cpp = d / "harness.cpp"
    cpp.write_text(src)
    exe = d / "harness"
    subprocess.run(
        ["c++", "-std=c++17", "-O1", f"-I{include_dir}", "-o", str(exe), str(cpp)],
        check=True,
    )
    return exe


def _payload(case: str) -> str:
    value = _CASES[case]
    if value is None:  # "absent": no deco/z key at all
        return "{}"
    return json.dumps({"deco": json.loads(value), "z": json.loads(value)})


def _run(exe: Path, cases: list[str]) -> list[tuple[str, int]]:
    stdin = "".join(_payload(case) + "\n" for case in cases)
    out = subprocess.run(
        [str(exe)], input=stdin.encode(), capture_output=True, check=True
    ).stdout.decode()
    results = []
    for line in out.splitlines():
        name, skipped = line.split()
        results.append((name, int(skipped)))
    return results


def test_parse_deco_matches_the_renderer_for_every_json_shape(type_guard_harness):
    from display_mcp.render import Ctx, _parse_deco

    cases = list(_CASES)
    results = _run(type_guard_harness, cases)
    assert len(results) == len(cases)
    for case, (cpp_deco, _cpp_skip) in zip(cases, results, strict=True):
        expected = _EXPECTED_DECO[case]
        assert cpp_deco == (expected or "none"), f"{case}: firmware said {cpp_deco!r}"
        ctx = Ctx({"v": 1, "bg": "white", "ops": []}, load_fonts=False)
        py_deco = _parse_deco(None if _CASES[case] is None else json.loads(_CASES[case]), "t", ctx)
        assert py_deco == expected, f"{case}: renderer said {py_deco!r}, expected {expected!r}"


def test_type_guard_skip_decision_matches_the_renderer_for_every_json_shape(type_guard_harness):
    cases = list(_CASES)
    results = _run(type_guard_harness, cases)
    for case, (_cpp_deco, cpp_skip) in zip(cases, results, strict=True):
        expected_skip = _EXPECTED_SKIP[case]
        assert bool(cpp_skip) == expected_skip, f"{case}: firmware skip={bool(cpp_skip)}"
        value = None if _CASES[case] is None else json.loads(_CASES[case])
        py_skip = value is not None and not isinstance(value, str)
        assert py_skip == expected_skip, f"{case}: renderer skip={py_skip}"
