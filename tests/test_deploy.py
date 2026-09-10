"""Shell-level tests for deploy/. Run on macOS without root: --dry-run and
--self-test paths only, never a real install.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
SETUP = DEPLOY / "setup.sh"
FETCH_FONTS = DEPLOY / "fetch-fonts.sh"
DEPLOY_SH = ROOT / "deploy.sh"
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


@pytest.mark.parametrize("script", [SETUP, FETCH_FONTS, DEPLOY_SH])
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


def test_install_dry_run_is_pragmatic_without_apt_or_systemctl():
    # apt-get and systemctl don't exist on macOS; --dry-run must still print
    # the plan rather than fail, because `run()` never execs them under DRY=1.
    assert shutil.which("apt-get") is None
    assert shutil.which("systemctl") is None
    result = run(
        [str(SETUP), "install", "--dry-run", "--bind", "127.0.0.1"],
        env=NONROOT_ENV,
    )
    assert result.returncode == 0, result.stdout + result.stderr


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
    for path in list(DEPLOY.rglob("*")) + [RUNBOOK, DEPLOY_SH]:
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


def test_fetch_fonts_usage_without_args():
    result = run(["bash", str(FETCH_FONTS)])
    assert result.returncode != 0
    assert "usage" in (result.stdout + result.stderr).lower()


# --- shellcheck, if available -------------------------------------------------


@pytest.mark.parametrize("script", [SETUP, FETCH_FONTS, DEPLOY_SH])
def test_shellcheck_clean(script):
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck not installed")
    # deploy.sh intentionally expands $DIR client-side in the ssh command
    # (SC2029, info-level); fail only on warning severity and above.
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
