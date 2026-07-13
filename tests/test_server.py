import hashlib
import hmac
import json
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient


SECRET = "test-secret"
GITHUB_REPO_URL = "https://github.com/owner/repo.git"
GITLAB_REPO_URL = "https://gitlab.example.com/owner/repo.git"


def _sign(body: bytes, secret: str = SECRET) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


ISSUE_OPENED = {
    "action": "opened",
    "repository": {"clone_url": GITHUB_REPO_URL},
    "issue": {"number": 42, "title": "Fix bug", "body": "There is a bug"},
}

GITLAB_ISSUE_OPENED = {
    "object_kind": "issue",
    "project": {"http_url_to_repo": GITLAB_REPO_URL},
    "object_attributes": {
        "iid": 7,
        "title": "Fix bug",
        "description": "There is a bug",
        "action": "open",
    },
}


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
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
    kwargs = mock_enqueue.call_args.kwargs
    assert kwargs["repo_url"] == GITHUB_REPO_URL
    assert kwargs["platform"] == "github"


def test_github_invalid_signature_returns_403(client):
    body = json.dumps(ISSUE_OPENED).encode()
    resp = client.post(
        "/webhook/github",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=badsig", "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_github_non_issue_event_is_ignored(client):
    payload = {"action": "labeled", "label": {"name": "bug"}, "repository": {"clone_url": GITHUB_REPO_URL}}
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
    kwargs = mock_enqueue.call_args.kwargs
    assert kwargs["repo_url"] == GITLAB_REPO_URL
    assert kwargs["platform"] == "gitlab"


def test_gitlab_invalid_token_returns_403(client):
    body = json.dumps(GITLAB_ISSUE_OPENED).encode()
    resp = client.post(
        "/webhook/gitlab",
        content=body,
        headers={"X-Gitlab-Token": "wrongtoken", "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_gitlab_non_issue_event_is_ignored(client):
    payload = {"object_kind": "push", "project": {"http_url_to_repo": GITLAB_REPO_URL}}
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
    "repository": {"clone_url": GITHUB_REPO_URL},
    "issue": {"number": 42, "title": "Fix bug", "body": "There is a bug"},
}

GITHUB_NON_AGENT_LABELED = {
    "action": "labeled",
    "label": {"name": "bug"},
    "repository": {"clone_url": GITHUB_REPO_URL},
    "issue": {"number": 42, "title": "Fix bug", "body": "There is a bug"},
}

GITLAB_LABEL_UPDATED = {
    "object_kind": "issue",
    "project": {"http_url_to_repo": GITLAB_REPO_URL},
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
    "project": {"http_url_to_repo": GITLAB_REPO_URL},
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
    assert mock_enqueue.call_args.kwargs["repo_url"] == GITHUB_REPO_URL


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
    assert mock_enqueue.call_args.kwargs["repo_url"] == GITLAB_REPO_URL


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
    "repository": {"clone_url": GITHUB_REPO_URL},
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
    "repository": {"clone_url": GITHUB_REPO_URL},
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
    "project": {"http_url_to_repo": GITLAB_REPO_URL},
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
    assert kwargs["repo_url"] == GITHUB_REPO_URL


def test_github_rework_on_plain_issue_queues_fresh_job(client):
    payload = {
        "action": "created",
        "sender": {"type": "User"},
        "repository": {"clone_url": GITHUB_REPO_URL},
        "comment": {"body": "/rework try again"},
        "issue": {
            "number": 5,
            "title": "Fix bug",
            "body": "There is a bug",
        },
    }
    body = json.dumps(payload).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()
    kwargs = mock_enqueue.call_args.kwargs
    assert kwargs["issue_number"] == 5
    assert "pr_branch" not in kwargs
    assert kwargs["repo_url"] == GITHUB_REPO_URL


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
    assert kwargs["repo_url"] == GITLAB_REPO_URL


def test_gitlab_rework_on_plain_issue_queues_fresh_job(client):
    payload = {
        "object_kind": "note",
        "project": {"http_url_to_repo": GITLAB_REPO_URL},
        "object_attributes": {
            "noteable_type": "Issue",
            "noteable_id": 7,
            "note": "/rework try again",
        },
        "issue": {
            "iid": 7,
            "title": "Fix bug",
            "description": "There is a bug",
        },
    }
    body = json.dumps(payload).encode()
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
    assert kwargs["issue_number"] == 7
    assert "pr_branch" not in kwargs
    assert kwargs["repo_url"] == GITLAB_REPO_URL


def test_api_jobs_open_when_no_password(client):
    with patch("server.store.list_jobs", return_value=[]):
        resp = client.get("/api/jobs")
    assert resp.status_code == 200


def test_api_jobs_wrong_token_returns_401(monkeypatch):
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


def test_github_webhook_missing_repo_url_is_ignored(client):
    payload = {
        "action": "opened",
        "issue": {"number": 1, "title": "T", "body": "B"},
        # no "repository" key
    }
    body = json.dumps(payload).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    mock_enqueue.assert_not_called()


def test_gitlab_webhook_missing_repo_url_is_ignored(client):
    payload = {
        "object_kind": "issue",
        "object_attributes": {"iid": 1, "title": "T", "description": "B", "action": "open"},
        # no "project" key
    }
    body = json.dumps(payload).encode()
    with patch("server.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = client.post(
            "/webhook/gitlab",
            content=body,
            headers={"X-Gitlab-Token": SECRET, "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    mock_enqueue.assert_not_called()


def test_api_jobs_forwards_limit_and_offset(client):
    from unittest.mock import ANY
    with patch("server.store.list_jobs", return_value=[]) as mock_list:
        resp = client.get("/api/jobs?limit=10&offset=20")
    assert resp.status_code == 200
    mock_list.assert_called_once_with(ANY, limit=10, offset=20)


def test_test_engine_start_no_password_returns_run_id(client):
    with patch("server.start_test_run", return_value="abc123") as mock_start, \
         patch("server.asyncio.to_thread", return_value=None), \
         patch("server.asyncio.create_task") as mock_create_task:
        resp = client.post("/api/test-engine?engine=aider")
    assert resp.status_code == 200
    assert resp.json() == {"run_id": "abc123", "status": "running"}
    mock_start.assert_called_once()
    mock_create_task.assert_called_once()


def test_test_engine_status_unknown_id_returns_404(client):
    with patch("server.get_test_run", return_value=None):
        resp = client.get("/api/test-engine/does-not-exist")
    assert resp.status_code == 404


def test_test_engine_status_known_id_returns_run(client):
    run = {"id": "abc123", "status": "done", "diff": "+x", "engine": "aider"}
    with patch("server.get_test_run", return_value=run):
        resp = client.get("/api/test-engine/abc123")
    assert resp.status_code == 200
    assert resp.json() == run


def test_test_engine_start_requires_admin_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret123")
    import importlib
    import server
    importlib.reload(server)
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    resp = c.post("/api/test-engine?engine=aider", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


def test_test_engine_status_requires_admin_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret123")
    import importlib
    import server
    importlib.reload(server)
    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    resp = c.get("/api/test-engine/abc123", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401
