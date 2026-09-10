"""Nothing in the repo names the network it happens to run on.

The hostnames, the account and the home-directory path are all incidental to
this service — it is configured by env var and flag — so they belong in the
operator's environment, not in a public repo. This test is the guard: an
editing session that reaches for a real hostname because it is concrete gets
a red test instead of a commit.

Deliberately narrow. Private addresses are fine and stay fine; so is naming
Cloudflare. It is the specific names that turn a repo into a map.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).name

# (pattern, what to do instead)
FORBIDDEN = [
    (re.compile(r"lusco\.family", re.I), "use a placeholder hostname (mcp.example.com)"),
    (re.compile(r"\bpool\.iot\b", re.I), "the host is configured, not named in the repo"),
    (re.compile(r"alexlusco", re.I), "use $USER or a placeholder"),
    (re.compile(r"/home/alex\w*", re.I), "paths are relative to the login home directory"),
]


def tracked_text_files() -> list[Path]:
    out = subprocess.run(  # noqa: S603
        ["git", "ls-files", "-z"],  # noqa: S607
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
    )
    paths = []
    for name in out.stdout.split("\0"):
        if not name or Path(name).name == SELF:
            continue
        path = ROOT / name
        if path.suffix.lower() in {".png", ".stl"} or not path.is_file():
            continue
        paths.append(path)
    return paths


@pytest.mark.parametrize("path", tracked_text_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_private_details(path: Path):
    try:
        text = path.read_text()
    except UnicodeDecodeError:
        pytest.skip("not a text file")
    hits = [
        f"line {i}: {line.strip()[:70]!r} — {advice}"
        for pattern, advice in FORBIDDEN
        for i, line in enumerate(text.splitlines(), 1)
        if pattern.search(line)
    ]
    assert not hits, "\n".join(hits)
