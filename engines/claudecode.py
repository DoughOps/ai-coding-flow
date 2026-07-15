import atexit
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from tempfile import gettempdir

from config import Settings
from engines.base import AgentEngine

logger = logging.getLogger(__name__)

_ROUTER_HOST = "127.0.0.1"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ccr's config and claude's settings/session state are sandboxed here instead of
# the user's real $HOME, so this engine's headless runs never touch — or are
# affected by — the user's own daily ~/.claude / ~/.claude-code-router state.
_SANDBOX_HOME = Path(gettempdir()) / "ai-coding-flow-ccr-home"

_router_lock = threading.Lock()
_router_proc: subprocess.Popen | None = None


def _ensure_router(settings: Settings) -> None:
    """Start the shared ccr router if it isn't running; reuse it otherwise.

    Engine runs execute on worker threads (asyncio.to_thread), so the whole
    check-and-start sequence holds a lock. The router config depends only on
    settings, so one router serves every concurrent job.
    """
    global _router_proc
    with _router_lock:
        _SANDBOX_HOME.mkdir(parents=True, exist_ok=True)
        _write_router_config(settings)
        port = settings.claudecode_router_port

        if _is_port_open(_ROUTER_HOST, port):
            if _our_router_pid() is None:
                raise RuntimeError(
                    f"Port {port} is already in use by a process this engine didn't start "
                    f"(possibly a ccr instance you run yourself). Set CLAUDECODE_ROUTER_PORT "
                    f"to a free port in .env."
                )
            return

        router_env = {**os.environ, "HOME": str(_SANDBOX_HOME), "SERVICE_PORT": str(port)}
        if not settings.verify_engine_ssl:
            router_env["NODE_TLS_REJECT_UNAUTHORIZED"] = "0"
        proc = subprocess.Popen(
            [_ccr_binary(), "start"],
            env=router_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        (_SANDBOX_HOME / "ccr.pid").write_text(str(proc.pid))
        try:
            _wait_for_port(_ROUTER_HOST, port, timeout=settings.claudecode_router_startup_timeout)
        except TimeoutError:
            proc.terminate()
            (_SANDBOX_HOME / "ccr.pid").unlink(missing_ok=True)
            raise
        _router_proc = proc


def shutdown_router() -> None:
    """Terminate the router if this process started it. Idempotent.

    A router inherited from a previous process (alive pid file, port open)
    is deliberately left running — we only own what we spawned."""
    global _router_proc
    with _router_lock:
        proc = _router_proc
        _router_proc = None
        if proc is None:
            return
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        (_SANDBOX_HOME / "ccr.pid").unlink(missing_ok=True)


atexit.register(shutdown_router)


class ClaudeCodeEngine(AgentEngine):
    @property
    def name(self) -> str:
        return "claudecode"

    def run(self, repo_path: Path, prompt: str, settings: Settings) -> str:
        _ensure_router(settings)
        router_url = f"http://{_ROUTER_HOST}:{settings.claudecode_router_port}"
        claude_env = {
            **os.environ,
            "ANTHROPIC_BASE_URL": router_url,
            "ANTHROPIC_AUTH_TOKEN": settings.openai_api_key,
            "CLAUDE_CODE_DISABLE_TELEMETRY": "1",
            "HOME": str(_SANDBOX_HOME),
            "CLAUDE_CONFIG_DIR": str(_SANDBOX_HOME / ".claude"),
        }
        # Claude Code refuses --dangerously-skip-permissions when running as root
        # unless it believes it is already sandboxed. The Docker image runs as
        # root and the container is our isolation boundary, so opt in there.
        if hasattr(os, "getuid") and os.getuid() == 0:
            claude_env["IS_SANDBOX"] = "1"
        result = subprocess.run(
            ["claude", "-p", prompt, "--dangerously-skip-permissions"],
            cwd=str(repo_path),
            env=claude_env,
            capture_output=True,
            text=True,
            timeout=settings.agent_timeout,
        )
        output = (result.stdout + result.stderr).strip()
        logger.info("Claude Code output:\n%s", output)
        _git_commit_all(repo_path)
        return output


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


def _our_router_pid() -> int | None:
    """Returns the PID if a router we ourselves started is still alive.

    Identified via the pid file we write on startup, which lives in the
    sandbox home alongside the single router this engine ever launches.
    """
    pid_file = _SANDBOX_HOME / "ccr.pid"
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        return None
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return None
    return pid


def _wait_for_port(host: str, port: int, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_port_open(host, port):
            return
        time.sleep(0.5)
    raise TimeoutError(f"ccr router did not start on {host}:{port} within {timeout}s")


def _ccr_binary() -> str:
    """Prefer the project-local npm install; fall back to a global 'ccr' on PATH."""
    local_bin = _PROJECT_ROOT / "node_modules" / ".bin" / "ccr"
    if local_bin.exists():
        return str(local_bin)
    return shutil.which("ccr") or "ccr"


def _write_router_config(settings: Settings) -> None:
    config_dir = _SANDBOX_HOME / ".claude-code-router"
    config_dir.mkdir(parents=True, exist_ok=True)

    base = settings.openai_api_base.rstrip("/")
    api_url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    model_id = settings.openai_model
    provider = {
        "name": "custom",
        "api_base_url": api_url,
        "api_key": settings.openai_api_key,
        "models": [model_id],
        # No transformer for generic OpenAI-compatible endpoints: ccr's default
        # Anthropic->OpenAI conversion handles them (matches ccr's own ollama
        # example). The old "Anthropic" transformer passed requests through
        # unconverted, which only suits Anthropic-native endpoints.
    }
    if "openrouter" in api_url:
        # Headless `claude -p` sends thinking:{type:"disabled"}, which ccr
        # converts to reasoning:{enabled:false} — OpenRouter rejects that with
        # 400 for reasoning-mandatory models (e.g. openai/gpt-oss-*). The
        # openrouter transformer's options replace the reasoning object
        # wholesale, and it also maps OpenRouter reasoning deltas back into
        # thinking blocks on the way out.
        provider["transformer"] = {
            "use": [["openrouter", {"reasoning": {"effort": "high", "enabled": True}}]]
        }
    config = {
        "NON_INTERACTIVE_MODE": True,
        "API_TIMEOUT_MS": 600000,
        "Providers": [provider],
        "Router": {
            "default": f"custom,{model_id}",
        },
    }
    (config_dir / "config.json").write_text(json.dumps(config, indent=2))
