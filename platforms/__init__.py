from .base import GitPlatform
from .github import GitHubPlatform
from .gitlab import GitLabPlatform


def create_platform(platform: str, repo_url: str, settings) -> GitPlatform:
    if platform == "github":
        return GitHubPlatform(token=settings.github_token, repo_url=repo_url)
    if platform == "gitlab":
        # The API host is the same as the git remote, so the repo SSL
        # trust decision applies to the API client as well.
        return GitLabPlatform(
            token=settings.gitlab_token,
            repo_url=repo_url,
            verify_ssl=settings.verify_repo_ssl,
        )
    raise ValueError(f"Unknown platform: {platform}")
