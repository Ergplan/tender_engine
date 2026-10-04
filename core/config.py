"""Settings from environment variables. No module-level singleton: callers build one and pass it."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://tender:tender@db:5432/tender"
    db_schema: str | None = None
    data_dir: str = "/data"
    tenant_id: str = "ergplan"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-fable-5-1"
    llm_max_retries: int = 4
    llm_timeout_seconds: float = 600.0
    llm_max_tokens: int = 16000

    openai_api_key: str = ""
