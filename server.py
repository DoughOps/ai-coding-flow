import asyncio
import hashlib
import hmac
import json
import logging
import re
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

import store
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from config import Settings
from worker import enqueue_job, start_worker

logger = logging.getLogger(__name__)
settings = Settings()
logging.basicConfig(level=logging.DEBUG if settings.verbose else logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db(settings.db_path)
    task = asyncio.create_task(start_worker(settings))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


_DOCS_DIR = Path(__file__).parent / "docs_site"

app = FastAPI(lifespan=lifespan)
app.mount("/guide", StaticFiles(directory=str(_DOCS_DIR), html=True), name="docs")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return RedirectResponse(url="/guide")


@app.get("/api/jobs")
async def api_jobs(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    if settings.admin_password:
        token = request.headers.get("X-Admin-Token", "")
        if not hmac.compare_digest(token, settings.admin_password):
            raise HTTPException(status_code=401, detail="Unauthorized")
    return store.list_jobs(settings.db_path, limit=limit, offset=offset)


@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    _verify_github_signature(body, signature, settings.webhook_secret)

    payload = await request.json()
    action = payload.get("action")
    repo_url = payload.get("repository", {}).get("clone_url", "")

    if not repo_url:
        logger.warning("GitHub webhook missing repository.clone_url — ignoring")
        return {"status": "ignored"}

    if action == "opened" and "issue" in payload:
        issue = payload["issue"]
        background_tasks.add_task(
            enqueue_job,
            platform="github",
            repo_url=repo_url,
            issue_number=issue["number"],
            title=issue.get("title", ""),
            body=issue.get("body") or "",
        )
        return {"status": "queued"}

    if action == "labeled" and "issue" in payload:
        label_name = payload.get("label", {}).get("name", "")
        if label_name.startswith("agent: "):
            issue = payload["issue"]
            background_tasks.add_task(
                enqueue_job,
                platform="github",
                repo_url=repo_url,
                issue_number=issue["number"],
                title=issue.get("title", ""),
                body=issue.get("body") or "",
            )
            return {"status": "queued"}

    if action == "created" and "comment" in payload and "issue" in payload:
        issue = payload["issue"]
        comment_body = payload["comment"].get("body", "")
        if "/rework" in comment_body and payload.get("sender", {}).get("type", "") != "Bot":
            if issue.get("pull_request"):
                pr_api_url = issue["pull_request"].get("url", "")
                try:
                    branch = await asyncio.to_thread(_get_github_pr_branch, pr_api_url, settings.github_token)
                except Exception:
                    logger.warning("Could not fetch PR branch from %s", pr_api_url)
                    return {"status": "ignored"}
                issue_number = _parse_issue_number_from_branch(branch)
                if not issue_number:
                    logger.warning("Could not parse issue number from branch %r", branch)
                    return {"status": "ignored"}
                background_tasks.add_task(
                    enqueue_job,
                    platform="github",
                    repo_url=repo_url,
                    issue_number=issue_number,
                    title=issue.get("title", ""),
                    body=issue.get("body") or "",
                    pr_branch=branch,
                    rework_comment=comment_body,
                )
            else:
                background_tasks.add_task(
                    enqueue_job,
                    platform="github",
                    repo_url=repo_url,
                    issue_number=issue["number"],
                    title=issue.get("title", ""),
                    body=issue.get("body") or "",
                    rework_comment=comment_body,
                )
            return {"status": "queued"}

    return {"status": "ignored"}


@app.post("/webhook/gitlab")
async def gitlab_webhook(request: Request, background_tasks: BackgroundTasks):
    token = request.headers.get("X-Gitlab-Token", "")
    if not hmac.compare_digest(token, settings.webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid token")

    payload = await request.json()
    attrs = payload.get("object_attributes", {})
    repo_url = payload.get("project", {}).get("http_url_to_repo", "")

    if not repo_url:
        logger.warning("GitLab webhook missing project.http_url_to_repo — ignoring")
        return {"status": "ignored"}

    if payload.get("object_kind") == "issue" and attrs.get("action") == "open":
        background_tasks.add_task(
            enqueue_job,
            platform="gitlab",
            repo_url=repo_url,
            issue_number=attrs["iid"],
            title=attrs.get("title", ""),
            body=attrs.get("description") or "",
        )
        return {"status": "queued"}

    if payload.get("object_kind") == "issue" and attrs.get("action") == "update":
        label_changes = payload.get("changes", {}).get("labels", {})
        previous = {l.get("title", "") for l in label_changes.get("previous", [])}
        current = {l.get("title", "") for l in label_changes.get("current", [])}
        newly_added = current - previous
        if any(lbl.startswith("agent: ") for lbl in newly_added):
            background_tasks.add_task(
                enqueue_job,
                platform="gitlab",
                repo_url=repo_url,
                issue_number=attrs["iid"],
                title=attrs.get("title", ""),
                body=attrs.get("description") or "",
            )
            return {"status": "queued"}

    if payload.get("object_kind") == "note":
        note_attrs = payload.get("object_attributes", {})
        note_text = note_attrs.get("note", "")
        if "/rework" in note_text:
            if note_attrs.get("noteable_type") == "MergeRequest":
                mr = payload.get("merge_request", {})
                branch = mr.get("source_branch", "")
                issue_number = _parse_issue_number_from_branch(branch)
                if not issue_number:
                    logger.warning("Could not parse issue number from branch %r", branch)
                    return {"status": "ignored"}
                background_tasks.add_task(
                    enqueue_job,
                    platform="gitlab",
                    repo_url=repo_url,
                    issue_number=issue_number,
                    title=mr.get("title", ""),
                    body=mr.get("description") or "",
                    pr_branch=branch,
                    rework_comment=note_text,
                )
                return {"status": "queued"}
            elif note_attrs.get("noteable_type") == "Issue":
                issue = payload.get("issue", {})
                issue_number = issue.get("iid") or note_attrs.get("noteable_id")
                if not issue_number:
                    logger.warning("Could not determine issue number from GitLab note payload")
                    return {"status": "ignored"}
                background_tasks.add_task(
                    enqueue_job,
                    platform="gitlab",
                    repo_url=repo_url,
                    issue_number=issue_number,
                    title=issue.get("title", ""),
                    body=issue.get("description") or "",
                    rework_comment=note_text,
                )
                return {"status": "queued"}

    return {"status": "ignored"}


def _verify_github_signature(body: bytes, signature: str, secret: str) -> None:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    expected = f"sha256={mac.hexdigest()}"
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")


def _parse_issue_number_from_branch(branch: str) -> int | None:
    m = re.search(r"ai/issue-(\d+)-", branch)
    return int(m.group(1)) if m else None


def _get_github_pr_branch(pr_api_url: str, token: str) -> str:
    req = urllib.request.Request(
        pr_api_url,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    return data.get("head", {}).get("ref", "")
