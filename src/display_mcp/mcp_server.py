"""The MCP server: tools, resources and the compose prompt.

Builds an MCPServer (mcp SDK v2) whose tools call the Store directly, and
exposes it as a Starlette app via streamable_http_app(stateless_http=True).

Tools: set_display, copy_display, preview, validate, get_display, status,
clear_display, describe, guide, swatches.
Resources: display://spec, display://sample, display://current/{name}.
Prompt: compose_display (text in prompts/compose.md).
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError
from mcp.server.mcpserver.utilities.types import Image
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ContentBlock, TextContent, ToolAnnotations
from starlette.types import ASGIApp

from . import render
from .auth import wrap_with_access_auth
from .config import Settings
from .store import (
    GENERATED_FMT,
    MAX_DOC_BYTES,
    DisplayError,
    FetchRecord,
    Store,
    UnknownDisplay,
    stamped_body,
    validate_name,
)

logger = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).parent
_PROMPTS_DIR = _PACKAGE_DIR / "prompts"
# parents[2]: src/display_mcp/mcp_server.py -> src/display_mcp -> src -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# What `preview` says about the image it just produced. The old caveat lived in
# the tool docstring, which is read once at tool-discovery time and a long way
# from the picture; a reader looking at an aliased swatch believed the pixels
# instead. These ride in the response, next to the image, and each says only
# what is true of the image actually returned.
_FLAT_NOTE = (
    "Colours are ink-approximated, and each mix is drawn as the single colour it "
    "averages to. The panel instead dithers a 1 px checkerboard of two inks, so "
    "small text in a mix reads lighter than it looks here, and a 25%/75% mix on a "
    "feature under 2 px cannot hold its density. Any warnings below are measured "
    "against that real dithered output, not against this image."
)
_DITHERED_NOTE = (
    "Colours are ink-approximated and mixes are drawn as the real 1 px checkerboard "
    "of two inks the panel lays down. Do not judge colour from this image: scaling "
    "it down aliases each mix to a solid patch of just one of its inks, which makes "
    "order-swapped mixes look like different colours and unrelated mixes look "
    "identical. Re-run without `dithered_colors` to see what these mixes average to."
)
_GRID_NOTE = (
    "Grid lines and labels are an overlay for placing things; they are not in the "
    "document and the panel never draws them."
)

COMPOSE_PROMPT = (_PROMPTS_DIR / "compose.md").read_text()

# `validate` has no `generated` timestamp yet -- nothing is being published
# -- but needs `stamped_body()`'s byte count to match `publish()`'s exactly,
# so it stands in a placeholder of the length the real stamp has (measured
# from the format itself, so the two cannot drift). Its content never
# reaches a caller: the stamped copy is used for its size and hash only.
_GENERATED_PLACEHOLDER = "0" * len(time.strftime(GENERATED_FMT))


def _merge_color_problems(problems: list[str], color_problems: list[str]) -> list[str]:
    """`problems` (`check()`'s, in order) plus whichever of `color_problems`
    (`document_colors()`'s) `check()` didn't already report for the same
    name.

    The two resolve colours through different `where`s — `check()` as
    `"ops[i] kind"`, `document_colors()` as `"palette '<name>'"` — so a mix
    malformed in the palette *and* used by an op would otherwise warn twice
    for the one mistake. Dedup compares each message's text after its own
    `"where: "` prefix, which is where the actual complaint (and the
    name it's about) lives; the prefix itself is expected to differ.
    """
    seen = {p.split(": ", 1)[-1] for p in problems}
    merged = list(problems)
    for p in color_problems:
        rest = p.split(": ", 1)[-1]
        if rest not in seen:
            merged.append(p)
            seen.add(rest)
    return merged


def _describe() -> dict[str, Any]:
    """Build `describe()`'s return from the renderer's own tables, at call
    time, so it can never say something `render()` doesn't do.

    Every hex comes from `INK` or `Ink.avg`, the same values `preview`
    paints and `docs/SPEC.md`'s named-palette table publishes — never typed
    twice. `OP_FIELDS`' `required` tuples become lists so the whole object
    round-trips through plain JSON.
    """
    mixes = {
        name: {
            "c": c,
            "c2": c2,
            "mix": mix,
            "hex": render.hex_of(render.Ink(render.INK[c], render.INK[c2], mix).avg),
            "tier": render.TIERS[name],
        }
        for name, (c, c2, mix) in render.BUILTIN_MIXES.items()
    }
    fonts = {
        name: {"px": px, "bold": bold, "line_height": round(px * 1.24)}
        for name, (px, bold) in render.FONTS.items()
    }
    ops = {
        op: {"required": list(spec["required"]), "optional": dict(spec["optional"])}
        for op, spec in render.OP_FIELDS.items()
    }
    # Only the size classes some compiled icon actually has — `md: 56` is
    # in ICON_SIZES for arithmetic elsewhere but has no icon behind it, and
    # advertising it here would invite `{"n": "check", "z": "md"}`, which
    # `check()` then has to reject as "not compiled in".
    used_sizes = {z for sizes in render.ICONS.values() for z in sizes}
    icon_sizes = {z: px for z, px in render.ICON_SIZES.items() if z in used_sizes}
    return {
        "canvas": {
            "w": render.WIDTH,
            "h": render.HEIGHT,
            "bezel_margin": render.BEZEL_MARGIN,
        },
        "inks": {name: render.hex_of(rgb) for name, rgb in render.INK.items()},
        "mixes": mixes,
        "densities": list(render.DENSITIES),
        "fonts": fonts,
        "anchors": list(render.ANCHOR),
        "icons": {name: sorted(sizes) for name, sizes in render.ICONS.items()},
        "icon_sizes": icon_sizes,
        "ops": ops,
        "fmt_fields": list(render.system_fields({}).keys()),
        "limits": {"max_bytes": MAX_DOC_BYTES},
    }


def _read_repo_or_bundled(repo_path: Path, bundled_path: Path) -> str:
    """Prefer the repo copy (the one docs/deploy actually edit); fall back to
    the copy bundled under prompts/ when the package is installed somewhere
    (e.g. /opt/display-mcp) that doesn't carry docs/ or samples/ alongside
    it. That is the normal case in production, not a corner case.

    The bundled copies are not checked in: pyproject's force-include copies
    docs/SPEC.md and samples/display.json into prompts/ at build time, so
    they cannot drift from the originals. In a source checkout they are
    absent and repo_path always wins.
    """
    if repo_path.exists():
        return repo_path.read_text()
    return bundled_path.read_text()


def _spec_text() -> str:
    return _read_repo_or_bundled(_REPO_ROOT / "docs" / "SPEC.md", _PROMPTS_DIR / "SPEC.md")


def _sample_text() -> str:
    repo_sample = _REPO_ROOT / "samples" / "display.json"
    return _read_repo_or_bundled(repo_sample, _PROMPTS_DIR / "sample.json")


def _coerce_document(document: dict[str, Any] | str) -> dict[str, Any]:
    """Accept a document as a plain object or as a JSON string.

    Some MCP clients serialize an object-typed tool argument to a string
    before sending it rather than nesting it as JSON (the dragon session's
    report, "5a"); the SDK's own reaction to that is a schema-validation
    error that reads as a bug in the tool rather than a hint about what to
    fix. A dict passes through untouched. A string is parsed with
    `json.loads`; a parse failure names where parsing stopped, and a value
    that parses but isn't a JSON object is named as what it actually is.
    """
    if isinstance(document, dict):
        return document
    try:
        parsed = json.loads(document)
    except json.JSONDecodeError as exc:
        raise ToolError(
            f"document arrived as a string and failed to parse as JSON at "
            f"line {exc.lineno} column {exc.colno} (char {exc.pos}): {exc.msg}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ToolError(
            "document arrived as a string and parsed to "
            f"{type(parsed).__name__}, not a JSON object"
        )
    return parsed


def _ago(ts: float | None) -> str | None:
    """Port of epaper_server.py's `ago()`: "3m ago" / "2h ago" / None."""
    if not ts:
        return None
    delta = int(time.time() - ts)
    if delta < 0:
        delta = 0
    if delta < 90:
        return f"{delta}s ago"
    if delta < 5400:
        return f"{delta // 60}m ago"
    return f"{delta // 3600}h ago"


def _iso(ts: float | None) -> str | None:
    """Unix float -> ISO 8601 with the local UTC offset, or None."""
    if not ts:
        return None
    return datetime.fromtimestamp(ts).astimezone().isoformat()


def build_mcp(store: Store, settings: Settings) -> MCPServer:
    mcp: MCPServer = MCPServer(
        "display",
        instructions=(
            "Publish display-list JSON documents for an e-paper panel that wakes about "
            "once an hour; an unchanged fetch (304) costs it roughly 0.15 mAh versus "
            "roughly 1.5 mAh for a full redraw, so draft with validate/preview before "
            "set_display and confirm the pickup with status."
        ),
    )

    # ---- tools ---------------------------------------------------------

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Set display",
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    def set_display(document: dict[str, Any] | str, name: str = "default") -> dict[str, Any]:
        """Publish a display-list document so the panel serves it on its next fetch.

        `document` is the document object, or a JSON string that parses to
        one — some clients send object arguments that way.

        `name` must match `^[a-z0-9-]{1,32}$` — lowercase letters, digits
        and hyphens, 1 to 32 characters. The panel wakes roughly once an
        hour; a fetch that gets a 304 (unchanged) costs it about 0.15 mAh,
        a full refresh about 1.5 mAh — ten times as much. Use `validate`
        and `preview` to check a draft first rather than publishing
        repeatedly to see what changed.
        `meta.hash` is stamped here from `bg` + `palette` + `ops`; do not set
        it yourself, it is overwritten (`meta.generated` is stamped too;
        anything else under `meta` is yours and is ignored). Renderer
        warnings (unknown op/font/icon/colour, off-canvas placement, low
        contrast, ...) never block the publish, but seeing one back is
        almost always a mistake worth fixing rather than shipping — see
        `validate` for the full list of what is and isn't checked.
        `recent_fetch_at` is when a panel last asked for this name, `null`
        if none has since the name was last created fresh (`clear_display`
        drops a name's fetch history along with its document); `status()`
        lists the names that have been requested.
        """
        try:
            validate_name(name)
            result = store.publish(_coerce_document(document), name=name)
        except DisplayError as exc:
            raise ToolError(str(exc)) from exc
        return {
            "name": result.name,
            "hash": result.hash,
            "etag": result.etag,
            "ops": result.ops,
            "bytes": result.bytes,
            "warnings": result.warnings,
            "recent_fetch_at": _iso(result.recent_fetch_at),
            "recent_fetch_ago": _ago(result.recent_fetch_at),
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Copy display",
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    def copy_display(source: str, name: str) -> dict[str, Any]:
        """Republish `source`'s currently published document under `name`, unchanged.

        For promoting a scratch name (draft a display under some other name,
        judge it with `preview`/`status`, then move it to `default`) without
        resending the body over the wire. `meta.hash` is unchanged — it
        covers `bg` + `palette` + `ops`, none of which this touches — and
        `meta.generated` is stamped fresh, exactly as for any publish;
        `first_fetch_at` on `name` resets the same way too, since as far as
        the panel is concerned this is an ordinary publish. `source == name`
        is allowed and is just a republish: same hash, fresh `generated`.
        If `name` already held this exact document the panel keeps getting
        304s and `first_fetch_at` stays `null`; `recent_fetch_status: 304`
        is then the signal that the wall is current, not that it never
        collected the copy. `recent_fetch_at` in the reply is the target
        name's, as for `set_display`.

        Raises if nothing is published under `source`.
        """
        try:
            validate_name(source)
            validate_name(name)
            doc = store.get(source).doc
            result = store.publish(doc, name=name)
        except DisplayError as exc:
            raise ToolError(str(exc)) from exc
        return {
            "name": result.name,
            "hash": result.hash,
            "etag": result.etag,
            "ops": result.ops,
            "bytes": result.bytes,
            "warnings": result.warnings,
            "recent_fetch_at": _iso(result.recent_fetch_at),
            "recent_fetch_ago": _ago(result.recent_fetch_at),
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Preview display",
            read_only_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    def preview(
        document: dict[str, Any] | str | None = None,
        name: str = "default",
        dithered_colors: bool = False,
        grid: bool = False,
    ) -> list[ContentBlock]:
        """Render a PNG of how the panel will draw this, plus its warnings.
        Publishes nothing.

        Omit `document` to see what is currently published under `name`; pass
        a draft (an object, or a JSON string that parses to one) to check it
        before spending a `set_display` call on it — a wasted publish either
        changes nothing (same hash) or forces the panel into a ~1.5 mAh
        redraw versus the ~0.15 mAh a 304 would have cost, so drafting here
        first is the cheap step. Colours are ink-approximated: this is
        roughly what the Spectra 6 glass shows, not the pure RGB the driver
        writes.

        Each mix is drawn as the single colour it averages to — the hex in
        the named-palette table — rather than as the 1 px checkerboard of two
        inks the panel lays down, so the colours in the image are the colours
        you asked for. Set `dithered_colors` only if you have been asked for
        a preview closer to what the panel really draws. The text block
        returned with the image explains the trade-off for whichever mode ran
        and carries the warnings `validate` would give you.

        `grid` overlays a labelled 100 px coordinate grid on the image, so an
        op's `x`/`y` can be placed by coordinate in one pass instead of a
        guess-preview-adjust round each time; it changes nothing about the
        document or the panel's output.
        """
        try:
            validate_name(name)
            doc = store.get(name).doc if document is None else _coerce_document(document)
        except DisplayError as exc:
            raise ToolError(str(exc)) from exc
        image, _problems = render.render(doc, settings.font_dir, dithered_colors=dithered_colors)
        if grid:
            # A real face at a size actually chosen to survive a client
            # downscaling the 1200x1600 PNG; PIL's bitmap default is a
            # handful of pixels tall and unreadable once scaled. Falls back
            # to that default (grid_overlay's own behaviour) if the face
            # isn't installed, so a missing font directory never fails a
            # grid preview -- it just looks the way it always did.
            try:
                grid_font = render.load_font(settings.font_dir, 22, False)
            except Exception:  # noqa: BLE001 - the grid must never break a preview
                grid_font = None
            image = render.grid_overlay(image, font=grid_font)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        # Warnings come from check() rather than from the render above. On a
        # flat canvas they cannot be computed at all — render() rejects
        # warn_ink there, because the checks that read pixels back would be
        # measuring an image the panel never draws — and check() adds the
        # bezel and stale-hash checks that no render() produces. Sourcing
        # them here is also what makes preview and validate agree word for
        # word.
        problems = render.check(doc, settings.font_dir)
        note = _DITHERED_NOTE if dithered_colors else _FLAT_NOTE
        if grid:
            note = "\n".join([note, _GRID_NOTE])
        if problems:
            note = "\n".join([note, "", *(f"- {p}" for p in problems)])
        return [
            Image(data=buf.getvalue(), format="png").to_image_content(),
            TextContent(type="text", text=note),
        ]

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Validate display",
            read_only_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    def validate(document: dict[str, Any] | str) -> dict[str, Any]:
        """Check a draft document. Nothing is rendered to an image, published, or stored.

        `document` is the document object, or a JSON string that parses to
        one — some clients send object arguments that way.

        Returns the hash `set_display` would stamp, the op count, the
        minified byte size *of the stamped document* — `bytes` is measured
        the same way `set_display` measures it (`v` defaulted, `meta.hash`
        and `meta.generated` added), not of the draft as given, so a
        document this reports as within `max_bytes` also publishes — and
        every renderer warning, plus two more: `colors` is the effective
        `{recipe, hex}` of every colour name the document references (`bg`,
        each op's `c`/`bgc`, every `palette` key) — a name that doesn't
        resolve is absent here and shows up in `warnings` instead.
        `max_bytes` is the ceiling `set_display` enforces (`bytes` above it
        is a `ToolError`, not a warning).

        What is actually checked: unknown op/font/icon/colour name; a field an op does not
        have (e.g. `c2`/`mix` written directly on an op — those are fields
        of a *palette* entry, not an op: write `palette: {name: {c, c2,
        mix}}` and `c: name` on the op instead); a malformed palette entry
        (missing `c`/`c2`, `c2` equal to `c`, a `mix` outside 25/50/75);
        an op placed off-canvas (`x`/`y`, and `x+w`/`y+h` for a rect,
        `x2`/`y2` for a line); a `text`, `fmt` or `icon` op anchored inside
        the 24 px band the printed bezel covers; `text`/`fmt`/`icon`
        contrast below 3:1 against what is actually behind it; a chromatic
        (non-black/white) mix used as text, which shifts toward its
        lighter ink; a 25%/75% mix on a feature thinner than 2 px, which
        can't carry the density; an unknown `{field}` in a `fmt` template;
        an op that changed not one pixel of its own box; a `meta.hash`
        present but stale.

        What it does **not** check: it does not warn when text is
        ellipsised or word-wrap runs past the canvas edge — set `w` on
        anything of unknown length, and look at `preview` to see the
        actual line breaks.

        Warnings never block a publish, but they are almost always worth
        fixing — run this (or `preview`) before every `set_display` rather
        than finding out from the panel a fetch later.
        """
        doc = _coerce_document(document)
        problems = render.check(doc, settings.font_dir)
        op_count = len(doc.get("ops") or [])
        stamped, body = stamped_body(doc, _GENERATED_PLACEHOLDER)
        colors, color_problems = render.document_colors(doc)
        warnings = _merge_color_problems(problems, color_problems)
        if len(body) > MAX_DOC_BYTES:
            # The hard ceiling, not a soft budget (D4 declined one): the
            # same refusal set_display would give, said here first.
            warnings.append(
                f"document too large: {len(body)} bytes > {MAX_DOC_BYTES} max "
                "— set_display will refuse it"
            )
        return {
            "hash": stamped["meta"]["hash"],
            "ops": op_count,
            "bytes": len(body),
            "warnings": warnings,
            "colors": colors,
            "max_bytes": MAX_DOC_BYTES,
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get published display",
            read_only_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    def get_display(name: str = "default") -> dict[str, Any]:
        """Return the document currently published under `name`.

        Raises if nothing has been published under that name — publish one
        with `set_display` first. `status(name)` reports `published: false`
        for the same case instead of erroring, since the panel may already
        be asking for a name nothing has been published under yet.
        """
        try:
            validate_name(name)
            return store.get(name).doc
        except DisplayError as exc:
            raise ToolError(str(exc)) from exc

    def _recent_fetch_fields(fetch: FetchRecord) -> dict[str, Any]:
        return {
            "recent_fetch_at": _iso(fetch.recent_fetch_at),
            "recent_fetch_ago": _ago(fetch.recent_fetch_at),
            "recent_fetch_status": fetch.recent_fetch_status,
            "recent_fetch_ip": fetch.recent_fetch_ip,
        }

    def _display_status(name: str) -> dict[str, Any]:
        try:
            published = store.get(name)
        except UnknownDisplay:
            # Not an error: the panel may be asking for a name nothing has
            # been published under yet, and the store records those requests.
            fetch = store.fetch_record(name) or FetchRecord()
            return {
                "published": False,
                "name": name,
                "hash": None,
                "ops": None,
                "bytes": None,
                "published_at": None,
                "published_ago": None,
                "first_fetch_at": None,
                "first_fetch_ago": None,
                **_recent_fetch_fields(fetch),
            }
        fetch = published.fetch
        return {
            "published": True,
            "name": published.name,
            "hash": published.hash,
            "ops": len(published.doc.get("ops") or []),
            "bytes": len(published.body),
            "published_at": _iso(fetch.published_at),
            "published_ago": _ago(fetch.published_at),
            "first_fetch_at": _iso(fetch.first_fetch_at),
            "first_fetch_ago": _ago(fetch.first_fetch_at),
            **_recent_fetch_fields(fetch),
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Display status",
            read_only_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    def status(name: str | None = None) -> dict[str, Any]:
        """Report whether the panel has actually picked up what was published.

        With `name`, one display's status. Without it, every known display,
        every name that has been requested, plus how the MCP endpoint is
        authenticated. `recent_fetch_status: 304` is the healthy answer: the
        panel already had this exact document and skipped the ~1.5 mAh
        redraw. `first_fetch_at` is when the panel first served the
        *current* hash (reset on every publish), so a stale `first_fetch_at`
        next to a recent `published_at` usually just means the panel hasn't
        woken up since — it wakes about hourly. `requested` covers every
        name `fetched_names()` knows, published or not — it is the answer
        to "which name is the panel actually configured to request", since
        the server cannot read the firmware's own `dl_url`, only what has
        actually shown up asking.
        """
        if name is not None:
            try:
                validate_name(name)
            except DisplayError as exc:
                raise ToolError(str(exc)) from exc
            return _display_status(name)
        return {
            "displays": {n: _display_status(n) for n in store.names()},
            "requested": {
                n: _recent_fetch_fields(store.fetch_record(n) or FetchRecord())
                for n in store.fetched_names()
            },
            "auth": "cloudflare-access" if settings.auth_enabled else "none",
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Clear display",
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    def clear_display(name: str = "default") -> dict[str, Any]:
        """Unpublish a display; the panel gets 503 on its next fetch until something new is set.

        The name's fetch history goes with it: after a clear, `status()`
        no longer lists it under `requested` and the next publish under
        it reports `recent_fetch_at: null` until the panel asks again.

        `cleared` is false when nothing was published under `name` to begin
        with — calling this twice in a row is safe.
        """
        try:
            validate_name(name)
            cleared = store.clear(name)
        except DisplayError as exc:
            raise ToolError(str(exc)) from exc
        return {"name": name, "cleared": cleared}

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Describe vocabulary",
            read_only_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    def describe() -> dict[str, Any]:
        """The renderer's whole vocabulary as one JSON object: canvas size,
        the inks and built-in mixes with their hexes and tiers, the fonts,
        the anchor values `text.a`/`fmt.a` accept, the icons and their size
        classes, the per-op field table, the `fmt` template fields, and the
        document byte ceiling.

        Built from the same tables `render()` draws with, so it cannot say
        something `render()` doesn't accept. A session calls this once
        before composing rather than guessing field names by trial and
        error; `guide()` is its prose companion.

        In `ops`, an optional field whose default is `null` has no fixed
        default and may simply be omitted — `lh` is computed from the font
        size, `w` means no width limit, `n` has no default, and `sprite`'s
        `mirror` means no mirroring (its only other legal value is `"x"`).
        """
        return _describe()

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Composing guide",
            read_only_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    def guide() -> str:
        """The prose guide to composing a display: canvas and bezel margin,
        the op vocabulary, the type scale, colour and contrast rules, and
        the validate -> preview -> set_display -> status workflow.

        This is the same text the `compose_display` prompt carries, as a
        plain tool call — for a client that surfaces tools but not prompts
        or resources. `describe()` is its machine-readable companion: call
        that for the exact names and fields, this for the why.
        """
        return COMPOSE_PROMPT

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Colour swatches",
            read_only_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    def swatches(
        document: dict[str, Any] | str | None = None,
        include_document: bool = False,
    ) -> list[ContentBlock]:
        """A PNG chip of every ink and every built-in mix, named and hexed.
        Publishes nothing.

        `document` is optional (an object, or a JSON string that parses to
        one); when given, its own `palette` field is appended as a final
        "document palette" group, so a draft's custom colours sit on the
        same sheet as the built-ins they were mixed from. Nothing else
        about `document` is read or changed.

        The image is flat, the trade-off `preview`'s default uses: each mix
        is drawn as the single colour it averages to, not the panel's 1 px
        checkerboard — this sheet is for judging colour, not layout. The
        sheet itself is an ordinary display-list document, but the PNG
        alone isn't it — pass `include_document=true` to receive the
        document JSON as a third block, then `set_display` it, and every
        named colour here sits on the wall with its name under it
        (docs/plans/ink-mixing.md, "Still open"'s closing-coupon bullet).
        """
        palette = None
        if document is not None:
            candidate = _coerce_document(document).get("palette")
            if isinstance(candidate, dict):
                palette = candidate
        sheet = render.swatch_document(palette=palette)
        image, _problems = render.render(sheet, settings.font_dir, dithered_colors=False)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        lines = [
            "Flat: each mix is drawn as the single colour it averages to, not the "
            "panel's 1 px checkerboard. This sheet is itself a valid document — pass "
            "`include_document=true` to receive it as a third block, then `set_display` "
            "it, and every named colour below sits on the wall with its name under it.",
            "",
        ]
        for title, entries in render.swatch_groups(palette):
            lines.append(f"{title}:")
            for label, _c_field, recipe, hexs in entries:
                lines.append(f"  {label} — {recipe} — {hexs}")
        # A document's own appended palette can still warn (a name that
        # doesn't resolve, say) even though the four built-in groups never
        # do; surfaced the same way `preview` appends check()'s problems
        # to its note, so a sheet that somehow warns says so.
        problems = render.check(sheet, settings.font_dir)
        if problems:
            lines = lines + ["", *(f"- {p}" for p in problems)]
        blocks: list[ContentBlock] = [
            Image(data=buf.getvalue(), format="png").to_image_content(),
            TextContent(type="text", text="\n".join(lines)),
        ]
        if include_document:
            blocks.append(TextContent(type="text", text=json.dumps(sheet, separators=(",", ":"))))
        return blocks

    # ---- resources -------------------------------------------------------

    @mcp.resource(
        "display://spec",
        name="spec",
        title="Display list spec",
        description=(
            "The document language: canvas, ops, fonts, icons, the six inks and "
            "the named two-ink mixes, change detection."
        ),
        mime_type="text/markdown",
    )
    def spec_resource() -> str:
        return _spec_text()

    @mcp.resource(
        "display://sample",
        name="sample",
        title="Sample display document",
        description="A known-good display-list document (hash 3cd62aa76e731d2d) to start from.",
        mime_type="application/json",
    )
    def sample_resource() -> str:
        return _sample_text()

    @mcp.resource(
        "display://current/{name}",
        name="current",
        title="Currently published display",
        description="The document currently published under a display name, as JSON.",
        mime_type="application/json",
    )
    def current_resource(name: str) -> str:
        try:
            validate_name(name)
            doc = store.get(name).doc
        except DisplayError as exc:
            raise ResourceNotFoundError(str(exc)) from exc
        return json.dumps(doc)

    # ---- prompt ------------------------------------------------------

    @mcp.prompt(
        name="compose_display",
        title="Compose a display",
        description=(
            "Guidance for building a display-list document: canvas, ops, type scale, "
            "icons, the six-ink rules, and the validate -> preview -> set_display -> "
            "status workflow."
        ),
    )
    def compose_display(name: str = "default", context: str = "") -> str:
        header = f"Target display name: {name!r}."
        if context:
            header += f"\n\nWhat to show:\n{context}"
        return f"{header}\n\n{COMPOSE_PROMPT}"

    return mcp


def _transport_security(settings: Settings) -> TransportSecuritySettings | None:
    """Host/Origin allowlist for the streamable-http endpoint (its DNS-rebinding guard).

    The SDK auto-enables this check whenever `host` is loopback/localhost
    (`streamable_http_app`'s default, and `settings.mcp_host`'s default too),
    allowing only `Host: 127.0.0.1:*` / `localhost:*` / `[::1]:*`. In
    production the tunnel carries requests straight through to that loopback
    listener with the public hostname still in `Host` and no header rewriting
    (docs/PLAN.md), which that default rejects outright with `421 Invalid
    Host header` — before Cloudflare Access (auth.py) ever sees the request.

    `config.py` (the core package's contract) doesn't carry a setting for
    this, so `DISPLAY_MCP_ALLOWED_HOSTS` — a comma-separated list of Host
    header values this deployment should accept, e.g. "mcp.example.com"
    — is read directly here as a one-off, mcp-only environment variable
    rather than expanding that contract for a single knob.

    When it's unset but Cloudflare Access is configured, the DNS-rebinding
    check is disabled outright instead of guessing the public hostname: the
    Access JWT check is the real security boundary for this endpoint (a
    request with no valid token is rejected regardless of its Host header),
    and the DNS-rebinding guard exists to stop a browser tricked into
    talking to a *local* server — a scenario Access's bearer-token
    requirement already defeats. Local dev (auth disabled, no override)
    keeps the SDK's secure localhost-only default by returning None.
    """
    allowed = os.environ.get("DISPLAY_MCP_ALLOWED_HOSTS", "").strip()
    if allowed:
        hosts = [h.strip() for h in allowed.split(",") if h.strip()]
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=[],
        )
    if settings.auth_enabled:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return None


def build_mcp_app(store: Store, settings: Settings) -> ASGIApp:
    """streamable_http_app() wrapped in the Access auth middleware."""
    mcp = build_mcp(store, settings)
    app = mcp.streamable_http_app(
        streamable_http_path=settings.mcp_path,
        json_response=True,
        stateless_http=True,
        transport_security=_transport_security(settings),
        host=settings.mcp_host,
    )
    return wrap_with_access_auth(app, settings)
