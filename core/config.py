"""Settings from environment variables. No module-level singleton: callers build one and pass it."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://tender:tender@db:5432/tender"
    db_schema: str | None = None
    data_dir: str = "/data"
    storage_backend: str = "local"
    tenant_id: str = "ergplan"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-fable-5-1"
    llm_max_retries: int = 4
    llm_timeout_seconds: float = 600.0
    llm_max_tokens: int = 16000
    llm_price_in_per_mtok: float = 10.0
    llm_price_out_per_mtok: float = 50.0

    extract_max_pages_per_call: int = 40
    extract_max_pages_per_group: int = 80
    evidence_match_threshold: float = 85.0
    render_dpi: int = 150
    worker_poll_seconds: float = 2.0

    openai_api_key: str = ""
