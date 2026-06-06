import pytest
from pydantic import ValidationError


def test_valid_github_config(monkeypatch):
    monkeypatch.setenv("PLATFORM", "github")
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("WEBHOOK_SECRET", "secret123")
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    from config import Settings
    s = Settings(_env_file=None)
    assert s.platform == "github"
    assert s.max_retries == 3
    assert s.test_cmd == ""
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
        from config import Settings
        Settings(_env_file=None)


def test_missing_webhook_secret_raises(monkeypatch):
    monkeypatch.setenv("PLATFORM", "github")
    monkeypatch.setenv("REPO_URL", "https://github.com/owner/repo")
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("OPENAI_API_BASE", "http://localhost:11434/v1")
    with pytest.raises(ValidationError):
        from config import Settings
        Settings(_env_file=None)


def test_default_agent_defaults_to_aider():
    from config import Settings
    s = Settings(
        platform="github",
        repo_url="https://github.com/owner/repo",
        github_token="ghp_test",
        webhook_secret="secret",
        openai_api_base="http://localhost/v1",
        _env_file=None,
    )
    assert s.default_agent == "aider"


def test_default_agent_can_be_set():
    from config import Settings
    s = Settings(
        platform="github",
        repo_url="https://github.com/owner/repo",
        github_token="ghp_test",
        webhook_secret="secret",
        openai_api_base="http://localhost/v1",
        default_agent="opencode",
        _env_file=None,
    )
    assert s.default_agent == "opencode"
