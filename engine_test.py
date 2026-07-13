import logging
import shutil
import subprocess
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from tempfile import gettempdir

from config import Settings
from engines.base import AgentEngine

logger = logging.getLogger(__name__)

TEST_WORK_DIR = Path(gettempdir()) / "ai-coding-flow-selftest"

TEST_PROMPT = (
    "Create a file called greeter.py with a function greet(name) that "
    "returns the string f'Hello, {name}!'. Also add a test for it."
)

_MAX_RUNS = 20
_runs: "OrderedDict[str, dict]" = OrderedDict()


def start_test_run(engine: AgentEngine, settings: Settings) -> str:
    run_id = uuid.uuid4().hex[:12]
    _runs[run_id] = {
        "id": run_id,
        "engine": engine.name,
        "status": "running",
        "diff": "",
        "output": "",
        "error": "",
        "duration_seconds": None,
        "created_at": time.time(),
    }
    while len(_runs) > _MAX_RUNS:
        _runs.popitem(last=False)
    return run_id


def get_test_run(run_id: str) -> dict | None:
    return _runs.get(run_id)


def run_smoke_test(run_id: str, engine: AgentEngine, settings: Settings) -> None:
    """Blocking — caller must invoke via asyncio.to_thread."""
    run = _runs[run_id]
    repo_path = TEST_WORK_DIR / run_id
    start = time.monotonic()
    try:
        _init_local_repo(repo_path)
        initial_commit = _git_head(repo_path)
        output = engine.run(repo_path, TEST_PROMPT, settings)
        run["output"] = output
        head_after = _git_head(repo_path)
        if head_after == initial_commit:
            run["status"] = "no_changes"
        else:
            run["diff"] = _git_diff(repo_path, initial_commit)
            run["status"] = "done"
    except Exception as exc:
        logger.exception("Engine self-test failed for run %s", run_id)
        run["status"] = "failed"
        run["error"] = str(exc)
    finally:
        run["duration_seconds"] = round(time.monotonic() - start, 1)
        shutil.rmtree(repo_path, ignore_errors=True)


def _init_local_repo(repo_path: Path) -> None:
    repo_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "ai-coding-flow@localhost"],
        cwd=repo_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "AI Coding Flow"],
        cwd=repo_path, check=True, capture_output=True,
    )
    (repo_path / "README.md").write_text("# Self-test scratch repo\n")
    subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=repo_path, check=True, capture_output=True,
    )


def _git_head(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _git_diff(repo_path: Path, initial_commit: str) -> str:
    result = subprocess.run(
        ["git", "diff", initial_commit, "HEAD"],
        cwd=repo_path, capture_output=True, text=True,
    )
    return result.stdout[:15000]
