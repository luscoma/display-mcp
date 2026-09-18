"""The sample document, and what the wheel actually ships.

The MCP server serves docs/SPEC.md and samples/display.json as the
display://spec and display://sample resources. A non-editable install — what
deploy/setup.sh does on the host — has no docs/ or samples/ next to it, so it
reads the copies inside the package instead. pyproject force-includes the
originals at build time so the packaged copies cannot drift from them, and
the tests below hold that shut.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from mcp import Client

from display_mcp import mcp_server
from display_mcp.config import Settings
from display_mcp.render import BUILTIN_MIXES, FONTS, OP_FIELDS, check, render_hash
from fakes import FakeStore

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "src" / "display_mcp" / "prompts"

# repo original -> path inside the wheel, mirroring pyproject's force-include
# and the pairs _spec_text/_sample_text ask for in mcp_server.py.
BUNDLED = {
    ROOT / "docs" / "SPEC.md": "display_mcp/prompts/SPEC.md",
    ROOT / "samples" / "display.json": "display_mcp/prompts/sample.json",
}


def test_sample_hash(sample_doc):
    assert render_hash(sample_doc) == "3cd62aa76e731d2d"


def test_sprite_sample_hash(sprite_sample_doc):
    """samples/sprite.json (docs/plans/dragon-feedback.md B1) — the second
    sample, showing off the `sprite` op the way samples/display.json shows
    off everything else."""
    assert render_hash(sprite_sample_doc) == "16274a2fe47fbd06"


def test_sprite_sample_checks_clean(sprite_sample_doc, font_dir):
    from display_mcp.render import check

    assert check(sprite_sample_doc, font_dir) == []


def test_vocabulary_sample_hash(vocabulary_sample_doc):
    """samples/vocabulary.json — the third sample, a labelled page putting
    every primitive only the wall can judge on the glass at once (a
    rounded rect and a max-radius pill, mono block art and ligature-free
    text, a sprite with mirror and a document mix and a built-in mix, a
    filled poly in a mix and an outline poly, a thick circle outline, a
    thick line), for the flash-and-judge step in RUNBOOK.md."""
    assert render_hash(vocabulary_sample_doc) == "91500ec10b0c26f7"


def test_vocabulary_sample_checks_clean(vocabulary_sample_doc, font_dir):

    assert check(vocabulary_sample_doc, font_dir) == []


def _fenced_json_sprite_op(text: str) -> dict:
    """The first ```json fenced block in `text` whose parsed object is a
    sprite op — docs/SPEC.md and compose.md each carry exactly one."""
    for block in re.findall(r"[ \t]*```json\n(.*?)\n[ \t]*```", text, re.DOTALL):
        try:
            obj = json.loads(block)
        except json.JSONDecodeError:
            continue  # a structural placeholder ("ops": [ ... ]), not a real example
        if isinstance(obj, dict) and obj.get("op") == "sprite":
            return obj
    raise AssertionError(f"no fenced json sprite example found in {text[:40]!r}...")


def test_spec_sprite_example_checks_clean(font_dir):
    """docs/SPEC.md's ### sprite example has to be something an agent can
    paste straight into a document — check() on it must come back clean,
    the same rule compose.md's example is held to below."""
    op = _fenced_json_sprite_op((ROOT / "docs" / "SPEC.md").read_text())
    assert check({"v": 1, "bg": "white", "ops": [op]}, font_dir) == []


def test_compose_sprite_example_checks_clean(font_dir):
    """The compose_display prompt's own sprite example, same rule."""
    op = _fenced_json_sprite_op((PROMPTS / "compose.md").read_text())
    assert check({"v": 1, "bg": "white", "ops": [op]}, font_dir) == []


def _fenced_json_poly_op(text: str) -> dict:
    """Like `_fenced_json_sprite_op`, for the `poly` example
    (docs/plans/dragon-feedback.md D12/B4)."""
    for block in re.findall(r"[ \t]*```json\n(.*?)\n[ \t]*```", text, re.DOTALL):
        try:
            obj = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("op") == "poly":
            return obj
    raise AssertionError(f"no fenced json poly example found in {text[:40]!r}...")


def test_spec_poly_example_checks_clean(font_dir):
    """docs/SPEC.md's ### poly example has to be pasteable as-is, the same
    rule the sprite example is held to."""
    op = _fenced_json_poly_op((ROOT / "docs" / "SPEC.md").read_text())
    assert check({"v": 1, "bg": "white", "ops": [op]}, font_dir) == []


def test_compose_poly_example_checks_clean(font_dir):
    """The compose_display prompt's own poly example, same rule."""
    op = _fenced_json_poly_op((PROMPTS / "compose.md").read_text())
    assert check({"v": 1, "bg": "white", "ops": [op]}, font_dir) == []


@pytest.mark.parametrize("source", BUNDLED, ids=lambda p: p.name)
def test_no_checked_in_duplicate(source):
    """The copy under prompts/ is a build product. If one is sitting in the
    source tree, someone re-added it and it will drift again."""
    dup = PROMPTS / Path(BUNDLED[source]).name
    assert not dup.exists(), (
        f"{dup.relative_to(ROOT)} is checked in again. It duplicates "
        f"{source.relative_to(ROOT)}, which the build already copies in — "
        "delete it rather than keeping the two in sync by hand."
    )


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> zipfile.ZipFile:
    """Build a wheel the way pip would, into a scratch dir."""
    pytest.importorskip("hatchling.build")
    out = tmp_path_factory.mktemp("wheel")
    proc = subprocess.run(
        [sys.executable, "-c", "import sys,hatchling.build as b;print(b.build_wheel(sys.argv[1]))",
         str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"hatchling could not build a wheel:\n{proc.stderr}"
    return zipfile.ZipFile(out / proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("source", BUNDLED, ids=lambda p: p.name)
def test_wheel_bundles_the_real_file(wheel, source):
    """What an installed server serves must be byte for byte the repo original."""
    name = BUNDLED[source]
    assert name in wheel.namelist(), (
        f"the wheel has no {name}; pyproject's [tool.hatch.build.targets.wheel."
        f"force-include] should map {source.relative_to(ROOT)} to it"
    )
    assert wheel.read(name) == source.read_bytes(), (
        f"{name} in the wheel differs from {source.relative_to(ROOT)}"
    )


# --------------------------------------------------------------------------
# Prose counts vs. the tables they describe: README.md, docs/SPEC.md and
# docs/RUNBOOK.md each state, in words, how many tools/ops/font sizes/
# built-in mixes this project has. If the vocabulary grows and a doc is not
# updated, this fails instead of the doc quietly going stale.
# --------------------------------------------------------------------------

_WORDNUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "twenty-one": 21,
}
# Word forms only: the vocabulary counts below are always spelled out in
# prose ("eight ops"), while a bare digit ("56 ops") names a specific
# document's op count elsewhere in the same files (e.g. README's sample
# byte-size callout) — matching digits too would pick those up as false
# positives.
_NUM_RE = "|".join(sorted(_WORDNUM, key=len, reverse=True))


def _int_of(word: str) -> int:
    return int(word) if word.isdigit() else _WORDNUM[word.lower()]


async def _tool_count() -> int:
    mcp = mcp_server.build_mcp(FakeStore(), Settings(state_dir=ROOT, font_dir=ROOT))
    async with Client(mcp) as c:
        return len((await c.list_tools()).tools)


def _found(pattern: str, *texts: str) -> set[int]:
    found = set()
    for text in texts:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            found.add(_int_of(m.group(1) if m.groups() else m.group(0)))
    return found


async def test_prose_tool_ops_font_and_mix_counts_match_the_code():
    readme = (ROOT / "README.md").read_text()
    spec = (ROOT / "docs" / "SPEC.md").read_text()
    runbook = (ROOT / "docs" / "RUNBOOK.md").read_text()

    tools_found = _found(rf"\b({_NUM_RE})\s+(?:MCP\s+)?tools\b", readme, spec, runbook)
    ops_found = _found(rf"\b({_NUM_RE})\s+ops\b", readme, spec)
    fonts_found = _found(rf"\b({_NUM_RE})\s+font sizes\b", readme, spec)
    mixes_found = _found(rf"\b({_NUM_RE})\s+built-in\b", readme, spec) | _found(
        rf"\ball\s+({_NUM_RE})\b", spec
    )

    assert tools_found == {await _tool_count()}, tools_found
    assert ops_found == {len(OP_FIELDS)}, ops_found
    assert fonts_found == {len(FONTS)}, fonts_found
    assert mixes_found == {len(BUILTIN_MIXES)}, mixes_found
