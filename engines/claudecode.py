import json
import logging
import os
import socket
import subprocess
import time
from pathlib import Path

from config import Settings
from engines.base import AgentEngine

logger = logging.getLogger(__name__)

_ROUTER_PORT = 3456
_ROUTER_HOST = "127.0.0.1"
_ROUTER_URL = f"http://{_ROUTER_HOST}:{_ROUTER_PORT}"


class ClaudeCodeEngine(AgentEngine):
    @property
    def name(self) -> str:
        return "claudecode"

    def run(self, repo_path: Path, prompt: str, settings: Settings) -> str:
        _write_router_config(settings)

        already_running = _is_port_open(_ROUTER_HOST, _ROUTER_PORT)
        router_proc = (
            None
            if already_running
            else subprocess.Popen(
                ["ccr", "start"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        try:
            _wait_for_port(_ROUTER_HOST, _ROUTER_PORT, timeout=15)
            result = subprocess.run(
                ["claude", "-p", prompt, "--dangerously-skip-permissions"],
                cwd=str(repo_path),
                env={
                    **os.environ,
                    "ANTHROPIC_BASE_URL": _ROUTER_URL,
                    "ANTHROPIC_AUTH_TOKEN": settings.openai_api_key,
                    "CLAUDE_CODE_DISABLE_TELEMETRY": "1",
                },
                capture_output=True,
                text=True,
                timeout=600,
            )
            output = (result.stdout + result.stderr).strip()
            logger.info("Claude Code output:\n%s", output)
            _git_commit_all(repo_path)
            return output
        finally:
            if router_proc is not None:
                try:
                    router_proc.terminate()
                except ProcessLookupError:
                    pass
                try:
                    router_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    router_proc.kill()


def _git_commit_all(repo_path: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=str(repo_path), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "ai: apply claude code changes"],
        cwd=str(repo_path),
        capture_output=True,
    )


def _is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _wait_for_port(host: str, port: int, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_port_open(host, port):
            return
        time.sleep(0.5)
    raise TimeoutError(f"ccr router did not start on {host}:{port} within {timeout}s")


def _write_router_config(settings: Settings) -> None:
    config_dir = Path.home() / ".claude-code-router"
    config_dir.mkdir(parents=True, exist_ok=True)

    base = settings.openai_api_base.rstrip("/")
    api_url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    model_id = settings.openai_model
    config = {
        "NON_INTERACTIVE_MODE": True,
        "API_TIMEOUT_MS": 600000,
        "Providers": [
            {
                "name": "custom",
                "api_base_url": api_url,
                "api_key": settings.openai_api_key,
                "models": [model_id],
                "transformer": {"use": ["Anthropic"]},
            }
        ],
        "Router": {
            "default": f"custom,{model_id}",
        },
    }
    (config_dir / "config.json").write_text(json.dumps(config, indent=2))
