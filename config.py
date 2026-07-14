from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    github_token: str = ""
    gitlab_token: str = ""
    webhook_secret: str
    verbose: bool = False
    verify_repo_ssl: bool = True
    verify_engine_ssl: bool = True
    openai_api_base: str
    openai_api_key: str = "local"
    openai_model: str = "qwen2.5-coder:32b"

    @field_validator("openai_model", mode="before")
    @classmethod
    def strip_model_quotes(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip("\"'")
        return v

    max_retries: int = 3
    max_concurrent_jobs: int = Field(3, ge=1)
    test_cmd: str = ""
    agent_timeout: int = 600
    default_agent: str = "aider"

    aider_verbose: bool = False
    aider_map_tokens: int = 2048
    aider_token_budget: int = 80000

    opencode_context_limit: int = 32768
    opencode_output_limit: int = 4096

    claudecode_router_port: int = 18456
    claudecode_router_startup_timeout: int = 15

    admin_password: str = ""
    db_path: str = str(Path(__file__).parent / "ai_jobs.db")

    model_config = {"env_file": ".env", "extra": "ignore"}
