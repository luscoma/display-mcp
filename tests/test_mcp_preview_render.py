"""`preview` driven through the real renderer.

tests/test_mcp.py stubs `display_mcp.render` out with fakes, which is right
for the tool plumbing but blind to what `preview` actually draws: the fake
accepts `dithered_colors` and ignores it, and its `check` is its `render`.
Under those fakes, deleting `dithered_colors=dithered_colors` from the tool
or swapping `check()` for the render's own problem list both pass the whole
suite. So the commit's headline behaviour needs a test that renders for
real, and it lives here rather than in test_mcp.py to stay clear of that
module's autouse fake-renderer fixture.
"""

from __future__ import annotations

import base64
import io
from collections import Counter

import pytest
from mcp import Client
from PIL import Image

from display_mcp import mcp_server, render
from display_mcp.config import Settings
from display_mcp.render import GRID_COLOR, INK
from fakes import FakeStore

# A rect of `grey-mid` (black+white 50). Dithered it is half black and half
# white; flat it is the single colour those fuse to, #7F7F7C in SPEC.md.
GREY_MID_FUSED = (127, 127, 124)
BOX = (20, 20, 180, 180)


def _doc(ops=None):
    return {
        "v": 1,
        "meta": {},
        "bg": "white",
        "palette": {},
        "ops": ops or [{"op": "rect", "x": 0, "y": 0, "w": 200, "h": 200, "c": "grey-mid"}],
    }


@pytest.fixture
def mcp(tmp_path, font_dir):
    """The real `display_mcp.render`, against a fake store."""
    settings = Settings(state_dir=tmp_path / "state", font_dir=font_dir)
    return mcp_server.build_mcp(FakeStore(), settings)


async def _preview_patch(mcp, document, **kwargs):
    async with Client(mcp) as c:
        result = await c.call_tool("preview", {"document": document, **kwargs})
    assert result.is_error is not True
    image = next(b for b in result.content if b.type == "image")
    text = next(b for b in result.content if b.type == "text")
    png = Image.open(io.BytesIO(base64.b64decode(image.data))).convert("RGB")
    return Counter(png.crop(BOX).get_flattened_data()), text.text


async def test_preview_flattens_a_mix_to_one_colour(mcp):
    """The default: what an agent judging a design actually sees."""
    patch, _ = await _preview_patch(mcp, _doc())
    assert set(patch) == {GREY_MID_FUSED}


async def test_preview_dithered_draws_the_real_checkerboard(mcp):
    """The escape hatch has to genuinely reach the panel's own output —
    under the fakes this parameter could be dropped entirely unnoticed."""
    patch, _ = await _preview_patch(mcp, _doc(), dithered_colors=True)
    assert set(patch) == {INK["black"], INK["white"]}
    assert patch[INK["black"]] == patch[INK["white"]]


async def test_preview_warnings_come_from_check_not_from_the_render(mcp):
    """`check()` adds the bezel and stale-hash checks on top of render()'s
    problems, so a bezel violation appears only if preview really is calling
    check(). Swapping in the render's own problem list drops it silently."""
    doc = _doc([{"op": "text", "x": 4, "y": 4, "s": "In the bezel", "f": "sm", "c": "black"}])
    _, note = await _preview_patch(mcp, doc)
    assert "bezel" in note
    assert any(line.startswith("- ") for line in note.splitlines())


async def test_preview_note_is_clean_when_there_is_nothing_to_warn_about(mcp):
    """No dangling "warnings below" with nothing below it."""
    _, note = await _preview_patch(mcp, _doc())
    assert not any(line.startswith("- ") for line in note.splitlines())
    assert note == mcp_server._FLAT_NOTE


async def _preview_bytes(mcp, document, **kwargs):
    async with Client(mcp) as c:
        result = await c.call_tool("preview", {"document": document, **kwargs})
    assert result.is_error is not True
    image = next(b for b in result.content if b.type == "image")
    text = next(b for b in result.content if b.type == "text")
    return base64.b64decode(image.data), text.text


async def test_preview_grid_draws_the_overlay_colour_and_note(mcp):
    png, note = await _preview_bytes(mcp, _doc(), grid=True)
    img = Image.open(io.BytesIO(png)).convert("RGB")
    colors = {c for c in img.get_flattened_data()}
    assert GRID_COLOR in colors
    assert mcp_server._GRID_NOTE in note


async def test_preview_without_grid_is_byte_identical_and_has_no_overlay_colour(mcp):
    """Default behaviour must be untouched: same bytes as before grid existed,
    and no stray grid pixels sneak into a plain preview."""
    plain_bytes, plain_note = await _preview_bytes(mcp, _doc())
    default_bytes, default_note = await _preview_bytes(mcp, _doc(), grid=False)
    assert plain_bytes == default_bytes
    assert plain_note == default_note
    img = Image.open(io.BytesIO(default_bytes)).convert("RGB")
    assert GRID_COLOR not in {c for c in img.get_flattened_data()}
    assert mcp_server._GRID_NOTE not in default_note


def test_grid_overlay_does_not_mutate_its_input(font_dir, sample_doc):
    img, _ = render.render(sample_doc, font_dir)
    before = img.copy()
    overlaid = render.grid_overlay(img)
    assert img.tobytes() == before.tobytes()
    assert overlaid is not img
    assert GRID_COLOR in {c for c in overlaid.get_flattened_data()}


def test_render_output_is_unchanged_whether_or_not_a_caller_later_grids_it(font_dir, sample_doc):
    """grid_overlay is applied to render()'s *return value*, never inside
    it — render() itself has no `grid` parameter and always emits only the
    six inks (test_render.py:test_render_emits_only_the_six_inks)."""
    img, _problems = render.render(sample_doc, font_dir)
    assert set(img.get_flattened_data()) <= set(INK.values())
    render.grid_overlay(img)  # a caller applying the overlay afterwards, on a copy
    assert set(img.get_flattened_data()) <= set(INK.values())  # img itself never changed


def test_grid_overlay_closes_the_far_edges_with_a_real_border_line(font_dir, sample_doc):
    """F6: a coordinate line at WIDTH/HEIGHT themselves lands one pixel past
    the last real column/row and PIL draws nothing there at all — not "drawn
    but not labelled" as the docstring used to claim. The far edges are
    closed with an explicit border at w-1/h-1 instead."""
    img, _ = render.render(sample_doc, font_dir)
    overlaid = render.grid_overlay(img)
    w, h = overlaid.size
    px = overlaid.load()
    assert px[w - 1, h // 2] == GRID_COLOR
    assert px[w // 2, h - 1] == GRID_COLOR
