# PR Feedback Loop & Jobs Admin UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/rework` command on AI-generated PRs that re-runs the agent with reviewer feedback, and a `/jobs` admin page backed by SQLite that shows all job history with status, engine, and PR links.

**Architecture:** A new `store.py` module owns all SQLite interaction (job CRUD). The worker writes to it at every state transition. The server reads from it for `/api/jobs`. PR comment webhooks parse the issue number from the branch name (`ai/issue-{N}-{slug}`) to avoid any DB lookup. Rework jobs reuse `run_agent` with a `start_ref` param to start from the existing AI branch instead of the repo default.

**Tech Stack:** Python `sqlite3` stdlib (no new deps), FastAPI (existing), Vanilla JS with `sessionStorage` for token persistence.

---

## File Map

| File | Change |
|---|---|
| `store.py` | **New** — SQLite job store (init, create, update, list) |
| `config.py` | Add `admin_password` and `db_path` fields |
| `agent.py` | Add `start_ref` param to `run_agent`/`_prepare_repo`; add `force` param to `push_branch` |
| `worker.py` | Add `_settings_ref`, update `Job` dataclass, add `_process_rework_job`, `_build_rework_body`, store writes |
| `server.py` | Add `/api/jobs`, PR comment handlers, `_parse_issue_number_from_branch`, `_get_github_pr_branch` |
| `docs_site/jobs.html` | **New** — admin UI with password prompt, job table, auto-refresh |
| `docs_site/index.html` | Add "Jobs" nav link |
| `tests/test_store.py` | **New** — store unit tests |
| `tests/test_agent.py` | Add `test_push_branch_force_flag`, `test_run_agent_accepts_start_ref` |
| `tests/test_worker.py` | Add `test_build_rework_body_*`, `test_process_rework_job_*` |
| `tests/test_server.py` | Add rework webhook tests and `/api/jobs` auth tests |

---

### Task 1: SQLite job store (`store.py`)

**Files:**
- Create: `store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_store.py
import pytest
import store


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    store.init_db(path)
    return path


def test_create_job_returns_id(db):
    job_id = store.create_job(db, platform="github", issue_number=1, issue_title="Fix bug")
    assert job_id == 1


def test_create_job_status_is_queued(db):
    store.create_job(db, platform="github", issue_number=1, issue_title="Fix bug")
    jobs = store.list_jobs(db)
    assert jobs[0]["status"] == "queued"


def test_update_job_status_and_engine(db):
    job_id = store.create_job(db, platform="github", issue_number=1, issue_title="Fix bug")
    store.update_job(db, job_id, status="processing", engine="aider")
    jobs = store.list_jobs(db)
    assert jobs[0]["status"] == "processing"
    assert jobs[0]["engine"] == "aider"


def test_list_jobs_newest_first(db):
    store.create_job(db, platform="github", issue_number=1, issue_title="First")
    store.create_job(db, platform="github", issue_number=2, issue_title="Second")
    jobs = store.list_jobs(db)
    assert jobs[0]["issue_title"] == "Second"
    assert jobs[1]["issue_title"] == "First"


def test_list_jobs_respects_limit(db):
    for i in range(5):
        store.create_job(db, platform="github", issue_number=i, issue_title=f"Issue {i}")
    jobs = store.list_jobs(db, limit=3)
    assert len(jobs) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_store.py -v
```

Expected: `ModuleNotFoundError: No module named 'store'`

- [ ] **Step 3: Implement `store.py`**

```python
# store.py
import sqlite3
from datetime import datetime, timezone


def init_db(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                platform     TEXT NOT NULL,
                issue_number INTEGER NOT NULL,
                issue_title  TEXT NOT NULL,
                engine       TEXT NOT NULL DEFAULT '',
                status       TEXT NOT NULL DEFAULT 'queued',
                pr_url       TEXT NOT NULL DEFAULT '',
                error_msg    TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
        """)


def create_job(db_path: str, *, platform: str, issue_number: int, issue_title: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        cur = conn.execute(
            "INSERT INTO jobs (platform, issue_number, issue_title, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (platform, issue_number, issue_title, now, now),
        )
        return cur.lastrowid


def update_job(db_path: str, job_id: int, **fields) -> None:
    allowed = {"status", "engine", "pr_url", "error_msg"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    now = datetime.now(timezone.utc).isoformat()
    updates["updated_at"] = now
    cols = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [job_id]
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", values)


def list_jobs(db_path: str, limit: int = 100) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_store.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add store.py tests/test_store.py
git commit -m "feat: add SQLite job store"
```

---

### Task 2: Config fields (`config.py`)

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_config.py`:

```python
def test_admin_password_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("PLATFORM", "github")
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.setenv("WEBHOOK_SECRET", "s")
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost/v1")
    from importlib import reload
    import config
    reload(config)
    s = config.Settings()
    assert s.admin_password == ""


def test_db_path_defaults_to_ai_jobs_db(monkeypatch):
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.setenv("PLATFORM", "github")
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.setenv("WEBHOOK_SECRET", "s")
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost/v1")
    from importlib import reload
    import config
    reload(config)
    s = config.Settings()
    assert s.db_path.endswith("ai_jobs.db")
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_config.py::test_admin_password_defaults_to_empty tests/test_config.py::test_db_path_defaults_to_ai_jobs_db -v
```

Expected: AttributeError or ValidationError

- [ ] **Step 3: Update `config.py`**

Replace the entire file:

```python
from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    platform: Literal["github", "gitlab"]
    repo_url: str
    github_token: str = ""
    gitlab_token: str = ""
    webhook_secret: str
    openai_api_base: str
    openai_api_key: str = "local"
    openai_model: str = "qwen2.5-coder:32b"
    max_retries: int = 3
    test_cmd: str = ""  # empty = skip testing entirely
    aider_verbose: bool = False  # set true to log all Aider output
    default_agent: str = "aider"
    admin_password: str = ""
    db_path: str = str(Path(__file__).parent / "ai_jobs.db")

    model_config = {"env_file": ".env"}
```

- [ ] **Step 4: Run all tests to verify nothing broke**

```
pytest -v
```

Expected: all existing tests still pass, 2 new tests pass

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add admin_password and db_path config fields"
```

---

### Task 3: `agent.py` — `start_ref` and `force` params

**Files:**
- Modify: `agent.py`
- Test: `tests/test_agent.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_agent.py`:

```python
def test_push_branch_includes_force_with_lease_when_force_true():
    from unittest.mock import patch
    from agent import push_branch

    settings = MagicMock()
    settings.platform = "github"
    settings.github_token = "tok"
    settings.repo_url = "https://github.com/owner/repo"

    with patch("agent.subprocess.run") as mock_run:
        push_branch("/repo", "ai/issue-1-test", settings, force=True)

    push_cmd = mock_run.call_args_list[1][0][0]
    assert "--force-with-lease" in push_cmd


def test_push_branch_no_force_flag_by_default():
    from unittest.mock import patch
    from agent import push_branch

    settings = MagicMock()
    settings.platform = "github"
    settings.github_token = "tok"
    settings.repo_url = "https://github.com/owner/repo"

    with patch("agent.subprocess.run") as mock_run:
        push_branch("/repo", "ai/issue-1-test", settings)

    push_cmd = mock_run.call_args_list[1][0][0]
    assert "--force-with-lease" not in push_cmd


def test_run_agent_accepts_start_ref():
    from unittest.mock import MagicMock, patch
    from agent import run_agent

    mock_engine = MagicMock()
    mock_engine.run.return_value = "output"

    settings = MagicMock()
    settings.test_cmd = ""
    settings.max_retries = 3
    settings.repo_url = "https://github.com/owner/repo"
    settings.platform = "github"
    settings.github_token = "ghp_test"

    captured = {}

    def fake_prepare(repo_path, branch, settings, start_ref=""):
        captured["start_ref"] = start_ref

    with patch("agent._prepare_repo", side_effect=fake_prepare), \
         patch("agent._configure_git_user"), \
         patch("agent._git_head", return_value="abc123"):
        run_agent(
            issue_number=1,
            issue_title="Test",
            issue_body="Body",
            branch="ai/issue-1-test",
            settings=settings,
            engine=mock_engine,
            start_ref="origin/ai/issue-1-test",
        )

    assert captured["start_ref"] == "origin/ai/issue-1-test"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_agent.py::test_push_branch_includes_force_with_lease_when_force_true tests/test_agent.py::test_push_branch_no_force_flag_by_default tests/test_agent.py::test_run_agent_accepts_start_ref -v
```

Expected: TypeError (unexpected keyword argument) or assertion failures

- [ ] **Step 3: Update `agent.py`**

Change `push_branch` (lines 62–71):

```python
def push_branch(repo_path: str, branch: str, settings: Settings, force: bool = False) -> None:
    auth_url = _authenticated_url(settings)
    subprocess.run(
        ["git", "remote", "set-url", "origin", auth_url],
        cwd=repo_path, check=True, capture_output=True,
    )
    cmd = ["git", "push", "-u", "origin", branch]
    if force:
        cmd.append("--force-with-lease")
    subprocess.run(cmd, cwd=repo_path, check=True, capture_output=True)
```

Change `run_agent` signature (lines 16–23) to add `start_ref`:

```python
def run_agent(
    issue_number: int,
    issue_title: str,
    issue_body: str,
    branch: str,
    settings: Settings,
    engine: AgentEngine,
    start_ref: str = "",
) -> tuple[bool, str, str, str]:
    """
    Clone repo, run engine, retry on test failure.
    Returns (success, repo_path, initial_commit, error_msg).
    Synchronous — caller must use asyncio.to_thread.
    """
    repo_path = WORK_DIR / str(issue_number)
    _prepare_repo(repo_path, branch, settings, start_ref=start_ref)
```

Change `_prepare_repo` (lines 82–99) to accept and use `start_ref`:

```python
def _prepare_repo(repo_path: Path, branch: str, settings: Settings, start_ref: str = "") -> None:
    auth_url = _authenticated_url(settings)
    if (repo_path / ".git").exists():
        subprocess.run(["git", "fetch", "origin"], cwd=repo_path, check=True, capture_output=True)
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
        subprocess.run(["git", "clone", auth_url, str(repo_path)], check=True, capture_output=True)
        if start_ref:
            subprocess.run(["git", "fetch", "origin"], cwd=repo_path, check=True, capture_output=True)
    checkout_cmd = ["git", "checkout", "-B", branch]
    if start_ref:
        checkout_cmd.append(start_ref)
    subprocess.run(checkout_cmd, cwd=repo_path, check=True, capture_output=True)
```

Also update the `run_agent` call site inside the function body — line 30 already calls `_prepare_repo(repo_path, branch, settings)`. After the signature change this becomes `_prepare_repo(repo_path, branch, settings, start_ref=start_ref)` as shown above.

- [ ] **Step 4: Run all tests to verify they pass**

```
pytest -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add agent.py tests/test_agent.py
git commit -m "feat: add start_ref and force params to agent run/push"
```

---

### Task 4: Worker store integration + rework job (`worker.py`)

**Files:**
- Modify: `worker.py`
- Test: `tests/test_worker.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_worker.py`:

```python
def test_build_rework_body_contains_original_and_feedback():
    from worker import _build_rework_body
    result = _build_rework_body("Original issue body", "/rework please add error handling")
    assert "Original issue body" in result
    assert "please add error handling" in result
    assert "Reviewer feedback" in result


def test_build_rework_body_separator_present():
    from worker import _build_rework_body
    result = _build_rework_body("Body", "/rework fix it")
    assert "---" in result


import asyncio
from unittest.mock import AsyncMock, patch

def test_process_rework_job_posts_completion_comment():
    from worker import Job, _process_rework_job

    job = Job(
        platform="github",
        issue_number=42,
        title="Fix bug",
        body="There is a bug",
        job_id=0,
        pr_branch="ai/issue-42-fix-bug",
        rework_comment="/rework add error handling",
    )

    settings = MagicMock()
    settings.db_path = ":memory:"
    settings.max_retries = 3
    settings.test_cmd = ""
    settings.default_agent = "aider"

    mock_platform = MagicMock()
    mock_issue = MagicMock()
    mock_issue.title = "Fix bug"
    mock_issue.body = "There is a bug"
    mock_platform.get_issue.return_value = mock_issue
    mock_platform.get_labels.return_value = []

    with patch("worker.create_platform", return_value=mock_platform), \
         patch("worker.store.update_job"), \
         patch("worker.run_agent", return_value=(True, "/tmp/repo", "abc", "")), \
         patch("worker.push_branch"):
        asyncio.run(_process_rework_job(job, settings))

    mock_platform.post_comment.assert_called_once()
    comment_text = mock_platform.post_comment.call_args[0][1]
    assert "updated" in comment_text.lower()


def test_process_rework_job_posts_failure_comment_on_error():
    from worker import Job, _process_rework_job

    job = Job(
        platform="github",
        issue_number=42,
        title="Fix bug",
        body="Body",
        job_id=0,
        pr_branch="ai/issue-42-fix-bug",
        rework_comment="/rework fix it",
    )

    settings = MagicMock()
    settings.db_path = ":memory:"
    settings.max_retries = 3
    settings.test_cmd = ""
    settings.default_agent = "aider"

    mock_platform = MagicMock()
    mock_issue = MagicMock()
    mock_issue.title = "Fix bug"
    mock_issue.body = "Body"
    mock_platform.get_issue.return_value = mock_issue
    mock_platform.get_labels.return_value = []

    with patch("worker.create_platform", return_value=mock_platform), \
         patch("worker.store.update_job"), \
         patch("worker.run_agent", return_value=(False, "/tmp/repo", "abc", "tests failed")):
        asyncio.run(_process_rework_job(job, settings))

    mock_platform.post_comment.assert_called_once()
    comment_text = mock_platform.post_comment.call_args[0][1]
    assert "tests failed" in comment_text
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_worker.py::test_build_rework_body_contains_original_and_feedback tests/test_worker.py::test_process_rework_job_posts_completion_comment tests/test_worker.py::test_process_rework_job_posts_failure_comment_on_error -v
```

Expected: ImportError (`_build_rework_body`) or AttributeError

- [ ] **Step 3: Replace `worker.py` with the updated version**

```python
# worker.py
import asyncio
import logging
import re
from dataclasses import dataclass

import store
from config import Settings
from agent import run_agent, push_branch, get_diff
from reviewer import run_review
from platforms import create_platform
from engines import get_engine
from engines.base import AgentEngine

logger = logging.getLogger(__name__)

_settings_ref: Settings | None = None


@dataclass
class Job:
    platform: str
    issue_number: int
    title: str
    body: str
    job_id: int = 0
    pr_branch: str = ""
    rework_comment: str = ""


_queue: asyncio.Queue = asyncio.Queue()


async def enqueue_job(
    *,
    platform: str,
    issue_number: int,
    title: str,
    body: str,
    pr_branch: str = "",
    rework_comment: str = "",
) -> None:
    job_id = 0
    if _settings_ref:
        job_id = store.create_job(
            _settings_ref.db_path,
            platform=platform,
            issue_number=issue_number,
            issue_title=title,
        )
    await _queue.put(Job(
        platform=platform,
        issue_number=issue_number,
        title=title,
        body=body,
        job_id=job_id,
        pr_branch=pr_branch,
        rework_comment=rework_comment,
    ))
    logger.info("Enqueued issue #%d (%s)", issue_number, platform)


async def start_worker(settings: Settings) -> None:
    global _settings_ref
    _settings_ref = settings
    logger.info("Worker started")
    while True:
        job = await _queue.get()
        try:
            if job.rework_comment:
                await _process_rework_job(job, settings)
            else:
                await _process_job(job, settings)
        except Exception as exc:
            logger.exception("Unhandled error for issue #%d", job.issue_number)
            try:
                platform = create_platform(settings)
                platform.remove_label(job.issue_number, _LABEL_PROCESSING)
                platform.set_label(job.issue_number, _LABEL_FAILED)
                platform.post_comment(
                    job.issue_number,
                    f"AI workflow encountered an unexpected error: {exc}",
                )
            except Exception:
                logger.exception("Failed to post error comment for issue #%d", job.issue_number)
        finally:
            _queue.task_done()


_LABEL_PROCESSING = "ai: processing"
_LABEL_DONE = "ai: done"
_LABEL_FAILED = "ai: failed"
_LABEL_NEEDS_CLARIFICATION = "ai: needs clarification"


def _swap_label(platform, issue_number: int, remove: str, add: str) -> None:
    try:
        platform.remove_label(issue_number, remove)
        platform.set_label(issue_number, add)
    except Exception:
        logger.exception("Failed to update labels on issue #%d", issue_number)


def _pick_engine(labels: list[str], settings: Settings) -> AgentEngine:
    for label in labels:
        if label.startswith("agent: "):
            engine_name = label[len("agent: "):]
            return get_engine(engine_name)
    return get_engine(settings.default_agent)


def _build_rework_body(original_body: str, rework_comment: str) -> str:
    return (
        f"{original_body}\n\n"
        f"---\n"
        f"**Reviewer feedback (please address):**\n\n"
        f"{rework_comment}"
    )


async def _process_job(job: Job, settings: Settings) -> None:
    platform = create_platform(settings)
    branch = f"ai/issue-{job.issue_number}-{_slugify(job.title)}"
    logger.info("Processing issue #%d on branch %s", job.issue_number, branch)

    labels = platform.get_labels(job.issue_number)
    engine = _pick_engine(labels, settings)
    logger.info("Using engine %r for issue #%d", engine.name, job.issue_number)

    platform.set_label(job.issue_number, _LABEL_PROCESSING)
    if job.job_id:
        store.update_job(settings.db_path, job.job_id, status="processing", engine=engine.name)

    success, repo_path, initial_commit, error_msg = await asyncio.to_thread(
        run_agent,
        issue_number=job.issue_number,
        issue_title=job.title,
        issue_body=job.body,
        branch=branch,
        settings=settings,
        engine=engine,
    )

    if not success:
        _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_FAILED)
        if job.job_id:
            store.update_job(settings.db_path, job.job_id, status="failed", error_msg=error_msg)
        platform.post_comment(
            job.issue_number,
            f"AI could not produce passing tests after {settings.max_retries} attempts.\n\n"
            f"Last test output:\n```\n{error_msg}\n```",
        )
        return

    diff = get_diff(repo_path, initial_commit)
    if not diff.strip():
        _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_NEEDS_CLARIFICATION)
        if job.job_id:
            store.update_job(settings.db_path, job.job_id, status="needs_clarification")
        platform.post_comment(
            job.issue_number,
            "AI made no code changes. Please add more detail or a concrete example to the issue description.",
        )
        return

    await asyncio.to_thread(push_branch, repo_path, branch, settings)

    pr_title = f"fix: {job.title} (resolves #{job.issue_number})"
    pr_body = (
        f"Closes #{job.issue_number}\n\n"
        f"This PR was automatically generated by the AI coding workflow."
    )
    pr_url = platform.create_pr(branch, pr_title, pr_body)
    logger.info("Created PR/MR: %s", pr_url)
    if job.job_id:
        store.update_job(settings.db_path, job.job_id, pr_url=pr_url)

    review_comment = await asyncio.to_thread(
        run_review,
        issue_title=job.title,
        issue_body=job.body,
        diff=diff,
        settings=settings,
    )

    _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_DONE)
    if job.job_id:
        store.update_job(settings.db_path, job.job_id, status="done")
    platform.post_comment(
        job.issue_number,
        f"PR: {pr_url}\n\n**Review:**\n\n{review_comment}",
    )
    logger.info("Posted review comment for issue #%d", job.issue_number)


async def _process_rework_job(job: Job, settings: Settings) -> None:
    platform = create_platform(settings)
    if job.job_id:
        store.update_job(settings.db_path, job.job_id, status="reworking")
    platform.set_label(job.issue_number, _LABEL_PROCESSING)

    issue = platform.get_issue(job.issue_number)
    labels = platform.get_labels(job.issue_number)
    engine = _pick_engine(labels, settings)

    success, repo_path_str, _initial_commit, error_msg = await asyncio.to_thread(
        run_agent,
        issue_number=job.issue_number,
        issue_title=issue.title,
        issue_body=_build_rework_body(issue.body, job.rework_comment),
        branch=job.pr_branch,
        settings=settings,
        engine=engine,
        start_ref=f"origin/{job.pr_branch}",
    )

    if not success:
        _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_FAILED)
        if job.job_id:
            store.update_job(settings.db_path, job.job_id, status="failed", error_msg=error_msg)
        platform.post_comment(
            job.issue_number,
            f"Re-run could not produce passing tests.\n\n```\n{error_msg}\n```",
        )
        return

    await asyncio.to_thread(push_branch, repo_path_str, job.pr_branch, settings, force=True)
    _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_DONE)
    if job.job_id:
        store.update_job(settings.db_path, job.job_id, status="done")
    platform.post_comment(
        job.issue_number,
        f"Re-run complete. Branch `{job.pr_branch}` updated.",
    )
    logger.info("Rework complete for issue #%d", job.issue_number)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:50]
```

- [ ] **Step 4: Run all tests to verify they pass**

```
pytest -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add worker.py tests/test_worker.py
git commit -m "feat: integrate job store and add rework job processing"
```

---

### Task 5: Server — `/api/jobs` and PR comment webhooks (`server.py`)

**Files:**
- Modify: `server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_server.py`:

```python
GITHUB_REWORK_COMMENT = {
    "action": "created",
    "sender": {"type": "User"},
    "comment": {"body": "/rework please add error handling"},
    "issue": {
        "number": 42,
        "title": "Fix bug",
        "body": "There is a bug",
        "pull_request": {"url": "https://api.github.com/repos/owner/repo/pulls/10"},
    },
}

GITHUB_BOT_REWORK_COMMENT = {
    "action": "created",
    "sender": {"type": "Bot"},
    "comment": {"body": "/rework please add error handling"},
    "issue": {
        "number": 42,
        "title": "Fix bug",
        "body": "There is a bug",
        "pull_request": {"url": "https://api.github.com/repos/owner/repo/pulls/10"},
    },
}

GITLAB_REWORK_NOTE = {
    "object_kind": "note",
    "object_attributes": {
        "noteable_type": "MergeRequest",
        "note": "/rework please add error handling",
    },
    "merge_request": {
        "title": "fix: Fix bug",
        "description": "There is a bug",
        "source_branch": "ai/issue-42-fix-bug",
    },
}


def test_github_rework_comment_queues_rework_job(client):
    body = json.dumps(GITHUB_REWORK_COMMENT).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue, \
         patch("server._get_github_pr_branch", return_value="ai/issue-42-fix-bug"):
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()
    kwargs = mock_enqueue.call_args.kwargs
    assert kwargs["pr_branch"] == "ai/issue-42-fix-bug"
    assert "/rework" in kwargs["rework_comment"]


def test_github_bot_rework_comment_is_ignored(client):
    body = json.dumps(GITHUB_BOT_REWORK_COMMENT).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    mock_enqueue.assert_not_called()


def test_gitlab_rework_note_queues_rework_job(client):
    body = json.dumps(GITLAB_REWORK_NOTE).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/gitlab",
            content=body,
            headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()
    kwargs = mock_enqueue.call_args.kwargs
    assert kwargs["pr_branch"] == "ai/issue-42-fix-bug"
    assert "/rework" in kwargs["rework_comment"]


def test_api_jobs_open_when_no_password(client):
    with patch("server.store.list_jobs", return_value=[]):
        resp = client.get("/api/jobs")
    assert resp.status_code == 200


def test_api_jobs_wrong_token_returns_401(monkeypatch):
    monkeypatch.setenv("PLATFORM", "github")
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret123")
    import importlib
    import server
    importlib.reload(server)
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    with patch("server.store.list_jobs", return_value=[]):
        resp = c.get("/api/jobs", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


def test_api_jobs_correct_token_returns_200(monkeypatch):
    monkeypatch.setenv("PLATFORM", "github")
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret123")
    import importlib
    import server
    importlib.reload(server)
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    with patch("server.store.list_jobs", return_value=[{"id": 1, "status": "done"}]):
        resp = c.get("/api/jobs", headers={"X-Admin-Token": "secret123"})
    assert resp.status_code == 200
    assert resp.json()[0]["status"] == "done"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_server.py::test_github_rework_comment_queues_rework_job tests/test_server.py::test_api_jobs_open_when_no_password -v
```

Expected: AttributeError or 404 (routes don't exist yet)

- [ ] **Step 3: Replace `server.py` with the updated version**

```python
# server.py
import asyncio
import hashlib
import hmac
import json
import logging
import re
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

import store
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from config import Settings
from worker import enqueue_job, start_worker

logger = logging.getLogger(__name__)
settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db(settings.db_path)
    task = asyncio.create_task(start_worker(settings))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


_DOCS_DIR = Path(__file__).parent / "docs_site"

app = FastAPI(lifespan=lifespan)
app.mount("/guide", StaticFiles(directory=str(_DOCS_DIR), html=True), name="docs")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return RedirectResponse(url="/guide")


@app.get("/api/jobs")
async def api_jobs(request: Request):
    if settings.admin_password:
        token = request.headers.get("X-Admin-Token", "")
        if not hmac.compare_digest(token, settings.admin_password):
            raise HTTPException(status_code=401, detail="Unauthorized")
    return store.list_jobs(settings.db_path)


@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    _verify_github_signature(body, signature, settings.webhook_secret)

    payload = await request.json()
    action = payload.get("action")

    if action == "opened" and "issue" in payload:
        issue = payload["issue"]
        background_tasks.add_task(
            enqueue_job,
            platform="github",
            issue_number=issue["number"],
            title=issue.get("title", ""),
            body=issue.get("body") or "",
        )
        return {"status": "queued"}

    if action == "labeled" and "issue" in payload:
        label_name = payload.get("label", {}).get("name", "")
        if label_name.startswith("agent: "):
            issue = payload["issue"]
            background_tasks.add_task(
                enqueue_job,
                platform="github",
                issue_number=issue["number"],
                title=issue.get("title", ""),
                body=issue.get("body") or "",
            )
            return {"status": "queued"}

    if action == "created" and "comment" in payload and "issue" in payload:
        issue = payload["issue"]
        comment_body = payload["comment"].get("body", "")
        if issue.get("pull_request") and "/rework" in comment_body:
            if payload.get("sender", {}).get("type", "") != "Bot":
                pr_api_url = issue["pull_request"].get("url", "")
                try:
                    branch = _get_github_pr_branch(pr_api_url, settings.github_token)
                except Exception:
                    logger.warning("Could not fetch PR branch from %s", pr_api_url)
                    return {"status": "ignored"}
                issue_number = _parse_issue_number_from_branch(branch)
                if issue_number:
                    background_tasks.add_task(
                        enqueue_job,
                        platform="github",
                        issue_number=issue_number,
                        title=issue.get("title", ""),
                        body=issue.get("body") or "",
                        pr_branch=branch,
                        rework_comment=comment_body,
                    )
                    return {"status": "queued"}

    return {"status": "ignored"}


@app.post("/webhook/gitlab")
async def gitlab_webhook(request: Request, background_tasks: BackgroundTasks):
    token = request.headers.get("X-Gitlab-Token", "")
    if not hmac.compare_digest(token, settings.webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid token")

    payload = await request.json()
    attrs = payload.get("object_attributes", {})

    if payload.get("object_kind") == "issue" and attrs.get("action") == "open":
        background_tasks.add_task(
            enqueue_job,
            platform="gitlab",
            issue_number=attrs["iid"],
            title=attrs.get("title", ""),
            body=attrs.get("description") or "",
        )
        return {"status": "queued"}

    if payload.get("object_kind") == "issue" and attrs.get("action") == "update":
        label_changes = payload.get("changes", {}).get("labels", {})
        previous = {l.get("title", "") for l in label_changes.get("previous", [])}
        current = {l.get("title", "") for l in label_changes.get("current", [])}
        newly_added = current - previous
        if any(lbl.startswith("agent: ") for lbl in newly_added):
            background_tasks.add_task(
                enqueue_job,
                platform="gitlab",
                issue_number=attrs["iid"],
                title=attrs.get("title", ""),
                body=attrs.get("description") or "",
            )
            return {"status": "queued"}

    if payload.get("object_kind") == "note":
        note_attrs = payload.get("object_attributes", {})
        if (note_attrs.get("noteable_type") == "MergeRequest"
                and "/rework" in note_attrs.get("note", "")):
            mr = payload.get("merge_request", {})
            branch = mr.get("source_branch", "")
            issue_number = _parse_issue_number_from_branch(branch)
            if issue_number:
                background_tasks.add_task(
                    enqueue_job,
                    platform="gitlab",
                    issue_number=issue_number,
                    title=mr.get("title", ""),
                    body=mr.get("description") or "",
                    pr_branch=branch,
                    rework_comment=note_attrs["note"],
                )
                return {"status": "queued"}

    return {"status": "ignored"}


def _verify_github_signature(body: bytes, signature: str, secret: str) -> None:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    expected = f"sha256={mac.hexdigest()}"
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")


def _parse_issue_number_from_branch(branch: str) -> int | None:
    m = re.search(r"ai/issue-(\d+)-", branch)
    return int(m.group(1)) if m else None


def _get_github_pr_branch(pr_api_url: str, token: str) -> str:
    req = urllib.request.Request(
        pr_api_url,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data.get("head", {}).get("ref", "")
```

- [ ] **Step 4: Run all tests to verify they pass**

```
pytest -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: add /api/jobs endpoint and /rework PR comment webhooks"
```

---

### Task 6: Jobs admin UI (`docs_site/jobs.html` + sidebar link)

**Files:**
- Create: `docs_site/jobs.html`
- Modify: `docs_site/index.html`

- [ ] **Step 1: Create `docs_site/jobs.html`**

```html
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Jobs — AI Coding Flow</title>
<style>
  :root, [data-theme="light"] {
    --bg: #ffffff;
    --surface: #f6f8fa;
    --border: #d0d7de;
    --text: #1f2328;
    --text-muted: #636c76;
    --accent: #0969da;
    --accent-fg: #ffffff;
    --badge-queued-bg: #ddf4ff;
    --badge-queued-fg: #0550ae;
    --badge-processing-bg: #fff8c5;
    --badge-processing-fg: #7d4e00;
    --badge-reworking-bg: #fff8c5;
    --badge-reworking-fg: #7d4e00;
    --badge-done-bg: #dafbe1;
    --badge-done-fg: #116329;
    --badge-failed-bg: #ffebe9;
    --badge-failed-fg: #82071e;
    --badge-needs-clarification-bg: #fff1e5;
    --badge-needs-clarification-fg: #953800;
  }
  [data-theme="dark"] {
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --text-muted: #8d96a0;
    --accent: #58a6ff;
    --accent-fg: #0d1117;
    --badge-queued-bg: #033d8b;
    --badge-queued-fg: #cae8ff;
    --badge-processing-bg: #4d2d00;
    --badge-processing-fg: #fae17d;
    --badge-reworking-bg: #4d2d00;
    --badge-reworking-fg: #fae17d;
    --badge-done-bg: #033a16;
    --badge-done-fg: #aff5b4;
    --badge-failed-bg: #4b1113;
    --badge-failed-fg: #ffa198;
    --badge-needs-clarification-bg: #4e2400;
    --badge-needs-clarification-fg: #ffc680;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; background: var(--bg); color: var(--text); font-size: 14px; line-height: 1.5; }
  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 12px 24px; display: flex; align-items: center; gap: 16px; }
  header a { color: var(--accent); text-decoration: none; font-size: 13px; }
  header a:hover { text-decoration: underline; }
  header h1 { flex: 1; font-size: 16px; font-weight: 600; }
  .theme-btn { background: none; border: 1px solid var(--border); border-radius: 6px; padding: 4px 10px; cursor: pointer; color: var(--text); font-size: 13px; }
  main { max-width: 1100px; margin: 0 auto; padding: 24px; }
  .toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
  .toolbar span { color: var(--text-muted); font-size: 13px; }
  .refresh-btn { background: var(--accent); color: var(--accent-fg); border: none; border-radius: 6px; padding: 6px 14px; cursor: pointer; font-size: 13px; }
  table { width: 100%; border-collapse: collapse; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  th { background: var(--surface); color: var(--text-muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .5px; padding: 10px 16px; text-align: left; border-bottom: 1px solid var(--border); }
  td { padding: 12px 16px; border-bottom: 1px solid var(--border); vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: color-mix(in srgb, var(--accent) 4%, transparent); }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; white-space: nowrap; }
  .badge-queued              { background: var(--badge-queued-bg);              color: var(--badge-queued-fg); }
  .badge-processing          { background: var(--badge-processing-bg);          color: var(--badge-processing-fg); }
  .badge-reworking           { background: var(--badge-reworking-bg);           color: var(--badge-reworking-fg); }
  .badge-done                { background: var(--badge-done-bg);                color: var(--badge-done-fg); }
  .badge-failed              { background: var(--badge-failed-bg);              color: var(--badge-failed-fg); }
  .badge-needs_clarification { background: var(--badge-needs-clarification-bg); color: var(--badge-needs-clarification-fg); }
  .issue-title { font-weight: 500; }
  .issue-num { color: var(--text-muted); font-size: 12px; }
  a.pr-link { color: var(--accent); text-decoration: none; font-size: 12px; }
  a.pr-link:hover { text-decoration: underline; }
  .empty { text-align: center; padding: 48px; color: var(--text-muted); }
  dialog { border: 1px solid var(--border); border-radius: 8px; background: var(--bg); color: var(--text); padding: 24px; width: 340px; }
  dialog::backdrop { background: rgba(0,0,0,.5); }
  dialog h2 { margin-bottom: 8px; font-size: 15px; }
  dialog p { color: var(--text-muted); font-size: 13px; margin-bottom: 16px; }
  dialog input { width: 100%; border: 1px solid var(--border); border-radius: 6px; padding: 8px 10px; background: var(--surface); color: var(--text); font-size: 14px; margin-bottom: 12px; }
  dialog .actions { display: flex; gap: 8px; justify-content: flex-end; }
  dialog button { padding: 6px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; }
  .btn-primary { background: var(--accent); color: var(--accent-fg); border: none; }
  .btn-secondary { background: none; border: 1px solid var(--border); color: var(--text); }
</style>
</head>
<body>
<header>
  <a href="/guide">← Guide</a>
  <h1>Jobs</h1>
  <button class="theme-btn" id="themeBtn" onclick="toggleTheme()">🌙</button>
</header>
<main>
  <div class="toolbar">
    <span id="statusLine">Loading…</span>
    <button class="refresh-btn" onclick="loadJobs()">Refresh</button>
  </div>
  <div id="tableWrap"></div>
</main>

<dialog id="authDialog">
  <h2>Admin password required</h2>
  <p>Enter the <code>ADMIN_PASSWORD</code> to view job history.</p>
  <input type="password" id="pwInput" placeholder="Password" autocomplete="current-password">
  <div class="actions">
    <button class="btn-primary" onclick="submitPassword()">Sign in</button>
  </div>
</dialog>

<script>
  // ── theme ─────────────────────────────────────────────────────────────────
  function applyTheme(t) {
    document.documentElement.dataset.theme = t;
    document.getElementById('themeBtn').textContent = t === 'dark' ? '☀️' : '🌙';
    localStorage.setItem('theme', t);
  }
  function toggleTheme() {
    applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  }
  (function () {
    const saved = localStorage.getItem('theme');
    const sys = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    applyTheme(saved || sys);
  })();

  // ── auth ──────────────────────────────────────────────────────────────────
  function getToken() { return sessionStorage.getItem('adminToken') || ''; }
  function submitPassword() {
    const pw = document.getElementById('pwInput').value;
    if (!pw) return;
    sessionStorage.setItem('adminToken', pw);
    document.getElementById('authDialog').close();
    document.getElementById('pwInput').value = '';
    loadJobs();
  }
  document.getElementById('pwInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') submitPassword();
  });

  // ── data ──────────────────────────────────────────────────────────────────
  function formatDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  function renderTable(jobs) {
    const wrap = document.getElementById('tableWrap');
    if (!jobs.length) {
      wrap.innerHTML = '<div class="empty">No jobs yet.</div>';
      return;
    }
    const rows = jobs.map(j => `
      <tr>
        <td><span class="badge badge-${j.status}">${j.status.replace('_', ' ')}</span></td>
        <td>
          <div class="issue-title">${escHtml(j.issue_title)}</div>
          <div class="issue-num">${escHtml(j.platform)} #${j.issue_number}</div>
        </td>
        <td>${j.engine ? escHtml(j.engine) : '—'}</td>
        <td>${formatDate(j.created_at)}</td>
        <td>${j.pr_url ? `<a class="pr-link" href="${escHtml(j.pr_url)}" target="_blank" rel="noopener">PR ↗</a>` : '—'}</td>
      </tr>`).join('');
    wrap.innerHTML = `
      <table>
        <thead><tr><th>Status</th><th>Issue</th><th>Engine</th><th>Created</th><th>PR</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  function escHtml(str) {
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  async function loadJobs() {
    const statusLine = document.getElementById('statusLine');
    statusLine.textContent = 'Loading…';
    try {
      const resp = await fetch('/api/jobs', {
        headers: getToken() ? { 'X-Admin-Token': getToken() } : {},
      });
      if (resp.status === 401) {
        sessionStorage.removeItem('adminToken');
        document.getElementById('authDialog').showModal();
        statusLine.textContent = 'Authentication required.';
        return;
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const jobs = await resp.json();
      renderTable(jobs);
      statusLine.textContent = `${jobs.length} job${jobs.length !== 1 ? 's' : ''} · refreshed ${new Date().toLocaleTimeString()}`;
    } catch (err) {
      statusLine.textContent = `Error: ${err.message}`;
    }
  }

  // ── boot ──────────────────────────────────────────────────────────────────
  loadJobs();
  setInterval(loadJobs, 30000);
</script>
</body>
</html>
```

- [ ] **Step 2: Add "Jobs" nav link to `docs_site/index.html`**

In `docs_site/index.html` around line 502–506, find this block:

```html
      <a class="nav-link" href="#" data-section="testing">
        <span class="icon">🧪</span> Testing
      </a>
    </div>
  </nav>
```

Replace it with:

```html
      <a class="nav-link" href="#" data-section="testing">
        <span class="icon">🧪</span> Testing
      </a>
      <a class="nav-link" href="/jobs" style="border-top:1px solid var(--border);margin-top:8px;padding-top:8px;">
        Jobs ↗
      </a>
    </div>
  </nav>
```

- [ ] **Step 3: Verify the page renders**

Start the server (requires a valid `.env`) or use the test client to confirm `/jobs` returns HTTP 200:

```python
# quick sanity check — run in a python3 shell
from fastapi.testclient import TestClient
import os; os.environ.update({"PLATFORM":"github","REPO_URL":"https://github.com/a/b","WEBHOOK_SECRET":"s","OPENAI_API_BASE":"http://localhost/v1"})
import importlib, server; importlib.reload(server)
c = TestClient(server.app)
print(c.get("/jobs").status_code)  # expected: 200
```

- [ ] **Step 4: Run full test suite**

```
pytest -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add docs_site/jobs.html docs_site/index.html
git commit -m "feat: add /jobs admin UI with job history table"
```

---

### Task 7: Final integration commit and push

- [ ] **Step 1: Run full test suite one final time**

```
pytest -v
```

Expected: all pass, count higher than before (was 66)

- [ ] **Step 2: Push**

```bash
git push origin master
```
