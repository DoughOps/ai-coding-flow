import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from config import Settings
from engines.base import AgentEngine

logger = logging.getLogger(__name__)

_PROVIDER_ID = "custom"


class OpenCodeEngine(AgentEngine):
    @property
    def name(self) -> str:
        return "opencode"

    def run(self, repo_path: Path, prompt: str, settings: Settings) -> str:
        _write_opencode_config(settings)
        model = f"{_PROVIDER_ID}/{settings.openai_model}"
        env = {**os.environ, "OPENAI_API_KEY": settings.openai_api_key}
        if not settings.verify_engine_ssl:
            env["NODE_TLS_REJECT_UNAUTHORIZED"] = "0"
        result = subprocess.run(
            [
                "opencode",
                "run",
                "--model", model,
                "--dir", str(repo_path),
                "--dangerously-skip-permissions",
                prompt,
            ],
            cwd=str(repo_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=settings.agent_timeout,
        )
        output = (result.stdout + result.stderr).strip()
        logger.info("OpenCode output:\n%s", output)
        _git_commit_all(repo_path)
        return output


def _git_commit_all(repo_path: Path) -> None:
    """Stage and commit any changes opencode left uncommitted. No-op if tree is clean."""
    subprocess.run(["git", "add", "-A"], cwd=str(repo_path), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "ai: apply opencode changes"],
        cwd=str(repo_path), capture_output=True,
    )


def _write_opencode_config(settings: Settings) -> None:
    """Write ~/.config/opencode/opencode.jsonc with a custom OpenAI-compatible provider."""
    config_dir = Path.home() / ".config" / "opencode"
    config_dir.mkdir(parents=True, exist_ok=True)
    model_id = settings.openai_model
    config = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            _PROVIDER_ID: {
                "name": "Custom",
                "id": _PROVIDER_ID,
                "npm": "@ai-sdk/openai-compatible",
                "api": settings.openai_api_base,
                "env": ["OPENAI_API_KEY"],
                "options": {
                    "baseURL": settings.openai_api_base,
                },
                "models": {
                    model_id: {
                        "id": model_id,
                        "name": model_id,
                        "attachment": False,
                        "reasoning": False,
                        "temperature": True,
                        "tool_call": True,
                        "limit": {"context": settings.opencode_context_limit, "output": settings.opencode_output_limit},
                        "cost": {"input": 0, "output": 0},
                    }
                },
            }
        },
    }
    config_path = config_dir / "opencode.jsonc"
    fd, tmp_path = tempfile.mkstemp(dir=str(config_dir), prefix=".opencode.jsonc.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(config, indent=2))
        os.replace(tmp_path, config_path)
    except BaseException:
        os.unlink(tmp_path)
        raise
