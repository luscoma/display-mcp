"""Per-display state: the published document, its identity, and what the panel did.

CONTRACT (stub). The core package implements this; the mcp package codes
against it. Field names are final; see docs/PLAN.md "Store" and "Status".

Files under `state_dir`:
    <name>.json        the published document, written atomically
    <name>.meta.json   FetchRecord fields, so status survives a restart

`publish()` is the ONLY code path that stamps meta.hash and meta.generated.

Loading: at construction every `<name>.json` and `<name>.meta.json` found in
`state_dir` is loaded. A file that fails to parse (bad JSON, wrong type, an
invalid name) is logged and skipped -- never fatal, so one corrupted display
does not take the whole service down.

`names()` only returns names with a *published document*. A name can have a
meta record but no document -- e.g. the panel asked for a display that was
never published, or one that was `clear()`-ed -- and `note_fetch()` still
tracks that so `status`/`/healthz` can say "the panel is asking for a display
that doesn't exist". Such names are deliberately left out of `names()`.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import render

logger = logging.getLogger(__name__)

NAME_RE = re.compile(r"^[a-z0-9-]{1,32}$")
DEFAULT_NAME = "default"
MAX_DOC_BYTES = 256 * 1024


class DisplayError(ValueError):
    """A hard error: bad name, malformed document, nothing published."""


class UnknownDisplay(DisplayError):
    """No document has been published under this name."""


@dataclass
class FetchRecord:
    """What the panel has done with the current document. Times are unix floats."""

    published_at: float | None = None
    first_fetch_at: float | None = None  # first 200 served for the current hash
    recent_fetch_at: float | None = None
    recent_fetch_status: int | None = None
    recent_fetch_ip: str | None = None


@dataclass
class Published:
    """One display's current state, as returned by get()/publish()."""

    name: str
    body: bytes  # minified JSON, exactly what the panel receives
    etag: str  # '"<meta.hash>"', quotes included
    hash: str
    doc: dict[str, Any]
    fetch: FetchRecord = field(default_factory=FetchRecord)


@dataclass
class PublishResult:
    name: str
    hash: str
    etag: str
    ops: int
    bytes: int
    warnings: list[str]


def validate_name(name: str) -> str:
    if not NAME_RE.match(name or ""):
        raise DisplayError(f"bad display name {name!r}: must match {NAME_RE.pattern}")
    return name


_FETCH_RECORD_FIELDS = {f.name for f in dataclasses.fields(FetchRecord)}


@dataclass
class _Entry:
    """Internal per-display state. One `lock` guards everything below it."""

    lock: threading.Lock
    doc: dict[str, Any] | None = None
    body: bytes | None = None
    hash: str | None = None
    fetch: FetchRecord = field(default_factory=FetchRecord)


def _atomic_write(path: Path, data: bytes) -> None:
    """mkstemp in the same dir, write, flush, fsync, replace. Cleans up on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Store:
    """Thread-safe (one lock per display); safe to call from both listeners."""

    def __init__(self, state_dir: Path, font_dir: Path) -> None:
        self.state_dir = Path(state_dir)
        self.font_dir = Path(font_dir)
        self._map_lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._load_all()

    # -- paths ---------------------------------------------------------

    def _doc_path(self, name: str) -> Path:
        return self.state_dir / f"{name}.json"

    def _meta_path(self, name: str) -> Path:
        return self.state_dir / f"{name}.meta.json"

    # -- loading ---------------------------------------------------------

    def _get_or_create_entry(self, name: str) -> _Entry:
        with self._map_lock:
            entry = self._entries.get(name)
            if entry is None:
                entry = _Entry(lock=threading.Lock())
                self._entries[name] = entry
            return entry

    def _load_all(self) -> None:
        try:
            paths = sorted(self.state_dir.iterdir())
        except OSError as exc:
            logger.warning("could not list state dir %s: %s", self.state_dir, exc)
            return

        for p in paths:
            if not p.is_file() or not p.name.endswith(".json"):
                continue
            if p.name.endswith(".meta.json"):
                name = p.name[: -len(".meta.json")]
                kind = "meta"
            else:
                name = p.name[: -len(".json")]
                kind = "doc"

            if not NAME_RE.match(name):
                logger.warning("skipping state file with an invalid display name: %s", p)
                continue

            entry = self._get_or_create_entry(name)

            if kind == "doc":
                try:
                    raw = p.read_bytes()
                    doc = json.loads(raw)
                except (OSError, ValueError) as exc:
                    logger.warning("could not load %s, skipping: %s", p, exc)
                    continue
                if not isinstance(doc, dict):
                    logger.warning("could not load %s, skipping: not a JSON object", p)
                    continue
                entry.doc = doc
                entry.body = raw
                entry.hash = (doc.get("meta") or {}).get("hash", "")
            else:
                try:
                    meta = json.loads(p.read_text())
                except (OSError, ValueError) as exc:
                    logger.warning("could not load %s, skipping: %s", p, exc)
                    continue
                if not isinstance(meta, dict):
                    logger.warning("could not load %s, skipping: not a JSON object", p)
                    continue
                kwargs = {k: v for k, v in meta.items() if k in _FETCH_RECORD_FIELDS}
                try:
                    entry.fetch = FetchRecord(**kwargs)
                except TypeError as exc:
                    logger.warning("could not load %s, skipping: %s", p, exc)

    # -- writing ---------------------------------------------------------

    def _write_doc(self, name: str, body: bytes) -> None:
        _atomic_write(self._doc_path(name), body)

    def _write_meta(self, name: str, fetch: FetchRecord) -> None:
        data = json.dumps(asdict(fetch), separators=(",", ":")).encode()
        _atomic_write(self._meta_path(name), data)

    # -- public API ---------------------------------------------------------

    def names(self) -> list[str]:
        """Display names with a published document, sorted."""
        with self._map_lock:
            return sorted(name for name, entry in self._entries.items() if entry.doc is not None)

    def get(self, name: str = DEFAULT_NAME) -> Published:
        """Raise UnknownDisplay if nothing is published under `name`."""
        validate_name(name)
        with self._map_lock:
            entry = self._entries.get(name)
        if entry is None or entry.doc is None:
            raise UnknownDisplay(f"no display published under {name!r}")
        with entry.lock:
            if entry.doc is None:  # re-check: could have been cleared meanwhile
                raise UnknownDisplay(f"no display published under {name!r}")
            doc_copy = json.loads(entry.body)
            return Published(
                name=name,
                body=entry.body,
                etag=f'"{entry.hash}"',
                hash=entry.hash,
                doc=doc_copy,
                fetch=replace(entry.fetch),
            )

    def publish(self, doc: dict[str, Any], name: str = DEFAULT_NAME) -> PublishResult:
        """Validate (via render), stamp meta.hash/meta.generated, write atomically.

        Warnings from the renderer are returned, never raised. Raises
        DisplayError for hard errors (not an object, no ops list, too big).
        Resets first_fetch_at and sets published_at.
        """
        validate_name(name)

        if not isinstance(doc, dict):
            raise DisplayError("document must be a JSON object")
        ops = doc.get("ops")
        if "ops" not in doc or not isinstance(ops, list):
            raise DisplayError("document must have an 'ops' array")

        try:
            warnings = list(render.check(doc, self.font_dir))
        except Exception as exc:  # noqa: BLE001 - validation must never block a publish
            logger.warning("validation unavailable for display %r: %s", name, exc)
            warnings = [f"validation unavailable: {exc}"]

        new_doc = dict(doc)
        new_doc.setdefault("v", 1)
        meta = dict(new_doc.get("meta") or {})
        meta["hash"] = render.render_hash(new_doc)
        meta["generated"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        new_doc["meta"] = meta

        body = json.dumps(new_doc, separators=(",", ":")).encode()
        if len(body) > MAX_DOC_BYTES:
            raise DisplayError(f"document too large: {len(body)} bytes > {MAX_DOC_BYTES} max")

        entry = self._get_or_create_entry(name)
        now = time.time()
        with entry.lock:
            self._write_doc(name, body)
            entry.doc = new_doc
            entry.body = body
            entry.hash = meta["hash"]
            entry.fetch.published_at = now
            entry.fetch.first_fetch_at = None
            self._write_meta(name, entry.fetch)

        return PublishResult(
            name=name,
            hash=meta["hash"],
            etag=f'"{meta["hash"]}"',
            ops=len(new_doc.get("ops", [])),
            bytes=len(body),
            warnings=warnings,
        )

    def clear(self, name: str = DEFAULT_NAME) -> bool:
        """Remove the document and its meta. Returns False if none existed."""
        validate_name(name)
        entry = self._get_or_create_entry(name)
        with entry.lock:
            if entry.doc is None:
                return False
            for path in (self._doc_path(name), self._meta_path(name)):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            entry.doc = None
            entry.body = None
            entry.hash = None
            entry.fetch = FetchRecord()
        return True

    def fetch_record(self, name: str) -> FetchRecord | None:
        """The panel's fetch record for `name`, published or not. None if never seen."""
        validate_name(name)
        with self._map_lock:
            entry = self._entries.get(name)
        if entry is None:
            return None
        with entry.lock:
            return replace(entry.fetch)

    def note_fetch(self, name: str, status: int, ip: str | None) -> None:
        """Record a panel request. A 200 sets first_fetch_at if unset.

        Works even when nothing is published under `name` -- the panel could
        be asking for a display that does not exist, and that is itself
        worth recording (see module docstring).
        """
        validate_name(name)
        entry = self._get_or_create_entry(name)
        now = time.time()
        with entry.lock:
            entry.fetch.recent_fetch_at = now
            entry.fetch.recent_fetch_status = status
            entry.fetch.recent_fetch_ip = ip
            if status == 200 and entry.fetch.first_fetch_at is None:
                entry.fetch.first_fetch_at = now
            self._write_meta(name, entry.fetch)
