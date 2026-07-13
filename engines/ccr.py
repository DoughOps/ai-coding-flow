import logging
import os
import subprocess
from pathlib import Path

from config import Settings
from engines.base import AgentEngine
from engines.claudecode import _git_commit_all, _write_router_config

logger = logging.getLogger(__name__)


class CCREngine(AgentEngine):
    """Runs Claude Code via `ccr code`, which manages the router's lifecycle itself."""

    @property
    def name(self) -> str:
        return "ccr"

    def run(self, repo_path: Path, prompt: str, settings: Settings) -> str:
        _write_router_config(settings)
        env = {**os.environ, "CLAUDE_CODE_DISABLE_TELEMETRY": "1"}
        if not settings.verify_engine_ssl:
            env["NODE_TLS_REJECT_UNAUTHORIZED"] = "0"
        result = subprocess.run(
            ["ccr", "code", "-p", prompt, "--dangerously-skip-permissions"],
            cwd=str(repo_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=settings.agent_timeout,
        )
        output = (result.stdout + result.stderr).strip()
        logger.info("CCR Code output:\n%s", output)
        _git_commit_all(repo_path)
        return output
