"""What a call costs at the configured prices. The provider's invoice is the truth; this is
the figure the reports print."""

from decimal import Decimal

from core.config import Settings


def call_cost(
    settings: Settings,
    *,
    tokens_in: int,
    tokens_out: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_write_1h_tokens: int = 0,
    batch: bool = False,
) -> Decimal:
    """tokens_in is the uncached input. cache_write_1h_tokens is the part of
    cache_write_tokens written with the one-hour lifetime."""
    price_in = settings.llm_price_in_per_mtok
    write_5m = cache_write_tokens - cache_write_1h_tokens
    usd = (
        tokens_in * price_in
        + cache_read_tokens * price_in * settings.llm_cache_read_factor
        + write_5m * price_in * settings.llm_cache_write_factor
        + cache_write_1h_tokens * price_in * settings.llm_cache_write_1h_factor
        + tokens_out * settings.llm_price_out_per_mtok
    ) / 1e6
    if batch:
        usd *= settings.llm_batch_factor
    return Decimal(str(round(usd, 6)))
