"""Settings from the environment. Every variable is DISPLAY_MCP_*.

Owned by the core package. Other packages import `Settings` and
`settings_from_env()`; do not read os.environ elsewhere.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    # One or more addresses, each bound explicitly. Never a wildcard.
    panel_bind: tuple[str, ...] = ("127.0.0.1",)
    panel_port: int = 8080
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8001
    mcp_path: str = "/mcp"
    state_dir: Path = Path("/var/lib/display-mcp")
    font_dir: Path = Path("/opt/display-mcp/fonts")
    # Cloudflare Access. Both unset -> authless (logged loudly at startup).
    cf_access_team_domain: str | None = None  # e.g. https://example.cloudflareaccess.com
    cf_access_aud: str | None = None  # the Access application's AUD tag

    @property
    def auth_enabled(self) -> bool:
        return bool(self.cf_access_team_domain and self.cf_access_aud)


def _addr_list(raw: str) -> tuple[str, ...]:
    """Comma-separated addresses -> tuple, whitespace and empties dropped."""
    return tuple(a.strip() for a in raw.split(",") if a.strip())


def settings_from_env(env: dict[str, str] | None = None) -> Settings:
    e = os.environ if env is None else env
    g = lambda k, d=None: e.get(f"DISPLAY_MCP_{k}", d)  # noqa: E731
    return Settings(
        panel_bind=_addr_list(g("PANEL_BIND", "127.0.0.1")),
        panel_port=int(g("PANEL_PORT", "8080")),
        mcp_host=g("MCP_HOST", "127.0.0.1"),
        mcp_port=int(g("MCP_PORT", "8001")),
        mcp_path=g("MCP_PATH", "/mcp"),
        state_dir=Path(g("STATE_DIR", "/var/lib/display-mcp")),
        font_dir=Path(g("FONT_DIR", "/opt/display-mcp/fonts")),
        cf_access_team_domain=g("CF_ACCESS_TEAM_DOMAIN") or None,
        cf_access_aud=g("CF_ACCESS_AUD") or None,
    )
