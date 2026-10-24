"""Settings from environment variables. No module-level singleton: callers build one and pass it."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://tender:tender@db:5432/tender"
    # The connection migrations use: the owner of the tables. The app itself connects as
    # `tender_app` (migration 0018), a role without ownership that row-level security
    # binds; empty means the same URL as database_url (the test harness, a dev database).
    migration_database_url: str = ""
    db_schema: str | None = None
    data_dir: str = "/data"
    # local: files under data_dir. gcs: the bucket (Cloud Run); the files route streams them.
    storage_backend: str = "local"
    gcs_bucket: str = ""
    tenant_id: str = "ergplan"
    # Which product this process serves (Stage 5C). enterprise: every route and the web
    # front end. api: the intelligence API only — the read routes, the published view,
    # the model, the reliability figures and the OpenAPI document — for API-key clients.
    # Same code either way; the difference is which routers are mounted.
    product: Literal["enterprise", "api"] = "enterprise"

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
    # Parsing layers (Stage 7, Block 2). Docling runs on the VM (compose service `docling`,
    # profile `parsing`); the worker sends it the pages pdfplumber found no text layer on,
    # and the pages with tables when `docling_tables` is on. Empty URL: the layer is off and
    # a scanned page keeps no text, as before. An unreachable service never fails a parse.
    docling_url: str = ""
    docling_timeout_seconds: float = 900.0
    docling_tables: bool = True
    # LlamaParse is optional and off: a document leaves the VM only for a tender whose
    # record says so (`tender.parser_llamaparse`), and the pages it read say `llamaparse`.
    llamaparse_api_key: str = ""
    llamaparse_url: str = "https://api.cloud.llamaindex.ai"
    worker_poll_seconds: float = 2.0

    openai_api_key: str = ""
    # The independent agent pass (Stage 5A): the OpenAI model it runs on, its list prices
    # (the invoice is the truth; these give the figure the run records) and the factor on
    # the input price for tokens the provider served from its prompt cache.
    openai_model: str = "gpt-6.1-sol"
    openai_price_in_per_mtok: float = 2.5
    openai_price_out_per_mtok: float = 10.0
    openai_cache_read_factor: float = 0.1
    # Model calls one pass may make; pages one read_pages call may return; whether page
    # images go with the text when the agent asks for them (a page without a text layer
    # always comes as an image).
    agent_max_turns: int = 200
    agent_max_pages_per_read: int = 6
    agent_page_images: bool = True
    # Where evaluation results are written and the review emphasis file is read from
    # (`evals/results/review-emphasis-<tenant>.json`, Stage 5B). Empty: `evals/results`.
    results_root: str = ""
    # Guards /api/v1/admin/* for internal automation and the tests; an admin who signed in
    # reaches the same routes with their session. Empty: the header opens nothing.
    admin_token: str = ""
    # The public library's free tier on the MCP server (Stage 5D): calls per minute and per
    # UTC day for a free-plan tenant or a token scoped to the library only.
    free_rate_limit_per_min: int = 20
    free_daily_cap: int = 200

    # Sign-in (Stage 5C): Google OIDC. The client is registered by the operator; the
    # callback is <public_base_url>/api/v1/auth/callback. Only verified addresses of the
    # allowed domains (comma list; empty: any) may sign in; a first sign-in creates the
    # user with the default role, or `admin` for the bootstrap addresses. The session
    # secret signs the sign-in state cookie; empty refuses sign-in with a plain message.
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_issuer: str = "https://accounts.google.com"
    oidc_allowed_domains: str = ""
    oidc_default_role: str = "reviewer"
    bootstrap_admin_emails: str = ""
    session_hours: float = 12.0
    session_secret: str = ""
    # The intelligence API's keys (Product B): calls per minute and per UTC day for a key
    # made without its own limits.
    api_key_rate_limit_per_min: int = 60
    api_key_daily_cap: int = 5000
    # The public library (Stage 5D): whether an address outside the allowed domains may
    # sign up for a free account (its own tenant, reading the library only), and the
    # score below which find_matching_tender answers no_match rather than a wrong match.
    free_signup_enabled: bool = True
    match_threshold: float = 0.75

    # Where reviewers reach the app; review links are built from it.
    public_base_url: str = "https://34.131.65.108"

    # The tender folders with their manifests (mounted read-only in the containers): the
    # freshness check reads each tender's source page from them. Days between two checks
    # of the corpus against the agencies' pages; 0 turns the weekly job off.
    tenders_root: str = "/work/tenders"
    freshness_interval_days: float = 7.0
