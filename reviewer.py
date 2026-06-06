from openai import OpenAI
from config import Settings


def run_review(
    issue_title: str,
    issue_body: str,
    diff: str,
    settings: Settings,
) -> str:
    """Call the LLM with a fresh context to review the diff. Returns review text."""
    client = OpenAI(
        base_url=settings.openai_api_base,
        api_key=settings.openai_api_key,
    )
    prompt = (
        f"You are an expert code reviewer. Review the following code changes that were made "
        f"to resolve an issue.\n\n"
        f"Issue: {issue_title}\n"
        f"Description: {issue_body}\n\n"
        f"Code diff:\n```diff\n{diff}\n```\n\n"
        f"Provide a concise review covering:\n"
        f"1. Correctness — does the change actually fix the issue?\n"
        f"2. Edge cases — any unhandled scenarios?\n"
        f"3. Code quality — any obvious improvements?\n"
        f"4. Test coverage — are the tests sufficient?\n\n"
        f"Be direct and specific. If the code looks good, say so."
    )
    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000,
    )
    return response.choices[0].message.content
