"""The OpenAI Agents SDK loop with a scripted model: tools wired, turns logged, limits kept."""

import json
from typing import Any

from agents.items import ModelResponse
from agents.models.interface import Model, ModelProvider
from agents.usage import InputTokensDetails, OutputTokensDetails, Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.harness import sdk_driver
from agent.service import AgentPassService
from core.llm.registry import load_prompt
from core.models import LLMCallLog
from tender.models import Tender
from tests.conftest import Pipeline
from tests.fixtures.tenders import DEADLINE

QUOTE = "The last date of bid submission is 30.03.2026 at 15:00 hrs."


def tool_call(call_id: str, name: str, **arguments: Any) -> ResponseFunctionToolCall:
    return ResponseFunctionToolCall(
        type="function_call", call_id=call_id, name=name, arguments=json.dumps(arguments)
    )


def final(text: str) -> ResponseOutputMessage:
    return ResponseOutputMessage(
        id="m-final",
        role="assistant",
        status="completed",
        type="message",
        content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
    )


class ScriptedModel(Model):
    """Plays a list of turns; past the end it keeps reading page 1."""

    def __init__(self, turns: list[list[Any]]) -> None:
        self.turns = turns
        self.inputs: list[Any] = []
        self.tools_seen: list[list[str]] = []

    async def get_response(
        self,
        system_instructions: Any,
        input: Any,
        model_settings: Any,
        tools: Any,
        *a: Any,
        **k: Any,
    ) -> ModelResponse:
        self.inputs.append(input)
        self.tools_seen.append(sorted(t.name for t in tools))
        n = len(self.inputs) - 1
        output = (
            self.turns[n]
            if n < len(self.turns)
            else [tool_call(f"loop-{n}", "read_pages", document_no=1, page_nos=[1], images=False)]
        )
        return ModelResponse(
            output=output,
            usage=Usage(
                requests=1,
                input_tokens=100 * (n + 1),
                input_tokens_details=InputTokensDetails(cached_tokens=0, cache_write_tokens=0),
                output_tokens=10,
                output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
                total_tokens=100 * (n + 1) + 10,
            ),
            response_id=f"resp-{n}",
        )

    def stream_response(self, *a: Any, **k: Any) -> Any:
        raise NotImplementedError


class ScriptedProvider(ModelProvider):
    def __init__(self, model: Model) -> None:
        self.model = model

    def get_model(self, model_name: str | None) -> Model:
        return self.model


def flat(items: Any) -> str:
    return json.dumps(items, default=str)


def test_the_loop_reads_submits_and_ends_with_every_turn_logged(
    pipeline: Pipeline, db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    model = ScriptedModel(
        [
            [tool_call("c1", "read_pages", document_no=1, page_nos=[2], images=False)],
            [
                tool_call(
                    "c2",
                    "submit_finding",
                    field_path=DEADLINE,
                    value='"30.03.2026"',
                    confidence=0.9,
                    rationale="the bid information sheet",
                    evidence=[{"document_no": 1, "page_no": 2, "quote": QUOTE}],
                )
            ],
            [final("done")],
        ]
    )
    driver = sdk_driver(
        pipeline.settings,
        pipeline.session_factory,
        load_prompt("agent_pass", "v1"),
        provider=ScriptedProvider(model),
    )
    run = service.start(db, readable_tender, created_by="pytest", is_fixture=True)
    done = service.run(db, run.id, driver)

    assert done.status == "done" and done.turns == 3
    assert done.pages_read == {"1": [2]}
    assert (done.tokens_in, done.tokens_out) == (600, 30) and done.cost_usd > 0
    rows = db.scalars(
        select(LLMCallLog).where(LLMCallLog.agent_run_id == run.id).order_by(LLMCallLog.created_at)
    ).all()
    assert [r.status for r in rows] == ["ok"] * 3
    assert all(
        r.prompt_name == "agent_pass" and r.model == pipeline.settings.openai_model for r in rows
    )
    assert all(r.is_fixture for r in rows)

    findings = service.findings(db, done)
    assert [(f.field_path, f.status, f.value) for f in findings] == [
        (DEADLINE, "accepted", "2026-03-30")
    ]
    span = findings[0].evidence[0]
    assert span["char_start"] is not None and span["page_no"] == 2

    assert model.tools_seen[0] == ["read_pages", "search_text", "submit_finding"]
    assert "Tender type: solar" in flat(model.inputs[0])
    assert "30.03.2026" in flat(model.inputs[1]), "the page text came back as the tool result"
    assert "accepted" in flat(model.inputs[2]) and DEADLINE in flat(model.inputs[2])


def test_the_turn_limit_stops_the_loop_and_keeps_what_was_read(
    pipeline: Pipeline, db: Session, service: AgentPassService, readable_tender: Tender
) -> None:
    settings = pipeline.settings.model_copy(update={"agent_max_turns": 3})
    model = ScriptedModel([])
    driver = sdk_driver(
        settings,
        pipeline.session_factory,
        load_prompt("agent_pass", "v1"),
        provider=ScriptedProvider(model),
    )
    run = service.start(db, readable_tender, created_by="pytest")
    stopped = service.run(db, run.id, driver)
    assert stopped.status == "stopped"
    assert stopped.error and stopped.error.startswith("stopped at the turn limit (3); ")
    assert stopped.turns == 3 and len(model.inputs) == 3
    assert stopped.pages_read == {"1": [1]}
