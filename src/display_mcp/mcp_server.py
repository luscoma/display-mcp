"""The MCP server: tools, resources and the compose prompt.

Builds an MCPServer (mcp SDK v2) whose tools call the Store directly, and
exposes it as a Starlette app via streamable_http_app(stateless_http=True).

Tools: set_display, preview, validate, get_display, status, clear_display.
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
from mcp.types import ToolAnnotations
from starlette.types import ASGIApp

from . import render
from .auth import wrap_with_access_auth
from .config import Settings
from .store import DisplayError, FetchRecord, Store, UnknownDisplay, validate_name

logger = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).parent
_PROMPTS_DIR = _PACKAGE_DIR / "prompts"
# parents[2]: src/display_mcp/mcp_server.py -> src/display_mcp -> src -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

COMPOSE_PROMPT = (_PROMPTS_DIR / "compose.md").read_text()


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
    def set_display(document: dict[str, Any], name: str = "default") -> dict[str, Any]:
        """Publish a display-list document so the panel serves it on its next fetch.

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
        """
        try:
            validate_name(name)
            result = store.publish(document, name=name)
        except DisplayError as exc:
            raise ToolError(str(exc)) from exc
        return {
            "name": result.name,
            "hash": result.hash,
            "etag": result.etag,
            "ops": result.ops,
            "bytes": result.bytes,
            "warnings": result.warnings,
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Preview display",
            read_only_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    def preview(document: dict[str, Any] | None = None, name: str = "default") -> Image:
        """Render a PNG the way the panel will draw it. Publishes nothing.

        Omit `document` to see what is currently published under `name`; pass
        a draft to check it before spending a `set_display` call on it — a
        wasted publish either changes nothing (same hash) or forces the panel
        into a ~1.5 mAh redraw versus the ~0.15 mAh a 304 would have cost, so
        drafting here first is the cheap step. This is the same renderer that
        backs `validate` and that the panel's own hashing has to agree with,
        so what you see here is what ends up on the wall (ink-approximated,
        not pure RGB) — with one exception: a mix is a 1 px checkerboard of
        two inks, and most image viewers scale this PNG down to fit, which
        aliases each mix to a solid patch of just one of its two inks. Judge
        layout and weight from this image; judge colour from the named
        palette table and from `validate`'s contrast warnings, not from the
        pixels you see here.
        """
        try:
            validate_name(name)
            doc = store.get(name).doc if document is None else document
        except DisplayError as exc:
            raise ToolError(str(exc)) from exc
        image, _problems = render.render(doc, settings.font_dir)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return Image(data=buf.getvalue(), format="png")

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Validate display",
            read_only_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    def validate(document: dict[str, Any]) -> dict[str, Any]:
        """Check a draft document. Nothing is rendered to an image, published, or stored.

        Returns the hash `set_display` would stamp, the op count, the
        minified byte size, and every renderer warning. What is actually
        checked: unknown op/font/icon/colour name; a malformed mix entry
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
        problems = render.check(document, settings.font_dir)
        op_count = len(document.get("ops") or [])
        body = json.dumps(document, separators=(",", ":")).encode("utf-8")
        return {
            "hash": render.render_hash(document),
            "ops": op_count,
            "bytes": len(body),
            "warnings": problems,
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
                "recent_fetch_at": _iso(fetch.recent_fetch_at),
                "recent_fetch_ago": _ago(fetch.recent_fetch_at),
                "recent_fetch_status": fetch.recent_fetch_status,
                "recent_fetch_ip": fetch.recent_fetch_ip,
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
            "recent_fetch_at": _iso(fetch.recent_fetch_at),
            "recent_fetch_ago": _ago(fetch.recent_fetch_at),
            "recent_fetch_status": fetch.recent_fetch_status,
            "recent_fetch_ip": fetch.recent_fetch_ip,
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

        With `name`, one display's status. Without it, every known display
        plus how the MCP endpoint is authenticated. `recent_fetch_status:
        304` is the healthy answer: the panel already had this exact
        document and skipped the ~1.5 mAh redraw. `first_fetch_at` is when
        the panel first served the *current* hash (reset on every publish),
        so a stale `first_fetch_at` next to a recent `published_at` usually
        just means the panel hasn't woken up since — it wakes about hourly.
        """
        if name is not None:
            try:
                validate_name(name)
            except DisplayError as exc:
                raise ToolError(str(exc)) from exc
            return _display_status(name)
        return {
            "displays": {n: _display_status(n) for n in store.names()},
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

        `cleared` is false when nothing was published under `name` to begin
        with — calling this twice in a row is safe.
        """
        try:
            validate_name(name)
            cleared = store.clear(name)
        except DisplayError as exc:
            raise ToolError(str(exc)) from exc
        return {"name": name, "cleared": cleared}

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
