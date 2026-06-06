import asyncio
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from config import Settings
from worker import enqueue_job, start_worker

logger = logging.getLogger(__name__)
settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
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


@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    _verify_github_signature(body, signature, settings.webhook_secret)

    payload = await request.json()
    action = payload.get("action")

    if action == "opened" and "issue" in payload:
        issue = payload["issue"]
        background_tasks.add_task(
            enqueue_job,
            platform="github",
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
                issue_number=issue["number"],
                title=issue.get("title", ""),
                body=issue.get("body") or "",
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

    if payload.get("object_kind") == "issue" and attrs.get("action") == "open":
        background_tasks.add_task(
            enqueue_job,
            platform="gitlab",
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
                issue_number=attrs["iid"],
                title=attrs.get("title", ""),
                body=attrs.get("description") or "",
            )
            return {"status": "queued"}

    return {"status": "ignored"}


def _verify_github_signature(body: bytes, signature: str, secret: str) -> None:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    expected = f"sha256={mac.hexdigest()}"
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")
