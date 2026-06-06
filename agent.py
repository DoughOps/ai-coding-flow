import logging
import os
import shlex
import subprocess
import sys
from pathlib import Path
from tempfile import gettempdir
from urllib.parse import urlparse, urlunparse

from config import Settings

logger = logging.getLogger(__name__)

WORK_DIR = Path(gettempdir()) / "ai-coding-flow"


def run_agent(
    issue_number: int,
    issue_title: str,
    issue_body: str,
    branch: str,
    settings: Settings,
) -> tuple[bool, str, str, str]:
    """
    Clone repo, run Aider, retry on test failure.
    Returns (success, repo_path, initial_commit, error_msg).
    Synchronous — caller must use asyncio.to_thread.
    """
    repo_path = WORK_DIR / str(issue_number)
    _prepare_repo(repo_path, branch, settings)
    _configure_git_user(repo_path)
    initial_commit = _git_head(repo_path)

    error_msg = ""
    for attempt in range(settings.max_retries):
        if attempt == 0:
            prompt = _build_prompt(issue_title, issue_body)
        else:
            prompt = (
                f"The tests are still failing after your last attempt.\n\n"
                f"Test output:\n```\n{error_msg}\n```\n\n"
                f"Please fix the code so all tests pass."
            )
        logger.info("Running Aider (attempt %d/%d) for issue #%d", attempt + 1, settings.max_retries, issue_number)
        _run_aider(repo_path, prompt, settings)
        passed, error_msg = _run_tests(repo_path, settings.test_cmd)
        if passed:
            return True, str(repo_path), initial_commit, ""

    logger.warning("Agent exhausted retries for issue #%d", issue_number)
    return False, str(repo_path), initial_commit, error_msg


def push_branch(repo_path: str, branch: str, settings: Settings) -> None:
    auth_url = _authenticated_url(settings)
    subprocess.run(
        ["git", "remote", "set-url", "origin", auth_url],
        cwd=repo_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", branch],
        cwd=repo_path, check=True, capture_output=True,
    )


def get_diff(repo_path: str, initial_commit: str) -> str:
    result = subprocess.run(
        ["git", "diff", initial_commit, "HEAD"],
        cwd=repo_path, capture_output=True, text=True,
    )
    return result.stdout[:15000]


def _prepare_repo(repo_path: Path, branch: str, settings: Settings) -> None:
    auth_url = _authenticated_url(settings)
    if (repo_path / ".git").exists():
        subprocess.run(["git", "fetch", "origin"], cwd=repo_path, check=True, capture_output=True)
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=repo_path, capture_output=True, text=True,
        )
        default = result.stdout.strip().split("/")[-1] if result.returncode == 0 else "main"
        subprocess.run(["git", "checkout", default], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "reset", "--hard", f"origin/{default}"],
            cwd=repo_path, check=True, capture_output=True,
        )
    else:
        repo_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", auth_url, str(repo_path)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", branch], cwd=repo_path, check=True, capture_output=True)


def _configure_git_user(repo_path: Path) -> None:
    subprocess.run(
        ["git", "config", "user.email", "ai-coding-flow@localhost"],
        cwd=repo_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "AI Coding Flow"],
        cwd=repo_path, check=True, capture_output=True,
    )


def _git_head(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _build_prompt(title: str, body: str) -> str:
    return (
        f"Resolve the following issue in this Python repository.\n\n"
        f"Issue title: {title}\n\n"
        f"Issue description:\n{body}\n\n"
        f"Instructions:\n"
        f"1. Understand what the issue requires.\n"
        f"2. Write the necessary code changes.\n"
        f"3. Write or update tests that verify the fix.\n"
        f"4. Make sure all tests pass before finishing."
    )


def _run_aider(repo_path: Path, prompt: str, settings: Settings) -> None:
    subprocess.run(
        [
            sys.executable, "-m", "aider",
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


_PY_COMPAT_SHIM = '''\
import pathlib
import py.path
_orig_local_init = py.path.local.__init__
def _patched_local_init(self, path=None, expanduser=False):
    if isinstance(path, pathlib.Path):
        path = str(path)
    _orig_local_init(self, path=path, expanduser=expanduser)
py.path.local.__init__ = _patched_local_init
'''


def _ensure_py_compat(repo_path: Path) -> None:
    """Prepend py.path.local shim to conftest.py so pytest 8 + py 1.4 don't crash."""
    conf = repo_path / "conftest.py"
    if conf.exists():
        content = conf.read_text()
        if "py.path.local.__init__" not in content:
            conf.write_text(_PY_COMPAT_SHIM + "\n" + content)
    else:
        conf.write_text(_PY_COMPAT_SHIM)


def _run_tests(repo_path: Path, test_cmd: str) -> tuple[bool, str]:
    _ensure_py_compat(repo_path)
    result = subprocess.run(
        shlex.split(test_cmd),
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = (result.stdout + result.stderr)[-3000:]
    return result.returncode == 0, output


def _authenticated_url(settings: Settings) -> str:
    parsed = urlparse(settings.repo_url)
    if settings.platform == "github":
        netloc = f"x-access-token:{settings.github_token}@{parsed.netloc}"
    else:
        netloc = f"oauth2:{settings.gitlab_token}@{parsed.netloc}"
    return urlunparse(parsed._replace(netloc=netloc))
