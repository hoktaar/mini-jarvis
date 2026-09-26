import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
EXAMPLES = ROOT / "config" / "examples"


@pytest.fixture
def intents_data():
    return yaml.safe_load((EXAMPLES / "intents.yaml").read_text())


@pytest.fixture
def config_dir(tmp_path):
    for f in EXAMPLES.glob("*.yaml"):
        (tmp_path / f.name).write_text(f.read_text())
    return tmp_path
