"""The OpenAI model behind the agent pass, logged like every other model call.

The OpenAI Agents SDK (agent/) asks a ModelProvider for its model and calls
`Model.get_response` once per turn. `LoggedProvider` hands it the provider's own
Responses-API model wrapped in `LoggedModel`, which writes one llm_call_log row per turn:
prompt name and version, model, input hash, the output items, tokens (cached input told
apart), cost at the configured list prices, latency and the outcome. This module and
`core.llm.client` are the only two that reach a model provider.
"""

import hashlib
import json
import time
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

from agents import OpenAIProvider
from agents.items import ModelResponse
from agents.models.interface import Model, ModelProvider
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings
from core.llm.registry import Prompt
from core.models import LLMCallLog

OUTPUT_SCHEMA = "agent_pass.turn"


def turn_cost(settings: Settings, *, tokens_in: int, cached: int, tokens_out: int) -> Decimal:
    """What one turn costs at the configured OpenAI prices. `tokens_in` is the whole
    input; `cached` the part of it the provider served from its prompt cache."""
    price_in = settings.openai_price_in_per_mtok
    usd = (
        (tokens_in - cached) * price_in
        + cached * price_in * settings.openai_cache_read_factor
        + tokens_out * settings.openai_price_out_per_mtok
    ) / 1e6
    return Decimal(str(round(usd, 6)))


class AgentCallLogger:
    """Writes the llm_call_log rows of one agent run."""

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        *,
        prompt: Prompt,
        agent_run_id: str,
        created_by: str,
        is_fixture: bool = False,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._prompt = prompt
        self._agent_run_id = agent_run_id
        self._created_by = created_by
        self._is_fixture = is_fixture

    def input_hash(self, system_instructions: str | None, turn_input: Any) -> str:
        canonical = json.dumps(
            {
                "model": self._settings.openai_model,
                "prompt": [self._prompt.name, self._prompt.version, self._prompt.sha256],
                "system": system_instructions,
                "input": turn_input,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def ok(self, input_hash: str, response: ModelResponse, latency_ms: int) -> str:
        usage = response.usage
        cached = usage.input_tokens_details.cached_tokens
        output = [_dump(item) for item in response.output]
        return self._write(
            input_hash=input_hash,
            status="ok",
            output={"items": output},
            request_id=response.request_id or response.response_id,
            tokens_in=usage.input_tokens - cached,
            tokens_out=usage.output_tokens,
            cache_read_tokens=cached,
            cost_usd=turn_cost(
                self._settings,
                tokens_in=usage.input_tokens,
                cached=cached,
                tokens_out=usage.output_tokens,
            ),
            latency_ms=latency_ms,
        )

    def failed(self, input_hash: str, error: str, latency_ms: int) -> str:
        return self._write(
            input_hash=input_hash, status="error", error=error[:2000], latency_ms=latency_ms
        )

    def _write(self, **fields: Any) -> str:
        row = LLMCallLog(
            tenant_id=self._settings.tenant_id,
            created_by=self._created_by,
            agent_run_id=self._agent_run_id,
            prompt_name=self._prompt.name,
            prompt_version=self._prompt.version,
            output_schema=OUTPUT_SCHEMA,
            model=self._settings.openai_model,
            is_fixture=self._is_fixture,
            **fields,
        )
        with self._session_factory() as session:
            session.add(row)
            session.commit()
            return row.id


class LoggedModel(Model):
    """The provider's model with one log row per call. The agent pass never streams."""

    def __init__(self, inner: Model, logger: AgentCallLogger) -> None:
        self._inner = inner
        self._logger = logger

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[Any],
        model_settings: Any,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: Any,
        *,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt: Any = None,
    ) -> ModelResponse:
        input_hash = self._logger.input_hash(system_instructions, input)
        started = time.perf_counter()
        try:
            response = await self._inner.get_response(
                system_instructions,
                input,
                model_settings,
                tools,
                output_schema,
                handoffs,
                tracing,
                previous_response_id=previous_response_id,
                conversation_id=conversation_id,
                prompt=prompt,
            )
        except Exception as exc:
            self._logger.failed(
                input_hash,
                f"{type(exc).__name__}: {exc}",
                int((time.perf_counter() - started) * 1000),
            )
            raise
        self._logger.ok(input_hash, response, int((time.perf_counter() - started) * 1000))
        return response

    def stream_response(
        self,
        system_instructions: str | None,
        input: str | list[Any],
        model_settings: Any,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: Any,
        *,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt: Any = None,
    ) -> AsyncIterator[Any]:
        raise NotImplementedError("the agent pass does not stream")


class LoggedProvider(ModelProvider):
    """Resolves the configured OpenAI model and wraps it for logging. `inner` may be any
    provider (tests hand in a scripted one)."""

    def __init__(self, logger: AgentCallLogger, inner: ModelProvider) -> None:
        self._logger = logger
        self._inner = inner

    def get_model(self, model_name: str | None) -> Model:
        return LoggedModel(self._inner.get_model(model_name), self._logger)


def openai_provider(settings: Settings) -> ModelProvider:
    """The real provider: the Responses API with the configured key."""
    return OpenAIProvider(api_key=settings.openai_api_key or None, use_responses=True)


def _dump(item: Any) -> Any:
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json", exclude_none=True)
    return json.loads(json.dumps(item, default=str))
