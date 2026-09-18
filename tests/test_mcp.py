"""mcp_server.py: tools, resources and the compose prompt, against FakeStore
and a fake renderer (both display_mcp.store.Store and display_mcp.render
are stubs on this branch)."""

from __future__ import annotations

import json

import pytest
from mcp import Client
from starlette.testclient import TestClient

from display_mcp import mcp_server, render
from display_mcp.config import Settings
from fakes import FakeStore, fake_check, fake_render
from test_render import _spec_palette_hexes


@pytest.fixture(autouse=True)
def _fake_renderer(monkeypatch):
    monkeypatch.setattr(render, "render", fake_render)
    monkeypatch.setattr(render, "check", fake_check)


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(state_dir=tmp_path / "state", font_dir=tmp_path / "fonts")


@pytest.fixture
def auth_settings(tmp_path) -> Settings:
    return Settings(
        state_dir=tmp_path / "state",
        font_dir=tmp_path / "fonts",
        cf_access_team_domain="https://example.cloudflareaccess.com",
        cf_access_aud="test-aud",
    )


@pytest.fixture
def mcp(store, settings):
    return mcp_server.build_mcp(store, settings)


def _text_of(result) -> str | None:
    for block in result.content:
        if block.type == "text":
            return block.text
    return None


# ---- tools ----------------------------------------------------------------


async def test_list_tools_and_annotations(mcp):
    async with Client(mcp) as c:
        tools = (await c.list_tools()).tools
    by_name = {t.name: t for t in tools}
    assert set(by_name) == {
        "set_display",
        "preview",
        "validate",
        "get_display",
        "status",
        "clear_display",
        "describe",
        "guide",
    }
    for name in ("preview", "validate", "get_display", "status", "describe", "guide"):
        assert by_name[name].annotations.read_only_hint is True
    assert by_name["set_display"].annotations.read_only_hint is False
    assert by_name["clear_display"].annotations.read_only_hint is False
    assert by_name["clear_display"].annotations.destructive_hint is True


async def test_set_display_shape_and_stamped_hash(mcp, store, sample_doc):
    async with Client(mcp) as c:
        result = await c.call_tool("set_display", {"document": sample_doc})
    assert result.is_error is not True
    data = result.structured_content
    assert set(data) == {"name", "hash", "etag", "ops", "bytes", "warnings"}
    assert data["name"] == "default"
    assert data["etag"] == f'"{data["hash"]}"'
    assert data["ops"] == len(sample_doc["ops"])
    assert data["warnings"] == []

    published = store.get("default")
    assert published.hash == data["hash"]
    assert published.hash == render.render_hash(published.doc)


async def test_set_display_named(mcp, store, sample_doc):
    async with Client(mcp) as c:
        result = await c.call_tool("set_display", {"document": sample_doc, "name": "kitchen"})
    assert result.structured_content["name"] == "kitchen"
    assert store.names() == ["kitchen"]


async def test_preview_published_returns_image_and_no_new_publish(mcp, store, sample_doc):
    store.publish(sample_doc)
    async with Client(mcp) as c:
        result = await c.call_tool("preview", {})
    assert result.is_error is not True
    assert any(block.type == "image" for block in result.content)


async def test_preview_draft_does_not_publish(mcp, store, sample_doc):
    async with Client(mcp) as c:
        result = await c.call_tool("preview", {"document": sample_doc})
    assert result.is_error is not True
    assert any(block.type == "image" for block in result.content)
    assert store.names() == []  # a draft preview publishes nothing


async def test_preview_returns_the_right_note_beside_the_image(mcp, sample_doc):
    """The caveat rides in the response, not only in the tool docstring.

    A docstring is read once at tool-discovery time and a long way from the
    picture; a reader looking at an aliased swatch believed the pixels
    instead, called it a renderer bug, and redesigned around it.

    These assert on the constants rather than on substrings of the prose:
    what is being pinned is that each mode gets its own note, not any
    particular wording. The dithered note has to differ because it re-opens
    the aliasing trap the flat note says has been closed — the flat text
    would be a lie about that image.
    """
    async with Client(mcp) as c:
        flat = await c.call_tool("preview", {"document": sample_doc})
        dithered = await c.call_tool("preview", {"document": sample_doc, "dithered_colors": True})
    for result, want in ((flat, mcp_server._FLAT_NOTE), (dithered, mcp_server._DITHERED_NOTE)):
        assert [b.type for b in result.content] == ["image", "text"]
        assert result.content[1].text.startswith(want)
    assert mcp_server._FLAT_NOTE != mcp_server._DITHERED_NOTE


async def test_preview_grid_parameter_is_accepted_and_notes_the_overlay(mcp, sample_doc):
    """Plumbing only — that the PNG genuinely carries the overlay is pinned
    for real in tests/test_mcp_preview_render.py, which doesn't stub the
    renderer out."""
    async with Client(mcp) as c:
        plain = await c.call_tool("preview", {"document": sample_doc})
        gridded = await c.call_tool("preview", {"document": sample_doc, "grid": True})
    assert plain.is_error is not True
    assert gridded.is_error is not True
    assert mcp_server._GRID_NOTE not in plain.content[1].text
    assert mcp_server._GRID_NOTE in gridded.content[1].text


def test_the_two_notes_each_describe_their_own_image():
    """The one place wording is pinned, because these two sentences are the
    whole point of the change: the flat note must not claim the image is
    what the panel draws, and the dithered note must warn that scaling it
    aliases each mix."""
    assert "averages to" in mcp_server._FLAT_NOTE
    assert "reads lighter" in mcp_server._FLAT_NOTE
    assert "Do not judge colour from this image" in mcp_server._DITHERED_NOTE
    assert "aliases" in mcp_server._DITHERED_NOTE


async def test_preview_warnings_are_the_ones_validate_reports(mcp):
    """Sourced from check(), so preview and validate cannot disagree.

    This pins the plumbing; that the warnings describe the *dithered* panel
    rather than the flat image is pinned for real in
    tests/test_mcp_preview_render.py, which does not stub the renderer out.
    """
    doc = {"v": 1, "bg": "white", "ops": "not a list"}
    async with Client(mcp) as c:
        preview = await c.call_tool("preview", {"document": doc})
        validate = await c.call_tool("validate", {"document": doc})
    warnings = validate.structured_content["warnings"]
    assert warnings
    for w in warnings:
        assert f"- {w}" in preview.content[1].text


async def test_preview_no_document_and_nothing_published_is_error(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("preview", {})
    assert result.is_error is True


async def test_validate_returns_shape(mcp, sample_doc):
    async with Client(mcp) as c:
        result = await c.call_tool("validate", {"document": sample_doc})
    assert result.is_error is not True
    data = result.structured_content
    assert set(data) == {"hash", "ops", "bytes", "warnings", "colors", "max_bytes"}
    assert data["hash"] == render.render_hash(sample_doc)
    assert data["ops"] == len(sample_doc["ops"])
    assert data["warnings"] == []
    assert data["bytes"] > 0
    assert data["max_bytes"] == mcp_server.MAX_DOC_BYTES
    assert set(data["colors"]) >= {
        "accent",
        "work",
        "home",
        "highlight",
        "grey-mid",
        "black",
        "white",
        "yellow",
    }


async def test_validate_stores_nothing(mcp, store, sample_doc):
    async with Client(mcp) as c:
        await c.call_tool("validate", {"document": sample_doc})
    assert store.names() == []


# ---- validate(): document_colors' own problems merged into warnings ----


async def test_validate_reports_a_malformed_mix_entry_nothing_draws_with(mcp):
    """A palette entry no op references: `check()` (faked here to a shape
    check only, same as `document_colors()` doesn't need it) never visits
    it, so this depends on `document_colors()`'s own problem reaching
    `warnings`."""
    doc = {"v": 1, "bg": "white", "palette": {"broken": {"c2": "red"}}, "ops": []}
    async with Client(mcp) as c:
        result = await c.call_tool("validate", {"document": doc})
    data = result.structured_content
    assert data["colors"]["broken"] == {"recipe": "ink", "hex": render.hex_of(render.INK["black"])}
    assert data["warnings"] == ["palette 'broken': mix 'broken' has no 'c'; using black"]


async def test_validate_reports_an_unresolvable_palette_alias(mcp):
    doc = {"v": 1, "bg": "white", "palette": {"ghost": "nope"}, "ops": []}
    async with Client(mcp) as c:
        result = await c.call_tool("validate", {"document": doc})
    data = result.structured_content
    assert "ghost" not in data["colors"]
    assert data["warnings"] == ["palette 'ghost': unknown colour 'nope'"]


def test_merge_color_problems_dedupes_by_message_text_keeping_check_order_first():
    checked = [
        "ops[0] rect: off-canvas",
        "ops[1] text: mix 'broken' has no 'c'; using black",
    ]
    color_problems = [
        "palette 'broken': mix 'broken' has no 'c'; using black",  # same complaint
        "palette 'ghost': unknown colour 'nope'",  # a genuinely new one
    ]
    merged = mcp_server._merge_color_problems(checked, color_problems)
    assert merged == [
        "ops[0] rect: off-canvas",
        "ops[1] text: mix 'broken' has no 'c'; using black",
        "palette 'ghost': unknown colour 'nope'",
    ]


# The end-to-end version of this — the real check() (not this file's fake)
# feeding _merge_color_problems() — is
# tests/test_render.py::test_check_and_document_colors_merge_does_not_duplicate,
# since this file's autouse fixture fakes render.check()/.render(), and
# check() calls render() as a same-module global, so even a reference
# captured before the fixture runs would still call the fake.


async def test_get_display_roundtrips(mcp, store, sample_doc):
    store.publish(sample_doc)
    async with Client(mcp) as c:
        result = await c.call_tool("get_display", {})
    assert result.is_error is not True
    assert result.structured_content["meta"]["hash"] == store.get("default").hash


async def test_status_single_display(mcp, store, sample_doc):
    store.publish(sample_doc)
    store.note_fetch("default", 200, "10.0.0.5")
    async with Client(mcp) as c:
        result = await c.call_tool("status", {"name": "default"})
    data = result.structured_content
    assert data["published"] is True
    assert data["name"] == "default"
    assert data["recent_fetch_status"] == 200
    assert data["recent_fetch_ip"] == "10.0.0.5"
    assert data["published_ago"].endswith("ago")
    assert data["first_fetch_ago"].endswith("ago")
    assert data["recent_fetch_ago"].endswith("ago")
    assert data["published_at"] is not None and "T" in data["published_at"]


async def test_status_all_displays(mcp, store, sample_doc, auth_settings):
    store.publish(sample_doc)
    async with Client(mcp) as c:
        result = await c.call_tool("status", {})
    data = result.structured_content
    assert "default" in data["displays"]
    assert data["displays"]["default"]["published"] is True
    assert data["auth"] == "none"

    # auth reflected in a server built with Cloudflare Access configured
    auth_mcp = mcp_server.build_mcp(store, auth_settings)
    async with Client(auth_mcp) as c:
        result2 = await c.call_tool("status", {})
    assert result2.structured_content["auth"] == "cloudflare-access"


async def test_status_unpublished_name_is_not_an_error(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("status", {"name": "nope"})
    assert result.is_error is not True
    data = result.structured_content
    assert data == {
        "published": False,
        "name": "nope",
        "hash": None,
        "ops": None,
        "bytes": None,
        "published_at": None,
        "published_ago": None,
        "first_fetch_at": None,
        "first_fetch_ago": None,
        "recent_fetch_at": None,
        "recent_fetch_ago": None,
        "recent_fetch_status": None,
        "recent_fetch_ip": None,
    }


async def test_clear_display(mcp, store, sample_doc):
    store.publish(sample_doc)
    async with Client(mcp) as c:
        result = await c.call_tool("clear_display", {})
    assert result.is_error is not True
    assert result.structured_content == {"name": "default", "cleared": True}
    assert store.names() == []


async def test_clear_display_already_absent(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("clear_display", {"name": "ghost"})
    assert result.structured_content == {"name": "ghost", "cleared": False}


# ---- describe() / guide() ----------------------------------------------


async def test_describe_shape(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("describe", {})
    assert result.is_error is not True
    data = result.structured_content
    assert set(data) == {
        "canvas",
        "inks",
        "mixes",
        "densities",
        "fonts",
        "anchors",
        "icons",
        "icon_sizes",
        "ops",
        "fmt_fields",
        "limits",
    }
    assert data["canvas"] == {
        "w": render.WIDTH,
        "h": render.HEIGHT,
        "bezel_margin": render.BEZEL_MARGIN,
    }
    assert data["densities"] == list(render.DENSITIES)
    assert data["limits"] == {"max_bytes": mcp_server.MAX_DOC_BYTES}
    assert set(data["fmt_fields"]) == set(render.system_fields({}))
    assert data["anchors"] == list(render.ANCHOR)


async def test_describe_icon_sizes_only_advertises_classes_some_icon_has(mcp):
    """`ICON_SIZES` has `md: 56` for arithmetic elsewhere, but no icon
    compiles to `md` today — advertising it would invite `{"n": ...,
    "z": "md"}`, which `check()` then rejects as not compiled in."""
    async with Client(mcp) as c:
        result = await c.call_tool("describe", {})
    used = {z for sizes in render.ICONS.values() for z in sizes}
    assert set(result.structured_content["icon_sizes"]) == used == {"sm", "lg"}
    for z in used:
        assert result.structured_content["icon_sizes"][z] == render.ICON_SIZES[z]


async def test_describe_inks_match_the_ink_table(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("describe", {})
    inks = result.structured_content["inks"]
    assert set(inks) == set(render.INK)
    for name, rgb in render.INK.items():
        assert inks[name] == "#{:02X}{:02X}{:02X}".format(*rgb)


async def test_describe_mixes_match_spec_md(mcp):
    """Pins `describe()` to `render.BUILTIN_MIXES`/`render.TIERS`, i.e. that
    `describe()` reports the renderer's own tables verbatim — not a second,
    independent read of SPEC.md. The guard that those renderer tables
    themselves match docs/SPEC.md's prose is
    tests/test_render.py::test_tier_matches_the_spec_heading; this test
    only reuses that file's SPEC-table parser for its expected hexes."""
    async with Client(mcp) as c:
        result = await c.call_tool("describe", {})
    mixes = result.structured_content["mixes"]
    spec = _spec_palette_hexes()
    assert set(mixes) == set(render.BUILTIN_MIXES) == set(spec)
    for name, row in mixes.items():
        c_, c2, pct, want_hex = spec[name]
        assert (row["c"], row["c2"], row["mix"]) == (c_, c2, pct)
        assert row["hex"] == f"#{want_hex.upper()}"
        assert row["tier"] == render.TIERS[name]


async def test_describe_ops_equals_op_fields_modulo_tuple_to_list(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("describe", {})
    ops = result.structured_content["ops"]
    assert set(ops) == set(render.OP_FIELDS)
    for name, spec in render.OP_FIELDS.items():
        assert ops[name] == {
            "required": list(spec["required"]),
            "optional": spec["optional"],
        }


async def test_describe_fonts_matches_fonts_table(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("describe", {})
    fonts = result.structured_content["fonts"]
    assert set(fonts) == set(render.FONTS)
    for name, (px, bold) in render.FONTS.items():
        assert fonts[name] == {"px": px, "bold": bold, "line_height": round(px * 1.24)}


async def test_describe_icons_matches_icons_table(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("describe", {})
    icons = result.structured_content["icons"]
    assert set(icons) == set(render.ICONS)
    for name, sizes in render.ICONS.items():
        assert set(icons[name]) == set(sizes)


async def test_describe_is_under_4096_bytes(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("describe", {})
    body = json.dumps(result.structured_content, separators=(",", ":")).encode("utf-8")
    assert len(body) < 4096


async def test_guide_returns_compose_md_verbatim(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("guide", {})
    assert result.is_error is not True
    assert _text_of(result) == mcp_server.COMPOSE_PROMPT


# ---- document may arrive as a JSON string ----------------------------
#
# Some MCP clients serialize an object-typed argument to a string before
# sending it rather than nesting it as JSON. Two layers handle that. The
# SDK itself pre-parses any string argument whose annotation is not plain
# `str` and, when it decodes to an object, hands the tool a dict — so the
# three round-trip tests below pin that an object-as-string reaches the
# tool at all and produces the same result, not that our helper parsed it.
# A string the SDK leaves alone (one that decodes to a scalar, or does not
# decode) is what reaches `_coerce_document`; those paths are pinned by
# the error tests and the direct unit test further down. A string that
# decodes to an array or null is rejected by the SDK's own validation
# before the tool runs ("Input should be a valid dictionary") — see
# docs/plans/dragon-feedback.md D2 for why that is left as it is.


async def test_tool_schema_still_accepts_a_plain_dict(mcp):
    """The `document` parameter's declared type widened to dict | str; a
    plain object is still valid input, not narrowed to string-only."""
    async with Client(mcp) as c:
        tools = (await c.list_tools()).tools
    schema = {t.name: t.input_schema for t in tools}["set_display"]
    variants = schema["properties"]["document"]["anyOf"]
    assert {"object", "string"} == {v["type"] for v in variants}


async def test_set_display_json_string_round_trips_to_the_same_hash(mcp, store, sample_doc):
    as_string = json.dumps(sample_doc)
    async with Client(mcp) as c:
        from_dict = await c.call_tool("set_display", {"document": sample_doc, "name": "a"})
        from_string = await c.call_tool("set_display", {"document": as_string, "name": "b"})
    assert from_dict.is_error is not True
    assert from_string.is_error is not True
    assert from_dict.structured_content["hash"] == from_string.structured_content["hash"]


async def test_validate_json_string_round_trips_to_the_same_hash(mcp, sample_doc):
    as_string = json.dumps(sample_doc)
    async with Client(mcp) as c:
        from_dict = await c.call_tool("validate", {"document": sample_doc})
        from_string = await c.call_tool("validate", {"document": as_string})
    assert from_dict.is_error is not True
    assert from_string.is_error is not True
    assert from_dict.structured_content == from_string.structured_content


async def test_preview_json_string_round_trips(mcp, sample_doc):
    as_string = json.dumps(sample_doc)
    async with Client(mcp) as c:
        from_dict = await c.call_tool("preview", {"document": sample_doc})
        from_string = await c.call_tool("preview", {"document": as_string})
    assert from_dict.is_error is not True
    assert from_string.is_error is not True
    assert from_dict.content[1].text == from_string.content[1].text


async def test_bad_json_string_document_is_a_tool_error_naming_the_position(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("set_display", {"document": '{"bg": "white", "ops": [}'})
    assert result.is_error is True
    text = _text_of(result) or ""
    assert "document arrived as a string" in text
    assert "line 1 column 25" in text


async def test_non_object_json_string_document_is_a_tool_error(mcp):
    """A JSON string that parses to a bare scalar (not an object). A JSON
    array is covered directly against `_coerce_document` below instead: the
    SDK's own argument pre-parsing (func_metadata.pre_parse_json) turns a
    string that decodes to a list or dict into that value *before* the tool
    body runs, so it never reaches `_coerce_document` as a string over this
    path — a scalar is the one shape that pre-parsing deliberately leaves
    as a string (its own docstring: `"hello"` should stay `"hello"`, not
    become `hello`)."""
    async with Client(mcp) as c:
        result = await c.call_tool("validate", {"document": "42"})
    assert result.is_error is True
    text = _text_of(result) or ""
    assert "document arrived as a string" in text
    assert "parsed to int" in text


def test_coerce_document_handles_every_shape():
    """Direct unit coverage of `_coerce_document`, independent of the MCP
    SDK's own argument pre-parsing — including the JSON-array case that
    pre-parsing intercepts before it ever reaches this function when called
    through a real tool invocation."""
    doc = {"bg": "white", "ops": []}
    assert mcp_server._coerce_document(doc) is doc
    assert mcp_server._coerce_document(json.dumps(doc)) == doc

    with pytest.raises(mcp_server.ToolError, match="document arrived as a string"):
        mcp_server._coerce_document('{"bg": "white", "ops": [}')

    with pytest.raises(mcp_server.ToolError, match="parsed to list"):
        mcp_server._coerce_document("[1, 2, 3]")


# ---- errors -----------------------------------------------------------


async def test_bad_name_is_tool_error(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("get_display", {"name": "Not A Valid Name!"})
    assert result.is_error is True
    assert "bad display name" in (_text_of(result) or "")


async def test_unknown_display_get_is_tool_error(mcp):
    async with Client(mcp) as c:
        result = await c.call_tool("get_display", {"name": "nope"})
    assert result.is_error is True


# ---- resources --------------------------------------------------------


async def test_spec_resource(mcp):
    async with Client(mcp) as c:
        result = await c.read_resource("display://spec")
    text = result.contents[0].text
    assert "hash" in text.lower()
    assert result.contents[0].mime_type == "text/markdown"


async def test_sample_resource(mcp):
    async with Client(mcp) as c:
        result = await c.read_resource("display://sample")
    doc = json.loads(result.contents[0].text)
    assert doc["meta"]["hash"] == "3cd62aa76e731d2d"


async def test_current_resource(mcp, store, sample_doc):
    store.publish(sample_doc)
    async with Client(mcp) as c:
        result = await c.read_resource("display://current/default")
    doc = json.loads(result.contents[0].text)
    assert doc["meta"]["hash"] == store.get("default").hash


# ---- prompt -------------------------------------------------------------


async def test_compose_prompt_listed(mcp):
    async with Client(mcp) as c:
        prompts = (await c.list_prompts()).prompts
    assert "compose_display" in {p.name for p in prompts}


async def test_compose_prompt_renders_without_args(mcp):
    async with Client(mcp) as c:
        result = await c.get_prompt("compose_display")
    text = result.messages[0].content.text
    assert "1200" in text and "1600" in text


async def test_compose_prompt_renders_with_args(mcp):
    async with Client(mcp) as c:
        result = await c.get_prompt(
            "compose_display", {"name": "kitchen", "context": "tomorrow's weather"}
        )
    text = result.messages[0].content.text
    assert "kitchen" in text
    assert "tomorrow's weather" in text


# ---- ASGI app / auth wiring --------------------------------------------


def test_build_mcp_app_returns_asgi_app(store, settings):
    app = mcp_server.build_mcp_app(store, settings)
    assert callable(app)


def test_build_mcp_app_401_without_token_when_auth_enabled(store, auth_settings):
    app = mcp_server.build_mcp_app(store, auth_settings)
    client = TestClient(app)
    resp = client.post(
        auth_settings.mcp_path,
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert resp.status_code == 401


def test_build_mcp_app_passes_through_without_auth(store, settings):
    app = mcp_server.build_mcp_app(store, settings)
    with TestClient(app) as client:  # enters the ASGI lifespan the session manager needs
        resp = client.post(
            settings.mcp_path,
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert resp.status_code != 401


async def test_status_unpublished_name_reports_panel_requests(mcp, store):
    store.note_fetch("ghost", 503, "172.17.0.5")
    async with Client(mcp) as c:
        result = await c.call_tool("status", {"name": "ghost"})
    assert result.is_error is not True
    data = result.structured_content
    assert data["published"] is False
    assert data["recent_fetch_status"] == 503
    assert data["recent_fetch_ip"] == "172.17.0.5"
    assert data["recent_fetch_ago"] is not None
