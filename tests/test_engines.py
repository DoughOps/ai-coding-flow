import json
import os
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
    s.aider_map_tokens = 2048
    s.agent_timeout = 600
    s.verify_engine_ssl = True
    s.verify_repo_ssl = True
    s.opencode_context_limit = 32768
    s.opencode_output_limit = 4096
    s.claudecode_router_port = 3456
    s.claudecode_router_startup_timeout = 15
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
    assert "openai/gpt-4o" in cmd
    assert "--message" in cmd
    assert "Fix the login bug" in cmd
    assert output == "Changes applied."


def test_aider_engine_prefixes_openai_for_litellm():
    from engines.aider import AiderEngine
    s = _mock_settings()
    s.openai_model = "poolside/laguna-m.1:free"
    with patch("engines.aider.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        AiderEngine().run(Path("/tmp/repo"), "prompt", s)
    cmd = mock_run.call_args[0][0]
    assert cmd[cmd.index("--model") + 1] == "openai/poolside/laguna-m.1:free"


def test_aider_engine_does_not_double_prefix_openai():
    from engines.aider import AiderEngine
    s = _mock_settings()
    s.openai_model = "openai/gpt-4o"
    with patch("engines.aider.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        AiderEngine().run(Path("/tmp/repo"), "prompt", s)
    cmd = mock_run.call_args[0][0]
    assert cmd[cmd.index("--model") + 1] == "openai/gpt-4o"


def test_aider_engine_run_passes_env_vars():
    from engines.aider import AiderEngine
    with patch("engines.aider.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        AiderEngine().run(Path("/tmp/repo"), "prompt", _mock_settings())
    env = mock_run.call_args[1]["env"]
    assert env["OPENAI_API_BASE"] == "http://localhost:11434/v1"
    assert env["OPENAI_API_KEY"] == "local"


def test_aider_engine_works_offline():
    from engines.aider import AiderEngine
    with patch("engines.aider.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        AiderEngine().run(Path("/tmp/repo"), "prompt", _mock_settings())
    cmd = mock_run.call_args[0][0]
    env = mock_run.call_args[1]["env"]
    assert "--no-check-update" in cmd
    assert env["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"


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
    # first call is the opencode invocation; later calls are git add / git commit
    cmd = mock_run.call_args_list[0][0][0]
    assert cmd[0] == "opencode"
    assert cmd[1] == "run"
    assert "--model" in cmd
    assert "custom/gpt-4o" in cmd       # model is prefixed with provider ID
    assert "--dir" in cmd
    assert str(tmp_path) in cmd         # --dir points to the repo
    assert cmd[-1] == "Fix the login bug"   # prompt is positional, must be last
    assert output == "Done."


def test_opencode_engine_run_passes_env_vars(tmp_path):
    from engines.opencode import OpenCodeEngine
    with patch("engines.opencode.subprocess.run") as mock_run, \
         patch("engines.opencode._write_opencode_config"):
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        OpenCodeEngine().run(tmp_path, "prompt", _mock_settings())
    # env is only set on the opencode call, not the git calls
    env = mock_run.call_args_list[0][1]["env"]
    assert env["OPENAI_API_KEY"] == "local"
    assert "OPENAI_BASE_URL" not in env     # URL is now in the config file, not env


def test_opencode_engine_commits_changes_after_run(tmp_path):
    from engines.opencode import OpenCodeEngine
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(stdout="", stderr="", returncode=0)
    with patch("engines.opencode.subprocess.run", side_effect=fake_run), \
         patch("engines.opencode._write_opencode_config"):
        OpenCodeEngine().run(tmp_path, "fix it", _mock_settings())
    cmds = [" ".join(c) for c in calls]
    assert any("git add" in c for c in cmds), "expected git add -A"
    assert any("git commit" in c for c in cmds), "expected git commit"


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


def test_opencode_config_write_is_atomic(tmp_path):
    from engines.opencode import _write_opencode_config
    s = _mock_settings()
    with patch("engines.opencode.Path.home", return_value=tmp_path), \
         patch("engines.opencode.os.replace", side_effect=os.replace) as mock_replace:
        _write_opencode_config(s)
    mock_replace.assert_called_once()
    src, dst = mock_replace.call_args[0]
    assert Path(dst) == tmp_path / ".config" / "opencode" / "opencode.jsonc"
    assert Path(src).parent == Path(dst).parent
    config = json.loads(Path(dst).read_text())
    assert "provider" in config


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


def test_get_engine_unknown_name_falls_back_to_opencode():
    from engines import get_engine
    from engines.opencode import OpenCodeEngine
    assert isinstance(get_engine("some-unknown-engine"), OpenCodeEngine)


# ── ClaudeCodeEngine ──────────────────────────────────────────────────────────

def test_claudecode_engine_name():
    from engines.claudecode import ClaudeCodeEngine
    assert ClaudeCodeEngine().name == "claudecode"


def test_claudecode_engine_run_calls_claude_binary(tmp_path):
    from engines.claudecode import ClaudeCodeEngine
    with patch("engines.claudecode.subprocess.Popen") as mock_popen, \
         patch("engines.claudecode.subprocess.run") as mock_run, \
         patch("engines.claudecode._wait_for_port"), \
         patch("engines.claudecode._is_port_open", return_value=False), \
         patch("engines.claudecode._write_router_config"):
        mock_popen.return_value = MagicMock()
        mock_run.return_value = MagicMock(stdout="Done.", stderr="", returncode=0)
        output = ClaudeCodeEngine().run(tmp_path, "Fix the login bug", _mock_settings())
    cmd = mock_run.call_args_list[0][0][0]
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "Fix the login bug" in cmd
    assert output == "Done."


def test_claudecode_engine_run_starts_router(tmp_path):
    from engines.claudecode import ClaudeCodeEngine
    with patch("engines.claudecode.subprocess.Popen") as mock_popen, \
         patch("engines.claudecode.subprocess.run") as mock_run, \
         patch("engines.claudecode._wait_for_port"), \
         patch("engines.claudecode._is_port_open", return_value=False), \
         patch("engines.claudecode._write_router_config"), \
         patch("engines.claudecode._ccr_binary", return_value="ccr"):
        mock_popen.return_value = MagicMock()
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        ClaudeCodeEngine().run(tmp_path, "prompt", _mock_settings())
    cmd = mock_popen.call_args[0][0]
    assert cmd[0] == "ccr"
    assert cmd[1] == "start"


def test_claudecode_engine_skips_router_start_if_we_own_it(tmp_path):
    from engines.claudecode import ClaudeCodeEngine
    with patch("engines.claudecode.subprocess.Popen") as mock_popen, \
         patch("engines.claudecode.subprocess.run") as mock_run, \
         patch("engines.claudecode._wait_for_port"), \
         patch("engines.claudecode._is_port_open", return_value=True), \
         patch("engines.claudecode._our_router_pid", return_value=99999), \
         patch("engines.claudecode._write_router_config"):
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        ClaudeCodeEngine().run(tmp_path, "prompt", _mock_settings())
    mock_popen.assert_not_called()


def test_claudecode_engine_refuses_foreign_router_on_port(tmp_path):
    from engines.claudecode import ClaudeCodeEngine
    with patch("engines.claudecode.subprocess.Popen") as mock_popen, \
         patch("engines.claudecode._is_port_open", return_value=True), \
         patch("engines.claudecode._our_router_pid", return_value=None), \
         patch("engines.claudecode._write_router_config"):
        with pytest.raises(RuntimeError, match="already in use"):
            ClaudeCodeEngine().run(tmp_path, "prompt", _mock_settings())
    mock_popen.assert_not_called()


def test_claudecode_engine_run_sets_env_vars(tmp_path):
    from engines.claudecode import ClaudeCodeEngine
    with patch("engines.claudecode.subprocess.Popen") as mock_popen, \
         patch("engines.claudecode.subprocess.run") as mock_run, \
         patch("engines.claudecode._wait_for_port"), \
         patch("engines.claudecode._is_port_open", return_value=False), \
         patch("engines.claudecode._write_router_config"):
        mock_popen.return_value = MagicMock()
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        ClaudeCodeEngine().run(tmp_path, "prompt", _mock_settings())
    env = mock_run.call_args_list[0][1]["env"]
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:3456"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "local"


def test_claudecode_sets_is_sandbox_when_root(tmp_path):
    from engines.claudecode import ClaudeCodeEngine
    with patch("engines.claudecode.subprocess.Popen") as mock_popen, \
         patch("engines.claudecode.subprocess.run") as mock_run, \
         patch("engines.claudecode._wait_for_port"), \
         patch("engines.claudecode._is_port_open", return_value=False), \
         patch("engines.claudecode._write_router_config"), \
         patch("engines.claudecode.os.getuid", return_value=0, create=True):
        mock_popen.return_value = MagicMock()
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        ClaudeCodeEngine().run(tmp_path, "prompt", _mock_settings())
    env = mock_run.call_args_list[0][1]["env"]
    assert env["IS_SANDBOX"] == "1"


def test_claudecode_no_is_sandbox_when_non_root(tmp_path):
    from engines.claudecode import ClaudeCodeEngine
    with patch("engines.claudecode.subprocess.Popen") as mock_popen, \
         patch("engines.claudecode.subprocess.run") as mock_run, \
         patch("engines.claudecode._wait_for_port"), \
         patch("engines.claudecode._is_port_open", return_value=False), \
         patch("engines.claudecode._write_router_config"), \
         patch("engines.claudecode.os.getuid", return_value=1000, create=True):
        mock_popen.return_value = MagicMock()
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        ClaudeCodeEngine().run(tmp_path, "prompt", _mock_settings())
    env = mock_run.call_args_list[0][1]["env"]
    assert "IS_SANDBOX" not in env


def test_claudecode_engine_commits_changes_after_run(tmp_path):
    from engines.claudecode import ClaudeCodeEngine
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(stdout="", stderr="", returncode=0)
    with patch("engines.claudecode.subprocess.Popen") as mock_popen, \
         patch("engines.claudecode.subprocess.run", side_effect=fake_run), \
         patch("engines.claudecode._wait_for_port"), \
         patch("engines.claudecode._is_port_open", return_value=False), \
         patch("engines.claudecode._write_router_config"):
        mock_popen.return_value = MagicMock()
        ClaudeCodeEngine().run(tmp_path, "fix it", _mock_settings())
    cmds = [" ".join(c) for c in calls]
    assert any("git add" in c for c in cmds)
    assert any("git commit" in c for c in cmds)


def test_claudecode_write_config_creates_provider(tmp_path):
    from engines.claudecode import _write_router_config
    s = _mock_settings()
    with patch("engines.claudecode._SANDBOX_HOME", tmp_path):
        _write_router_config(s)
    config_file = tmp_path / ".claude-code-router" / "config.json"
    assert config_file.exists()
    config = json.loads(config_file.read_text())
    provider = config["Providers"][0]
    assert provider["api_base_url"] == "http://localhost:11434/v1/chat/completions"
    assert "gpt-4o" in provider["models"]
    assert config["Router"]["default"] == "custom,gpt-4o"


def test_claudecode_write_config_openrouter_forces_reasoning_on(tmp_path):
    from engines.claudecode import _write_router_config
    s = _mock_settings()
    s.openai_api_base = "https://openrouter.ai/api/v1"
    with patch("engines.claudecode._SANDBOX_HOME", tmp_path):
        _write_router_config(s)
    config = json.loads((tmp_path / ".claude-code-router" / "config.json").read_text())
    provider = config["Providers"][0]
    assert provider["transformer"] == {
        "use": [["openrouter", {"reasoning": {"effort": "high", "enabled": True}}]]
    }


def test_claudecode_write_config_generic_endpoint_has_no_transformer(tmp_path):
    from engines.claudecode import _write_router_config
    s = _mock_settings()
    with patch("engines.claudecode._SANDBOX_HOME", tmp_path):
        _write_router_config(s)
    config = json.loads((tmp_path / ".claude-code-router" / "config.json").read_text())
    assert "transformer" not in config["Providers"][0]


def test_get_engine_returns_claudecode():
    from engines import get_engine
    from engines.claudecode import ClaudeCodeEngine
    assert isinstance(get_engine("claudecode"), ClaudeCodeEngine)


def test_our_router_pid_none_when_no_pid_file(tmp_path):
    from engines import claudecode
    with patch("engines.claudecode._SANDBOX_HOME", tmp_path):
        assert claudecode._our_router_pid() is None


def test_our_router_pid_none_when_process_dead(tmp_path):
    from engines import claudecode
    (tmp_path / "ccr.pid").write_text("999999999")
    with patch("engines.claudecode._SANDBOX_HOME", tmp_path):
        assert claudecode._our_router_pid() is None


def test_our_router_pid_returns_pid_when_alive(tmp_path):
    from engines import claudecode
    (tmp_path / "ccr.pid").write_text(str(os.getpid()))
    with patch("engines.claudecode._SANDBOX_HOME", tmp_path):
        assert claudecode._our_router_pid() == os.getpid()


def test_ccr_binary_prefers_project_local_install(tmp_path):
    from engines import claudecode
    local_bin = tmp_path / "node_modules" / ".bin" / "ccr"
    local_bin.parent.mkdir(parents=True)
    local_bin.write_text("#!/bin/sh\n")
    with patch("engines.claudecode._PROJECT_ROOT", tmp_path):
        assert claudecode._ccr_binary() == str(local_bin)


def test_ccr_binary_falls_back_to_global_path(tmp_path):
    from engines import claudecode
    with patch("engines.claudecode._PROJECT_ROOT", tmp_path), \
         patch("engines.claudecode.shutil.which", return_value="/usr/local/bin/ccr"):
        assert claudecode._ccr_binary() == "/usr/local/bin/ccr"


def test_claudecode_engine_run_isolates_home_for_router_and_claude(tmp_path):
    from engines.claudecode import ClaudeCodeEngine
    with patch("engines.claudecode.subprocess.Popen") as mock_popen, \
         patch("engines.claudecode.subprocess.run") as mock_run, \
         patch("engines.claudecode._wait_for_port"), \
         patch("engines.claudecode._is_port_open", return_value=False), \
         patch("engines.claudecode._write_router_config"), \
         patch("engines.claudecode._SANDBOX_HOME", tmp_path):
        mock_popen.return_value = MagicMock()
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        ClaudeCodeEngine().run(tmp_path, "prompt", _mock_settings())
    router_env = mock_popen.call_args[1]["env"]
    assert router_env["HOME"] == str(tmp_path)
    claude_env = mock_run.call_args_list[0][1]["env"]
    assert claude_env["HOME"] == str(tmp_path)
    assert claude_env["CLAUDE_CONFIG_DIR"] == str(tmp_path / ".claude")


@pytest.mark.skipif(
    __import__("shutil").which("claude") is None,
    reason="claude binary not installed",
)
def test_claude_binary_accepts_help():
    """Integration: verify 'claude --help' exits cleanly."""
    import subprocess
    result = subprocess.run(["claude", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "print" in (result.stdout + result.stderr).lower()


# ── shared persistent router ──────────────────────────────────────────────────

def _reset_router_state(claudecode, tmp_path):
    claudecode._router_proc = None
    return patch("engines.claudecode._SANDBOX_HOME", tmp_path)


def test_claudecode_second_run_reuses_router(tmp_path):
    from engines import claudecode
    from engines.claudecode import ClaudeCodeEngine
    port_open = {"value": False}

    def fake_popen(*args, **kwargs):
        port_open["value"] = True
        return MagicMock(pid=12345)

    with _reset_router_state(claudecode, tmp_path), \
         patch("engines.claudecode.subprocess.Popen", side_effect=fake_popen) as mock_popen, \
         patch("engines.claudecode.subprocess.run") as mock_run, \
         patch("engines.claudecode._wait_for_port"), \
         patch("engines.claudecode._is_port_open", side_effect=lambda h, p: port_open["value"]), \
         patch("engines.claudecode._our_router_pid", return_value=12345), \
         patch("engines.claudecode._write_router_config"):
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        engine = ClaudeCodeEngine()
        engine.run(tmp_path, "first", _mock_settings())
        engine.run(tmp_path, "second", _mock_settings())
    assert mock_popen.call_count == 1


def test_claudecode_run_does_not_terminate_router(tmp_path):
    from engines import claudecode
    from engines.claudecode import ClaudeCodeEngine
    proc = MagicMock(pid=12345)
    with _reset_router_state(claudecode, tmp_path), \
         patch("engines.claudecode.subprocess.Popen", return_value=proc), \
         patch("engines.claudecode.subprocess.run") as mock_run, \
         patch("engines.claudecode._wait_for_port"), \
         patch("engines.claudecode._is_port_open", return_value=False), \
         patch("engines.claudecode._write_router_config"):
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        ClaudeCodeEngine().run(tmp_path, "prompt", _mock_settings())
    proc.terminate.assert_not_called()
    proc.kill.assert_not_called()


def test_shutdown_router_terminates_started_router(tmp_path):
    from engines import claudecode
    proc = MagicMock(pid=12345)
    with patch("engines.claudecode._SANDBOX_HOME", tmp_path):
        claudecode._router_proc = proc
        # pid file is cleanup-only, not ownership evidence: ownership is
        # determined solely by the in-memory `_router_proc` handle.
        (tmp_path / "ccr.pid").write_text("12345")
        claudecode.shutdown_router()
    proc.terminate.assert_called_once()
    assert claudecode._router_proc is None
    assert not (tmp_path / "ccr.pid").exists()


def test_shutdown_router_noop_when_not_started(tmp_path):
    from engines import claudecode
    with patch("engines.claudecode._SANDBOX_HOME", tmp_path):
        claudecode._router_proc = None
        claudecode.shutdown_router()  # must not raise
