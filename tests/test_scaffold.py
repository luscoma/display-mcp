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
from pathlib import Path

import pytest
from mcp import Client

from display_mcp import mcp_server
from display_mcp.config import Settings
from display_mcp.render import (
    BUILTIN_MIXES,
    OP_FIELDS,
    check,
    render,
    render_hash,
)
from display_mcp.render import (
    SAMPLE_PIXEL_PIN_NOW as _PIXEL_PIN_NOW,
)
from display_mcp.render.fonts import SIZES
from fakes import FakeStore

# Fixed for every pixel-pin test below: both samples' footers print
# {time}/{time24}, so a bare `render(doc, font_dir)` would pin against
# whatever second the test happened to run in. This repo's own convention
# for a short pixel-identity check (docs/plans/fonts-and-icons.md B4b
# review, item 1) -- see test_swatches.py's pre-B1 pin for the pattern.
# Imported from display_mcp.render rather than kept as a local copy (final
# review, B7/F, item 8) so docs/images/generate.py renders the checked-in
# sample.png against this exact same moment, not its own drifted copy.

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "src" / "display_mcp" / "prompts"

# repo original -> path inside the wheel, mirroring pyproject's force-include
# and the pairs _spec_text/_sample_text ask for in mcp_server.py.
BUNDLED = {
    ROOT / "docs" / "SPEC.md": "display_mcp/prompts/SPEC.md",
    ROOT / "samples" / "display.json": "display_mcp/prompts/sample.json",
}


def test_sample_hash(sample_doc):
    assert render_hash(sample_doc) == "ab71629b1ca76ea6"


def test_sprite_sample_hash(sprite_sample_doc):
    """samples/sprite.json (docs/plans/dragon-feedback.md B1) — the second
    sample, showing off the `sprite` op the way samples/display.json shows
    off everything else."""
    assert render_hash(sprite_sample_doc) == "16274a2fe47fbd06"


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
    assert digest == "d0404a75ef13eebd"


def test_sprite_sample_renders_pixel_identical(sprite_sample_doc, font_dir):
    """Same guard as `test_sample_renders_pixel_identical`, for the second
    sample's own icon op. Unlike `samples/display.json`, `sprite.json`
    was deliberately left in the bare legacy names when B7/E re-cut the
    first sample into the finished vocabulary (final review, B8) -- so
    this pin is no longer "the sample, pixel for pixel" but the
    legacy-vocabulary pixel pin: proof that the five bare aliases
    (`xl lg md sm xs`) still resolve to the same Instrument Sans faces,
    at the same pixels, that they always did."""
    img, problems = render(sprite_sample_doc, font_dir, now=_PIXEL_PIN_NOW)
    assert problems == []
    digest = hashlib.sha256(img.tobytes()).hexdigest()[:16]
    assert digest == "9e5f7b4fa62384f1"


def test_vocabulary_sample_hash(vocabulary_sample_doc):
    """samples/vocabulary.json — the third sample, a labelled page putting
    every primitive only the wall can judge on the glass at once (a
    rounded rect and a max-radius pill, mono block art and ligature-free
    text, a sprite with mirror and a document mix and a built-in mix, a
    filled poly in a mix and an outline poly, a thick circle outline, a
    thick line, and — added in B4b — the eight new activity icons at `md`
    and a couple at `xl`), for the flash-and-judge step in RUNBOOK.md."""
    assert render_hash(vocabulary_sample_doc) == "a61aaa35fa2a186b"


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


@pytest.mark.parametrize("kind", ["sprite", "poly"])
@pytest.mark.parametrize(
    "source",
    [
        pytest.param(ROOT / "docs" / "SPEC.md", id="spec"),
        pytest.param(PROMPTS / "compose.md", id="compose"),
    ],
)
def test_fenced_op_example_checks_clean(font_dir, source, kind):
    """Every fenced `sprite`/`poly` example in docs/SPEC.md and in the
    compose_display prompt has to be something an agent can paste straight
    into a document (docs/plans/dragon-feedback.md D12/B4) -- `check()` on
    it must come back clean, not merely look plausible."""
    op = _fenced_op(source.read_text(), kind)
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


def test_prose_font_size_count_matches_the_code():
    """Split out of test_prose_tool_ops_font_and_mix_counts_match_the_code
    (docs/plans/fonts-and-icons.md B1 review): `len(FONTS)` grew from 6 to
    33 in B1, but README.md/docs/SPEC.md were owned by other batches — B1's
    own rules said not to touch them — and said "six font sizes" until B6's
    prose pass reconciled every count with what the finished vocabulary
    compiles. Still derived from `len(FONTS)`, not a frozen number. The
    count is `len(SIZES)` -- "font sizes" is the ladder (eleven), which the
    prose can say in words; `len(FONTS)` is the table (33 in B1, 110 now
    that B3b has landed Petrona and Karla), which no prose will ever spell
    out, so asserting that would leave this test unable to pass (B1
    re-review, finding A). No longer `xfail` -- B6 rewrote the prose."""
    readme = (ROOT / "README.md").read_text()
    spec = (ROOT / "docs" / "SPEC.md").read_text()
    fonts_found = _found(rf"\b({_NUM_RE})\s+font sizes\b", readme, spec)
    assert fonts_found == {len(SIZES)}, fonts_found


def test_compose_md_cites_every_icon_depicts_phrase():
    """compose.md's icon list carries a parenthetical per name, cited from
    `ICON_DEPICTS` (final review, "Composer over MCP") -- so a wrong icon
    name can be caught by reading the guide, not just by opening a PNG."""
    from display_mcp.render import ICON_DEPICTS

    # Collapsed to single spaces: the guide is hand-wrapped prose, so a
    # phrase this test looks for may cross a line break in the source.
    compose = re.sub(r"\s+", " ", (PROMPTS / "compose.md").read_text())
    for name, depicts in ICON_DEPICTS.items():
        assert f"`{name}` ({depicts})" in compose, f"{name}: {depicts!r} not in compose.md"


def test_prose_icon_count_matches_the_code():
    """Same shape as `test_prose_font_size_count_matches_the_code` (docs/plans/
    fonts-and-icons.md B4b review, item 4): `len(ICONS)` grew from 11 to 19
    in B4b (the eight lucide activity icons), but README.md's header count
    sentence and docs/SPEC.md's header line were B6's to rewrite, not B4b's
    -- the ### icon section and the Vocabulary section's own Icons line, both
    in scope for B4b, already said nineteen names. No longer `xfail` -- B6
    rewrote the two header lines, and `_WORDNUM` gained `"nineteen"`, which
    it did not carry before (nothing before B4b needed to spell 19)."""
    from display_mcp.render import ICONS

    readme = (ROOT / "README.md").read_text()
    spec = (ROOT / "docs" / "SPEC.md").read_text()
    icons_found = _found(rf"\b({_NUM_RE})\s+icons\b", readme, spec)
    assert icons_found == {len(ICONS)}, icons_found


def test_fonts_sample_is_a_complete_type_specimen(font_dir):
    """samples/fonts.json -- the fourth sample, a type specimen to publish
    when judging the faces on the glass: every family-style at `md`,
    Petrona at every compiled size below `xl` (the header is `xl`), the
    five bare names, mono, both decorations, the five slots in Karla. It
    must validate clean, be stamped, and keep naming the whole vocabulary
    -- regenerate it with samples/gen_fonts_sample.py when that changes."""
    import json

    from display_mcp.render import FONTS, SIZES, check, render_hash, resolve_font
    from display_mcp.render.fonts import FAMILIES
    doc = json.loads((ROOT / "samples" / "fonts.json").read_text())
    assert check(doc, font_dir) == []
    assert doc["meta"]["hash"] == render_hash(doc)
    used = {resolve_font(op["f"]) for op in doc["ops"] if op["op"] in ("text", "fmt")}
    family_styles = {FONTS[name].family + ("-" + FONTS[name].style if FONTS[name].style else "")
                     for name in used}
    expected = {fam if not style else f"{fam}-{style}"
                for fam, family in FAMILIES.items() for style in family.styles}
    assert family_styles == expected, expected - family_styles
    sizes = {FONTS[name].size for name in used}
    assert sizes == set(SIZES), set(SIZES) - sizes
    assert {op.get("deco") for op in doc["ops"] if op["op"] == "text"} >= {"underline", "strike"}
    assert {op["f"] for op in doc["ops"] if op["op"] == "text"} >= {"xl", "lg", "md", "sm", "xs"}
