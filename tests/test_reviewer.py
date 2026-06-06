from unittest.mock import MagicMock, patch
import pytest


def _make_settings():
    s = MagicMock()
    s.openai_api_base = "http://localhost:11434/v1"
    s.openai_api_key = "local"
    s.openai_model = "qwen2.5-coder:32b"
    return s


def _mock_openai_response(content: str):
    response = MagicMock()
    response.choices[0].message.content = content
    return response


def test_run_review_returns_string():
    with patch("reviewer.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response("LGTM")
        mock_cls.return_value = mock_client

        from reviewer import run_review
        result = run_review(
            issue_title="Fix bug",
            issue_body="There is a bug",
            diff="+def fix(): pass",
            settings=_make_settings(),
        )

    assert result == "LGTM"


def test_run_review_passes_diff_to_llm():
    with patch("reviewer.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response("ok")
        mock_cls.return_value = mock_client

        from reviewer import run_review
        run_review(
            issue_title="Fix bug",
            issue_body="Description",
            diff="+UNIQUE_DIFF_MARKER",
            settings=_make_settings(),
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages_text = str(call_kwargs.get("messages", ""))
        assert "UNIQUE_DIFF_MARKER" in messages_text


def test_run_review_uses_configured_model():
    with patch("reviewer.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response("ok")
        mock_cls.return_value = mock_client

        settings = _make_settings()
        settings.openai_model = "my-custom-model"

        from reviewer import run_review
        run_review("title", "body", "diff", settings)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "my-custom-model"
