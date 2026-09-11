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

from display_mcp import mcp_server
from display_mcp.config import Settings
from display_mcp.render import INK
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
