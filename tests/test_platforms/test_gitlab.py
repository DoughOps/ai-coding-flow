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
