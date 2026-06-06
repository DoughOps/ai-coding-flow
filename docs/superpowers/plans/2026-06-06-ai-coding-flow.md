# AI Coding Flow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an autonomous AI coding workflow that watches GitHub/GitLab issues, writes code, runs tests, creates PRs/MRs, and posts a review comment — with the human only deciding whether to merge.

**Architecture:** A FastAPI webhook server receives issue-opened events, verifies signatures, and enqueues jobs to an asyncio worker. The worker clones the repo, runs Aider (AI coding agent) as a subprocess to write code and fix failing tests, then pushes the branch and creates a PR/MR via the platform API. A separate review agent (fresh LLM call) posts a structured review comment on the issue. All AI calls go through a configurable OpenAI-compatible endpoint.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, Aider (aider-chat), openai SDK, PyGitHub, python-gitlab, pydantic-settings, pytest, pytest-asyncio

---

## File Map

| File | Responsibility |
|---|---|
| `config.py` | Pydantic-settings config, loaded from `.env` |
| `platforms/base.py` | `Issue` dataclass + `GitPlatform` ABC |
| `platforms/github.py` | GitHub implementation (PyGitHub) |
| `platforms/gitlab.py` | GitLab implementation (python-gitlab) |
| `platforms/__init__.py` | `create_platform()` factory |
| `server.py` | FastAPI app, webhook endpoints, signature verification, lifespan startup |
| `worker.py` | Asyncio job queue, `process_job` orchestrator, `_slugify` |
| `agent.py` | Aider subprocess wrapper, git operations, retry loop |
| `reviewer.py` | Fresh LLM call that returns a review string |
| `requirements.txt` | Pinned dependencies |
| `.env.example` | Config reference |
| `tests/test_config.py` | Config validation tests |
| `tests/test_server.py` | Webhook endpoint tests (TestClient) |
| `tests/test_worker.py` | `_slugify` unit tests |
| `tests/test_agent.py` | Agent helper function tests |
| `tests/test_reviewer.py` | Reviewer tests (mocked OpenAI) |
| `tests/test_platforms/test_github.py` | GitHub platform tests (mocked PyGitHub) |
| `tests/test_platforms/test_gitlab.py` | GitLab platform tests (mocked python-gitlab) |

---

## Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `platforms/__init__.py` (empty for now)
- Create: `tests/__init__.py`
- Create: `tests/test_platforms/__init__.py`

- [ ] **Step 1: Create `requirements.txt`**

```
fastapi>=0.100.0
uvicorn[standard]>=0.23.0
pydantic-settings>=2.0.0
aider-chat>=0.50.0
openai>=1.0.0
PyGitHub>=2.0.0
python-gitlab>=4.0.0
httpx>=0.24.0
pytest>=7.0.0
pytest-asyncio>=0.21.0
```

- [ ] **Step 2: Create `.env.example`**

```
PLATFORM=github
REPO_URL=https://github.com/owner/repo
GITHUB_TOKEN=ghp_...
GITLAB_TOKEN=
WEBHOOK_SECRET=your-webhook-secret
OPENAI_API_BASE=http://localhost:11434/v1
OPENAI_API_KEY=local
OPENAI_MODEL=qwen2.5-coder:32b
MAX_RETRIES=3
TEST_CMD=pytest
```

- [ ] **Step 3: Create directory structure**

```bash
mkdir -p platforms tests/test_platforms
touch platforms/__init__.py tests/__init__.py tests/test_platforms/__init__.py
```

- [ ] **Step 4: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: no errors, all packages install.

- [ ] **Step 5: Verify key packages are importable**

```bash
python -c "import fastapi; import aider; import github; import gitlab; import openai; print('OK')"
```

Expected output: `OK`

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .env.example platforms/__init__.py tests/__init__.py tests/test_platforms/__init__.py
git commit -m "chore: project setup with dependencies"
```

---

## Task 2: Config Module

**Files:**
- Create: `config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config.py`:

```python
import pytest
from pydantic import ValidationError


def test_valid_github_config(monkeypatch):
    monkeypatch.setenv("PLATFORM", "github")
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("WEBHOOK_SECRET", "secret123")
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    from config import Settings
    s = Settings()
    assert s.platform == "github"
    assert s.max_retries == 3
    assert s.test_cmd == "pytest"
    assert s.openai_api_key == "local"


def test_invalid_platform_raises(monkeypatch):
    monkeypatch.setenv("PLATFORM", "bitbucket")
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.setenv("WEBHOOK_SECRET", "secret123")
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    with pytest.raises(ValidationError):
        from importlib import reload
        import config
        reload(config)
        config.Settings()


def test_missing_platform_raises(monkeypatch):
    monkeypatch.delenv("PLATFORM", raising=False)
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.setenv("WEBHOOK_SECRET", "secret123")
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    with pytest.raises(ValidationError):
        from importlib import reload
        import config
        reload(config)
        config.Settings()


def test_missing_webhook_secret_raises(monkeypatch):
    monkeypatch.setenv("PLATFORM", "github")
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    with pytest.raises(ValidationError):
        from importlib import reload
        import config
        reload(config)
        config.Settings()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Implement `config.py`**

```python
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
    test_cmd: str = "pytest"

    model_config = {"env_file": ".env"}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add config module with pydantic-settings"
```

---

## Task 3: Platform Base

**Files:**
- Create: `platforms/base.py`

- [ ] **Step 1: Implement `platforms/base.py`**

No tests needed for a pure ABC — it has no logic to test.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Issue:
    number: int
    title: str
    body: str
    url: str


class GitPlatform(ABC):
    @abstractmethod
    def get_issue(self, number: int) -> Issue: ...

    @abstractmethod
    def create_pr(self, branch: str, title: str, body: str) -> str:
        """Create a PR (GitHub) or MR (GitLab). Returns the PR/MR URL."""
        ...

    @abstractmethod
    def post_comment(self, issue_number: int, body: str) -> None: ...
```

- [ ] **Step 2: Verify it imports cleanly**

```bash
python -c "from platforms.base import GitPlatform, Issue; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add platforms/base.py
git commit -m "feat: add GitPlatform ABC and Issue dataclass"
```

---

## Task 4: GitHub Platform

**Files:**
- Create: `platforms/github.py`
- Create: `tests/test_platforms/test_github.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_platforms/test_github.py`:

```python
from unittest.mock import MagicMock, patch
import pytest
from platforms.base import Issue


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.default_branch = "main"
    return repo


@pytest.fixture
def platform(mock_repo):
    with patch("platforms.github.Github") as mock_gh_cls:
        mock_gh_cls.return_value.get_repo.return_value = mock_repo
        from platforms.github import GitHubPlatform
        p = GitHubPlatform(token="ghp_test", repo_url="https://github.com/owner/repo")
        return p


def test_get_issue_returns_issue(platform, mock_repo):
    gh_issue = MagicMock()
    gh_issue.number = 42
    gh_issue.title = "Fix the bug"
    gh_issue.body = "There is a bug in login"
    gh_issue.html_url = "https://github.com/owner/repo/issues/42"
    mock_repo.get_issue.return_value = gh_issue

    issue = platform.get_issue(42)

    assert isinstance(issue, Issue)
    assert issue.number == 42
    assert issue.title == "Fix the bug"
    assert issue.body == "There is a bug in login"
    assert issue.url == "https://github.com/owner/repo/issues/42"


def test_get_issue_none_body_becomes_empty_string(platform, mock_repo):
    gh_issue = MagicMock()
    gh_issue.number = 1
    gh_issue.title = "No body"
    gh_issue.body = None
    gh_issue.html_url = "https://github.com/owner/repo/issues/1"
    mock_repo.get_issue.return_value = gh_issue

    issue = platform.get_issue(1)

    assert issue.body == ""


def test_create_pr_returns_url(platform, mock_repo):
    pr = MagicMock()
    pr.html_url = "https://github.com/owner/repo/pull/1"
    mock_repo.create_pull.return_value = pr

    url = platform.create_pr(
        branch="ai/issue-42-fix-bug",
        title="fix: Fix the bug (resolves #42)",
        body="Closes #42\n\nAI generated.",
    )

    assert url == "https://github.com/owner/repo/pull/1"
    mock_repo.create_pull.assert_called_once_with(
        title="fix: Fix the bug (resolves #42)",
        body="Closes #42\n\nAI generated.",
        head="ai/issue-42-fix-bug",
        base="main",
    )


def test_post_comment_calls_create_comment(platform, mock_repo):
    issue = MagicMock()
    mock_repo.get_issue.return_value = issue

    platform.post_comment(42, "AI could not fix this issue.")

    mock_repo.get_issue.assert_called_once_with(42)
    issue.create_comment.assert_called_once_with("AI could not fix this issue.")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_platforms/test_github.py -v
```

Expected: `ModuleNotFoundError: No module named 'platforms.github'`

- [ ] **Step 3: Implement `platforms/github.py`**

```python
from github import Github
from .base import GitPlatform, Issue


class GitHubPlatform(GitPlatform):
    def __init__(self, token: str, repo_url: str) -> None:
        self._gh = Github(token)
        parts = repo_url.rstrip("/").rstrip(".git").split("/")
        self._repo = self._gh.get_repo(f"{parts[-2]}/{parts[-1]}")

    def get_issue(self, number: int) -> Issue:
        gh_issue = self._repo.get_issue(number)
        return Issue(
            number=gh_issue.number,
            title=gh_issue.title,
            body=gh_issue.body or "",
            url=gh_issue.html_url,
        )

    def create_pr(self, branch: str, title: str, body: str) -> str:
        pr = self._repo.create_pull(
            title=title,
            body=body,
            head=branch,
            base=self._repo.default_branch,
        )
        return pr.html_url

    def post_comment(self, issue_number: int, body: str) -> None:
        issue = self._repo.get_issue(issue_number)
        issue.create_comment(body)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_platforms/test_github.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add platforms/github.py tests/test_platforms/test_github.py
git commit -m "feat: add GitHub platform implementation"
```

---

## Task 5: GitLab Platform

**Files:**
- Create: `platforms/gitlab.py`
- Create: `tests/test_platforms/test_gitlab.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_platforms/test_gitlab.py`:

```python
from unittest.mock import MagicMock, patch
import pytest
from platforms.base import Issue


@pytest.fixture
def mock_project():
    project = MagicMock()
    project.default_branch = "main"
    project.web_url = "https://gitlab.example.com/owner/repo"
    return project


@pytest.fixture
def platform(mock_project):
    with patch("platforms.gitlab.gitlab.Gitlab") as mock_gl_cls:
        mock_gl = MagicMock()
        mock_gl.projects.get.return_value = mock_project
        mock_gl_cls.return_value = mock_gl
        from platforms.gitlab import GitLabPlatform
        p = GitLabPlatform(
            token="glpat-test",
            repo_url="https://gitlab.example.com/owner/repo",
        )
        return p


def test_get_issue_returns_issue(platform, mock_project):
    gl_issue = MagicMock()
    gl_issue.iid = 7
    gl_issue.title = "Fix the bug"
    gl_issue.description = "There is a bug"
    gl_issue.web_url = "https://gitlab.example.com/owner/repo/-/issues/7"
    mock_project.issues.list.return_value = [gl_issue]

    issue = platform.get_issue(7)

    assert isinstance(issue, Issue)
    assert issue.number == 7
    assert issue.title == "Fix the bug"
    assert issue.body == "There is a bug"
    mock_project.issues.list.assert_called_once_with(iid=7)


def test_get_issue_none_description_becomes_empty_string(platform, mock_project):
    gl_issue = MagicMock()
    gl_issue.iid = 1
    gl_issue.title = "No desc"
    gl_issue.description = None
    gl_issue.web_url = "https://gitlab.example.com/owner/repo/-/issues/1"
    mock_project.issues.list.return_value = [gl_issue]

    issue = platform.get_issue(1)

    assert issue.body == ""


def test_create_mr_returns_url(platform, mock_project):
    mr = MagicMock()
    mr.web_url = "https://gitlab.example.com/owner/repo/-/merge_requests/1"
    mock_project.mergerequests.create.return_value = mr

    url = platform.create_pr(
        branch="ai/issue-7-fix-bug",
        title="fix: Fix the bug (resolves #7)",
        body="Closes #7\n\nAI generated.",
    )

    assert url == "https://gitlab.example.com/owner/repo/-/merge_requests/1"
    mock_project.mergerequests.create.assert_called_once_with({
        "source_branch": "ai/issue-7-fix-bug",
        "target_branch": "main",
        "title": "fix: Fix the bug (resolves #7)",
        "description": "Closes #7\n\nAI generated.",
    })


def test_post_comment_creates_note(platform, mock_project):
    gl_issue = MagicMock()
    mock_project.issues.list.return_value = [gl_issue]

    platform.post_comment(7, "AI review comment")

    gl_issue.notes.create.assert_called_once_with({"body": "AI review comment"})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_platforms/test_gitlab.py -v
```

Expected: `ModuleNotFoundError: No module named 'platforms.gitlab'`

- [ ] **Step 3: Implement `platforms/gitlab.py`**

```python
import gitlab
from urllib.parse import urlparse
from .base import GitPlatform, Issue


class GitLabPlatform(GitPlatform):
    def __init__(self, token: str, repo_url: str) -> None:
        parsed = urlparse(repo_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        self._gl = gitlab.Gitlab(base_url, private_token=token)
        project_path = parsed.path.lstrip("/").rstrip(".git")
        self._project = self._gl.projects.get(project_path)

    def get_issue(self, number: int) -> Issue:
        issues = self._project.issues.list(iid=number)
        gl_issue = issues[0]
        return Issue(
            number=gl_issue.iid,
            title=gl_issue.title,
            body=gl_issue.description or "",
            url=gl_issue.web_url,
        )

    def create_pr(self, branch: str, title: str, body: str) -> str:
        mr = self._project.mergerequests.create({
            "source_branch": branch,
            "target_branch": self._project.default_branch,
            "title": title,
            "description": body,
        })
        return mr.web_url

    def post_comment(self, issue_number: int, body: str) -> None:
        issues = self._project.issues.list(iid=issue_number)
        gl_issue = issues[0]
        gl_issue.notes.create({"body": body})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_platforms/test_gitlab.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add platforms/gitlab.py tests/test_platforms/test_gitlab.py
git commit -m "feat: add GitLab platform implementation"
```

---

## Task 6: Platform Factory

**Files:**
- Modify: `platforms/__init__.py`
- Create: `tests/test_platforms/test_factory.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_platforms/test_factory.py`:

```python
from unittest.mock import MagicMock, patch
import pytest


def _make_settings(platform: str) -> MagicMock:
    s = MagicMock()
    s.platform = platform
    s.github_token = "ghp_test"
    s.gitlab_token = "glpat_test"
    s.repo_url = "https://github.com/owner/repo"
    return s


def test_factory_returns_github_platform():
    settings = _make_settings("github")
    with patch("platforms.GitHubPlatform") as mock_cls:
        from platforms import create_platform
        create_platform(settings)
        mock_cls.assert_called_once_with(
            token="ghp_test",
            repo_url="https://github.com/owner/repo",
        )


def test_factory_returns_gitlab_platform():
    settings = _make_settings("gitlab")
    settings.repo_url = "https://gitlab.example.com/owner/repo"
    with patch("platforms.GitLabPlatform") as mock_cls:
        from platforms import create_platform
        create_platform(settings)
        mock_cls.assert_called_once_with(
            token="glpat_test",
            repo_url="https://gitlab.example.com/owner/repo",
        )


def test_factory_raises_on_unknown_platform():
    settings = _make_settings("bitbucket")
    from platforms import create_platform
    with pytest.raises(ValueError, match="Unknown platform"):
        create_platform(settings)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_platforms/test_factory.py -v
```

Expected: `ImportError` or `AttributeError` since `platforms/__init__.py` is empty.

- [ ] **Step 3: Implement `platforms/__init__.py`**

```python
from .base import GitPlatform, Issue
from .github import GitHubPlatform
from .gitlab import GitLabPlatform


def create_platform(settings) -> GitPlatform:
    if settings.platform == "github":
        return GitHubPlatform(token=settings.github_token, repo_url=settings.repo_url)
    if settings.platform == "gitlab":
        return GitLabPlatform(token=settings.gitlab_token, repo_url=settings.repo_url)
    raise ValueError(f"Unknown platform: {settings.platform}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_platforms/ -v
```

Expected: all 9 tests pass (4 GitHub + 4 GitLab + 3 factory).

- [ ] **Step 5: Commit**

```bash
git add platforms/__init__.py tests/test_platforms/test_factory.py
git commit -m "feat: add platform factory"
```

---

## Task 7: Webhook Server

**Files:**
- Create: `server.py`
- Create: `tests/test_server.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_server.py`:

```python
import hashlib
import hmac
import json
import os
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient


SECRET = "test-secret"


def _sign(body: bytes, secret: str = SECRET) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


ISSUE_OPENED = {
    "action": "opened",
    "issue": {"number": 42, "title": "Fix bug", "body": "There is a bug"},
}

GITLAB_ISSUE_OPENED = {
    "object_kind": "issue",
    "object_attributes": {
        "iid": 7,
        "title": "Fix bug",
        "description": "There is a bug",
        "action": "open",
    },
}


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("PLATFORM", "github")
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")


@pytest.fixture
def client():
    import importlib
    import server
    importlib.reload(server)
    return TestClient(server.app, raise_server_exceptions=True)


def test_github_valid_signature_queues_job(client):
    body = json.dumps(ISSUE_OPENED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()


def test_github_invalid_signature_returns_403(client):
    body = json.dumps(ISSUE_OPENED).encode()
    resp = client.post(
        "/webhook/github",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=badsig", "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_github_non_issue_event_is_ignored(client):
    payload = {"action": "labeled", "label": {"name": "bug"}}
    body = json.dumps(payload).encode()
    resp = client.post(
        "/webhook/github",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_github_issue_not_opened_is_ignored(client):
    payload = {**ISSUE_OPENED, "action": "closed"}
    body = json.dumps(payload).encode()
    resp = client.post(
        "/webhook/github",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_gitlab_valid_token_queues_job(client):
    body = json.dumps(GITLAB_ISSUE_OPENED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/gitlab",
            content=body,
            headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()


def test_gitlab_invalid_token_returns_403(client):
    body = json.dumps(GITLAB_ISSUE_OPENED).encode()
    resp = client.post(
        "/webhook/gitlab",
        content=body,
        headers={"X-Gitlab-Token": "wrongtoken", "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_gitlab_non_issue_event_is_ignored(client):
    payload = {"object_kind": "push"}
    body = json.dumps(payload).encode()
    resp = client.post(
        "/webhook/gitlab",
        content=body,
        headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_server.py -v
```

Expected: `ModuleNotFoundError: No module named 'server'`

- [ ] **Step 3: Implement `server.py`**

```python
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from config import Settings
from worker import enqueue_job, start_worker

logger = logging.getLogger(__name__)
settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    task = asyncio.create_task(start_worker(settings))
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    _verify_github_signature(body, signature, settings.webhook_secret)

    payload = await request.json()
    if payload.get("action") != "opened" or "issue" not in payload:
        return {"status": "ignored"}

    issue = payload["issue"]
    background_tasks.add_task(
        enqueue_job,
        platform="github",
        issue_number=issue["number"],
        title=issue["title"],
        body=issue.get("body") or "",
    )
    return {"status": "queued"}


@app.post("/webhook/gitlab")
async def gitlab_webhook(request: Request, background_tasks: BackgroundTasks):
    token = request.headers.get("X-Gitlab-Token", "")
    if not hmac.compare_digest(token, settings.webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid token")

    payload = await request.json()
    attrs = payload.get("object_attributes", {})
    if payload.get("object_kind") != "issue" or attrs.get("action") != "open":
        return {"status": "ignored"}

    background_tasks.add_task(
        enqueue_job,
        platform="gitlab",
        issue_number=attrs["iid"],
        title=attrs["title"],
        body=attrs.get("description") or "",
    )
    return {"status": "queued"}


def _verify_github_signature(body: bytes, signature: str, secret: str) -> None:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    expected = f"sha256={mac.hexdigest()}"
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_server.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: add webhook server with GitHub and GitLab endpoints"
```

---

## Task 8: Agent Module

**Files:**
- Create: `agent.py`
- Create: `tests/test_agent.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_agent.py`:

```python
from unittest.mock import MagicMock
import pytest
from agent import _build_prompt, _authenticated_url


def _settings(platform="github"):
    s = MagicMock()
    s.platform = platform
    s.github_token = "ghp_testtoken"
    s.gitlab_token = "glpat_testtoken"
    s.repo_url = (
        "https://github.com/owner/repo"
        if platform == "github"
        else "https://gitlab.example.com/owner/repo"
    )
    return s


def test_build_prompt_contains_title():
    prompt = _build_prompt("Fix the login bug", "Users cannot log in")
    assert "Fix the login bug" in prompt


def test_build_prompt_contains_body():
    prompt = _build_prompt("Fix the login bug", "Users cannot log in after update")
    assert "Users cannot log in after update" in prompt


def test_authenticated_url_github_embeds_token():
    url = _authenticated_url(_settings("github"))
    assert "x-access-token:ghp_testtoken@github.com" in url
    assert url.startswith("https://")


def test_authenticated_url_gitlab_embeds_token():
    url = _authenticated_url(_settings("gitlab"))
    assert "oauth2:glpat_testtoken@gitlab.example.com" in url
    assert url.startswith("https://")


def test_authenticated_url_github_no_dot_git():
    s = MagicMock()
    s.platform = "github"
    s.github_token = "tok"
    s.repo_url = "https://github.com/owner/repo.git"
    url = _authenticated_url(s)
    assert url.startswith("https://x-access-token:tok@github.com")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_agent.py -v
```

Expected: `ModuleNotFoundError: No module named 'agent'`

- [ ] **Step 3: Implement `agent.py`**

```python
import logging
import os
import re
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


def _run_tests(repo_path: Path, test_cmd: str) -> tuple[bool, str]:
    result = subprocess.run(
        test_cmd.split(),
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


```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_agent.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add agent.py tests/test_agent.py
git commit -m "feat: add agent module with Aider wrapper and git helpers"
```

---

## Task 9: Worker Module

**Files:**
- Create: `worker.py`
- Create: `tests/test_worker.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_worker.py`:

```python
import pytest
from worker import _slugify


def test_slugify_basic():
    assert _slugify("Fix the login bug") == "fix-the-login-bug"


def test_slugify_special_characters():
    assert _slugify("Support UTF-8 & unicode!") == "support-utf-8-unicode"


def test_slugify_truncates_at_50():
    result = _slugify("word " * 20)
    assert len(result) <= 50


def test_slugify_trims_leading_trailing_hyphens():
    result = _slugify("  Fix bug  ")
    assert not result.startswith("-")
    assert not result.endswith("-")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_worker.py -v
```

Expected: `ModuleNotFoundError: No module named 'worker'`

- [ ] **Step 3: Implement `worker.py`**

```python
import asyncio
import logging
import re
from dataclasses import dataclass

from config import Settings
from agent import run_agent, push_branch, get_diff
from reviewer import run_review
from platforms import create_platform

logger = logging.getLogger(__name__)


@dataclass
class Job:
    platform: str
    issue_number: int
    title: str
    body: str


_queue: asyncio.Queue = asyncio.Queue()


async def enqueue_job(*, platform: str, issue_number: int, title: str, body: str) -> None:
    await _queue.put(Job(platform=platform, issue_number=issue_number, title=title, body=body))
    logger.info("Enqueued issue #%d (%s)", issue_number, platform)


async def start_worker(settings: Settings) -> None:
    logger.info("Worker started")
    while True:
        job = await _queue.get()
        try:
            await _process_job(job, settings)
        except Exception as exc:
            logger.exception("Unhandled error for issue #%d", job.issue_number)
            try:
                platform = create_platform(settings)
                platform.post_comment(
                    job.issue_number,
                    f"AI workflow encountered an unexpected error: {exc}",
                )
            except Exception:
                logger.exception("Failed to post error comment for issue #%d", job.issue_number)
        finally:
            _queue.task_done()


async def _process_job(job: Job, settings: Settings) -> None:
    platform = create_platform(settings)
    branch = f"ai/issue-{job.issue_number}-{_slugify(job.title)}"
    logger.info("Processing issue #%d on branch %s", job.issue_number, branch)

    success, repo_path, initial_commit, error_msg = await asyncio.to_thread(
        run_agent,
        issue_number=job.issue_number,
        issue_title=job.title,
        issue_body=job.body,
        branch=branch,
        settings=settings,
    )

    if not success:
        platform.post_comment(
            job.issue_number,
            f"AI attempted to fix this issue but could not produce passing tests "
            f"after {settings.max_retries} attempts.\n\nLast test output:\n```\n{error_msg}\n```",
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

    diff = get_diff(repo_path, initial_commit)
    review_comment = await asyncio.to_thread(
        run_review,
        issue_title=job.title,
        issue_body=job.body,
        diff=diff,
        settings=settings,
    )
    platform.post_comment(job.issue_number, f"**AI Review:**\n\n{review_comment}")
    logger.info("Posted review comment for issue #%d", job.issue_number)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:50]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_worker.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add worker.py tests/test_worker.py
git commit -m "feat: add async worker with job queue and job orchestration"
```

---

## Task 10: Reviewer Module

**Files:**
- Create: `reviewer.py`
- Create: `tests/test_reviewer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_reviewer.py`:

```python
from unittest.mock import MagicMock, patch
import pytest


def _make_settings():
    s = MagicMock()
    s.openai_api_base = "http://localhost:11434/v1"
    s.openai_api_key = "local"
    s.openai_model = "qwen2.5-coder:32b"
    return s


def _mock_openai_response(content: str):
    response = MagicMock()
    response.choices[0].message.content = content
    return response


def test_run_review_returns_string():
    with patch("reviewer.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response("LGTM")
        mock_cls.return_value = mock_client

        from reviewer import run_review
        result = run_review(
            issue_title="Fix bug",
            issue_body="There is a bug",
            diff="+def fix(): pass",
            settings=_make_settings(),
        )

    assert result == "LGTM"


def test_run_review_passes_diff_to_llm():
    with patch("reviewer.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response("ok")
        mock_cls.return_value = mock_client

        from reviewer import run_review
        run_review(
            issue_title="Fix bug",
            issue_body="Description",
            diff="+UNIQUE_DIFF_MARKER",
            settings=_make_settings(),
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages_text = str(call_kwargs.get("messages", ""))
        assert "UNIQUE_DIFF_MARKER" in messages_text


def test_run_review_uses_configured_model():
    with patch("reviewer.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response("ok")
        mock_cls.return_value = mock_client

        settings = _make_settings()
        settings.openai_model = "my-custom-model"

        from reviewer import run_review
        run_review("title", "body", "diff", settings)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "my-custom-model"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_reviewer.py -v
```

Expected: `ModuleNotFoundError: No module named 'reviewer'`

- [ ] **Step 3: Implement `reviewer.py`**

```python
from openai import OpenAI
from config import Settings


def run_review(
    issue_title: str,
    issue_body: str,
    diff: str,
    settings: Settings,
) -> str:
    """Call the LLM with a fresh context to review the diff. Returns review text."""
    client = OpenAI(
        base_url=settings.openai_api_base,
        api_key=settings.openai_api_key,
    )
    prompt = (
        f"You are an expert code reviewer. Review the following code changes that were made "
        f"to resolve an issue.\n\n"
        f"Issue: {issue_title}\n"
        f"Description: {issue_body}\n\n"
        f"Code diff:\n```diff\n{diff}\n```\n\n"
        f"Provide a concise review covering:\n"
        f"1. Correctness — does the change actually fix the issue?\n"
        f"2. Edge cases — any unhandled scenarios?\n"
        f"3. Code quality — any obvious improvements?\n"
        f"4. Test coverage — are the tests sufficient?\n\n"
        f"Be direct and specific. If the code looks good, say so."
    )
    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000,
    )
    return response.choices[0].message.content
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_reviewer.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add reviewer.py tests/test_reviewer.py
git commit -m "feat: add reviewer module for AI code review comments"
```

---

## Task 11: Full Test Suite + Smoke Run

**Files:**
- No new files — verify all tests pass, then run the server.

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass (7 server + 4 github + 4 gitlab + 3 factory + 5 agent + 4 worker + 3 reviewer + 4 config = 34 tests).

- [ ] **Step 2: Verify server starts cleanly**

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

Expected output includes:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Stop with Ctrl+C after confirming startup.

- [ ] **Step 3: Expose the server and register the webhook**

Expose the local server (e.g., via ngrok):
```bash
ngrok http 8000
```

Register the webhook URL in GitHub or GitLab:
- **GitHub:** Repo → Settings → Webhooks → Add webhook
  - Payload URL: `https://<ngrok-url>/webhook/github`
  - Content type: `application/json`
  - Secret: value of `WEBHOOK_SECRET` from `.env`
  - Events: "Issues" only
- **GitLab:** Project → Settings → Webhooks
  - URL: `https://<ngrok-url>/webhook/gitlab`
  - Secret token: value of `WEBHOOK_SECRET` from `.env`
  - Trigger: "Issues events"

- [ ] **Step 4: Commit final state**

```bash
git add -A
git commit -m "chore: verify all tests pass and document run instructions"
```

---

## Human Assistance Required

Before running end-to-end:

1. **Provide a `.env` file** based on `.env.example` with real values:
   - `REPO_URL` pointing to a test Python repository
   - `GITHUB_TOKEN` or `GITLAB_TOKEN` with repo write permissions
   - `WEBHOOK_SECRET` (any random string, must match webhook config)
   - `OPENAI_API_BASE` pointing to your local LLM endpoint

2. **Ensure the target repo has a test suite** (`pytest` runnable at repo root).

3. **Expose the local server** (ngrok or port forwarding) and register the webhook URL on the platform.

4. **Verify your LLM endpoint is running** at `OPENAI_API_BASE` before creating a test issue.
