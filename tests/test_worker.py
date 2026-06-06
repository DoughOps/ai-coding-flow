import pytest
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
