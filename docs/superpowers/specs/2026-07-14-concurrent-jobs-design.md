# Concurrent Job Processing — Design

**Date:** 2026-07-14
**Branch:** `feature/concurrent-jobs` (not to be merged to master as part of this work)

## Goal

Process up to `MAX_CONCURRENT_JOBS` webhook jobs in parallel (default 3,
configurable via `.env`), while jobs that target the same issue never overlap.

## Background

Today `server.py` spawns exactly one `start_worker` task, which drains an
in-memory `asyncio.Queue` strictly serially. Making that loop concurrent
exposes three shared-state hazards:

1. **Work dir reuse** — `agent.py` clones into
   `WORK_DIR/{repo-slug}-{issue_number}`. Two jobs on the same issue
   (initial run + rework, duplicate webhooks) would corrupt each other's
   checkout.
2. **Issue-level side effects** — label swaps, comments, and branch pushes
   for the same issue would interleave.
3. **Claude Code router** — `engines/claudecode.py` starts the ccr router on
   one fixed port with one shared sandbox HOME and pid file, and terminates
   it in `finally`. With two concurrent claudecode jobs, one job kills the
   router mid-flight for the other, and the pid file races.

Aider and OpenCode engines are already concurrency-safe: they run per-repo
subprocesses with no shared mutable state (OpenCode rewrites an identical
config file each run, which is an idempotent race).

## Design

### 1. Worker pool

- `config.py`: new setting `max_concurrent_jobs: int = 3`.
- `worker.py`: new coroutine `start_workers(settings)` that performs the
  one-time init (set `_settings_ref`, `cleanup_old_repos()`), then spawns
  `max_concurrent_jobs` copies of the existing worker loop as tasks and
  awaits them (`asyncio.gather`).
- `server.py` lifespan starts `start_workers` instead of `start_worker`;
  cancelling the parent task on shutdown propagates to all worker loops.
- The queue, `enqueue_job`, and webhook handlers are unchanged.

### 2. Per-issue serialization (keyed locks)

- New refcounted keyed-lock helper in `worker.py`:
  `async with job_locks.acquire((platform, repo_url, issue_number)): ...`
- Each worker wraps the *entire* processing of a job
  (`_process_job` / `_process_rework_job`, including label swaps and error
  handling) in this lock.
- Lock entries are refcounted and removed when no longer held, so the dict
  does not grow unboundedly.
- Different issues — including different issues on the same repo — take
  different keys and run fully in parallel (distinct work dirs, distinct
  branches).
- Accepted trade-off: a duplicate same-issue job blocks one worker slot
  while it waits for the lock. At the default pool size of 3 this is fine.

### 3. Claude Code router: shared persistent singleton

- Engine runs execute in threads (`asyncio.to_thread`), so lifecycle is
  guarded by a module-level `threading.Lock`.
- New `_ensure_router(settings)`, called at the start of every run, under
  the lock:
  - write the router config (settings-derived, identical for every job);
  - if the port is open but owned by a foreign process (no pid file /
    dead pid), raise the same `RuntimeError` as today;
  - if the router is not running, start ccr, write the pid file, and wait
    for the port;
  - otherwise reuse the running router.
- Runs **never** terminate the router. If it crashed, the next run's
  `_ensure_router` restarts it.
- New `shutdown_router()` terminates the router only if we started it
  (pid file check). Called from the server lifespan on shutdown, with an
  `atexit` fallback for non-server usage.
- The `/api/test-engine` smoke runs go through the same path and therefore
  share the router safely.

### 4. SQLite hardening

- `store.py`: pass `timeout=30` to every `sqlite3.connect` so concurrent
  status writes wait instead of raising `database is locked`. WAL mode is
  already enabled.

### 5. Out of scope

- The queue stays in-memory. Jobs that are queued but not started are lost
  on restart — a pre-existing property, unchanged by this work. A
  DB-backed queue was considered (approach C) and deferred.
- No per-engine concurrency limits; the single global pool bounds load on
  the LLM endpoint.

## Error handling

Unchanged per job: each worker loop catches all exceptions for a job,
labels the issue `ai: failed`, posts a comment, and continues. Worker loops
only exit on cancellation.

## Testing

New tests:

- Keyed-lock helper: exclusion per key, independence across keys, entry
  cleanup after release.
- Worker pool: two jobs on *different* issues demonstrably overlap (slow
  fake processing, assert concurrency observed); two jobs on the *same*
  issue serialize.
- Claude Code router: concurrent runs start ccr exactly once; a run no
  longer terminates the router; `shutdown_router()` terminates a router we
  started and is a no-op otherwise; foreign-port refusal preserved.

Updated tests:

- `tests/test_engines.py` router-lifecycle tests (start/terminate moved out
  of `run`).
- `tests/test_worker.py` / `tests/test_server.py` for the
  `start_worker` → `start_workers` change.
