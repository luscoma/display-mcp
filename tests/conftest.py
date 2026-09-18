from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "display.json"
SAMPLE_HASH = "3cd62aa76e731d2d"
SPRITE_SAMPLE = ROOT / "samples" / "sprite.json"
SPRITE_SAMPLE_HASH = "d5d25873e7907f20"


@pytest.fixture
def sample_doc():
    import json

    return json.loads(SAMPLE.read_text())


@pytest.fixture
def sprite_sample_doc():
    import json

    return json.loads(SPRITE_SAMPLE.read_text())


@pytest.fixture
def font_dir() -> Path:
    """All three compiled faces: the Instrument Sans pair and JetBrains
    Mono. Tests that need real fonts skip if any are missing -- checked
    with fonts_available(), the same check render()/the CLI use, so a
    `mono`-only test can't pass here and then OSError at runtime instead of
    skipping cleanly (F5)."""
    from display_mcp.render import fonts_available

    d = Path(__import__("os").environ.get("DISPLAY_MCP_FONT_DIR", ROOT / "fonts"))
    if not fonts_available(d):
        pytest.skip(f"fonts not present in {d}; run deploy/fetch-fonts.sh")
    return d
