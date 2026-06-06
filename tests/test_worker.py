import pytest
from unittest.mock import MagicMock
from worker import _slugify


def test_slugify_basic():
    assert _slugify("Fix the login bug") == "fix-the-login-bug"


def test_slugify_special_characters():
    assert _slugify("Support UTF-8 & unicode!") == "support-utf-8-unicode"


def test_slugify_truncates_at_50():
    result = _slugify("word " * 20)
    assert len(result) <= 50


def test_slugify_trims_leading_trailing_hyphens():
    result = _slugify("  Fix bug  ")
    assert not result.startswith("-")
    assert not result.endswith("-")


def test_pick_engine_selects_aider_by_label():
    from worker import _pick_engine
    from engines.aider import AiderEngine
    settings = MagicMock()
    settings.default_agent = "aider"
    engine = _pick_engine(["ai: processing", "agent: aider", "bug"], settings)
    assert isinstance(engine, AiderEngine)


def test_pick_engine_selects_opencode_by_label():
    from worker import _pick_engine
    from engines.opencode import OpenCodeEngine
    settings = MagicMock()
    settings.default_agent = "aider"
    engine = _pick_engine(["agent: opencode"], settings)
    assert isinstance(engine, OpenCodeEngine)


def test_pick_engine_uses_default_when_no_agent_label():
    from worker import _pick_engine
    from engines.aider import AiderEngine
    settings = MagicMock()
    settings.default_agent = "aider"
    engine = _pick_engine(["bug", "ai: done"], settings)
    assert isinstance(engine, AiderEngine)


def test_pick_engine_unknown_label_falls_back_to_aider():
    from worker import _pick_engine
    from engines.aider import AiderEngine
    settings = MagicMock()
    settings.default_agent = "aider"
    engine = _pick_engine(["agent: nonexistent"], settings)
    assert isinstance(engine, AiderEngine)
