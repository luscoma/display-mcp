"""The sample document, and what the wheel actually ships.

The MCP server serves docs/SPEC.md and samples/display.json as the
display://spec and display://sample resources. A non-editable install — what
deploy/setup.sh does on the host — has no docs/ or samples/ next to it, so it
reads the copies inside the package instead. pyproject force-includes the
originals at build time so the packaged copies cannot drift from them, and
the tests below hold that shut.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from mcp import Client

from display_mcp import mcp_server
from display_mcp.config import Settings
from display_mcp.render import BUILTIN_MIXES, OP_FIELDS, check, render, render_hash
from display_mcp.render.fonts import SIZES
from fakes import FakeStore

# Fixed for every pixel-pin test below: both samples' footers print
# {time}/{time24}, so a bare `render(doc, font_dir)` would pin against
# whatever second the test happened to run in. This repo's own convention
# for a short pixel-identity check (docs/plans/fonts-and-icons.md B4b
# review, item 1) -- see test_swatches.py's pre-B1 pin for the pattern.
_PIXEL_PIN_NOW = datetime(2026, 9, 9, 13, 43)

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "src" / "display_mcp" / "prompts"

# repo original -> path inside the wheel, mirroring pyproject's force-include
# and the pairs _spec_text/_sample_text ask for in mcp_server.py.
BUNDLED = {
    ROOT / "docs" / "SPEC.md": "display_mcp/prompts/SPEC.md",
    ROOT / "samples" / "display.json": "display_mcp/prompts/sample.json",
}


def test_sample_hash(sample_doc):
    assert render_hash(sample_doc) == "1c772cd7a6ebc2c7"


def test_sprite_sample_hash(sprite_sample_doc):
    """samples/sprite.json (docs/plans/dragon-feedback.md B1) — the second
    sample, showing off the `sprite` op the way samples/display.json shows
    off everything else."""
    assert render_hash(sprite_sample_doc) == "f6b199c715336753"


def test_sprite_sample_checks_clean(sprite_sample_doc, font_dir):
    from display_mcp.render import check

    assert check(sprite_sample_doc, font_dir) == []


def test_sample_renders_pixel_identical(sample_doc, font_dir):
    """`render_hash` alone (`test_sample_hash` above) covers `bg`+`palette`+
    `ops` -- it cannot see a vocabulary change that leaves an icon op's `n`/
    `z` looking like valid JSON but silently changes what pixels they
    resolve to. That's exactly what slipped through the first pass of
    docs/plans/fonts-and-icons.md's B4b: `weather-partly-cloudy/lg`,
    `map-marker/sm` and `check/sm` were left with their pre-B4b spellings,
    still legal keys under the new slot table but no longer the sizes they
    used to draw, and `check()` had nothing to say about it (B4b review,
    item 1). This pins the actual rendered pixels at a fixed clock, so a
    future vocabulary change that reflows the sample without touching
    `render_hash` fails loudly here instead."""
    img, problems = render(sample_doc, font_dir, now=_PIXEL_PIN_NOW)
    assert problems == []
    digest = hashlib.sha256(img.tobytes()).hexdigest()[:16]
    assert digest == "3b736f169ee472d0"


def test_sprite_sample_renders_pixel_identical(sprite_sample_doc, font_dir):
    """Same guard as `test_sample_renders_pixel_identical`, for the second
    sample's own icon op."""
    img, problems = render(sprite_sample_doc, font_dir, now=_PIXEL_PIN_NOW)
    assert problems == []
    digest = hashlib.sha256(img.tobytes()).hexdigest()[:16]
    assert digest == "a2777e10b45469a2"


def test_vocabulary_sample_hash(vocabulary_sample_doc):
    """samples/vocabulary.json — the third sample, a labelled page putting
    every primitive only the wall can judge on the glass at once (a
    rounded rect and a max-radius pill, mono block art and ligature-free
    text, a sprite with mirror and a document mix and a built-in mix, a
    filled poly in a mix and an outline poly, a thick circle outline, a
    thick line, and — added in B4b — the eight new activity icons at `md`
    and a couple at `xl`), for the flash-and-judge step in RUNBOOK.md."""
    assert render_hash(vocabulary_sample_doc) == "101dd11be8557e3f"


def test_vocabulary_sample_checks_clean(vocabulary_sample_doc, font_dir):

    assert check(vocabulary_sample_doc, font_dir) == []


def _fenced_op(text: str, kind: str) -> dict:
    """The first ```json fenced block in `text` whose parsed object is a
    `kind` op — docs/SPEC.md and compose.md each carry exactly one sprite
    example and one poly example (docs/plans/dragon-feedback.md D12/B4)."""
    for block in re.findall(r"[ \t]*```json\n(.*?)\n[ \t]*```", text, re.DOTALL):
        try:
            obj = json.loads(block)
        except json.JSONDecodeError:
            continue  # a structural placeholder ("ops": [ ... ]), not a real example
        if isinstance(obj, dict) and obj.get("op") == kind:
            return obj
    raise AssertionError(f"no fenced json {kind} example found in {text[:40]!r}...")


def test_spec_sprite_example_checks_clean(font_dir):
    """docs/SPEC.md's ### sprite example has to be something an agent can
    paste straight into a document — check() on it must come back clean,
    the same rule compose.md's example is held to below."""
    op = _fenced_op((ROOT / "docs" / "SPEC.md").read_text(), "sprite")
    assert check({"v": 1, "bg": "white", "ops": [op]}, font_dir) == []


def test_compose_sprite_example_checks_clean(font_dir):
    """The compose_display prompt's own sprite example, same rule."""
    op = _fenced_op((PROMPTS / "compose.md").read_text(), "sprite")
    assert check({"v": 1, "bg": "white", "ops": [op]}, font_dir) == []


def test_spec_poly_example_checks_clean(font_dir):
    """docs/SPEC.md's ### poly example has to be pasteable as-is, the same
    rule the sprite example is held to."""
    op = _fenced_op((ROOT / "docs" / "SPEC.md").read_text(), "poly")
    assert check({"v": 1, "bg": "white", "ops": [op]}, font_dir) == []


def test_compose_poly_example_checks_clean(font_dir):
    """The compose_display prompt's own poly example, same rule."""
    op = _fenced_op((PROMPTS / "compose.md").read_text(), "poly")
    assert check({"v": 1, "bg": "white", "ops": [op]}, font_dir) == []


def _fenced_document(text: str) -> dict:
    """The first fenced ```json block in `text` that parses to a whole
    document (an object with an `ops` key, not a lone op) -- compose.md's
    own opening "A complete example"."""
    for block in re.findall(r"[ \t]*```json\n(.*?)\n[ \t]*```", text, re.DOTALL):
        try:
            obj = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "ops" in obj:
            return obj
    raise AssertionError(f"no fenced json document found in {text[:40]!r}...")


def test_compose_complete_example_checks_clean(font_dir):
    """The guide opens with one complete, minimal document (header bar,
    one `text`, the standard footer) -- it has to actually validate clean,
    not just look plausible."""
    doc = _fenced_document((PROMPTS / "compose.md").read_text())
    assert check(doc, font_dir) == []


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


def test_wheel_bundles_every_icon_png(wheel):
    """The eight lucide activity icons' committed rasters (docs/plans/
    fonts-and-icons.md Decision 4) are git-tracked non-`.py` files under a
    package directory with no `[tool.hatch.build.targets.wheel.artifacts]`
    entry of their own -- unlike `compose.md`, which needed one. Confirmed
    here rather than assumed: hatchling's default VCS-based file selection
    includes them because they're tracked, but a future `.gitignore`/build
    config change could silently drop them from an install `draw_icon()`
    would then find nothing under (B4b review, nit 11)."""
    icon_dir = ROOT / "src" / "display_mcp" / "render" / "icons"
    expected = {f"display_mcp/render/icons/{p.name}" for p in icon_dir.glob("*.png")}
    assert len(expected) == 40
    assert expected <= set(wheel.namelist())


# --------------------------------------------------------------------------
# Prose counts vs. the tables they describe: README.md, docs/SPEC.md and
# docs/RUNBOOK.md each state, in words, how many tools/ops/font sizes/
# built-in mixes this project has. If the vocabulary grows and a doc is not
# updated, this fails instead of the doc quietly going stale.
# --------------------------------------------------------------------------

_WORDNUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "twenty-one": 21,
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
    mixes_found = _found(rf"\b({_NUM_RE})\s+built-in\b", readme, spec) | _found(
        rf"\ball\s+({_NUM_RE})\b", spec
    )

    assert tools_found == {await _tool_count()}, tools_found
    assert ops_found == {len(OP_FIELDS)}, ops_found
    assert mixes_found == {len(BUILTIN_MIXES)}, mixes_found


@pytest.mark.xfail(
    strict=True, reason="README/SPEC say six font sizes until batch B6 rewrites them"
)
def test_prose_font_size_count_matches_the_code():
    """Split out of test_prose_tool_ops_font_and_mix_counts_match_the_code
    (docs/plans/fonts-and-icons.md B1 review): `len(FONTS)` grew from 6 to
    33 in B1, but README.md/docs/SPEC.md are owned by other batches — B1's
    own rules say not to touch them — and still say "six font sizes" until
    B6's prose pass reconciles every count with what the finished
    vocabulary compiles. Still derived from `len(FONTS)`, not a frozen
    number, and `strict=True` so it flips red-to-green (an unexpected pass
    fails the suite) the moment B6 lands, rather than staying silently
    green forever. The count is `len(SIZES)` -- "font sizes" is the ladder
    (eleven), which the prose can say in words; `len(FONTS)` is the table
    (33 in B1, 110 now that B3b has landed Petrona and Karla), which no
    prose will ever spell out, so asserting that would leave this xfail
    unable to flip (B1 re-review, finding A)."""
    readme = (ROOT / "README.md").read_text()
    spec = (ROOT / "docs" / "SPEC.md").read_text()
    fonts_found = _found(rf"\b({_NUM_RE})\s+font sizes\b", readme, spec)
    assert fonts_found == {len(SIZES)}, fonts_found


@pytest.mark.xfail(
    strict=True, reason="README/SPEC say eleven icons until batch B6 rewrites them"
)
def test_prose_icon_count_matches_the_code():
    """Same shape as `test_prose_font_size_count_matches_the_code` (docs/plans/
    fonts-and-icons.md B4b review, item 4): `len(ICONS)` grew from 11 to 19
    in B4b (the eight lucide activity icons), but README.md's header count
    sentence and docs/SPEC.md's header line are B6's to rewrite, not B4b's
    -- the ### icon section and the Vocabulary section's own Icons line, both
    in scope for B4b, already say nineteen names. `strict=True` so this
    flips red-to-green (an unexpected pass fails the suite) the moment B6
    lands, rather than staying silently green forever."""
    from display_mcp.render import ICONS

    readme = (ROOT / "README.md").read_text()
    spec = (ROOT / "docs" / "SPEC.md").read_text()
    icons_found = _found(rf"\b({_NUM_RE})\s+icons\b", readme, spec)
    assert icons_found == {len(ICONS)}, icons_found
