import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).parent))
EXAMPLES = ROOT / "config" / "examples"


@pytest.fixture
def intents_data():
    return yaml.safe_load((EXAMPLES / "intents.yaml").read_text())


@pytest.fixture
def config_dir(tmp_path):
    for f in EXAMPLES.glob("*.yaml"):
        (tmp_path / f.name).write_text(f.read_text())
    return tmp_path


@pytest.fixture(scope="session")
def mock_llm_url():
    from mock_llm import free_port, serve_in_thread

    port = free_port()
    server = serve_in_thread(port)
    yield f"http://127.0.0.1:{port}/v1"
    server.should_exit = True


@pytest.fixture
def dev_config(tmp_path, mock_llm_url):
    """Konfiguration ohne Audio-Modelle: Text-STT/TTS aus, LLM = Mock, Trigramm-Router."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    for f in EXAMPLES.glob("*.yaml"):
        (cfg_dir / f.name).write_text(f.read_text())
    cfg = yaml.safe_load((cfg_dir / "config.yaml").read_text())
    cfg["providers"]["stt"] = {"type": "none"}
    cfg["providers"]["tts"] = {"type": "none"}
    cfg["providers"]["llm"]["local"].update({"base_url": mock_llm_url, "model": "mock"})
    cfg["router"]["embedding_model"] = ""
    cfg["location"].update({"latitude": 52.52, "longitude": 13.4, "name": "Berlin"})
    cfg["mcp_servers"] = [m for m in cfg["mcp_servers"] if m["name"] != "searxng"]
    cfg["server"]["https"] = {"enabled": False}
    (cfg_dir / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True))
    return cfg_dir


@pytest.fixture
def services(dev_config, tmp_path):
    from jarvis.app import build_services

    return build_services(dev_config, tmp_path / "data", tmp_path / "data" / "j.db",
                          runner_socket=str(tmp_path / "runner.sock"))
