"""Panel listener: the LAN-facing, read-only, unauthenticated Starlette app.

Routes:
    GET|HEAD /display.json       alias for /d/default.json
    GET|HEAD /d/{name}.json      ETag = "<meta.hash>"; If-None-Match -> 304
    GET      /healthz

Implemented by the core package.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from . import render
from .config import Settings
from .store import DEFAULT_NAME, DisplayError, PanelReport, Store, UnknownDisplay, validate_name

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str | None:
    # Nothing proxies this listener, so X-Forwarded-For is deliberately ignored.
    return request.client.host if request.client else None


# 2020-01-01 .. 2100-01-01. See the bound check in `_panel_report`.
PLAUSIBLE_DRAW_AT = (1577836800.0, 4102444800.0)


def _int_header(request: Request, name: str, lo: int, hi: int) -> int | None:
    try:
        value = int((request.headers.get(name) or "").strip())
    except ValueError:
        return None
    return value if lo <= value <= hi else None


def _panel_report(request: Request) -> PanelReport:
    """Parse the panel's `X-Panel-*` self-report off a fetch.

    Anything missing, empty or malformed becomes `None`. This listener is
    unauthenticated, so these values are hearsay from whoever made the
    request -- worth recording, never worth trusting enough to raise over.
    Ranges are sanity bounds, not validation: they keep a garbled header out
    of `status` rather than rejecting the fetch, which must still be served.
    """
    volts: float | None = None
    try:
        volts = float((request.headers.get("x-panel-volts") or "").strip())
    except ValueError:
        volts = None
    else:
        if not 0.0 <= volts <= 10.0:
            volts = None

    draw_at: float | None = None
    raw_draw = (request.headers.get("x-panel-last-draw") or "").strip()
    if raw_draw:
        try:
            # The firmware sends "2026-09-19T14:03:11Z"; fromisoformat only
            # learned "Z" in 3.11, which is the floor this package targets.
            parsed = datetime.fromisoformat(raw_draw)
        except ValueError:
            draw_at = None
        else:
            # A stamp with no zone would otherwise be read as the *server's*
            # local time, quietly off by the offset. Treat it as UTC, which
            # is what the firmware sends.
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            draw_at = parsed.timestamp()
            # The one field whose range is not obviously bounded by its type,
            # and the one that reaches `status` through a formatter that
            # raises. `0001-01-01` parses fine and lands at -6.2e10, which
            # `datetime.fromtimestamp` cannot represent -- one unauthenticated
            # GET would then have broken `status` for every display, for good,
            # since the value is persisted to the meta file. The panel only
            # stamps this after an SNTP sync, so anything outside a plausible
            # decade is a bad clock or a forgery either way.
            if not PLAUSIBLE_DRAW_AT[0] <= draw_at <= PLAUSIBLE_DRAW_AT[1]:
                draw_at = None

    return PanelReport(
        battery=_int_header(request, "x-panel-battery", 0, 100),
        volts=volts,
        draw_at=draw_at,
        # An upper bound only so a garbled value cannot look like a real count.
        wakes=_int_header(request, "x-panel-wakes", 0, 2**32 - 1),
    )


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    """Accept an exact quoted match, an unquoted value, or a weak (W/) prefix."""
    if not if_none_match:
        return False
    target = etag.strip('"')
    for candidate in if_none_match.split(","):
        value = candidate.strip()
        if value == "*":
            return True
        if value[:2] in ("W/", "w/"):
            value = value[2:].strip()
        if value.strip('"') == target:
            return True
    return False


def _state_dir_writable(state_dir: Path) -> bool:
    try:
        fd, tmp = tempfile.mkstemp(dir=state_dir, prefix=".healthz-", suffix=".tmp")
        os.close(fd)
        os.unlink(tmp)
        return True
    except OSError:
        return False


class _AccessLogMiddleware(BaseHTTPMiddleware):
    """One INFO line per request: method, path, status, client ip."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        ip = _client_ip(request) or "-"
        logger.info("%s %s -> %s %s", request.method, request.url.path, response.status_code, ip)
        return response


def build_panel_app(store: Store, settings: Settings) -> Starlette:
    async def _serve_display(request: Request, name: str) -> Response:
        try:
            validate_name(name)
        except DisplayError as exc:
            # Bad names are a client mistake, not a fetch worth recording.
            return JSONResponse({"error": str(exc)}, status_code=404)

        ip = _client_ip(request)
        panel = _panel_report(request)

        try:
            published = store.get(name)
        except UnknownDisplay:
            store.note_fetch(name, 503, ip, panel)
            return PlainTextResponse("no display list yet", status_code=503)

        if _etag_matches(request.headers.get("if-none-match"), published.etag):
            store.note_fetch(name, 304, ip, panel)
            return Response(
                content=b"",
                status_code=304,
                headers={"ETag": published.etag, "Content-Length": "0"},
            )

        if request.method == "GET":
            # HEAD is how a human looks at the ETag; only a GET is the panel
            # collecting the document, so only a GET counts as a fetch.
            store.note_fetch(name, 200, ip, panel)
        headers = {
            "Content-Type": "application/json",
            "ETag": published.etag,
            "Cache-Control": "no-cache",
            "Content-Length": str(len(published.body)),
        }
        body = b"" if request.method == "HEAD" else published.body
        return Response(content=body, status_code=200, headers=headers)

    async def display_default(request: Request) -> Response:
        return await _serve_display(request, DEFAULT_NAME)

    async def display_named(request: Request) -> Response:
        return await _serve_display(request, request.path_params["name"])

    async def healthz(request: Request) -> Response:
        try:
            fonts_loaded = bool(render.fonts_available(settings.font_dir))
        except Exception:  # noqa: BLE001 - health check must never 500
            fonts_loaded = False

        displays = []
        for name in store.names():
            try:
                published = store.get(name)
            except UnknownDisplay:
                continue
            displays.append(
                {
                    "name": name,
                    "hash": published.hash,
                    "published_at": published.fetch.published_at,
                    "first_fetch_at": published.fetch.first_fetch_at,
                    "recent_fetch_at": published.fetch.recent_fetch_at,
                    "recent_fetch_status": published.fetch.recent_fetch_status,
                    # What the panel said about itself on that fetch. This is
                    # what a Home Assistant REST sensor polls: the panel itself
                    # is unreachable for most of the hour, this endpoint is not.
                    "panel_battery": published.fetch.panel_battery,
                    "panel_volts": published.fetch.panel_volts,
                    "panel_draw_at": published.fetch.panel_draw_at,
                    "panel_wakes": published.fetch.panel_wakes,
                }
            )

        return JSONResponse(
            {
                "ok": True,
                "fonts_loaded": fonts_loaded,
                "state_dir_writable": _state_dir_writable(store.state_dir),
                "displays": displays,
            }
        )

    routes = [
        Route("/display.json", display_default, methods=["GET", "HEAD"]),
        Route("/d/{name}.json", display_named, methods=["GET", "HEAD"]),
        Route("/healthz", healthz, methods=["GET"]),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(_AccessLogMiddleware)
    return app
