import asyncio
import logging
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass

import store
from config import Settings
from agent import run_agent, push_branch, get_diff, cleanup_repo, cleanup_old_repos
from reviewer import run_review
from platforms import create_platform
from engines import get_engine
from engines.base import AgentEngine

logger = logging.getLogger(__name__)

_settings_ref: Settings | None = None


@dataclass
class Job:
    platform: str
    repo_url: str
    issue_number: int
    title: str
    body: str
    job_id: int = 0
    pr_branch: str = ""
    rework_comment: str = ""


class _KeyedLocks:
    """Serialize coroutines sharing a key; independent keys don't contend.

    Entries are refcounted and removed once no coroutine holds or awaits
    the key, so the dict can't grow unboundedly. Safe without extra locking
    because all mutation happens synchronously on the event loop thread.
    """

    def __init__(self) -> None:
        self._locks: dict = {}
        self._refcounts: dict = {}

    @asynccontextmanager
    async def acquire(self, key):
        self._refcounts[key] = self._refcounts.get(key, 0) + 1
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                yield
        finally:
            self._refcounts[key] -= 1
            if self._refcounts[key] == 0:
                del self._refcounts[key]
                del self._locks[key]


job_locks = _KeyedLocks()


_queue: asyncio.Queue = asyncio.Queue()


async def enqueue_job(
    *,
    platform: str,
    repo_url: str,
    issue_number: int,
    title: str,
    body: str,
    pr_branch: str = "",
    rework_comment: str = "",
) -> None:
    job_id = 0
    if _settings_ref:
        job_id = store.create_job(
            _settings_ref.db_path,
            platform=platform,
            repo_url=repo_url,
            issue_number=issue_number,
            issue_title=title,
        )
    await _queue.put(Job(
        platform=platform,
        repo_url=repo_url,
        issue_number=issue_number,
        title=title,
        body=body,
        job_id=job_id,
        pr_branch=pr_branch,
        rework_comment=rework_comment,
    ))
    logger.info("Enqueued issue #%d (%s) from %s", issue_number, platform, repo_url)


async def start_worker(settings: Settings) -> None:
    global _settings_ref
    _settings_ref = settings
    cleanup_old_repos()
    logger.info("Worker started")
    while True:
        job = await _queue.get()
        try:
            if job.rework_comment and job.pr_branch:
                await _process_rework_job(job, settings)
            else:
                await _process_job(job, settings)
        except Exception as exc:
            logger.exception("Unhandled error for issue #%d", job.issue_number)
            try:
                platform = create_platform(job.platform, job.repo_url, settings)
                platform.remove_label(job.issue_number, _LABEL_PROCESSING)
                platform.set_label(job.issue_number, _LABEL_FAILED)
                platform.post_comment(
                    job.issue_number,
                    f"AI workflow encountered an unexpected error: {exc}",
                )
            except Exception:
                logger.exception("Failed to post error comment for issue #%d", job.issue_number)
        finally:
            _queue.task_done()


_LABEL_PROCESSING = "ai: processing"
_LABEL_DONE = "ai: done"
_LABEL_FAILED = "ai: failed"
_LABEL_NEEDS_CLARIFICATION = "ai: needs clarification"

_ALL_AI_LABELS = (
    _LABEL_PROCESSING,
    _LABEL_DONE,
    _LABEL_FAILED,
    _LABEL_NEEDS_CLARIFICATION,
)


def _swap_label(platform, issue_number: int, remove: str, add: str) -> None:
    for label in _ALL_AI_LABELS:
        if label == add:
            continue
        try:
            platform.remove_label(issue_number, label)
        except Exception:
            pass
    try:
        platform.set_label(issue_number, add)
    except Exception:
        logger.exception("Failed to set label %r on issue #%d", add, issue_number)


def _pick_engine(labels: list[str], settings: Settings) -> AgentEngine:
    for label in labels:
        if label.startswith("agent: "):
            engine_name = label[len("agent: "):]
            return get_engine(engine_name)
    return get_engine(settings.default_agent)


def _build_rework_body(original_body: str, rework_comment: str) -> str:
    return (
        f"{original_body}\n\n"
        f"---\n"
        f"**Reviewer feedback (please address):**\n\n"
        f"{rework_comment}"
    )


async def _process_job(job: Job, settings: Settings) -> None:
    platform = create_platform(job.platform, job.repo_url, settings)
    branch = f"ai/issue-{job.issue_number}-{_slugify(job.title)}"
    logger.info("Processing issue #%d on branch %s", job.issue_number, branch)

    labels = platform.get_labels(job.issue_number)
    engine = _pick_engine(labels, settings)
    logger.info("Using engine %r for issue #%d", engine.name, job.issue_number)

    _swap_label(platform, job.issue_number, "", _LABEL_PROCESSING)
    if job.job_id:
        store.update_job(settings.db_path, job.job_id, status="processing", engine=engine.name)

    issue_body = _build_rework_body(job.body, job.rework_comment) if job.rework_comment else job.body
    success, repo_path, initial_commit, error_msg = await asyncio.to_thread(
        run_agent,
        issue_number=job.issue_number,
        issue_title=job.title,
        issue_body=issue_body,
        branch=branch,
        settings=settings,
        engine=engine,
        repo_url=job.repo_url,
        platform=job.platform,
    )

    try:
        if not success:
            _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_FAILED)
            if job.job_id:
                store.update_job(settings.db_path, job.job_id, status="failed", error_msg=error_msg)
            platform.post_comment(
                job.issue_number,
                f"AI could not produce passing tests after {settings.max_retries} attempts.\n\n"
                f"Last test output:\n```\n{error_msg}\n```",
            )
            return

        diff = get_diff(repo_path, initial_commit)
        if not diff.strip():
            _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_NEEDS_CLARIFICATION)
            if job.job_id:
                store.update_job(settings.db_path, job.job_id, status="needs_clarification")
            platform.post_comment(
                job.issue_number,
                "AI made no code changes. Please add more detail or a concrete example to the issue description.",
            )
            return

        await asyncio.to_thread(
            push_branch,
            repo_path,
            branch,
            settings,
            job.repo_url,
            job.platform,
            force=True,
        )

        pr_title = f"fix: {job.title} (resolves #{job.issue_number})"
        pr_body = (
            f"Closes #{job.issue_number}\n\n"
            f"This PR was automatically generated by the AI coding workflow."
        )
        pr_url = platform.create_pr(branch, pr_title, pr_body)
        logger.info("Created PR/MR: %s", pr_url)
        if job.job_id:
            store.update_job(settings.db_path, job.job_id, pr_url=pr_url)

        review_comment = await asyncio.to_thread(
            run_review,
            issue_title=job.title,
            issue_body=job.body,
            diff=diff,
            settings=settings,
        )

        _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_DONE)
        if job.job_id:
            store.update_job(settings.db_path, job.job_id, status="done")
        platform.post_comment(
            job.issue_number,
            f"PR: {pr_url}\n\n**Review:**\n\n{review_comment}",
        )
        logger.info("Posted review comment for issue #%d", job.issue_number)
    finally:
        cleanup_repo(repo_path)


async def _process_rework_job(job: Job, settings: Settings) -> None:
    platform = create_platform(job.platform, job.repo_url, settings)
    if job.job_id:
        store.update_job(settings.db_path, job.job_id, status="reworking")
    _swap_label(platform, job.issue_number, "", _LABEL_PROCESSING)
    logger.info("Processing rework for issue #%d on branch %s", job.issue_number, job.pr_branch)

    issue = platform.get_issue(job.issue_number)
    labels = platform.get_labels(job.issue_number)
    engine = _pick_engine(labels, settings)
    logger.info("Using engine %r for rework of issue #%d", engine.name, job.issue_number)

    if not job.pr_branch:
        logger.error("Rework job for issue #%d has empty pr_branch — skipping", job.issue_number)
        platform.post_comment(job.issue_number, "Rework skipped: could not determine branch name.")
        _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_FAILED)
        return

    success, repo_path_str, _initial_commit, error_msg = await asyncio.to_thread(
        run_agent,
        issue_number=job.issue_number,
        issue_title=issue.title,
        issue_body=_build_rework_body(issue.body, job.rework_comment),
        branch=job.pr_branch,
        settings=settings,
        engine=engine,
        repo_url=job.repo_url,
        platform=job.platform,
        start_ref=f"origin/{job.pr_branch}",
    )

    try:
        if not success:
            _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_FAILED)
            if job.job_id:
                store.update_job(settings.db_path, job.job_id, status="failed", error_msg=error_msg)
            platform.post_comment(
                job.issue_number,
                f"Re-run could not produce passing tests.\n\n```\n{error_msg}\n```",
            )
            return

        await asyncio.to_thread(
            push_branch,
            repo_path_str,
            job.pr_branch,
            settings,
            job.repo_url,
            job.platform,
            force=True,
        )
        _swap_label(platform, job.issue_number, _LABEL_PROCESSING, _LABEL_DONE)
        if job.job_id:
            store.update_job(settings.db_path, job.job_id, status="done")
        platform.post_comment(
            job.issue_number,
            f"Re-run complete. Branch `{job.pr_branch}` updated.",
        )
        logger.info("Rework complete for issue #%d", job.issue_number)
    finally:
        cleanup_repo(repo_path_str)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:50]
