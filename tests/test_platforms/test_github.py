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


def test_get_labels_returns_empty_when_issue_not_found(platform, mock_repo):
    mock_repo.get_issue.side_effect = Exception("Not found")

    labels = platform.get_labels(999)
    assert labels == []
