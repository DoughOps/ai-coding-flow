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
