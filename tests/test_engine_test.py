import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import engine_test


class _FakeEngine:
    name = "fake"

    def __init__(self, action="commit"):
        self._action = action

    def run(self, repo_path: Path, prompt: str, settings) -> str:
        if self._action == "commit":
            (repo_path / "greeter.py").write_text("def greet(name):\n    return f'Hello, {name}!'\n")
            subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "add greeter"],
                cwd=repo_path, check=True, capture_output=True,
            )
            return "Changes applied."
        if self._action == "noop":
            return "Nothing to do."
        raise RuntimeError("engine exploded")


@pytest.fixture(autouse=True)
def _clear_runs():
    engine_test._runs.clear()
    yield
    engine_test._runs.clear()


@pytest.fixture(autouse=True)
def _isolate_work_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_test, "TEST_WORK_DIR", tmp_path / "selftest")


def test_start_test_run_registers_running_state():
    run_id = engine_test.start_test_run(_FakeEngine(), MagicMock())
    run = engine_test.get_test_run(run_id)
    assert run["status"] == "running"
    assert run["engine"] == "fake"


def test_get_test_run_unknown_id_returns_none():
    assert engine_test.get_test_run("nope") is None


def test_run_smoke_test_success_produces_diff():
    run_id = engine_test.start_test_run(_FakeEngine("commit"), MagicMock())
    engine_test.run_smoke_test(run_id, _FakeEngine("commit"), MagicMock())
    run = engine_test.get_test_run(run_id)
    assert run["status"] == "done"
    assert "greeter.py" in run["diff"]
    assert run["duration_seconds"] is not None
    assert not (engine_test.TEST_WORK_DIR / run_id).exists()


def test_run_smoke_test_no_changes():
    run_id = engine_test.start_test_run(_FakeEngine("noop"), MagicMock())
    engine_test.run_smoke_test(run_id, _FakeEngine("noop"), MagicMock())
    run = engine_test.get_test_run(run_id)
    assert run["status"] == "no_changes"
    assert run["diff"] == ""


def test_run_smoke_test_engine_exception_marks_failed_and_cleans_up():
    run_id = engine_test.start_test_run(_FakeEngine("boom"), MagicMock())
    engine_test.run_smoke_test(run_id, _FakeEngine("boom"), MagicMock())
    run = engine_test.get_test_run(run_id)
    assert run["status"] == "failed"
    assert "engine exploded" in run["error"]
    assert not (engine_test.TEST_WORK_DIR / run_id).exists()


def test_runs_registry_evicts_oldest_beyond_cap():
    ids = [engine_test.start_test_run(_FakeEngine(), MagicMock()) for _ in range(engine_test._MAX_RUNS + 1)]
    assert len(engine_test._runs) == engine_test._MAX_RUNS
    assert engine_test.get_test_run(ids[0]) is None
    assert engine_test.get_test_run(ids[-1]) is not None
