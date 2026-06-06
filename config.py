from typing import Literal
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    platform: Literal["github", "gitlab"]
    repo_url: str
    github_token: str = ""
    gitlab_token: str = ""
    webhook_secret: str
    openai_api_base: str
    openai_api_key: str = "local"
    openai_model: str = "qwen2.5-coder:32b"
    max_retries: int = 3
    test_cmd: str = ""  # empty = skip testing entirely
    aider_verbose: bool = False  # set true to log all Aider output
    default_agent: str = "aider"

    model_config = {"env_file": ".env"}
