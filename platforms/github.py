from github import Github
from .base import GitPlatform, Issue


class GitHubPlatform(GitPlatform):
    def __init__(self, token: str, repo_url: str) -> None:
        self._gh = Github(token)
        parts = repo_url.rstrip("/").rstrip(".git").split("/")
        self._repo = self._gh.get_repo(f"{parts[-2]}/{parts[-1]}")

    def get_issue(self, number: int) -> Issue:
        gh_issue = self._repo.get_issue(number)
        return Issue(
            number=gh_issue.number,
            title=gh_issue.title,
            body=gh_issue.body or "",
            url=gh_issue.html_url,
        )

    def create_pr(self, branch: str, title: str, body: str) -> str:
        pr = self._repo.create_pull(
            title=title,
            body=body,
            head=branch,
            base=self._repo.default_branch,
        )
        return pr.html_url

    def post_comment(self, issue_number: int, body: str) -> None:
        issue = self._repo.get_issue(issue_number)
        issue.create_comment(body)

    def set_label(self, issue_number: int, label: str) -> None:
        try:
            self._repo.get_label(label)
        except Exception:
            self._repo.create_label(label, "ededed")
        self._repo.get_issue(issue_number).add_to_labels(label)

    def remove_label(self, issue_number: int, label: str) -> None:
        try:
            self._repo.get_issue(issue_number).remove_from_labels(label)
        except Exception:
            pass
