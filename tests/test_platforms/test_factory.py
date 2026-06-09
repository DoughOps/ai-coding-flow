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
        create_platform("github", "https://github.com/owner/repo", settings)
        mock_cls.assert_called_once_with(
            token="ghp_test",
            repo_url="https://github.com/owner/repo",
        )


def test_factory_returns_gitlab_platform():
    settings = _make_settings("gitlab")
    settings.repo_url = "https://gitlab.example.com/owner/repo"
    with patch("platforms.GitLabPlatform") as mock_cls:
        from platforms import create_platform
        create_platform("gitlab", "https://gitlab.example.com/owner/repo", settings)
        mock_cls.assert_called_once_with(
            token="glpat_test",
            repo_url="https://gitlab.example.com/owner/repo",
        )


def test_factory_raises_on_unknown_platform():
    settings = _make_settings("bitbucket")
    from platforms import create_platform
    with pytest.raises(ValueError, match="Unknown platform"):
        create_platform("bitbucket", "https://github.com/owner/repo", settings)
