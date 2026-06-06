import hashlib
import hmac
import json
import os
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient


SECRET = "test-secret"


def _sign(body: bytes, secret: str = SECRET) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


ISSUE_OPENED = {
    "action": "opened",
    "issue": {"number": 42, "title": "Fix bug", "body": "There is a bug"},
}

GITLAB_ISSUE_OPENED = {
    "object_kind": "issue",
    "object_attributes": {
        "iid": 7,
        "title": "Fix bug",
        "description": "There is a bug",
        "action": "open",
    },
}


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("PLATFORM", "github")
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")


@pytest.fixture
def client():
    import importlib
    import server
    importlib.reload(server)
    return TestClient(server.app, raise_server_exceptions=True)


def test_github_valid_signature_queues_job(client):
    body = json.dumps(ISSUE_OPENED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()


def test_github_invalid_signature_returns_403(client):
    body = json.dumps(ISSUE_OPENED).encode()
    resp = client.post(
        "/webhook/github",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=badsig", "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_github_non_issue_event_is_ignored(client):
    payload = {"action": "labeled", "label": {"name": "bug"}}
    body = json.dumps(payload).encode()
    resp = client.post(
        "/webhook/github",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_github_issue_not_opened_is_ignored(client):
    payload = {**ISSUE_OPENED, "action": "closed"}
    body = json.dumps(payload).encode()
    resp = client.post(
        "/webhook/github",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_gitlab_valid_token_queues_job(client):
    body = json.dumps(GITLAB_ISSUE_OPENED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/gitlab",
            content=body,
            headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()


def test_gitlab_invalid_token_returns_403(client):
    body = json.dumps(GITLAB_ISSUE_OPENED).encode()
    resp = client.post(
        "/webhook/gitlab",
        content=body,
        headers={"X-Gitlab-Token": "wrongtoken", "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_gitlab_non_issue_event_is_ignored(client):
    payload = {"object_kind": "push"}
    body = json.dumps(payload).encode()
    resp = client.post(
        "/webhook/gitlab",
        content=body,
        headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


GITHUB_AGENT_LABELED = {
    "action": "labeled",
    "label": {"name": "agent: opencode"},
    "issue": {"number": 42, "title": "Fix bug", "body": "There is a bug"},
}

GITHUB_NON_AGENT_LABELED = {
    "action": "labeled",
    "label": {"name": "bug"},
    "issue": {"number": 42, "title": "Fix bug", "body": "There is a bug"},
}

GITLAB_LABEL_UPDATED = {
    "object_kind": "issue",
    "object_attributes": {
        "iid": 7,
        "title": "Fix bug",
        "description": "There is a bug",
        "action": "update",
    },
    "changes": {
        "labels": {
            "previous": [],
            "current": [{"id": 1, "title": "agent: opencode"}],
        }
    },
}

GITLAB_NON_AGENT_LABEL_UPDATED = {
    "object_kind": "issue",
    "object_attributes": {
        "iid": 7,
        "title": "Fix bug",
        "description": "There is a bug",
        "action": "update",
    },
    "changes": {
        "labels": {
            "previous": [],
            "current": [{"id": 2, "title": "priority: high"}],
        }
    },
}


def test_github_agent_label_added_queues_job(client):
    body = json.dumps(GITHUB_AGENT_LABELED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()


def test_github_non_agent_label_added_is_ignored(client):
    body = json.dumps(GITHUB_NON_AGENT_LABELED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    mock_enqueue.assert_not_called()


def test_gitlab_agent_label_added_queues_job(client):
    body = json.dumps(GITLAB_LABEL_UPDATED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/gitlab",
            content=body,
            headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()


def test_gitlab_non_agent_label_update_is_ignored(client):
    body = json.dumps(GITLAB_NON_AGENT_LABEL_UPDATED).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/gitlab",
            content=body,
            headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    mock_enqueue.assert_not_called()


GITHUB_REWORK_COMMENT = {
    "action": "created",
    "sender": {"type": "User"},
    "comment": {"body": "/rework please add error handling"},
    "issue": {
        "number": 42,
        "title": "Fix bug",
        "body": "There is a bug",
        "pull_request": {"url": "https://api.github.com/repos/owner/repo/pulls/10"},
    },
}

GITHUB_BOT_REWORK_COMMENT = {
    "action": "created",
    "sender": {"type": "Bot"},
    "comment": {"body": "/rework please add error handling"},
    "issue": {
        "number": 42,
        "title": "Fix bug",
        "body": "There is a bug",
        "pull_request": {"url": "https://api.github.com/repos/owner/repo/pulls/10"},
    },
}

GITLAB_REWORK_NOTE = {
    "object_kind": "note",
    "object_attributes": {
        "noteable_type": "MergeRequest",
        "note": "/rework please add error handling",
    },
    "merge_request": {
        "title": "fix: Fix bug",
        "description": "There is a bug",
        "source_branch": "ai/issue-42-fix-bug",
    },
}


def test_github_rework_comment_queues_rework_job(client):
    body = json.dumps(GITHUB_REWORK_COMMENT).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue, \
         patch("server._get_github_pr_branch", return_value="ai/issue-42-fix-bug"):
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()
    kwargs = mock_enqueue.call_args.kwargs
    assert kwargs["pr_branch"] == "ai/issue-42-fix-bug"
    assert "/rework" in kwargs["rework_comment"]


def test_github_bot_rework_comment_is_ignored(client):
    body = json.dumps(GITHUB_BOT_REWORK_COMMENT).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    mock_enqueue.assert_not_called()


def test_gitlab_rework_note_queues_rework_job(client):
    body = json.dumps(GITLAB_REWORK_NOTE).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/gitlab",
            content=body,
            headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()
    kwargs = mock_enqueue.call_args.kwargs
    assert kwargs["pr_branch"] == "ai/issue-42-fix-bug"
    assert "/rework" in kwargs["rework_comment"]


def test_api_jobs_open_when_no_password(client):
    with patch("server.store.list_jobs", return_value=[]):
        resp = client.get("/api/jobs")
    assert resp.status_code == 200


def test_api_jobs_wrong_token_returns_401(monkeypatch):
    monkeypatch.setenv("PLATFORM", "github")
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret123")
    import importlib
    import server
    importlib.reload(server)
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    with patch("server.store.list_jobs", return_value=[]):
        resp = c.get("/api/jobs", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


def test_api_jobs_correct_token_returns_200(monkeypatch):
    monkeypatch.setenv("PLATFORM", "github")
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret123")
    import importlib
    import server
    importlib.reload(server)
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    with patch("server.store.list_jobs", return_value=[{"id": 1, "status": "done"}]):
        resp = c.get("/api/jobs", headers={"X-Admin-Token": "secret123"})
    assert resp.status_code == 200
    assert resp.json()[0]["status"] == "done"
