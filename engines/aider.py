import logging
import os
import subprocess
from pathlib import Path

from config import Settings
from engines.base import AgentEngine

logger = logging.getLogger(__name__)


class AiderEngine(AgentEngine):
    @property
    def name(self) -> str:
        return "aider"

    def run(self, repo_path: Path, prompt: str, settings: Settings) -> str:
        result = subprocess.run(
            [
                "aider",
                "--model", settings.openai_model,
                "--yes",
                "--auto-commits",
                "--no-stream",
                "--message", prompt,
            ],
            cwd=str(repo_path),
            env={
                **os.environ,
                "OPENAI_API_BASE": settings.openai_api_base,
                "OPENAI_API_KEY": settings.openai_api_key,
            },
            capture_output=True,
            text=True,
            timeout=600,
        )
        output = (result.stdout + result.stderr).strip()
        if settings.aider_verbose:
            logger.info("Aider output:\n%s", output)
        return output
