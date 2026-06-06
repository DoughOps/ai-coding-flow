import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


def test_agent_engine_is_abstract():
    from engines.base import AgentEngine
    with pytest.raises(TypeError):
        AgentEngine()  # type: ignore[abstract]


def test_agent_engine_name_is_abstract():
    from engines.base import AgentEngine
    assert "name" in AgentEngine.__abstractmethods__


def test_agent_engine_run_is_abstract():
    from engines.base import AgentEngine
    assert "run" in AgentEngine.__abstractmethods__


def _mock_settings():
    s = MagicMock()
    s.openai_model = "gpt-4o"
    s.openai_api_base = "http://localhost:11434/v1"
    s.openai_api_key = "local"
    s.aider_verbose = False
    return s


def test_aider_engine_name():
    from engines.aider import AiderEngine
    assert AiderEngine().name == "aider"


def test_aider_engine_run_calls_aider_binary():
    from engines.aider import AiderEngine
    with patch("engines.aider.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="Changes applied.", stderr="", returncode=0)
        output = AiderEngine().run(Path("/tmp/repo"), "Fix the login bug", _mock_settings())
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "aider"
    assert "--model" in cmd
    assert "gpt-4o" in cmd
    assert "--message" in cmd
    assert "Fix the login bug" in cmd
    assert output == "Changes applied."


def test_aider_engine_run_passes_env_vars():
    from engines.aider import AiderEngine
    import os
    with patch("engines.aider.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        AiderEngine().run(Path("/tmp/repo"), "prompt", _mock_settings())
    env = mock_run.call_args[1]["env"]
    assert env["OPENAI_API_BASE"] == "http://localhost:11434/v1"
    assert env["OPENAI_API_KEY"] == "local"


def test_aider_engine_run_verbose_logs(caplog):
    import logging
    from engines.aider import AiderEngine
    s = _mock_settings()
    s.aider_verbose = True
    with patch("engines.aider.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="aider said something", stderr="", returncode=0)
        with caplog.at_level(logging.INFO, logger="engines.aider"):
            AiderEngine().run(Path("/tmp/repo"), "prompt", s)
    assert "aider said something" in caplog.text


def test_opencode_engine_name():
    from engines.opencode import OpenCodeEngine
    assert OpenCodeEngine().name == "opencode"


def test_opencode_engine_run_calls_opencode_binary(tmp_path):
    from engines.opencode import OpenCodeEngine
    with patch("engines.opencode.subprocess.run") as mock_run, \
         patch("engines.opencode._write_opencode_config"):
        mock_run.return_value = MagicMock(stdout="Done.", stderr="", returncode=0)
        output = OpenCodeEngine().run(tmp_path, "Fix the login bug", _mock_settings())
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "opencode"
    assert cmd[1] == "run"
    assert "--model" in cmd
    assert "custom/gpt-4o" in cmd       # model is prefixed with provider ID
    assert cmd[-1] == "Fix the login bug"   # prompt is positional, must be last
    assert output == "Done."


def test_opencode_engine_run_passes_env_vars(tmp_path):
    from engines.opencode import OpenCodeEngine
    with patch("engines.opencode.subprocess.run") as mock_run, \
         patch("engines.opencode._write_opencode_config"):
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        OpenCodeEngine().run(tmp_path, "prompt", _mock_settings())
    env = mock_run.call_args[1]["env"]
    assert env["OPENAI_API_KEY"] == "local"
    assert "OPENAI_BASE_URL" not in env     # URL is now in the config file, not env


def test_opencode_write_config_creates_provider(tmp_path):
    from engines.opencode import _write_opencode_config
    s = _mock_settings()
    with patch("engines.opencode.Path.home", return_value=tmp_path):
        _write_opencode_config(s)
    config_file = tmp_path / ".config" / "opencode" / "opencode.jsonc"
    assert config_file.exists()
    config = json.loads(config_file.read_text())
    provider = config["provider"]["custom"]
    assert provider["options"]["baseURL"] == "http://localhost:11434/v1"
    assert "gpt-4o" in provider["models"]


@pytest.mark.skipif(
    __import__("shutil").which("opencode") is None,
    reason="opencode binary not installed",
)
def test_opencode_binary_accepts_run_help():
    """Integration: verify 'opencode run --help' exits cleanly."""
    import subprocess
    result = subprocess.run(["opencode", "run", "--help"], capture_output=True, text=True)
    assert result.returncode == 0, f"opencode run --help exited {result.returncode}"
    assert "message" in (result.stdout + result.stderr).lower()


def test_get_engine_returns_aider_by_default():
    from engines import get_engine
    from engines.aider import AiderEngine
    assert isinstance(get_engine("aider"), AiderEngine)


def test_get_engine_returns_opencode():
    from engines import get_engine
    from engines.opencode import OpenCodeEngine
    assert isinstance(get_engine("opencode"), OpenCodeEngine)


def test_get_engine_unknown_name_falls_back_to_aider():
    from engines import get_engine
    from engines.aider import AiderEngine
    assert isinstance(get_engine("some-unknown-engine"), AiderEngine)
