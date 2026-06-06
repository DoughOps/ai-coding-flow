import logging
import os
import subprocess
from pathlib import Path

from config import Settings
from engines.base import AgentEngine

logger = logging.getLogger(__name__)


class OpenCodeEngine(AgentEngine):
    @property
    def name(self) -> str:
        return "opencode"

    def run(self, repo_path: Path, prompt: str, settings: Settings) -> str:
        result = subprocess.run(
            [
                "opencode",
                "run",
                "--model", settings.openai_model,
                prompt,
            ],
            cwd=str(repo_path),
            env={
                **os.environ,
                # OpenCode uses OPENAI_BASE_URL; Aider uses OPENAI_API_BASE
                "OPENAI_BASE_URL": settings.openai_api_base,
                "OPENAI_API_KEY": settings.openai_api_key,
            },
            capture_output=True,
            text=True,
            timeout=600,
        )
        output = (result.stdout + result.stderr).strip()
        logger.info("OpenCode output:\n%s", output)
        return output
