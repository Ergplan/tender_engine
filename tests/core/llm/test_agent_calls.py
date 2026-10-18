"""The agent's model calls are logged like every other call."""

import asyncio
from decimal import Decimal
from typing import Any

import pytest
from agents.items import ModelResponse
from agents.models.interface import Model, ModelProvider
from agents.usage import InputTokensDetails, OutputTokensDetails, Usage
from openai.types.responses import ResponseOutputMessage, ResponseOutputText
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from agent.models import AgentRun
from core.config import Settings
from core.llm.agent_calls import (
    AgentCallLogger,
    LoggedModel,
    LoggedProvider,
    openai_provider,
    turn_cost,
)
from core.llm.registry import load_prompt
from core.models import LLMCallLog


def usage(tokens_in: int = 1000, cached: int = 400, tokens_out: int = 50) -> Usage:
    return Usage(
        requests=1,
        input_tokens=tokens_in,
        input_tokens_details=InputTokensDetails(cached_tokens=cached, cache_write_tokens=0),
        output_tokens=tokens_out,
        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        total_tokens=tokens_in + tokens_out,
    )


def message(text: str = "hi") -> ResponseOutputMessage:
    return ResponseOutputMessage(
        id="m1",
        role="assistant",
        status="completed",
        type="message",
        content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
    )


class FakeModel(Model):
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def get_response(
        self, system_instructions: Any, input: Any, *args: Any, **kwargs: Any
    ) -> ModelResponse:
        self.calls.append({"system": system_instructions, "input": input})
        if self.error is not None:
            raise self.error
        return ModelResponse(output=[message()], usage=usage(), response_id="resp_1")

    def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


class FakeProvider(ModelProvider):
    def __init__(self, model: Model) -> None:
        self.model = model
        self.asked: list[str | None] = []

    def get_model(self, model_name: str | None) -> Model:
        self.asked.append(model_name)
        return self.model


def agent_run(db: Session, settings: Settings) -> AgentRun:
    run = AgentRun(
        tenant_id=settings.tenant_id,
        created_by="pytest",
        object_type="tender",
        object_id="0" * 32,
        object_version=1,
        schema_name="power.solar",
        schema_version="v4",
        prompt_name="agent_pass",
        prompt_version="v1",
        model=settings.openai_model,
        status="running",
        is_fixture=True,
    )
    db.add(run)
    db.commit()
    return run


def logger_for(
    settings: Settings, session_factory: sessionmaker[Session], run: AgentRun
) -> AgentCallLogger:
    return AgentCallLogger(
        settings,
        session_factory,
        prompt=load_prompt("agent_pass", "v1"),
        agent_run_id=run.id,
        created_by="pytest",
        is_fixture=True,
    )


def call(model: Model, turn_input: Any = "hello") -> ModelResponse:
    from agents import ModelSettings
    from agents.models.interface import ModelTracing

    return asyncio.run(
        model.get_response(
            "be brief",
            turn_input,
            ModelSettings(),
            [],
            None,
            [],
            ModelTracing.DISABLED,
            previous_response_id=None,
            conversation_id=None,
            prompt=None,
        )
    )


def test_turn_cost_prices_cached_input_at_the_factor(settings: Settings) -> None:
    local = settings.model_copy(
        update={
            "openai_price_in_per_mtok": 2.0,
            "openai_price_out_per_mtok": 8.0,
            "openai_cache_read_factor": 0.25,
        }
    )
    # 600 uncached at 2.0, 400 cached at 0.5, 50 out at 8.0: (1200 + 200 + 400) / 1e6
    assert turn_cost(local, tokens_in=1000, cached=400, tokens_out=50) == Decimal("0.0018")
    assert turn_cost(local, tokens_in=0, cached=0, tokens_out=0) == Decimal("0")


def test_a_call_is_logged_with_its_tokens_cost_output_and_run(
    settings: Settings, session_factory: sessionmaker[Session], db: Session
) -> None:
    run = agent_run(db, settings)
    inner = FakeModel()
    logged = LoggedModel(inner, logger_for(settings, session_factory, run))

    response = call(logged, [{"role": "user", "content": "page two"}])
    assert response.response_id == "resp_1" and inner.calls[0]["system"] == "be brief"

    row = db.scalars(select(LLMCallLog).where(LLMCallLog.agent_run_id == run.id)).one()
    assert (row.status, row.prompt_name, row.prompt_version, row.model) == (
        "ok",
        "agent_pass",
        "v1",
        settings.openai_model,
    )
    assert (row.tokens_in, row.cache_read_tokens, row.tokens_out) == (600, 400, 50)
    assert row.cost_usd == turn_cost(settings, tokens_in=1000, cached=400, tokens_out=50)
    assert row.cost_usd > 0
    assert row.output is not None and row.output["items"][0]["content"][0]["text"] == "hi"
    assert row.request_id == "resp_1" and row.latency_ms >= 0
    assert row.output_schema == "agent_pass.turn" and row.is_fixture and row.created_by == "pytest"
    assert row.extraction_run_id is None and len(row.input_hash) == 64

    # The same turn hashes the same; another input differently.
    logger = logger_for(settings, session_factory, run)
    same = logger.input_hash("be brief", [{"role": "user", "content": "page two"}])
    assert same == row.input_hash
    assert logger.input_hash("be brief", "other") != same


def test_a_failed_call_is_logged_as_an_error_and_raised(
    settings: Settings, session_factory: sessionmaker[Session], db: Session
) -> None:
    run = agent_run(db, settings)
    logged = LoggedModel(
        FakeModel(error=TimeoutError("provider timed out")),
        logger_for(settings, session_factory, run),
    )
    with pytest.raises(TimeoutError, match="provider timed out"):
        call(logged)
    row = db.scalars(select(LLMCallLog).where(LLMCallLog.agent_run_id == run.id)).one()
    assert (row.status, row.error) == ("error", "TimeoutError: provider timed out")
    assert (row.tokens_in, row.tokens_out, row.cost_usd, row.output) == (0, 0, 0, None)


def test_the_provider_wraps_the_inner_model_and_streaming_is_refused(
    settings: Settings, session_factory: sessionmaker[Session], db: Session
) -> None:
    run = agent_run(db, settings)
    inner = FakeProvider(FakeModel())
    provider = LoggedProvider(logger_for(settings, session_factory, run), inner)
    model = provider.get_model("gpt-test")
    assert isinstance(model, LoggedModel) and inner.asked == ["gpt-test"]
    with pytest.raises(NotImplementedError):
        model.stream_response("s", "i", None, [], None, [], None)
    call(model)
    assert db.scalar(select(LLMCallLog.status).where(LLMCallLog.agent_run_id == run.id)) == "ok"


def test_the_real_provider_uses_the_responses_api(settings: Settings) -> None:
    provider = openai_provider(settings.model_copy(update={"openai_api_key": "sk-test-not-real"}))
    from agents.models.openai_responses import OpenAIResponsesModel

    assert isinstance(provider.get_model("gpt-test"), OpenAIResponsesModel)
