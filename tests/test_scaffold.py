"""The sample document, and what the wheel actually ships.

The MCP server serves docs/SPEC.md and samples/display.json as the
display://spec and display://sample resources. A non-editable install — what
deploy/setup.sh does on the host — has no docs/ or samples/ next to it, so it
reads the copies inside the package instead. Those copies used to be checked
in and drifted for months without anyone noticing; pyproject now force-includes
the originals at build time, and the tests below hold that shut.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from display_mcp.render import render_hash

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "src" / "display_mcp" / "prompts"

# repo original -> path inside the wheel, mirroring pyproject's force-include
# and the pairs _spec_text/_sample_text ask for in mcp_server.py.
BUNDLED = {
    ROOT / "docs" / "SPEC.md": "display_mcp/prompts/SPEC.md",
    ROOT / "samples" / "display.json": "display_mcp/prompts/sample.json",
}


def test_sample_hash(sample_doc):
    assert render_hash(sample_doc) == "21a77f4c46f1534d"


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
