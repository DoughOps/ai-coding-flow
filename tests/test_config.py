import pytest
from pydantic import ValidationError


def test_valid_github_config(monkeypatch):
    monkeypatch.setenv("PLATFORM", "github")
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("WEBHOOK_SECRET", "secret123")
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    from config import Settings
    s = Settings()
    assert s.platform == "github"
    assert s.max_retries == 3
    assert s.test_cmd == "pytest"
    assert s.openai_api_key == "local"


def test_invalid_platform_raises(monkeypatch):
    monkeypatch.setenv("PLATFORM", "bitbucket")
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.setenv("WEBHOOK_SECRET", "secret123")
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    with pytest.raises(ValidationError):
        from importlib import reload
        import config
        reload(config)
        config.Settings()


def test_missing_platform_raises(monkeypatch):
    monkeypatch.delenv("PLATFORM", raising=False)
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.setenv("WEBHOOK_SECRET", "secret123")
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    with pytest.raises(ValidationError):
        from importlib import reload
        import config
        reload(config)
        config.Settings()


def test_missing_webhook_secret_raises(monkeypatch):
    monkeypatch.setenv("PLATFORM", "github")
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    with pytest.raises(ValidationError):
        from importlib import reload
        import config
        reload(config)
        config.Settings()
