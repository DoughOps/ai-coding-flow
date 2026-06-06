import json
import logging
import os
import subprocess
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
        result = subprocess.run(
            [
                "opencode",
                "run",
                "--model", model,
                "--dangerously-skip-permissions",
                prompt,
            ],
            cwd=str(repo_path),
            env={
                **os.environ,
                "OPENAI_API_KEY": settings.openai_api_key,
            },
            capture_output=True,
            text=True,
            timeout=600,
        )
        output = (result.stdout + result.stderr).strip()
        logger.info("OpenCode output:\n%s", output)
        return output


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
                        "limit": {"context": 32768, "output": 4096},
                        "cost": {"input": 0, "output": 0},
                    }
                },
            }
        },
    }
    (config_dir / "opencode.jsonc").write_text(json.dumps(config, indent=2))
