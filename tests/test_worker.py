import asyncio
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
