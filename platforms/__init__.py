from .base import GitPlatform, Issue
from .github import GitHubPlatform
from .gitlab import GitLabPlatform


def create_platform(settings) -> GitPlatform:
    if settings.platform == "github":
        return GitHubPlatform(token=settings.github_token, repo_url=settings.repo_url)
    if settings.platform == "gitlab":
        return GitLabPlatform(token=settings.gitlab_token, repo_url=settings.repo_url)
    raise ValueError(f"Unknown platform: {settings.platform}")
