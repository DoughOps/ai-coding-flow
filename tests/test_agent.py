import subprocess
from pathlib import Path
from unittest.mock import MagicMock
from agent import _build_prompt, _authenticated_url, _repo_slug, _exclude_build_artifacts


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def test_exclude_build_artifacts_prevents_pycache_commit(tmp_path):
    _git_init(tmp_path)
    _exclude_build_artifacts(tmp_path)
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "mod.cpython-313.pyc").write_bytes(b"\x00")
    (tmp_path / "real.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout
    assert "real.py" in staged
    assert "__pycache__" not in staged
    assert ".pyc" not in staged


def test_exclude_build_artifacts_is_idempotent(tmp_path):
    _git_init(tmp_path)
    _exclude_build_artifacts(tmp_path)
    _exclude_build_artifacts(tmp_path)
    exclude = (tmp_path / ".git" / "info" / "exclude").read_text()
    assert exclude.count("__pycache__/") == 1


def test_exclude_build_artifacts_noop_when_not_a_repo(tmp_path):
    # No .git — must not raise.
    _exclude_build_artifacts(tmp_path / "missing")


def _settings(platform="github"):
    s = MagicMock()
    s.github_token = "ghp_testtoken"
    s.gitlab_token = "glpat_testtoken"
    return s


def _repo_url(platform="github"):
    if platform == "github":
        return "https://github.com/owner/repo"
    return "https://gitlab.example.com/owner/repo"


def test_build_prompt_contains_title():
    prompt = _build_prompt("Fix the login bug", "Users cannot log in")
    assert "Fix the login bug" in prompt


def test_build_prompt_contains_body():
    prompt = _build_prompt("Fix the login bug", "Users cannot log in after update")
    assert "Users cannot log in after update" in prompt


def test_repo_slug_github():
    assert _repo_slug("https://github.com/owner/repo") == "owner-repo"


def test_repo_slug_strips_dot_git():
    assert _repo_slug("https://github.com/owner/repo.git") == "owner-repo"


def test_repo_slug_gitlab_namespace():
    assert _repo_slug("https://gitlab.example.com/group/project") == "group-project"


def test_authenticated_url_github_embeds_token():
    url = _authenticated_url(_settings("github"), _repo_url("github"), "github")
    assert "x-access-token:ghp_testtoken@github.com" in url
    assert url.startswith("https://")


def test_authenticated_url_gitlab_embeds_token():
    url = _authenticated_url(_settings("gitlab"), _repo_url("gitlab"), "gitlab")
    assert "oauth2:glpat_testtoken@gitlab.example.com" in url
    assert url.startswith("https://")


def test_authenticated_url_github_no_dot_git():
    s = MagicMock()
    s.github_token = "tok"
    s.gitlab_token = ""
    url = _authenticated_url(s, "https://github.com/owner/repo.git", "github")
    assert url.startswith("https://x-access-token:tok@github.com")


def test_run_agent_uses_provided_engine():
    from unittest.mock import MagicMock, patch
    from agent import run_agent

    mock_engine = MagicMock()
    mock_engine.run.return_value = "Engine output"

    settings = MagicMock()
    settings.test_cmd = ""
    settings.max_retries = 3

    with patch("agent._prepare_repo"), \
         patch("agent._configure_git_user"), \
         patch("agent._git_head", return_value="abc123"):
        success, _, initial, err = run_agent(
            issue_number=1,
            issue_title="Test",
            issue_body="Body",
            branch="ai/issue-1-test",
            settings=settings,
            engine=mock_engine,
            repo_url="https://github.com/owner/repo",
            platform="github",
        )

    assert success is True
    mock_engine.run.assert_called_once()


def test_push_branch_includes_force_with_lease_when_force_true():
    from unittest.mock import patch
    from agent import push_branch

    settings = MagicMock()
    settings.github_token = "tok"

    with patch("agent.subprocess.run") as mock_run:
        push_branch(
            "/repo",
            "ai/issue-1-test",
            settings,
            repo_url="https://github.com/owner/repo",
            platform="github",
            force=True,
        )

    push_cmd = mock_run.call_args_list[1][0][0]
    assert "--force-with-lease" in push_cmd


def test_push_branch_no_force_flag_by_default():
    from unittest.mock import patch
    from agent import push_branch

    settings = MagicMock()
    settings.github_token = "tok"

    with patch("agent.subprocess.run") as mock_run:
        push_branch(
            "/repo",
            "ai/issue-1-test",
            settings,
            repo_url="https://github.com/owner/repo",
            platform="github",
        )

    push_cmd = mock_run.call_args_list[1][0][0]
    assert "--force-with-lease" not in push_cmd


def test_run_agent_accepts_start_ref():
    from unittest.mock import MagicMock, patch
    from agent import run_agent

    mock_engine = MagicMock()
    mock_engine.run.return_value = "output"

    settings = MagicMock()
    settings.test_cmd = ""
    settings.max_retries = 3

    captured = {}

    def fake_prepare(repo_path, branch, settings, repo_url, platform, start_ref=""):
        captured["start_ref"] = start_ref

    with patch("agent._prepare_repo", side_effect=fake_prepare), \
         patch("agent._configure_git_user"), \
         patch("agent._git_head", return_value="abc123"):
        run_agent(
            issue_number=1,
            issue_title="Test",
            issue_body="Body",
            branch="ai/issue-1-test",
            settings=settings,
            engine=mock_engine,
            repo_url="https://github.com/owner/repo",
            platform="github",
            start_ref="origin/ai/issue-1-test",
        )

    assert captured["start_ref"] == "origin/ai/issue-1-test"
