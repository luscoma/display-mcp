from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "display.json"
SAMPLE_HASH = "3cd62aa76e731d2d"
SPRITE_SAMPLE = ROOT / "samples" / "sprite.json"
VOCABULARY_SAMPLE = ROOT / "samples" / "vocabulary.json"


@pytest.fixture
def sample_doc():
    import json

    return json.loads(SAMPLE.read_text())


@pytest.fixture
def sprite_sample_doc():
    import json

    return json.loads(SPRITE_SAMPLE.read_text())


@pytest.fixture
def vocabulary_sample_doc():
    import json

    return json.loads(VOCABULARY_SAMPLE.read_text())


@pytest.fixture
def font_dir() -> Path:
    """The seven compiled font files: Petrona, Instrument Sans and Karla
    (each upright + italic) plus JetBrains Mono. Tests that need real fonts
    skip if any are missing -- checked with fonts_available(), the same
    check render()/the CLI use, so a `mono`-only test can't pass here and
    then OSError at runtime instead of skipping cleanly."""
    from display_mcp.render import fonts_available

    d = Path(__import__("os").environ.get("DISPLAY_MCP_FONT_DIR", ROOT / "fonts"))
    if not fonts_available(d):
        pytest.skip(f"fonts not present in {d}; run deploy/fetch-fonts.sh")
    return d
