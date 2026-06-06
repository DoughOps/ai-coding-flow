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
