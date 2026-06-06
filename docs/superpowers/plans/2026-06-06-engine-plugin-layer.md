# Engine Plugin Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hard-coded Aider call with a pluggable engine system that lets each GitHub issue select its coding agent via an `agent: <name>` label, defaulting to Aider.

**Architecture:** A new `engines/` module mirrors the `platforms/` pattern — an `AgentEngine` ABC, per-engine implementations (`AiderEngine`, `OpenCodeEngine`), and a `get_engine(name)` factory. `agent.py` accepts an engine instance instead of calling Aider directly. `worker.py` reads the issue's labels at processing time to select the engine. `server.py` handles `labeled` webhook events so adding an `agent:*` label re-triggers the workflow with the new engine.

**Tech Stack:** Python stdlib `subprocess`, `abc`, existing `config.py` Settings, `platforms/` abstraction (PyGitHub / python-gitlab), pytest + unittest.mock.

---

## File Map

**New files:**
- `engines/__init__.py` — factory: `get_engine(name: str) -> AgentEngine`
- `engines/base.py` — `AgentEngine` ABC
- `engines/aider.py` — `AiderEngine` (extracts `_run_aider` from `agent.py`)
- `engines/opencode.py` — `OpenCodeEngine`
- `tests/test_engines.py` — unit tests for all engine components

**Modified files:**
- `platforms/base.py` — add `get_labels(issue_number: int) -> list[str]` to ABC
- `platforms/github.py` — implement `get_labels`
- `platforms/gitlab.py` — implement `get_labels`
- `config.py` — add `default_agent: str = "aider"`
- `agent.py` — accept `engine: AgentEngine` param; remove `_run_aider`
- `worker.py` — read labels, call `_pick_engine`, pass engine to `run_agent`
- `server.py` — handle GitHub `labeled` action and GitLab label-update events
- `tests/test_platforms/test_github.py` — add `get_labels` tests
- `tests/test_platforms/test_gitlab.py` — add `get_labels` tests
- `tests/test_agent.py` — add engine-param test
- `tests/test_worker.py` — add `_pick_engine` tests
- `tests/test_server.py` — add labeled-webhook tests

---

### Task 1: AgentEngine ABC

**Files:**
- Create: `engines/base.py`
- Create (stub): `engines/__init__.py`
- Create: `tests/test_engines.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engines.py
import pytest


def test_agent_engine_is_abstract():
    from engines.base import AgentEngine
    with pytest.raises(TypeError):
        AgentEngine()  # type: ignore[abstract]


def test_agent_engine_name_is_abstract():
    from engines.base import AgentEngine
    assert "name" in AgentEngine.__abstractmethods__


def test_agent_engine_run_is_abstract():
    from engines.base import AgentEngine
    assert "run" in AgentEngine.__abstractmethods__
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_engines.py -v
```

Expected: `ModuleNotFoundError: No module named 'engines'`

- [ ] **Step 3: Create the stub `__init__.py` and `base.py`**

```python
# engines/__init__.py
# (empty for now — factory added in Task 4)
```

```python
# engines/base.py
from abc import ABC, abstractmethod
from pathlib import Path

from config import Settings


class AgentEngine(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def run(self, repo_path: Path, prompt: str, settings: Settings) -> str:
        """Run the engine against the repo. Returns stdout+stderr output."""
        ...
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_engines.py -v
```

Expected: 3 tests PASS

---

### Task 2: AiderEngine

**Files:**
- Create: `engines/aider.py`
- Test: `tests/test_engines.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engines.py`:

```python
from unittest.mock import patch, MagicMock
from pathlib import Path


def _mock_settings():
    s = MagicMock()
    s.openai_model = "gpt-4o"
    s.openai_api_base = "http://localhost:11434/v1"
    s.openai_api_key = "local"
    s.aider_verbose = False
    return s


def test_aider_engine_name():
    from engines.aider import AiderEngine
    assert AiderEngine().name == "aider"


def test_aider_engine_run_calls_aider_binary():
    from engines.aider import AiderEngine
    with patch("engines.aider.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="Changes applied.", stderr="", returncode=0)
        output = AiderEngine().run(Path("/tmp/repo"), "Fix the login bug", _mock_settings())
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "aider"
    assert "--model" in cmd
    assert "gpt-4o" in cmd
    assert "--message" in cmd
    assert "Fix the login bug" in cmd
    assert output == "Changes applied."


def test_aider_engine_run_passes_env_vars():
    from engines.aider import AiderEngine
    import os
    with patch("engines.aider.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        AiderEngine().run(Path("/tmp/repo"), "prompt", _mock_settings())
    env = mock_run.call_args[1]["env"]
    assert env["OPENAI_API_BASE"] == "http://localhost:11434/v1"
    assert env["OPENAI_API_KEY"] == "local"


def test_aider_engine_run_verbose_logs(caplog):
    import logging
    from engines.aider import AiderEngine
    s = _mock_settings()
    s.aider_verbose = True
    with patch("engines.aider.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="aider said something", stderr="", returncode=0)
        with caplog.at_level(logging.INFO, logger="engines.aider"):
            AiderEngine().run(Path("/tmp/repo"), "prompt", s)
    assert "aider said something" in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_engines.py::test_aider_engine_name -v
```

Expected: `ModuleNotFoundError: No module named 'engines.aider'`

- [ ] **Step 3: Create `engines/aider.py`**

```python
# engines/aider.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_engines.py -v
```

Expected: all 7 tests PASS

---

### Task 3: OpenCodeEngine

**Files:**
- Create: `engines/opencode.py`
- Test: `tests/test_engines.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engines.py`:

```python
def test_opencode_engine_name():
    from engines.opencode import OpenCodeEngine
    assert OpenCodeEngine().name == "opencode"


def test_opencode_engine_run_calls_opencode_binary():
    from engines.opencode import OpenCodeEngine
    with patch("engines.opencode.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="Done.", stderr="", returncode=0)
        output = OpenCodeEngine().run(Path("/tmp/repo"), "Fix the login bug", _mock_settings())
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "opencode"
    assert output == "Done."


def test_opencode_engine_run_passes_env_vars():
    from engines.opencode import OpenCodeEngine
    with patch("engines.opencode.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        OpenCodeEngine().run(Path("/tmp/repo"), "prompt", _mock_settings())
    env = mock_run.call_args[1]["env"]
    assert env["OPENAI_BASE_URL"] == "http://localhost:11434/v1"
    assert env["OPENAI_API_KEY"] == "local"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_engines.py::test_opencode_engine_name -v
```

Expected: `ModuleNotFoundError: No module named 'engines.opencode'`

- [ ] **Step 3: Create `engines/opencode.py`**

OpenCode reads its LLM config from environment variables. It is invoked with `--message` for non-interactive use, similar to Aider. Note: `OPENAI_BASE_URL` (not `OPENAI_API_BASE`) is the env var OpenCode expects.

```python
# engines/opencode.py
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
                "--model", settings.openai_model,
                "--message", prompt,
            ],
            cwd=str(repo_path),
            env={
                **os.environ,
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_engines.py -v
```

Expected: all 10 tests PASS

---

### Task 4: Engine factory

**Files:**
- Modify: `engines/__init__.py`
- Test: `tests/test_engines.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engines.py`:

```python
def test_get_engine_returns_aider_by_default():
    from engines import get_engine
    from engines.aider import AiderEngine
    assert isinstance(get_engine("aider"), AiderEngine)


def test_get_engine_returns_opencode():
    from engines import get_engine
    from engines.opencode import OpenCodeEngine
    assert isinstance(get_engine("opencode"), OpenCodeEngine)


def test_get_engine_unknown_name_falls_back_to_aider():
    from engines import get_engine
    from engines.aider import AiderEngine
    assert isinstance(get_engine("some-unknown-engine"), AiderEngine)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_engines.py::test_get_engine_returns_aider_by_default -v
```

Expected: `ImportError: cannot import name 'get_engine' from 'engines'`

- [ ] **Step 3: Write the factory in `engines/__init__.py`**

```python
# engines/__init__.py
import logging

from engines.base import AgentEngine
from engines.aider import AiderEngine
from engines.opencode import OpenCodeEngine

logger = logging.getLogger(__name__)

_ENGINES: dict[str, type[AgentEngine]] = {
    "aider": AiderEngine,
    "opencode": OpenCodeEngine,
}


def get_engine(name: str) -> AgentEngine:
    engine_cls = _ENGINES.get(name)
    if engine_cls is None:
        logger.warning("Unknown engine %r — falling back to AiderEngine", name)
        return AiderEngine()
    return engine_cls()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_engines.py -v
```

Expected: all 13 tests PASS

---

### Task 5: Platform `get_labels`

**Files:**
- Modify: `platforms/base.py`
- Modify: `platforms/github.py`
- Modify: `platforms/gitlab.py`
- Test: `tests/test_platforms/test_github.py` (append)
- Test: `tests/test_platforms/test_gitlab.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_platforms/test_github.py`:

```python
def test_get_labels_returns_list(platform, mock_repo):
    mock_issue = MagicMock()
    lbl1 = MagicMock()
    lbl1.name = "agent: aider"
    lbl2 = MagicMock()
    lbl2.name = "ai: processing"
    mock_issue.labels = [lbl1, lbl2]
    mock_repo.get_issue.return_value = mock_issue

    labels = platform.get_labels(42)
    assert labels == ["agent: aider", "ai: processing"]


def test_get_labels_empty_when_no_labels(platform, mock_repo):
    mock_issue = MagicMock()
    mock_issue.labels = []
    mock_repo.get_issue.return_value = mock_issue

    labels = platform.get_labels(42)
    assert labels == []
```

Append to `tests/test_platforms/test_gitlab.py`:

```python
def test_get_labels_returns_list(platform, mock_project):
    gl_issue = MagicMock()
    gl_issue.labels = ["agent: opencode", "ai: done"]
    mock_project.issues.list.return_value = [gl_issue]

    labels = platform.get_labels(7)
    assert labels == ["agent: opencode", "ai: done"]


def test_get_labels_returns_empty_when_issue_not_found(platform, mock_project):
    mock_project.issues.list.return_value = []

    labels = platform.get_labels(999)
    assert labels == []


def test_get_labels_returns_empty_when_labels_is_none(platform, mock_project):
    gl_issue = MagicMock()
    gl_issue.labels = None
    mock_project.issues.list.return_value = [gl_issue]

    labels = platform.get_labels(7)
    assert labels == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_platforms/ -v -k "get_labels"
```

Expected: `AttributeError: 'GitHubPlatform' object has no attribute 'get_labels'`

- [ ] **Step 3: Add `get_labels` to the ABC**

In `platforms/base.py`, add after `remove_label`:

```python
@abstractmethod
def get_labels(self, issue_number: int) -> list[str]:
    """Return the names of all labels on the issue."""
    ...
```

- [ ] **Step 4: Implement `get_labels` in `platforms/github.py`**

Add after `remove_label`:

```python
def get_labels(self, issue_number: int) -> list[str]:
    return [label.name for label in self._repo.get_issue(issue_number).labels]
```

- [ ] **Step 5: Implement `get_labels` in `platforms/gitlab.py`**

Add after `remove_label`:

```python
def get_labels(self, issue_number: int) -> list[str]:
    issues = self._project.issues.list(iid=issue_number)
    return list(issues[0].labels or []) if issues else []
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_platforms/ -v
```

Expected: all platform tests PASS (including the new 5 tests)

---

### Task 6: Config — add `default_agent`

**Files:**
- Modify: `config.py`
- Test: `tests/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_default_agent_defaults_to_aider():
    from config import Settings
    s = Settings(
        platform="github",
        repo_url="https://github.com/owner/repo",
        github_token="ghp_test",
        webhook_secret="secret",
        openai_api_base="http://localhost/v1",
        _env_file=None,
    )
    assert s.default_agent == "aider"


def test_default_agent_can_be_set():
    from config import Settings
    s = Settings(
        platform="github",
        repo_url="https://github.com/owner/repo",
        github_token="ghp_test",
        webhook_secret="secret",
        openai_api_base="http://localhost/v1",
        default_agent="opencode",
        _env_file=None,
    )
    assert s.default_agent == "opencode"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py::test_default_agent_defaults_to_aider -v
```

Expected: `ValidationError` or `TypeError` because `default_agent` field doesn't exist yet

- [ ] **Step 3: Add `default_agent` to `config.py`**

In `config.py`, add after `aider_verbose`:

```python
default_agent: str = "aider"
```

Full `Settings` class after change:

```python
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
    test_cmd: str = ""
    aider_verbose: bool = False
    default_agent: str = "aider"

    model_config = {"env_file": ".env"}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: all config tests PASS

---

### Task 7: Update `agent.py` — accept engine parameter

**Files:**
- Modify: `agent.py` (accept `engine` param; remove `_run_aider`)
- Test: `tests/test_agent.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent.py`:

```python
def test_run_agent_uses_provided_engine():
    """run_agent must call engine.run, not a hard-coded aider subprocess."""
    from unittest.mock import MagicMock, patch
    from pathlib import Path
    from agent import run_agent

    mock_engine = MagicMock()
    mock_engine.run.return_value = "Engine output"

    settings = MagicMock()
    settings.test_cmd = ""
    settings.max_retries = 3
    settings.repo_url = "https://github.com/owner/repo"
    settings.platform = "github"
    settings.github_token = "ghp_test"

    with patch("agent._prepare_repo"), \
         patch("agent._configure_git_user"), \
         patch("agent._git_head", return_value="abc123"):
        success, _, initial, err = run_agent(
            issue_number=1,
            issue_title="Test",
            issue_body="Body",
            branch="ai/issue-1-test",
            settings=settings,
            engine=mock_engine,
        )

    assert success is True
    mock_engine.run.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_agent.py::test_run_agent_uses_provided_engine -v
```

Expected: `TypeError: run_agent() got an unexpected keyword argument 'engine'`

- [ ] **Step 3: Update `agent.py`**

Add `from engines.base import AgentEngine` to imports (add after `from config import Settings`):

```python
from engines.base import AgentEngine
```

Change `run_agent` signature and body. Replace the old function with:

```python
def run_agent(
    issue_number: int,
    issue_title: str,
    issue_body: str,
    branch: str,
    settings: Settings,
    engine: AgentEngine,
) -> tuple[bool, str, str, str]:
    """
    Clone repo, run engine, retry on test failure.
    Returns (success, repo_path, initial_commit, error_msg).
    Synchronous — caller must use asyncio.to_thread.
    """
    repo_path = WORK_DIR / str(issue_number)
    _prepare_repo(repo_path, branch, settings)
    _configure_git_user(repo_path)
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
```

Remove the entire `_run_aider` function (lines 133–156 in the original).

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_agent.py -v
```

Expected: all agent tests PASS

---

### Task 8: Update `worker.py` — read labels, pick engine

**Files:**
- Modify: `worker.py`
- Test: `tests/test_worker.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_worker.py`:

```python
def test_pick_engine_selects_aider_by_label():
    from worker import _pick_engine
    from engines.aider import AiderEngine
    settings = MagicMock()
    settings.default_agent = "aider"
    engine = _pick_engine(["ai: processing", "agent: aider", "bug"], settings)
    assert isinstance(engine, AiderEngine)


def test_pick_engine_selects_opencode_by_label():
    from worker import _pick_engine
    from engines.opencode import OpenCodeEngine
    settings = MagicMock()
    settings.default_agent = "aider"
    engine = _pick_engine(["agent: opencode"], settings)
    assert isinstance(engine, OpenCodeEngine)


def test_pick_engine_uses_default_when_no_agent_label():
    from worker import _pick_engine
    from engines.aider import AiderEngine
    settings = MagicMock()
    settings.default_agent = "aider"
    engine = _pick_engine(["bug", "ai: done"], settings)
    assert isinstance(engine, AiderEngine)


def test_pick_engine_unknown_label_falls_back_to_aider():
    from worker import _pick_engine
    from engines.aider import AiderEngine
    settings = MagicMock()
    settings.default_agent = "aider"
    engine = _pick_engine(["agent: nonexistent"], settings)
    assert isinstance(engine, AiderEngine)
```

These tests import `MagicMock`; add `from unittest.mock import MagicMock` to the top of `tests/test_worker.py` if it's not already there. (Current `test_worker.py` only imports `pytest` and `_slugify` — add the import.)

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_worker.py::test_pick_engine_selects_aider_by_label -v
```

Expected: `ImportError: cannot import name '_pick_engine' from 'worker'`

- [ ] **Step 3: Update `worker.py`**

At the top of `worker.py`, add imports:

```python
from engines import get_engine
from engines.base import AgentEngine
```

Add `_pick_engine` helper after the `_LABEL_*` constants:

```python
def _pick_engine(labels: list[str], settings: Settings) -> AgentEngine:
    for label in labels:
        if label.startswith("agent: "):
            engine_name = label[len("agent: "):]
            return get_engine(engine_name)
    return get_engine(settings.default_agent)
```

In `_process_job`, read labels and pass the engine to `run_agent`. Replace the current start of `_process_job`:

```python
async def _process_job(job: Job, settings: Settings) -> None:
    platform = create_platform(settings)
    branch = f"ai/issue-{job.issue_number}-{_slugify(job.title)}"
    logger.info("Processing issue #%d on branch %s", job.issue_number, branch)

    labels = platform.get_labels(job.issue_number)
    engine = _pick_engine(labels, settings)
    logger.info("Using engine %r for issue #%d", engine.name, job.issue_number)

    platform.set_label(job.issue_number, _LABEL_PROCESSING)

    success, repo_path, initial_commit, error_msg = await asyncio.to_thread(
        run_agent,
        issue_number=job.issue_number,
        issue_title=job.title,
        issue_body=job.body,
        branch=branch,
        settings=settings,
        engine=engine,
    )
    # ... rest of function unchanged
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_worker.py -v
```

Expected: all worker tests PASS

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
pytest -v
```

Expected: all existing tests still PASS

---

### Task 9: Update `server.py` — handle `labeled` webhook events

**Files:**
- Modify: `server.py`
- Test: `tests/test_server.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_server.py`:

```python
GITHUB_AGENT_LABELED = {
    "action": "labeled",
    "label": {"name": "agent: opencode"},
    "issue": {"number": 42, "title": "Fix bug", "body": "There is a bug"},
}

GITHUB_NON_AGENT_LABELED = {
    "action": "labeled",
    "label": {"name": "bug"},
    "issue": {"number": 42, "title": "Fix bug", "body": "There is a bug"},
}

GITLAB_LABEL_UPDATED = {
    "object_kind": "issue",
    "object_attributes": {
        "iid": 7,
        "title": "Fix bug",
        "description": "There is a bug",
        "action": "update",
    },
    "changes": {
        "labels": {
            "previous": [],
            "current": [{"id": 1, "title": "agent: opencode"}],
        }
    },
}

GITLAB_NON_AGENT_LABEL_UPDATED = {
    "object_kind": "issue",
    "object_attributes": {
        "iid": 7,
        "title": "Fix bug",
        "description": "There is a bug",
        "action": "update",
    },
    "changes": {
        "labels": {
            "previous": [],
            "current": [{"id": 2, "title": "priority: high"}],
        }
    },
}


def test_github_agent_label_added_queues_job(client):
    body = json.dumps(GITHUB_AGENT_LABELED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()


def test_github_non_agent_label_added_is_ignored(client):
    body = json.dumps(GITHUB_NON_AGENT_LABELED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    mock_enqueue.assert_not_called()


def test_gitlab_agent_label_added_queues_job(client):
    body = json.dumps(GITLAB_LABEL_UPDATED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/gitlab",
            content=body,
            headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()


def test_gitlab_non_agent_label_update_is_ignored(client):
    body = json.dumps(GITLAB_NON_AGENT_LABEL_UPDATED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/gitlab",
            content=body,
            headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    mock_enqueue.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_server.py::test_github_agent_label_added_queues_job -v
```

Expected: `AssertionError: assert 'ignored' == 'queued'` (current code ignores all non-`opened` actions)

- [ ] **Step 3: Update `server.py` GitHub webhook handler**

Replace the current `github_webhook` function body:

```python
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

    return {"status": "ignored"}
```

- [ ] **Step 4: Update `server.py` GitLab webhook handler**

Replace the current `gitlab_webhook` function body:

```python
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

    return {"status": "ignored"}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_server.py -v
```

Expected: all server tests PASS (including the 4 new + all pre-existing tests)

- [ ] **Step 6: Run full test suite**

```bash
pytest -v
```

Expected: all tests PASS with no regressions

---

## Note on Commits

> **This session:** The user has requested no git commits during implementation. Skip commit steps while implementing in this session.

---

## Self-Review Checklist

After writing this plan, verifying against the design spec:

- [x] **AgentEngine ABC** → Task 1
- [x] **AiderEngine (extracted from agent.py)** → Task 2
- [x] **OpenCodeEngine** → Task 3
- [x] **Engine factory with fallback** → Task 4
- [x] **`get_labels` on both platforms** → Task 5
- [x] **`default_agent` config field** → Task 6
- [x] **`agent.py` accepts engine param** → Task 7; `_run_aider` removed in Task 7
- [x] **`worker.py` reads labels, picks engine, passes to run_agent** → Task 8
- [x] **GitHub `labeled` webhook → re-enqueue** → Task 9
- [x] **GitLab label-update webhook → re-enqueue** → Task 9
- [x] **Unknown engine falls back gracefully** → Task 4 (factory fallback)
- [x] **Binary not found → propagates as exception → worker posts comment** → covered by existing worker error handler; no extra task needed
- [x] **All tasks have TDD steps (write failing test, implement, verify passing)** → yes
- [x] **No placeholders or TBD** → verified
- [x] **Type consistency** — `AgentEngine` ABC defined in Task 1, used in Tasks 2–3 (implementations), Task 4 (factory return type), Task 7 (`agent.py` param), Task 8 (`worker.py` usage) — all consistent
