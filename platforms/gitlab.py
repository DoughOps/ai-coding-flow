import gitlab
from gitlab.exceptions import GitlabCreateError
from urllib.parse import urlparse
from .base import GitPlatform, Issue


class GitLabPlatform(GitPlatform):
    def __init__(self, token: str, repo_url: str) -> None:
        parsed = urlparse(repo_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        self._gl = gitlab.Gitlab(base_url, private_token=token, ssl_verify=False)
        project_path = parsed.path.lstrip("/").removesuffix(".git")
        self._project = self._gl.projects.get(project_path)

    def get_issue(self, number: int) -> Issue:
        issues = self._project.issues.list(iid=number)
        if not issues:
            raise ValueError(f"Issue #{number} not found")
        gl_issue = issues[0]
        return Issue(
            number=gl_issue.iid,
            title=gl_issue.title,
            body=gl_issue.description or "",
            url=gl_issue.web_url,
        )

    def create_pr(self, branch: str, title: str, body: str) -> str:
        try:
            mr = self._project.mergerequests.create({
                "source_branch": branch,
                "target_branch": self._project.default_branch,
                "title": title,
                "description": body,
            })
            return mr.web_url
        except GitlabCreateError as exc:
            if exc.response_code == 409:
                existing = self._project.mergerequests.list(
                    source_branch=branch, state="opened"
                )
                if existing:
                    return existing[0].web_url
            raise

    def post_comment(self, issue_number: int, body: str) -> None:
        issues = self._project.issues.list(iid=issue_number)
        if not issues:
            raise ValueError(f"Issue #{issue_number} not found")
        gl_issue = issues[0]
        gl_issue.notes.create({"body": body})

    def set_label(self, issue_number: int, label: str) -> None:
        issues = self._project.issues.list(iid=issue_number)
        if not issues:
            return
        gl_issue = issues[0]
        labels = list(gl_issue.labels or [])
        if label not in labels:
            labels.append(label)
            gl_issue.labels = labels
            gl_issue.save()

    def remove_label(self, issue_number: int, label: str) -> None:
        issues = self._project.issues.list(iid=issue_number)
        if not issues:
            return
        gl_issue = issues[0]
        labels = [lbl for lbl in (gl_issue.labels or []) if lbl != label]
        gl_issue.labels = labels
        gl_issue.save()

    def get_labels(self, issue_number: int) -> list[str]:
        issues = self._project.issues.list(iid=issue_number)
        return list(issues[0].labels or []) if issues else []
