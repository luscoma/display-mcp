"""The sample document, and what the wheel actually ships.

The MCP server serves docs/SPEC.md and samples/display.json as the
display://spec and display://sample resources. A non-editable install — what
deploy/setup.sh does on the host — has no docs/ or samples/ next to it, so it
reads the copies inside the package instead. Those copies used to be checked
in and drifted for months without anyone noticing; pyproject now force-includes
the originals at build time, and the tests below hold that shut.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from display_mcp.render import check, render_hash

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
    """F10 (docs/plans/dragon-feedback.md): docs/SPEC.md's ### sprite
    example has to be something an agent can paste straight into a
    document — check() on it must come back clean, the same rule
    compose.md's example is held to below."""
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
