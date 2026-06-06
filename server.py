import hashlib
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from config import Settings
from worker import enqueue_job, start_worker

logger = logging.getLogger(__name__)
settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    task = asyncio.create_task(start_worker(settings))
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    _verify_github_signature(body, signature, settings.webhook_secret)

    payload = await request.json()
    if payload.get("action") != "opened" or "issue" not in payload:
        return {"status": "ignored"}

    issue = payload["issue"]
    background_tasks.add_task(
        enqueue_job,
        platform="github",
        issue_number=issue["number"],
        title=issue["title"],
        body=issue.get("body") or "",
    )
    return {"status": "queued"}


@app.post("/webhook/gitlab")
async def gitlab_webhook(request: Request, background_tasks: BackgroundTasks):
    token = request.headers.get("X-Gitlab-Token", "")
    if not hmac.compare_digest(token, settings.webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid token")

    payload = await request.json()
    attrs = payload.get("object_attributes", {})
    if payload.get("object_kind") != "issue" or attrs.get("action") != "open":
        return {"status": "ignored"}

    background_tasks.add_task(
        enqueue_job,
        platform="gitlab",
        issue_number=attrs["iid"],
        title=attrs["title"],
        body=attrs.get("description") or "",
    )
    return {"status": "queued"}


def _verify_github_signature(body: bytes, signature: str, secret: str) -> None:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    expected = f"sha256={mac.hexdigest()}"
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")
