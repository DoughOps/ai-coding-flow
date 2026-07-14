import gitlab
from gitlab.exceptions import GitlabCreateError, GitlabGetError
from urllib.parse import urlparse
from .base import GitPlatform, Issue


class GitLabPlatform(GitPlatform):
    def __init__(self, token: str, repo_url: str, verify_ssl: bool = True) -> None:
        parsed = urlparse(repo_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        self._gl = gitlab.Gitlab(base_url, private_token=token, ssl_verify=verify_ssl)
        project_path = parsed.path.lstrip("/").removesuffix(".git")
        self._project = self._gl.projects.get(project_path)

    def _get_gl_issue(self, number: int):
        # Fetch by iid via GET /projects/:id/issues/:issue_iid. The list
        # endpoint must not be used with an iid= filter: GitLab silently
        # ignores unknown params and returns all issues newest-first, so
        # issues.list(iid=7)[0] resolves to the most recent issue instead.
        try:
            return self._project.issues.get(number)
        except GitlabGetError:
            return None

    def get_issue(self, number: int) -> Issue:
        gl_issue = self._get_gl_issue(number)
        if gl_issue is None:
            raise ValueError(f"Issue #{number} not found")
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
        gl_issue = self._get_gl_issue(issue_number)
        if gl_issue is None:
            raise ValueError(f"Issue #{issue_number} not found")
        gl_issue.notes.create({"body": body})

    def set_label(self, issue_number: int, label: str) -> None:
        gl_issue = self._get_gl_issue(issue_number)
        if gl_issue is None:
            return
        labels = list(gl_issue.labels or [])
        if label not in labels:
            labels.append(label)
            gl_issue.labels = labels
            gl_issue.save()

    def remove_label(self, issue_number: int, label: str) -> None:
        gl_issue = self._get_gl_issue(issue_number)
        if gl_issue is None:
            return
        labels = [lbl for lbl in (gl_issue.labels or []) if lbl != label]
        gl_issue.labels = labels
        gl_issue.save()

    def get_labels(self, issue_number: int) -> list[str]:
        gl_issue = self._get_gl_issue(issue_number)
        return list(gl_issue.labels or []) if gl_issue else []
