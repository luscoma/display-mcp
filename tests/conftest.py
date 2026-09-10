from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "display.json"
SAMPLE_HASH = "21a77f4c46f1534d"


@pytest.fixture
def sample_doc():
    import json

    return json.loads(SAMPLE.read_text())


@pytest.fixture
def font_dir() -> Path:
    """Instrument Sans pair. Tests that need real fonts skip if absent."""
    d = Path(__import__("os").environ.get("DISPLAY_MCP_FONT_DIR", ROOT / "fonts"))
    if not (d / "InstrumentSans-Regular.ttf").exists():
        pytest.skip(f"fonts not present in {d}; run deploy/fetch-fonts.sh")
    return d
