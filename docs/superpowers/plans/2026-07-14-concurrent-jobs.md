# Concurrent Job Processing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Process up to `MAX_CONCURRENT_JOBS` webhook jobs in parallel (default 3), with jobs targeting the same issue strictly serialized.

**Architecture:** A pool of N asyncio worker tasks drains the existing in-memory queue. A refcounted keyed lock serializes jobs sharing a `(platform, repo_url, issue_number)` key. The Claude Code ccr router becomes a process-wide singleton guarded by a `threading.Lock`, started on first use and shut down with the server instead of per-run.

**Tech Stack:** Python 3.11+, asyncio, FastAPI, pytest, sqlite3 (WAL).

**Spec:** `docs/superpowers/specs/2026-07-14-concurrent-jobs-design.md`

## Global Constraints

- All work happens on branch `feature/concurrent-jobs`. **Never merge to master.**
- Default pool size is exactly **3**; setting name is `max_concurrent_jobs` (env var `MAX_CONCURRENT_JOBS`).
- The webhook handlers, `enqueue_job`, and the in-memory `asyncio.Queue` must not change behavior.
- Run tests with `pytest` from the repo root (`/home/neverleave0916/workspace/ai-test`). The venv is `.venv`; activate or use `.venv/bin/pytest` if plain `pytest` is missing.
- Commit after every green task with the trailer lines shown in Task 1 Step 5 (same trailers every commit).

---

### Task 1: Refcounted keyed lock (`_KeyedLocks`) in worker.py

**Files:**
- Modify: `worker.py` (add class near top, after the `Job` dataclass)
- Test: `tests/test_worker.py` (append)

**Interfaces:**
- Produces: class `_KeyedLocks` with `acquire(key) -> async context manager`; module-level instance `job_locks = _KeyedLocks()`. Task 2 wraps job processing in `job_locks.acquire((job.platform, job.repo_url, job.issue_number))`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_worker.py`:

```python
# ── _KeyedLocks ───────────────────────────────────────────────────────────────

def test_keyed_locks_same_key_serializes():
    from worker import _KeyedLocks

    async def main():
        locks = _KeyedLocks()
        events = []

        async def hold(name):
            async with locks.acquire("issue-1"):
                events.append(f"{name}-enter")
                await asyncio.sleep(0.02)
                events.append(f"{name}-exit")

        await asyncio.gather(hold("a"), hold("b"))
        # Whoever enters first must exit before the other enters.
        assert events[1].endswith("-exit")
        assert events[0][0] == events[1][0]

    asyncio.run(main())


def test_keyed_locks_different_keys_run_concurrently():
    from worker import _KeyedLocks

    async def main():
        locks = _KeyedLocks()
        running = 0
        max_running = 0

        async def hold(key):
            nonlocal running, max_running
            async with locks.acquire(key):
                running += 1
                max_running = max(max_running, running)
                await asyncio.sleep(0.02)
                running -= 1

        await asyncio.gather(hold("k1"), hold("k2"))
        assert max_running == 2

    asyncio.run(main())


def test_keyed_locks_entries_removed_after_release():
    from worker import _KeyedLocks

    async def main():
        locks = _KeyedLocks()
        async with locks.acquire("k"):
            assert "k" in locks._locks
        assert locks._locks == {}
        assert locks._refcounts == {}

    asyncio.run(main())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_worker.py -k keyed_locks -v`
Expected: 3 FAILED / ERROR with `ImportError: cannot import name '_KeyedLocks'`

- [ ] **Step 3: Implement `_KeyedLocks`**

In `worker.py`, add `from contextlib import asynccontextmanager` to the imports, then insert after the `Job` dataclass (before `_queue = asyncio.Queue()`):

```python
class _KeyedLocks:
    """Serialize coroutines sharing a key; independent keys don't contend.

    Entries are refcounted and removed once no coroutine holds or awaits
    the key, so the dict can't grow unboundedly. Safe without extra locking
    because all mutation happens synchronously on the event loop thread.
    """

    def __init__(self) -> None:
        self._locks: dict = {}
        self._refcounts: dict = {}

    @asynccontextmanager
    async def acquire(self, key):
        self._refcounts[key] = self._refcounts.get(key, 0) + 1
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                yield
        finally:
            self._refcounts[key] -= 1
            if self._refcounts[key] == 0:
                del self._refcounts[key]
                del self._locks[key]


job_locks = _KeyedLocks()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_worker.py -v`
Expected: all PASS (new 3 plus the existing ones)

- [ ] **Step 5: Commit**

```bash
git add worker.py tests/test_worker.py
git commit -m "feat: add refcounted keyed lock for per-issue serialization

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01B8znQSzUuCiyRnEWXHpnT4"
```

---

### Task 2: Worker pool with per-issue locking

**Files:**
- Modify: `config.py` (add setting), `worker.py` (replace `start_worker` with `_worker_loop` + `start_workers`), `server.py:20,40` (import + task)
- Test: `tests/test_worker.py`, `tests/test_config.py` if present — otherwise put the settings test in `tests/test_worker.py`

**Interfaces:**
- Consumes: `job_locks` from Task 1.
- Produces: `async def start_workers(settings: Settings) -> None` (replaces `start_worker`; `start_worker` is deleted). New setting `Settings.max_concurrent_jobs: int = 3`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_worker.py`:

```python
# ── worker pool ───────────────────────────────────────────────────────────────

def _pool_settings():
    settings = MagicMock()
    settings.max_concurrent_jobs = 3
    settings.db_path = ":memory:"
    return settings


def _job(issue_number, repo_url="https://github.com/owner/repo"):
    from worker import Job
    return Job(
        platform="github",
        repo_url=repo_url,
        issue_number=issue_number,
        title=f"Issue {issue_number}",
        body="body",
    )


def _run_pool(jobs, fake_process):
    """Start the worker pool, feed it jobs, wait for them all, tear down."""
    import worker

    async def main():
        worker._queue = asyncio.Queue()
        for job in jobs:
            await worker._queue.put(job)
        with patch("worker.cleanup_old_repos"), \
             patch("worker._process_job", side_effect=fake_process), \
             patch("worker._process_rework_job", side_effect=fake_process):
            pool = asyncio.create_task(worker.start_workers(_pool_settings()))
            await asyncio.wait_for(worker._queue.join(), timeout=5)
            pool.cancel()
            try:
                await pool
            except asyncio.CancelledError:
                pass

    asyncio.run(main())


def test_pool_runs_different_issues_concurrently():
    state = {"running": 0, "max_running": 0}

    async def fake_process(job, settings):
        state["running"] += 1
        state["max_running"] = max(state["max_running"], state["running"])
        await asyncio.sleep(0.05)
        state["running"] -= 1

    _run_pool([_job(1), _job(2), _job(3)], fake_process)
    assert state["max_running"] >= 2


def test_pool_serializes_same_issue_jobs():
    state = {"running": 0, "max_running": 0}

    async def fake_process(job, settings):
        state["running"] += 1
        state["max_running"] = max(state["max_running"], state["running"])
        await asyncio.sleep(0.05)
        state["running"] -= 1

    _run_pool([_job(7), _job(7)], fake_process)
    assert state["max_running"] == 1


def test_settings_default_max_concurrent_jobs(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "x")
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    from config import Settings
    assert Settings(_env_file=None).max_concurrent_jobs == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_worker.py -k "pool or max_concurrent" -v`
Expected: FAIL — `AttributeError: <module 'worker'> does not have the attribute 'start_workers'` and the settings test fails with `AttributeError: max_concurrent_jobs`

- [ ] **Step 3: Implement**

`config.py` — directly under `max_retries: int = 3` add:

```python
    max_concurrent_jobs: int = 3
```

`worker.py` — replace the whole `start_worker` function with:

```python
async def _worker_loop(settings: Settings) -> None:
    while True:
        job = await _queue.get()
        try:
            async with job_locks.acquire((job.platform, job.repo_url, job.issue_number)):
                if job.rework_comment and job.pr_branch:
                    await _process_rework_job(job, settings)
                else:
                    await _process_job(job, settings)
        except Exception as exc:
            logger.exception("Unhandled error for issue #%d", job.issue_number)
            try:
                platform = create_platform(job.platform, job.repo_url, settings)
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


async def start_workers(settings: Settings) -> None:
    global _settings_ref
    _settings_ref = settings
    cleanup_old_repos()
    count = settings.max_concurrent_jobs
    logger.info("Starting %d worker(s)", count)
    await asyncio.gather(*(_worker_loop(settings) for _ in range(count)))
```

(The `try/except/finally` body is today's `start_worker` body unchanged — only the keyed-lock `async with` is new. Do not keep a `start_worker` alias.)

`server.py` — line 20 becomes:

```python
from worker import enqueue_job, start_workers
```

and in `lifespan` (line 40):

```python
    task = asyncio.create_task(start_workers(settings))
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: all PASS (`tests/test_server.py` never enters the lifespan, so nothing else references `start_worker`)

- [ ] **Step 5: Commit**

```bash
git add config.py worker.py server.py tests/test_worker.py
git commit -m "feat: run jobs through a concurrent worker pool with per-issue locks"
```

(with the same trailer lines as Task 1.)

---

### Task 3: Claude Code router as a shared persistent singleton

**Files:**
- Modify: `engines/claudecode.py`
- Test: `tests/test_engines.py`

**Interfaces:**
- Produces: `_ensure_router(settings) -> None` (module function, thread-safe), `shutdown_router() -> None` (module function, idempotent; Task 4 calls it from the server lifespan). Module global `_router_proc: subprocess.Popen | None`. `ClaudeCodeEngine.run` no longer starts/terminates the router inline.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engines.py` (the file already imports `os`, `json`, `pytest`, `MagicMock`, `patch`, and defines `_mock_settings()`):

```python
# ── shared persistent router ──────────────────────────────────────────────────

def _reset_router_state(claudecode, tmp_path):
    claudecode._router_proc = None
    return patch("engines.claudecode._SANDBOX_HOME", tmp_path)


def test_claudecode_second_run_reuses_router(tmp_path):
    from engines import claudecode
    from engines.claudecode import ClaudeCodeEngine
    port_open = {"value": False}

    def fake_popen(*args, **kwargs):
        port_open["value"] = True
        return MagicMock(pid=12345)

    with _reset_router_state(claudecode, tmp_path), \
         patch("engines.claudecode.subprocess.Popen", side_effect=fake_popen) as mock_popen, \
         patch("engines.claudecode.subprocess.run") as mock_run, \
         patch("engines.claudecode._wait_for_port"), \
         patch("engines.claudecode._is_port_open", side_effect=lambda h, p: port_open["value"]), \
         patch("engines.claudecode._our_router_pid", return_value=12345), \
         patch("engines.claudecode._write_router_config"):
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        engine = ClaudeCodeEngine()
        engine.run(tmp_path, "first", _mock_settings())
        engine.run(tmp_path, "second", _mock_settings())
    assert mock_popen.call_count == 1


def test_claudecode_run_does_not_terminate_router(tmp_path):
    from engines import claudecode
    from engines.claudecode import ClaudeCodeEngine
    proc = MagicMock(pid=12345)
    with _reset_router_state(claudecode, tmp_path), \
         patch("engines.claudecode.subprocess.Popen", return_value=proc), \
         patch("engines.claudecode.subprocess.run") as mock_run, \
         patch("engines.claudecode._wait_for_port"), \
         patch("engines.claudecode._is_port_open", return_value=False), \
         patch("engines.claudecode._write_router_config"):
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        ClaudeCodeEngine().run(tmp_path, "prompt", _mock_settings())
    proc.terminate.assert_not_called()
    proc.kill.assert_not_called()


def test_shutdown_router_terminates_started_router(tmp_path):
    from engines import claudecode
    proc = MagicMock(pid=12345)
    with patch("engines.claudecode._SANDBOX_HOME", tmp_path):
        claudecode._router_proc = proc
        (tmp_path / "ccr.pid").write_text("12345")
        claudecode.shutdown_router()
    proc.terminate.assert_called_once()
    assert claudecode._router_proc is None
    assert not (tmp_path / "ccr.pid").exists()


def test_shutdown_router_noop_when_not_started(tmp_path):
    from engines import claudecode
    with patch("engines.claudecode._SANDBOX_HOME", tmp_path):
        claudecode._router_proc = None
        claudecode.shutdown_router()  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_engines.py -k "reuses_router or does_not_terminate or shutdown_router" -v`
Expected: FAIL — `AttributeError: module 'engines.claudecode' has no attribute '_router_proc'` / `shutdown_router`; the terminate test fails because today's `run` calls `proc.terminate()` in `finally`

- [ ] **Step 3: Implement**

In `engines/claudecode.py`:

Add imports `atexit` and `threading` to the stdlib import block. Add module globals under `_SANDBOX_HOME`:

```python
_router_lock = threading.Lock()
_router_proc: subprocess.Popen | None = None
```

Add the two module functions (above the class):

```python
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
```

Replace `ClaudeCodeEngine.run` entirely with:

```python
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
```

Delete nothing else — `_write_router_config`, `_our_router_pid`, `_is_port_open`, `_wait_for_port`, `_ccr_binary`, `_git_commit_all` stay as they are.

- [ ] **Step 4: Run the engine test file**

Run: `pytest tests/test_engines.py -v`
Expected: all PASS. The pre-existing router tests keep passing because `_ensure_router` preserves the same observable behavior (Popen of `ccr start`, foreign-port `RuntimeError`, skip when `_our_router_pid()` is truthy, router env `HOME`). If one fails, the failure is in the new code, not the test — fix the implementation.

- [ ] **Step 5: Run the full suite and commit**

Run: `pytest -q` → all PASS

```bash
git add engines/claudecode.py tests/test_engines.py
git commit -m "feat: share one persistent ccr router across concurrent claudecode runs"
```

(with the same trailer lines as Task 1.)

---

### Task 4: Server shuts the router down on exit

**Files:**
- Modify: `server.py` (import + lifespan)
- Test: `tests/test_server.py` (append)

**Interfaces:**
- Consumes: `shutdown_router()` from Task 3, `start_workers` from Task 2.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_server.py`:

```python
def test_lifespan_shuts_down_claudecode_router(set_env):
    import importlib
    import server
    importlib.reload(server)
    with patch("server.start_workers", new=AsyncMock()), \
         patch("server.claudecode.shutdown_router") as mock_shutdown:
        with TestClient(server.app):
            pass
    mock_shutdown.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_server.py::test_lifespan_shuts_down_claudecode_router -v`
Expected: FAIL with `AttributeError: <module 'server'> does not have the attribute 'claudecode'`

- [ ] **Step 3: Implement**

`server.py` — add to the imports:

```python
from engines import claudecode
```

and extend `lifespan` so shutdown also stops the router (after the worker task is awaited):

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db(settings.db_path)
    task = asyncio.create_task(start_workers(settings))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await asyncio.to_thread(claudecode.shutdown_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_server.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat: stop shared ccr router on server shutdown"
```

(with the same trailer lines as Task 1.)

---

### Task 5: SQLite busy timeout

**Files:**
- Modify: `store.py`
- Test: `tests/test_store.py` (append)

**Interfaces:**
- Produces: module constant `_CONNECT_TIMEOUT = 30` used by every `sqlite3.connect` call in `store.py`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store.py` (check its existing imports; it already imports `store` — add `import sqlite3` and `from unittest.mock import patch` if missing):

```python
def test_all_connections_use_busy_timeout(tmp_path):
    db = str(tmp_path / "jobs.db")
    calls = []
    real_connect = sqlite3.connect

    def spy(path, *args, **kwargs):
        calls.append(kwargs)
        return real_connect(path, *args, **kwargs)

    with patch("store.sqlite3.connect", side_effect=spy):
        store.init_db(db)
        job_id = store.create_job(db, platform="github", issue_number=1, issue_title="t")
        store.update_job(db, job_id, status="done")
        store.list_jobs(db)

    assert len(calls) == 4
    assert all(kwargs.get("timeout") == 30 for kwargs in calls)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_store.py::test_all_connections_use_busy_timeout -v`
Expected: FAIL — `assert all(...)` is False (no `timeout` kwarg today)

- [ ] **Step 3: Implement**

In `store.py`, add under the imports:

```python
# Concurrent workers write job rows in parallel; wait for the write lock
# instead of raising "database is locked". WAL mode keeps readers unblocked.
_CONNECT_TIMEOUT = 30
```

and change all four `sqlite3.connect(db_path)` calls (in `init_db`, `create_job`, `update_job`, `list_jobs`) to:

```python
sqlite3.connect(db_path, timeout=_CONNECT_TIMEOUT)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_store.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add store.py tests/test_store.py
git commit -m "feat: add sqlite busy timeout for concurrent job writes"
```

(with the same trailer lines as Task 1.)

---

### Task 6: Documentation and final verification

**Files:**
- Modify: `README.md`, `.env.example`, `docs_site/index.html`

No code — docs must stop claiming serial processing.

- [ ] **Step 1: Update README.md**

Line 15 currently reads:

```markdown
- **Sequential queue** — processes one issue at a time to avoid git conflicts
```

Replace with:

```markdown
- **Concurrent queue** — runs up to `MAX_CONCURRENT_JOBS` jobs in parallel (default 3); jobs for the same issue are serialized to avoid git conflicts
```

Line 214's table row:

```markdown
| `worker.py` | asyncio job queue, orchestrates each issue |
```

Replace with:

```markdown
| `worker.py` | asyncio job queue + worker pool, orchestrates each issue |
```

Also grep README for the environment-variable table (`grep -n MAX_RETRIES README.md`); if one exists, add a `MAX_CONCURRENT_JOBS` row styled like the `MAX_RETRIES` row: name `MAX_CONCURRENT_JOBS`, default `3`, description "How many jobs run in parallel; same-issue jobs never overlap".

- [ ] **Step 2: Update .env.example**

Next to `MAX_RETRIES=3` (line 20) add:

```bash
# How many jobs may run in parallel (same-issue jobs are always serialized)
MAX_CONCURRENT_JOBS=3
```

- [ ] **Step 3: Update docs_site/index.html**

Three spots (line numbers approximate — grep for the text):

1. Line ~678, remove this limitation bullet entirely:
   `<li>Parallel issue processing — jobs run sequentially</li>`
2. Line ~1141, replace:
   `<p>FastAPI handles concurrent HTTP requests asynchronously. AI coding work runs in a thread pool via <code>asyncio.to_thread()</code>. The job queue is sequential — one issue processes at a time — to avoid git conflicts.</p>`
   with:
   `<p>FastAPI handles concurrent HTTP requests asynchronously. AI coding work runs in a thread pool via <code>asyncio.to_thread()</code>. A worker pool processes up to <code>MAX_CONCURRENT_JOBS</code> issues in parallel (default 3); jobs targeting the same issue are serialized to avoid git conflicts.</p>`
3. Line ~1649, replace:
   `<p><strong>Jobs are processed one at a time.</strong> If multiple issues are opened quickly, they queue up and run sequentially. The <span class="label-pill label-yellow">ai: processing</span> label tells you which one is active.</p>`
   with:
   `<p><strong>Up to <code>MAX_CONCURRENT_JOBS</code> jobs run at a time (default 3).</strong> Additional issues queue up, and jobs for the same issue never run simultaneously. The <span class="label-pill label-yellow">ai: processing</span> label tells you which issues are active.</p>`

- [ ] **Step 4: Full suite + final check**

Run: `pytest -q`
Expected: all PASS

Run: `git status` — working tree should only show the three doc files as modified before commit; branch must be `feature/concurrent-jobs`.

- [ ] **Step 5: Commit**

```bash
git add README.md .env.example docs_site/index.html
git commit -m "docs: describe concurrent worker pool and MAX_CONCURRENT_JOBS"
```

(with the same trailer lines as Task 1.)
