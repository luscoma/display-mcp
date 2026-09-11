"""Test doubles for the mcp package: a Store implemented in memory, and a
fake renderer, so tests here don't depend on the (stubbed, NotImplementedError)
`store.py` / `render` implementations the core and renderer packages own.
"""

from __future__ import annotations

import copy
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from PIL import Image as PILImage

from display_mcp.render import HEIGHT, WIDTH, render_hash
from display_mcp.store import (
    DEFAULT_NAME,
    MAX_DOC_BYTES,
    DisplayError,
    FetchRecord,
    Published,
    PublishResult,
    UnknownDisplay,
    validate_name,
)


class FakeStore:
    """In-memory stand-in for `display_mcp.store.Store`.

    Implements the same public surface (`names`, `get`, `publish`, `clear`,
    `note_fetch`) so `mcp_server.py` can be exercised without the real
    Store, which is a stub (`raise NotImplementedError`) on this branch.
    `publish()` stamps `meta.hash`/`meta.generated` the same way the real
    Store's docstring promises, using the renderer's own (implemented)
    `render_hash` so a test asserting `hash == render_hash(doc)` is
    checking something meaningful.
    """

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}
        self._bodies: dict[str, bytes] = {}
        self._hashes: dict[str, str] = {}
        self._etags: dict[str, str] = {}
        self._fetch: dict[str, FetchRecord] = {}

    def names(self) -> list[str]:
        return sorted(self._docs)

    def get(self, name: str = DEFAULT_NAME) -> Published:
        if name not in self._docs:
            raise UnknownDisplay(f"no display published under {name!r}")
        return Published(
            name=name,
            body=self._bodies[name],
            etag=self._etags[name],
            hash=self._hashes[name],
            doc=copy.deepcopy(self._docs[name]),
            fetch=replace(self._fetch.get(name, FetchRecord())),
        )

    def publish(self, doc: dict[str, Any], name: str = DEFAULT_NAME) -> PublishResult:
        validate_name(name)
        if not isinstance(doc, dict):
            raise DisplayError("document must be a JSON object")
        if not isinstance(doc.get("ops"), list):
            raise DisplayError("document must have an 'ops' list")

        stamped = copy.deepcopy(doc)
        stamped["meta"] = dict(stamped.get("meta") or {})
        h = render_hash(stamped)
        stamped["meta"]["hash"] = h
        stamped["meta"]["generated"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

        body = json.dumps(stamped, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_DOC_BYTES:
            raise DisplayError(f"document body exceeds {MAX_DOC_BYTES} bytes")
        etag = f'"{h}"'

        self._docs[name] = stamped
        self._bodies[name] = body
        self._hashes[name] = h
        self._etags[name] = etag

        fetch = self._fetch.setdefault(name, FetchRecord())
        fetch.published_at = time.time()
        fetch.first_fetch_at = None  # a new publish resets it

        return PublishResult(
            name=name,
            hash=h,
            etag=etag,
            ops=len(stamped["ops"]),
            bytes=len(body),
            warnings=[],
        )

    def clear(self, name: str = DEFAULT_NAME) -> bool:
        existed = name in self._docs
        self._docs.pop(name, None)
        self._bodies.pop(name, None)
        self._hashes.pop(name, None)
        self._etags.pop(name, None)
        self._fetch.pop(name, None)
        return existed

    def fetch_record(self, name: str) -> FetchRecord | None:
        rec = self._fetch.get(name)
        return replace(rec) if rec is not None else None

    def note_fetch(self, name: str, status: int, ip: str | None) -> None:
        """Simulate the panel listener recording a request for `name`."""
        fetch = self._fetch.setdefault(name, FetchRecord())
        now = time.time()
        fetch.recent_fetch_at = now
        fetch.recent_fetch_status = status
        fetch.recent_fetch_ip = ip
        if status == 200 and fetch.first_fetch_at is None:
            fetch.first_fetch_at = now


def fake_render(
    doc: dict[str, Any], font_dir: Path, dithered_colors: bool = True
) -> tuple[PILImage.Image, list[str]]:
    """Stand-in for `display_mcp.render.render`: no fonts, no real drawing."""
    problems: list[str] = []
    if not isinstance(doc, dict):
        problems.append("document is not an object")
    elif not isinstance(doc.get("ops"), list):
        problems.append("document has no 'ops' list")
    image = PILImage.new("RGB", (WIDTH, HEIGHT), "white")
    return image, problems


def fake_check(doc: dict[str, Any], font_dir: Path) -> list[str]:
    """Stand-in for `display_mcp.render.check`: same validation, no image."""
    _, problems = fake_render(doc, font_dir)
    return problems
