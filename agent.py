import logging
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from tempfile import gettempdir
from urllib.parse import urlparse, urlunparse

from config import Settings
from engines.base import AgentEngine

logger = logging.getLogger(__name__)

WORK_DIR = Path(gettempdir()) / "ai-coding-flow"


def cleanup_repo(repo_path: str) -> None:
    try:
        shutil.rmtree(repo_path, ignore_errors=True)
        logger.info("Cleaned up work dir: %s", repo_path)
    except Exception:
        logger.exception("Failed to clean up %s", repo_path)


def cleanup_old_repos(max_age_days: int = 2) -> None:
    """Remove any work directories older than max_age_days. Call on startup."""
    if not WORK_DIR.exists():
        return
    cutoff = time.time() - max_age_days * 86400
    for child in WORK_DIR.iterdir():
        if child.is_dir() and child.stat().st_mtime < cutoff:
            try:
                shutil.rmtree(child)
                logger.info("Evicted stale work dir: %s", child)
            except Exception:
                logger.exception("Failed to evict stale dir: %s", child)


def run_agent(
    issue_number: int,
    issue_title: str,
    issue_body: str,
    branch: str,
    settings: Settings,
    engine: AgentEngine,
    repo_url: str,
    platform: str,
    start_ref: str = "",
) -> tuple[bool, str, str, str]:
    """
    Clone repo, run engine, retry on test failure.
    Returns (success, repo_path, initial_commit, error_msg).
    Synchronous — caller must use asyncio.to_thread.
    """
    repo_path = WORK_DIR / f"{_repo_slug(repo_url)}-{issue_number}"
    _prepare_repo(repo_path, branch, settings, repo_url, platform, start_ref=start_ref)
    _configure_git_user(repo_path)
    _exclude_build_artifacts(repo_path)
    initial_commit = _git_head(repo_path)

    prompt = _build_prompt(issue_title, issue_body)

    if not settings.test_cmd:
        logger.info("Running %s (no test cmd) for issue #%d", engine.name, issue_number)
        engine_output = engine.run(repo_path, prompt, settings)
        head_after = _git_head(repo_path)
        if head_after == initial_commit:
            logger.warning("%s made no commits for issue #%d. Output:\n%s", engine.name, issue_number, engine_output)
        return True, str(repo_path), initial_commit, ""

    error_msg = ""
    for attempt in range(settings.max_retries):
        if attempt > 0:
            prompt = (
                f"The tests are still failing after your last attempt.\n\n"
                f"Test output:\n```\n{error_msg}\n```\n\n"
                f"Please fix the code so all tests pass."
            )
        logger.info("Running %s (attempt %d/%d) for issue #%d", engine.name, attempt + 1, settings.max_retries, issue_number)
        engine.run(repo_path, prompt, settings)
        passed, error_msg = _run_tests(repo_path, settings.test_cmd)
        if passed:
            return True, str(repo_path), initial_commit, ""

    logger.warning("Agent exhausted retries for issue #%d", issue_number)
    return False, str(repo_path), initial_commit, error_msg


def push_branch(
    repo_path: str,
    branch: str,
    settings: Settings,
    repo_url: str,
    platform: str,
    force: bool = False,
) -> None:
    auth_url = _authenticated_url(settings, repo_url, platform)
    subprocess.run(
        ["git", "remote", "set-url", "origin", auth_url],
        cwd=repo_path, check=True, capture_output=True,
    )
    cmd = ["git", "push", "-u", "origin", branch]
    if force:
        cmd.append("--force-with-lease")
    subprocess.run(cmd, cwd=repo_path, check=True, capture_output=True,
                   env={**os.environ, **_git_ssl_env(settings)})


def get_diff(repo_path: str, initial_commit: str) -> str:
    result = subprocess.run(
        ["git", "diff", initial_commit, "HEAD"],
        cwd=repo_path, capture_output=True, text=True,
    )
    return result.stdout[:15000]


def _repo_slug(repo_url: str) -> str:
    path = urlparse(repo_url).path.strip("/").removesuffix(".git")
    return re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")


def _prepare_repo(
    repo_path: Path,
    branch: str,
    settings: Settings,
    repo_url: str,
    platform: str,
    start_ref: str = "",
) -> None:
    auth_url = _authenticated_url(settings, repo_url, platform)
    net_env = {**os.environ, **_git_ssl_env(settings)}
    if (repo_path / ".git").exists():
        subprocess.run(["git", "fetch", "origin"], cwd=repo_path, check=True, capture_output=True,
                       env=net_env)
        if not start_ref:
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
        subprocess.run(["git", "clone", auth_url, str(repo_path)], check=True, capture_output=True,
                       env=net_env)
        if start_ref:
            subprocess.run(["git", "fetch", "origin"], cwd=repo_path, check=True, capture_output=True,
                           env=net_env)
    checkout_cmd = ["git", "checkout", "-B", branch]
    if start_ref:
        checkout_cmd.append(start_ref)
    subprocess.run(checkout_cmd, cwd=repo_path, check=True, capture_output=True)


_BUILD_ARTIFACT_PATTERNS = [
    "__pycache__/",
    "*.py[cod]",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    "node_modules/",
    ".DS_Store",
]


def _exclude_build_artifacts(repo_path: Path) -> None:
    """Add common build/test artifacts to the clone's local git excludes so the
    engines' ``git add -A`` never commits them onto the AI branch.

    Uses ``.git/info/exclude`` (untracked, local to this clone) rather than the
    repo's tracked ``.gitignore``, so the target repo's own files are left
    untouched. Idempotent — patterns already present are not re-added.
    """
    exclude_file = repo_path / ".git" / "info" / "exclude"
    if not exclude_file.parent.exists():
        return
    existing = exclude_file.read_text().splitlines() if exclude_file.exists() else []
    missing = [p for p in _BUILD_ARTIFACT_PATTERNS if p not in existing]
    if not missing:
        return
    with exclude_file.open("a") as f:
        if existing and existing[-1].strip():
            f.write("\n")
        f.write("\n".join(missing) + "\n")


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


def _authenticated_url(settings: Settings, repo_url: str, platform: str) -> str:
    parsed = urlparse(repo_url)
    if platform == "github":
        netloc = f"x-access-token:{settings.github_token}@{parsed.netloc}"
    else:
        netloc = f"oauth2:{settings.gitlab_token}@{parsed.netloc}"
    return urlunparse(parsed._replace(netloc=netloc))


def _git_ssl_env(settings: Settings) -> dict:
    if not settings.verify_repo_ssl:
        return {"GIT_SSL_NO_VERIFY": "true"}
    return {}
