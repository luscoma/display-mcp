"""Shell-level tests for deploy/. Run on macOS without root: --dry-run and
--self-test paths only, never a real install.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
SETUP = DEPLOY / "setup.sh"
FETCH_FONTS = DEPLOY / "fetch-fonts.sh"
UNIT = DEPLOY / "display-mcp.service"
RUNBOOK = ROOT / "docs" / "RUNBOOK.md"

NONROOT_ENV = {**os.environ, "DISPLAY_MCP_SETUP_ALLOW_NONROOT": "1"}

REQUIRED_ENV_VARS = [
    "DISPLAY_MCP_PANEL_BIND",
    "DISPLAY_MCP_PANEL_PORT",
    "DISPLAY_MCP_MCP_HOST",
    "DISPLAY_MCP_MCP_PORT",
    "DISPLAY_MCP_MCP_PATH",
    "DISPLAY_MCP_STATE_DIR",
    "DISPLAY_MCP_FONT_DIR",
    "DISPLAY_MCP_CF_ACCESS_TEAM_DOMAIN",
    "DISPLAY_MCP_CF_ACCESS_AUD",
]


def run(args, **kw):
    kw.setdefault("cwd", ROOT)
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("timeout", 30)
    return subprocess.run(args, **kw)  # noqa: S603


# --- syntax -----------------------------------------------------------------


@pytest.mark.parametrize("script", [SETUP, FETCH_FONTS])
def test_bash_syntax(script):
    result = run(["bash", "-n", str(script)])
    assert result.returncode == 0, result.stderr


# --- setup.sh install --dry-run ---------------------------------------------


def test_install_dry_run_mentions_the_plan():
    result = run(
        [str(SETUP), "install", "--dry-run", "--bind", "127.0.0.1"],
        env=NONROOT_ENV,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout

    # the unit path
    assert "/etc/systemd/system/display-mcp.service" in out
    # the venv
    assert "/opt/display-mcp/venv" in out
    # pip install of $PREFIX/app
    assert "pip" in out
    assert "/opt/display-mcp/app" in out
    # the state seed
    assert "/var/lib/display-mcp" in out
    assert "default.json" in out


# --- status / uninstall ------------------------------------------------------


def test_status_dry_run_parses_and_exits_zero():
    result = run(
        [str(SETUP), "status", "--dry-run", "--bind", "127.0.0.1"],
        env=NONROOT_ENV,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "endpoint" in result.stdout


def test_uninstall_dry_run_parses_and_exits_zero():
    result = run([str(SETUP), "uninstall", "--dry-run"], env=NONROOT_ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "uninstalled" in result.stdout


def test_help_exits_zero():
    result = run([str(SETUP), "--help"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Commands:" in result.stdout


def test_help_and_dispatch_agree():
    """Every command --help documents dispatches, and vice versa.

    setup.sh is the whole deploy story now, so its --help is the only place
    anyone finds out what it can do. `sync` was missing from the synopsis for
    long enough that it looked like it did not exist.
    """
    text = SETUP.read_text()
    dispatched = set(re.findall(r"^  (\w+}?\)|\w+\))\s+(?:need_root; )?do_", text, re.M))
    dispatched = {d.rstrip(")") for d in dispatched}

    out = run([str(SETUP), "--help"]).stdout
    commands_block = out.split("Commands:")[1].split("Flags:")[0]
    documented = set(re.findall(r"^  (\w+)\s{2,}", commands_block, re.M))

    assert documented == dispatched, (
        f"only documented: {documented - dispatched}; "
        f"only dispatched: {dispatched - documented}"
    )

    # The synopsis at the top is what people actually read; it should name
    # them all too.
    synopsis = out.split("Commands:")[0]
    missing = {c for c in dispatched if f"setup.sh {c}" not in synopsis}
    assert not missing, f"missing from the synopsis at the top of --help: {missing}"


# --- the unit file ------------------------------------------------------------


def test_unit_has_required_fields():
    text = UNIT.read_text()
    assert "ExecStart=/opt/display-mcp/venv/bin/display-mcp" in text
    assert "User=display-mcp" in text
    assert "StateDirectory=display-mcp" in text
    for var in REQUIRED_ENV_VARS:
        assert var in text, f"{var} missing from {UNIT}"


def test_no_epaper_env_prefix_anywhere_in_deploy_or_runbook():
    offenders = []
    for path in list(DEPLOY.rglob("*")) + [RUNBOOK]:
        if path.is_dir():
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        if "EPAPER_" in text:
            offenders.append(str(path))
    assert not offenders, f"found EPAPER_ in: {offenders}"


# --- fetch-fonts.sh -----------------------------------------------------------

# The seven files fetch-fonts.sh downloads (one per family per slant, mono
# has no italic). A fresh directory ends with all seven.
FETCHED_FONT_NAMES = (
    "Petrona.ttf",
    "Petrona-Italic.ttf",
    "InstrumentSans.ttf",
    "InstrumentSans-Italic.ttf",
    "Karla.ttf",
    "Karla-Italic.ttf",
    "JetBrainsMono-Regular.ttf",
)
ALL_FONT_NAMES = FETCHED_FONT_NAMES

# Each two-file family's (upright, italic) destination pair -- used to check
# the per-destination italic filter actually kept the two apart.
ITALIC_PAIRS = (
    ("Petrona.ttf", "Petrona-Italic.ttf"),
    ("InstrumentSans.ttf", "InstrumentSans-Italic.ttf"),
    ("Karla.ttf", "Karla-Italic.ttf"),
)

# The magic bytes is_font() (in both shell scripts) accepts: TrueType,
# OpenType/CFF, a TrueType collection, and the same TrueType tag again (its
# case list has it twice under two names).
_FONT_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"ttcf", b"true")


def test_fetch_fonts_usage_without_args():
    result = run(["bash", str(FETCH_FONTS)])
    assert result.returncode != 0
    assert "usage" in (result.stdout + result.stderr).lower()


def _fake_font(path: Path) -> None:
    """A file `is_font()` accepts: >20000 bytes, TrueType magic -- big
    enough to skip the network without ever making a real request."""
    path.write_bytes(b"\x00\x01\x00\x00" + b"\x00" * 20000)


def _looks_like_font(path: Path) -> bool:
    return (
        path.is_file()
        and path.stat().st_size > 20000
        and path.read_bytes()[:4] in _FONT_MAGIC
    )


def _subfamily(path: Path) -> str:
    """The named instance a variable font resolves to by default -- e.g.
    "Regular" or "Italic" -- via the same library the renderer itself uses
    to load faces, rather than trusting a filename."""
    return ImageFont.truetype(str(path), 20).getname()[1]


def test_fetch_fonts_skips_the_network_when_all_seven_are_present(tmp_path):
    """The early return (main()'s `all_present` check) needs all seven
    files, not just a subset -- run for real, with fake-but-valid fonts
    already in place, so this never touches the network and can't be flaky
    in a sandboxed CI run."""
    for name in ALL_FONT_NAMES:
        _fake_font(tmp_path / name)
    result = run(["bash", str(FETCH_FONTS), str(tmp_path)])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "already present" in result.stdout.lower()


def test_fetch_fonts_downloads_all_seven_files_for_real(tmp_path):
    """No fixture fonts this time -- an empty directory, so every one of the
    seven downloads has to actually happen.

    A single family timing out under load (seen on a review run, back when
    this fetched nine files: Petrona's curl hit its own --max-time and all
    but one landed) is not the
    deterministic bug class this test exists to catch -- that's covered
    offline, with a captured listing and no network at all, by
    test_fetch_fonts_select_urls_picks_the_right_file below. So a first
    pass that leaves anything missing gets one retry into the *same*
    directory -- fetch-fonts.sh only re-fetches what's still missing (see
    all_present/fetch_if_missing) -- and only skips, rather than fails, if
    files are still missing after that: from here that's indistinguishable
    from a slow or rate-limited network.
    """
    result = run(["bash", str(FETCH_FONTS), str(tmp_path)], timeout=120)
    missing = [name for name in ALL_FONT_NAMES if not _looks_like_font(tmp_path / name)]

    if missing:
        result = run(["bash", str(FETCH_FONTS), str(tmp_path)], timeout=120)
        missing = [name for name in ALL_FONT_NAMES if not _looks_like_font(tmp_path / name)]

    if missing:
        pytest.skip(
            f"still missing after a retry (transient network): {missing}\n"
            + result.stdout
            + result.stderr
        )

    for name in ALL_FONT_NAMES:
        f = tmp_path / name
        assert f.is_file(), f"{name} was not installed"
        assert f.stat().st_size > 20000, f"{name} is too small to be a real font"
        magic = f.read_bytes()[:4]
        assert magic in _FONT_MAGIC, f"{name} does not start with a font magic ({magic!r})"

    # The per-destination italic filter: an upright destination must resolve
    # to a non-italic named instance and its `-Italic` sibling to an italic
    # one -- checked through the actual font data (Pillow's getname()), not
    # a size or filename proxy that a swapped pair would still pass.
    for upright, italic in ITALIC_PAIRS:
        upright_name = _subfamily(tmp_path / upright)
        italic_name = _subfamily(tmp_path / italic)
        assert "italic" not in upright_name.lower(), (
            f"{upright}'s default instance is {upright_name!r} -- looks italic"
        )
        assert "italic" in italic_name.lower(), (
            f"{italic}'s default instance is {italic_name!r} -- doesn't look italic"
        )

    mono_name = _subfamily(tmp_path / "JetBrainsMono-Regular.ttf")
    assert mono_name == "Regular", (
        f"JetBrainsMono-Regular.ttf's default instance is {mono_name!r}, not Regular"
    )


# --- fetch-fonts.sh's URL selection, offline ---------------------------------

# One captured (trimmed, hand-written but shaped like the real thing)
# `ofl/<slug>` directory listing per family -- each a `"download_url": "..."`
# line per file, which is all select_urls's sed/grep pipeline looks at.
# Petrona's also carries a synthetic static `Petrona-Regular.ttf` entry (no
# variable-font `[wght]` suffix) to prove the %5B filter keeps a static file
# from winning the upright slot over `Petrona[wght].ttf` -- the scenario
# fetch-fonts.sh's own comment on select_urls calls out by name.
_LISTING_FIXTURES = {
    "petrona": """
    "download_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/petrona/Petrona%5Bwght%5D.ttf",
    "download_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/petrona/Petrona-Italic%5Bwght%5D.ttf",
    "download_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/petrona/Petrona-Regular.ttf",
""",
    "instrumentsans": """
    "download_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/instrumentsans/InstrumentSans%5Bwdth,wght%5D.ttf",
    "download_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/instrumentsans/InstrumentSans-Italic%5Bwdth,wght%5D.ttf",
""",
    "karla": """
    "download_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/karla/Karla%5Bwght%5D.ttf",
    "download_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/karla/Karla-Italic%5Bwght%5D.ttf",
""",
    "jetbrainsmono": """
    "download_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf",
""",
}

# (slug, italic) -> the one URL select_urls must put first for that
# destination -- mono has no italic entry, so (jetbrainsmono, 1) isn't here;
# it's covered by its own "nothing matches" test below instead.
_EXPECTED_SELECTION = {
    ("petrona", 0): "https://raw.githubusercontent.com/google/fonts/main/ofl/petrona/Petrona%5Bwght%5D.ttf",
    ("petrona", 1): "https://raw.githubusercontent.com/google/fonts/main/ofl/petrona/Petrona-Italic%5Bwght%5D.ttf",
    ("instrumentsans", 0): "https://raw.githubusercontent.com/google/fonts/main/ofl/instrumentsans/InstrumentSans%5Bwdth,wght%5D.ttf",
    ("instrumentsans", 1): "https://raw.githubusercontent.com/google/fonts/main/ofl/instrumentsans/InstrumentSans-Italic%5Bwdth,wght%5D.ttf",
    ("karla", 0): "https://raw.githubusercontent.com/google/fonts/main/ofl/karla/Karla%5Bwght%5D.ttf",
    ("karla", 1): "https://raw.githubusercontent.com/google/fonts/main/ofl/karla/Karla-Italic%5Bwght%5D.ttf",
    ("jetbrainsmono", 0): "https://raw.githubusercontent.com/google/fonts/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf",
}


def _select_urls(listing: str, italic: int) -> list[str]:
    """Drives fetch-fonts.sh's own select_urls (the pure filter fetch_one
    calls) with a captured listing on stdin -- no network, no curl.
    fetch-fonts.sh is `source`d rather than reimplementing its filter here,
    guarded (see its own bottom-of-file `if`) so sourcing it doesn't also
    run main() against whatever $1 this shell happens to have."""
    script = f'source "{FETCH_FONTS}" dummy; printf "%s" "$1" | select_urls "$2"'
    result = subprocess.run(
        ["bash", "-c", script, "bash", listing, str(italic)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line]


@pytest.mark.parametrize(("slug", "italic"), sorted(_EXPECTED_SELECTION))
def test_fetch_fonts_select_urls_picks_the_right_file(slug, italic):
    urls = _select_urls(_LISTING_FIXTURES[slug], italic)
    assert urls, f"no candidate URL for slug={slug} italic={italic}"
    assert urls[0] == _EXPECTED_SELECTION[(slug, italic)]
    # No static (non-variable-font) filename should ever survive the filter,
    # for either slant -- this is what catches Petrona-Regular.ttf without
    # relying on it happening to sort after the variable font.
    assert all("%5B" in u for u in urls), f"a non-variable-font URL leaked through: {urls}"


def test_fetch_fonts_select_urls_finds_nothing_for_mono_italic():
    """JetBrains Mono has no italic in this vocabulary -- its listing has no
    italic entry, so the italic slant must select nothing (fetch_one then
    falls through to $fallback_url, same as a rate-limited API would)."""
    assert _select_urls(_LISTING_FIXTURES["jetbrainsmono"], 1) == []


# --- fetch-fonts.sh's fallback URLs ------------------------------------------


def _fallback_urls() -> list[str]:
    """The fixed raw.githubusercontent.com URLs fetch-fonts.sh falls back to
    when the API listing is rate limited -- read out of the script itself so
    this test can't silently drift from what it actually fetches."""
    text = FETCH_FONTS.read_text()
    return re.findall(r"https://raw\.githubusercontent\.com/\S+?\.ttf", text)


def _http_status(url: str) -> str | None:
    try:
        result = subprocess.run(
            ["curl", "-sI", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "10", url],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


@pytest.mark.parametrize("url", _fallback_urls(), ids=lambda u: u.rsplit("/", 1)[-1])
def test_fetch_fonts_fallback_url_is_reachable(url):
    """A wrong fallback URL is invisible as long as the API listing keeps
    working -- this is what would catch a rename or a typo before a rate
    limit does."""
    status = _http_status(url)
    if status is None:
        pytest.skip(f"network unavailable for {url}")
    assert status == "200", f"{url} returned HTTP {status}"


def test_fetch_fonts_has_seven_fallback_urls():
    """A guard on `_fallback_urls()` itself: if this drifts from seven, the
    parametrized test above silently covers fewer (or more) URLs than the
    script actually has."""
    assert len(_fallback_urls()) == len(FETCHED_FONT_NAMES)


# --- shellcheck, if available -------------------------------------------------


@pytest.mark.parametrize("script", [SETUP, FETCH_FONTS])
def test_shellcheck_clean(script):
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck not installed")
    result = run(["shellcheck", "--severity=warning", str(script)])
    assert result.returncode == 0, result.stdout + result.stderr


def test_install_dry_run_with_tunnel_plans_cloudflared_and_hides_the_token():
    result = run(
        [str(SETUP), "install", "--dry-run", "--bind", "127.0.0.1",
         "--with-tunnel", "--tunnel-token", "SECRET-TOKEN-123"],
        env=NONROOT_ENV,
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "cloudflared service install <token>" in out
    assert "SECRET-TOKEN-123" not in out
    assert "--with-tunnel" in run([str(SETUP), "--help"], env=NONROOT_ENV).stdout
