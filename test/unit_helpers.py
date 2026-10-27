"""Shared fixtures; application defaults are always read from their source."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def app_settings():
    return json.loads((ROOT / "config/RobGPT_config.json").read_text())
