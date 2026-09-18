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
from display_mcp.store import MAX_DOC_BYTES, Store, stamped_body
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


async def test_preview_no_document_returns_the_published_document(tmp_path, font_dir):
    """With no `document` argument, `preview` renders whatever is currently
    published under `name`, not a blank canvas -- publish a `grey-mid` fill
    and check the previewed patch fuses to the same colour an explicit doc
    would."""
    settings = Settings(state_dir=tmp_path / "state", font_dir=font_dir)
    store = FakeStore()
    store.publish(_doc())
    mcp = mcp_server.build_mcp(store, settings)
    patch, _ = await _preview_patch(mcp, None)
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


def test_grid_overlay_closes_the_far_edges_with_a_real_border_line(font_dir, sample_doc):
    """A coordinate line at WIDTH/HEIGHT themselves lands one pixel past
    the last real column/row and PIL draws nothing there at all. The far
    edges are closed with an explicit border at w-1/h-1 instead."""
    img, _ = render.render(sample_doc, font_dir)
    overlaid = render.grid_overlay(img)
    w, h = overlaid.size
    px = overlaid.load()
    assert px[w - 1, h // 2] == GRID_COLOR
    assert px[w // 2, h - 1] == GRID_COLOR


def test_grid_overlay_runs_with_a_real_font_and_draws_the_grid_colour(font_dir, sample_doc):
    """`grid_overlay` takes an optional real face (what `preview` loads
    from `font_dir` via `load_font`) instead of only PIL's bitmap default;
    the overlay colour still appears wherever the face comes from."""
    img, _ = render.render(sample_doc, font_dir)
    grid_face = render.Face(22, False, "InstrumentSans-Regular.ttf", 0)
    face = render.load_font(font_dir, grid_face)
    overlaid = render.grid_overlay(img, font=face)
    bitmap = render.grid_overlay(img)
    assert GRID_COLOR in {c for c in overlaid.get_flattened_data()}
    # A 22 px face makes bigger label chips than PIL's bitmap default, so
    # the overlay paints more pixels. If `font` were ignored the two renders
    # would be identical.
    def overlay_pixels(im):
        return sum(1 for c in im.get_flattened_data() if c == GRID_COLOR)

    assert overlaid.tobytes() != bitmap.tobytes()
    assert overlay_pixels(overlaid) > overlay_pixels(bitmap)


def test_grid_overlay_with_no_font_dir_still_produces_a_grid():
    """A missing font directory (the common case for a bare `grid_overlay`
    call, and `preview`'s fallback when Instrument Sans isn't installed)
    must never fail the overlay — it falls back to PIL's bitmap default."""
    img = Image.new("RGB", (render.WIDTH, render.HEIGHT), "white")
    overlaid = render.grid_overlay(img, font=None)
    assert GRID_COLOR in {c for c in overlaid.get_flattened_data()}


async def test_preview_grid_survives_a_missing_grid_font(
    monkeypatch, tmp_path, font_dir, sample_doc
):
    """`preview`'s own fallback: when `load_font` can't produce the grid's
    face specifically (the document's own fonts still load fine, so this
    isn't just `render()` failing outright), the grid still renders rather
    than erroring the tool call."""
    real_load_font = render.load_font

    def flaky(fd, face):
        if face.size == 22 and not face.bold:  # exactly the grid label's request
            raise OSError("simulated: grid face not installed")
        return real_load_font(fd, face)

    monkeypatch.setattr(render, "load_font", flaky)
    settings = Settings(state_dir=tmp_path / "state", font_dir=font_dir)
    mcp = mcp_server.build_mcp(FakeStore(), settings)
    png, note = await _preview_bytes(mcp, sample_doc, grid=True)
    img = Image.open(io.BytesIO(png)).convert("RGB")
    assert GRID_COLOR in {c for c in img.get_flattened_data()}
    assert mcp_server._GRID_NOTE in note


# --------------------------------------------------------------------------
# `validate`'s `bytes` must be the number `set_display` actually gates.
#
# FakeStore stamps independently of `display_mcp.store.stamped_body`, so it
# can't catch the two drifting apart -- these use the real Store.
# --------------------------------------------------------------------------


@pytest.fixture
def real_mcp(tmp_path, font_dir):
    settings = Settings(state_dir=tmp_path / "state", font_dir=font_dir)
    store = Store(tmp_path / "state", font_dir)
    return mcp_server.build_mcp(store, settings)


async def _call(mcp, tool, **kwargs):
    async with Client(mcp) as c:
        return await c.call_tool(tool, kwargs)


def _padded_doc(target_bytes: int) -> dict:
    """A minimal, valid document with an unused top-level `pad` field (kept
    out of meta.hash, which covers only bg/palette/ops) sized so its
    *stamped* body is exactly `target_bytes`."""
    doc = {"bg": "white", "ops": [], "pad": ""}
    _, body = stamped_body(doc, "0" * 24)
    pad_needed = target_bytes - len(body)
    assert pad_needed >= 0
    doc["pad"] = "x" * pad_needed
    _, body = stamped_body(doc, "0" * 24)
    assert len(body) == target_bytes
    return doc


async def test_validate_bytes_equals_set_display_bytes_for_the_sample(real_mcp, sample_doc):
    validated = await _call(real_mcp, "validate", document=sample_doc)
    published = await _call(real_mcp, "set_display", document=sample_doc, name="probe")
    assert validated.is_error is not True
    assert published.is_error is not True
    assert validated.structured_content["bytes"] == published.structured_content["bytes"]
    assert validated.structured_content["hash"] == published.structured_content["hash"]


async def test_document_exactly_at_the_ceiling_validates_and_publishes(real_mcp):
    doc = _padded_doc(MAX_DOC_BYTES)
    validated = await _call(real_mcp, "validate", document=doc)
    assert validated.structured_content["bytes"] == MAX_DOC_BYTES
    assert validated.structured_content["max_bytes"] == MAX_DOC_BYTES
    published = await _call(real_mcp, "set_display", document=doc, name="ceiling")
    assert published.is_error is not True
    assert published.structured_content["bytes"] == MAX_DOC_BYTES


async def test_one_byte_over_is_refused_by_set_display_and_flagged_by_validate(real_mcp):
    doc = _padded_doc(MAX_DOC_BYTES + 1)
    validated = await _call(real_mcp, "validate", document=doc)
    assert validated.structured_content["bytes"] == MAX_DOC_BYTES + 1
    assert validated.structured_content["bytes"] > validated.structured_content["max_bytes"]
    published = await _call(real_mcp, "set_display", document=doc, name="over")
    assert published.is_error is True
