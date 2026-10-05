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
    # Reasoning counts towards this limit. 20,000 is as far as a call that is waited for
    # can go before the SDK asks for streaming; a summary with forty quotes came close to
    # 16,000.
    llm_max_tokens: int = 20000
    llm_price_in_per_mtok: float = 10.0
    llm_price_out_per_mtok: float = 50.0
    # Factors on the input price: a read from the prompt cache, a write to it (5-minute
    # and 1-hour lifetime), and the batch API's discount on everything.
    llm_cache_read_factor: float = 0.025
    llm_cache_write_factor: float = 1.25
    llm_cache_write_1h_factor: float = 2.0
    llm_batch_factor: float = 0.5
    llm_batch_poll_seconds: float = 60.0

    extract_max_pages_per_call: int = 40
    extract_max_pages_per_group: int = 80
    extract_keyword_pages: int = 12
    # Field groups of one run share a page window when that is cheaper (see
    # core.services.extract_plan). A call's output is weighed as this many input pages.
    extract_share_windows: bool = True
    extract_call_overhead_pages: float = 6.0
    evidence_match_threshold: float = 85.0
    render_dpi: int = 150
    worker_poll_seconds: float = 2.0

    openai_api_key: str = ""

    # Where reviewers reach the app; review links are built from it.
    public_base_url: str = "https://34.131.65.108"
