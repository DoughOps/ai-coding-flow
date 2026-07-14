from unittest.mock import MagicMock, patch
import pytest
from gitlab.exceptions import GitlabGetError
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


def _not_found():
    return GitlabGetError("404 Issue Not Found", response_code=404)


def test_ssl_verify_setting_is_passed_to_client():
    with patch("platforms.gitlab.gitlab.Gitlab") as mock_gl_cls:
        from platforms.gitlab import GitLabPlatform
        GitLabPlatform(
            token="glpat-test",
            repo_url="https://gitlab.example.com/owner/repo",
            verify_ssl=True,
        )
    mock_gl_cls.assert_called_once_with(
        "https://gitlab.example.com",
        private_token="glpat-test",
        ssl_verify=True,
    )


def test_ssl_verify_disabled_is_passed_to_client():
    with patch("platforms.gitlab.gitlab.Gitlab") as mock_gl_cls:
        from platforms.gitlab import GitLabPlatform
        GitLabPlatform(
            token="glpat-test",
            repo_url="https://gitlab.example.com/owner/repo",
            verify_ssl=False,
        )
    assert mock_gl_cls.call_args.kwargs["ssl_verify"] is False


def test_get_issue_returns_issue(platform, mock_project):
    gl_issue = MagicMock()
    gl_issue.iid = 7
    gl_issue.title = "Fix the bug"
    gl_issue.description = "There is a bug"
    gl_issue.web_url = "https://gitlab.example.com/owner/repo/-/issues/7"
    mock_project.issues.get.return_value = gl_issue

    issue = platform.get_issue(7)

    assert isinstance(issue, Issue)
    assert issue.number == 7
    assert issue.title == "Fix the bug"
    assert issue.body == "There is a bug"
    # Must fetch by iid via the project-scoped GET endpoint. Filtering the
    # list endpoint with iid= is silently ignored by GitLab and returns the
    # newest issue instead (regression: rework on issue 7 hit issue 8).
    mock_project.issues.get.assert_called_once_with(7)
    mock_project.issues.list.assert_not_called()


def test_get_issue_none_description_becomes_empty_string(platform, mock_project):
    gl_issue = MagicMock()
    gl_issue.iid = 1
    gl_issue.title = "No desc"
    gl_issue.description = None
    gl_issue.web_url = "https://gitlab.example.com/owner/repo/-/issues/1"
    mock_project.issues.get.return_value = gl_issue

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
    mock_project.issues.get.return_value = gl_issue

    platform.post_comment(7, "AI review comment")

    mock_project.issues.get.assert_called_once_with(7)
    gl_issue.notes.create.assert_called_once_with({"body": "AI review comment"})


def test_get_issue_not_found_raises(platform, mock_project):
    mock_project.issues.get.side_effect = _not_found()
    with pytest.raises(ValueError, match="Issue #99 not found"):
        platform.get_issue(99)


def test_post_comment_not_found_raises(platform, mock_project):
    mock_project.issues.get.side_effect = _not_found()
    with pytest.raises(ValueError, match="Issue #99 not found"):
        platform.post_comment(99, "comment")


def test_set_label_adds_label(platform, mock_project):
    gl_issue = MagicMock()
    gl_issue.labels = ["existing"]
    mock_project.issues.get.return_value = gl_issue

    platform.set_label(7, "ai: processing")

    mock_project.issues.get.assert_called_once_with(7)
    assert gl_issue.labels == ["existing", "ai: processing"]
    gl_issue.save.assert_called_once()


def test_set_label_not_found_is_noop(platform, mock_project):
    mock_project.issues.get.side_effect = _not_found()
    platform.set_label(999, "ai: processing")  # must not raise


def test_remove_label_removes_label(platform, mock_project):
    gl_issue = MagicMock()
    gl_issue.labels = ["ai: processing", "other"]
    mock_project.issues.get.return_value = gl_issue

    platform.remove_label(7, "ai: processing")

    assert gl_issue.labels == ["other"]
    gl_issue.save.assert_called_once()


def test_remove_label_not_found_is_noop(platform, mock_project):
    mock_project.issues.get.side_effect = _not_found()
    platform.remove_label(999, "ai: processing")  # must not raise


def test_get_labels_returns_list(platform, mock_project):
    gl_issue = MagicMock()
    gl_issue.labels = ["agent: opencode", "ai: done"]
    mock_project.issues.get.return_value = gl_issue

    labels = platform.get_labels(7)
    assert labels == ["agent: opencode", "ai: done"]
    mock_project.issues.get.assert_called_once_with(7)


def test_get_labels_returns_empty_when_issue_not_found(platform, mock_project):
    mock_project.issues.get.side_effect = _not_found()

    labels = platform.get_labels(999)
    assert labels == []


def test_get_labels_returns_empty_when_labels_is_none(platform, mock_project):
    gl_issue = MagicMock()
    gl_issue.labels = None
    mock_project.issues.get.return_value = gl_issue

    labels = platform.get_labels(7)
    assert labels == []
