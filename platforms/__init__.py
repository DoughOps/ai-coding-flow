from .base import GitPlatform, Issue
from .github import GitHubPlatform
from .gitlab import GitLabPlatform


def create_platform(platform: str, repo_url: str, settings) -> GitPlatform:
    if platform == "github":
        return GitHubPlatform(token=settings.github_token, repo_url=repo_url)
    if platform == "gitlab":
        return GitLabPlatform(token=settings.gitlab_token, repo_url=repo_url)
    raise ValueError(f"Unknown platform: {platform}")
