import pytest

from jarvis.runner.registry import ValidationError, load_registry, validate_params
from jarvis.runner.server import run_script


def registry(tmp_path):
    script = tmp_path / "hello.sh"
    script.write_text("#!/bin/sh\nprintf 'Hallo %s' \"$1\"\n")
    script.chmod(0o755)
    data = {"scripts": {"hello": {"path": str(script), "timeout": 5, "params": {
        "name": {"type": "str", "pattern": "^[A-Za-z ]{1,20}$", "required": True}}}}}
    return load_registry(data, str(tmp_path))


def test_rejects_outside_root(tmp_path):
    with pytest.raises(ValidationError):
        load_registry({"scripts": {"x": {"path": "/etc/passwd"}}}, str(tmp_path))


def test_validation(tmp_path):
    spec = registry(tmp_path)["hello"]
    assert validate_params(spec, {"name": "Daniel"}) == ["Daniel"]
    with pytest.raises(ValidationError):
        validate_params(spec, {"name": "Daniel; rm -rf /"})
    with pytest.raises(ValidationError):
        validate_params(spec, {})
    with pytest.raises(ValidationError):
        validate_params(spec, {"name": "x", "extra": 1})


async def test_run(tmp_path):
    reg = registry(tmp_path)
    result = await run_script(reg, "hello", {"name": "Daniel"})
    assert result["ok"] and result["output"] == "Hallo Daniel"
    assert not (await run_script(reg, "nope", {}))["ok"]
