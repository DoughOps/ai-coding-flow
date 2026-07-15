import asyncio

import pytest
from unittest.mock import MagicMock, patch

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


def test_pick_engine_unknown_label_falls_back_to_opencode():
    from worker import _pick_engine
    from engines.opencode import OpenCodeEngine
    settings = MagicMock()
    settings.default_agent = "aider"
    engine = _pick_engine(["agent: nonexistent"], settings)
    assert isinstance(engine, OpenCodeEngine)


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


def test_process_rework_job_posts_completion_comment():
    from worker import Job, _process_rework_job

    job = Job(
        platform="github",
        repo_url="https://github.com/owner/repo",
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
        repo_url="https://github.com/owner/repo",
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


def test_settings_rejects_nonpositive_max_concurrent_jobs(monkeypatch):
    import pydantic
    monkeypatch.setenv("WEBHOOK_SECRET", "x")
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    from config import Settings
    with pytest.raises(pydantic.ValidationError):
        Settings(_env_file=None, max_concurrent_jobs=0)
