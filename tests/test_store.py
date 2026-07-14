import pytest
import sqlite3
from unittest.mock import patch
import store


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    store.init_db(path)
    return path


def test_create_job_returns_id(db):
    job_id = store.create_job(db, platform="github", issue_number=1, issue_title="Fix bug")
    assert isinstance(job_id, int) and job_id > 0


def test_create_job_status_is_queued(db):
    store.create_job(db, platform="github", issue_number=1, issue_title="Fix bug")
    jobs = store.list_jobs(db)
    assert jobs[0]["status"] == "queued"


def test_update_job_status_and_engine(db):
    job_id = store.create_job(db, platform="github", issue_number=1, issue_title="Fix bug")
    store.update_job(db, job_id, status="processing", engine="aider")
    jobs = store.list_jobs(db)
    assert jobs[0]["status"] == "processing"
    assert jobs[0]["engine"] == "aider"


def test_list_jobs_newest_first(db):
    store.create_job(db, platform="github", issue_number=1, issue_title="First")
    store.create_job(db, platform="github", issue_number=2, issue_title="Second")
    jobs = store.list_jobs(db)
    assert jobs[0]["issue_title"] == "Second"
    assert jobs[1]["issue_title"] == "First"


def test_list_jobs_respects_limit(db):
    for i in range(5):
        store.create_job(db, platform="github", issue_number=i, issue_title=f"Issue {i}")
    jobs = store.list_jobs(db, limit=3)
    assert len(jobs) == 3


def test_create_job_stores_repo_url(db):
    store.create_job(
        db,
        platform="github",
        repo_url="https://github.com/owner/repo.git",
        issue_number=1,
        issue_title="Fix bug",
    )
    jobs = store.list_jobs(db)
    assert jobs[0]["repo_url"] == "https://github.com/owner/repo.git"


def test_list_jobs_respects_offset(db):
    for i in range(5):
        store.create_job(db, platform="github", issue_number=i, issue_title=f"Issue {i}")
    jobs = store.list_jobs(db, limit=5, offset=2)
    assert len(jobs) == 3
    assert jobs[0]["issue_title"] == "Issue 2"


def test_all_connections_use_busy_timeout(tmp_path):
    db = str(tmp_path / "jobs.db")
    calls = []
    real_connect = sqlite3.connect

    def spy(path, *args, **kwargs):
        calls.append(kwargs)
        return real_connect(path, *args, **kwargs)

    with patch("store.sqlite3.connect", side_effect=spy):
        store.init_db(db)
        job_id = store.create_job(db, platform="github", issue_number=1, issue_title="t")
        store.update_job(db, job_id, status="done")
        store.list_jobs(db)

    assert len(calls) == 4
    assert all(kwargs.get("timeout") == 30 for kwargs in calls)
