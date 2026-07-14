import logging
import os
import subprocess
from pathlib import Path

from config import Settings
from engines.base import AgentEngine

logger = logging.getLogger(__name__)


def _litellm_model(model: str) -> str:
    """aider routes through litellm, which reads the model's first path segment
    as the provider. OPENAI_API_BASE here is always an OpenAI-compatible endpoint
    (OpenRouter, ollama, ...), so the model must be routed via litellm's generic
    'openai/' provider. A bare OpenRouter slug like 'poolside/laguna-m.1:free'
    would otherwise make litellm treat 'poolside' as the provider and fail with
    'LLM Provider NOT provided'. Prefix with 'openai/' unless already present."""
    if model.startswith("openai/"):
        return model
    return f"openai/{model}"


class AiderEngine(AgentEngine):
    @property
    def name(self) -> str:
        return "aider"

    def run(self, repo_path: Path, prompt: str, settings: Settings) -> str:
        cmd = [
            "aider",
            "--model", _litellm_model(settings.openai_model),
            "--yes",
            "--auto-commits",
            "--no-stream",
            "--no-show-model-warnings",
            "--map-tokens", str(settings.aider_map_tokens),
            "--message", prompt,
        ]
        if not settings.verify_engine_ssl:
            cmd.append("--no-verify-ssl")
        result = subprocess.run(
            cmd,
            cwd=str(repo_path),
            env={
                **os.environ,
                "OPENAI_API_BASE": settings.openai_api_base,
                "OPENAI_API_KEY": settings.openai_api_key,
            },
            capture_output=True,
            text=True,
            timeout=settings.agent_timeout,
        )
        output = (result.stdout + result.stderr).strip()
        if settings.aider_verbose:
            logger.info("Aider output:\n%s", output)
        return output
