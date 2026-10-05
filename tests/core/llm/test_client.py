"""LLMClient against a mocked SDK: every outcome writes exactly one llm_call_log row."""

from types import SimpleNamespace
from typing import Any, cast

import anthropic
import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings
from core.llm.client import LLMCallError, LLMClient, LLMRequest, PdfPart, TextPart
from core.llm.registry import UnregisteredPromptError
from core.llm.smoke import SmokeResult
from core.models import LLMCallLog


class FakeMessages:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def message(**overrides: Any) -> SimpleNamespace:
    parsed = SmokeResult(answer="It works.", saw_document=False, quote=None)
    fields: dict[str, Any] = {
        "model": "claude-fable-5-1",
        "stop_reason": "end_turn",
        "stop_details": None,
        "_request_id": "req_test_1",
        "usage": SimpleNamespace(input_tokens=321, output_tokens=45, cache_read_input_tokens=0),
        "content": [SimpleNamespace(type="text", text=parsed.model_dump_json())],
        "parsed_output": parsed,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def make_client(
    settings: Settings, session_factory: sessionmaker[Session], result: Any
) -> tuple[LLMClient, FakeMessages]:
    fake = FakeMessages(result)
    sdk = cast(anthropic.Anthropic, SimpleNamespace(messages=fake))
    return LLMClient(settings, session_factory, sdk=sdk), fake


def request(**overrides: Any) -> LLMRequest[SmokeResult]:
    fields: dict[str, Any] = {
        "prompt_name": "smoke",
        "prompt_version": "v1",
        "content": [TextPart(text="Reply that the connection works.")],
        "response_model": SmokeResult,
        "created_by": "pytest",
        "is_fixture": True,
    }
    fields.update(overrides)
    return LLMRequest[SmokeResult](**fields)


def rows(db: Session) -> list[LLMCallLog]:
    return list(db.scalars(select(LLMCallLog)))


def test_successful_call_returns_typed_output_and_writes_one_log_row(
    settings: Settings, session_factory: sessionmaker[Session], db: Session
) -> None:
    client, fake = make_client(settings, session_factory, message())

    response = client.call(request())

    assert response.parsed == SmokeResult(answer="It works.", saw_document=False, quote=None)
    assert (response.prompt_name, response.prompt_version) == ("smoke", "v1")
    [row] = rows(db)
    assert row.id == response.call_log_id
    assert row.status == "ok"
    assert row.tenant_id == "ergplan" and row.created_by == "pytest"
    assert (row.prompt_name, row.prompt_version) == ("smoke", "v1")
    assert row.output_schema == "core.llm.smoke.SmokeResult"
    assert row.model == "claude-fable-5-1"
    assert len(row.input_hash) == 64
    assert row.output == {"answer": "It works.", "saw_document": False, "quote": None}
    assert (row.tokens_in, row.tokens_out) == (321, 45)
    assert row.latency_ms >= 0
    assert row.request_id == "req_test_1" and row.stop_reason == "end_turn"
    assert row.is_fixture is True and row.error is None


def test_request_uses_the_registered_prompt_the_configured_model_and_the_schema(
    settings: Settings, session_factory: sessionmaker[Session], db: Session
) -> None:
    client, fake = make_client(settings, session_factory, message())
    client.call(request(max_tokens=1234))
    [call] = fake.calls
    assert call["model"] == "claude-fable-5-1"
    assert call["max_tokens"] == 1234
    assert "connectivity check" in call["system"]
    assert call["output_format"] is SmokeResult
    assert "tool_choice" not in call and "thinking" not in call


def test_pdf_parts_are_sent_as_documents_before_text(
    settings: Settings, session_factory: sessionmaker[Session], db: Session
) -> None:
    client, fake = make_client(settings, session_factory, message())
    client.call(
        request(content=[TextPart(text="Who issued it?"), PdfPart(data_b64="QUJD", title="a.pdf")])
    )
    blocks = fake.calls[0]["messages"][0]["content"]
    assert [b["type"] for b in blocks] == ["document", "text"]
    assert blocks[0]["source"] == {
        "type": "base64",
        "media_type": "application/pdf",
        "data": "QUJD",
    }
    assert blocks[0]["title"] == "a.pdf"


def test_input_hash_is_stable_and_changes_with_the_input(
    settings: Settings, session_factory: sessionmaker[Session], db: Session
) -> None:
    client, _ = make_client(settings, session_factory, message())
    client.call(request())
    client.call(request())
    client.call(request(content=[TextPart(text="A different question.")]))
    hashes = [row.input_hash for row in rows(db)]
    assert len(hashes) == 3
    assert len(set(hashes)) == 2


def test_refusal_is_logged_and_raised_not_returned(
    settings: Settings, session_factory: sessionmaker[Session], db: Session
) -> None:
    refused = message(
        stop_reason="refusal",
        stop_details=SimpleNamespace(category="cyber", explanation="declined"),
        parsed_output=None,
        content=[],
    )
    client, _ = make_client(settings, session_factory, refused)
    with pytest.raises(LLMCallError) as caught:
        client.call(request())
    assert caught.value.status == "refusal" and caught.value.retryable is False
    [row] = rows(db)
    assert row.id == caught.value.call_log_id
    assert row.status == "refusal" and row.error == "cyber: declined" and row.output is None


def test_truncated_output_is_logged_with_the_raw_text(
    settings: Settings, session_factory: sessionmaker[Session], db: Session
) -> None:
    cut = message(
        stop_reason="max_tokens",
        parsed_output=None,
        content=[SimpleNamespace(type="text", text='{"answer": "It wor')],
    )
    client, _ = make_client(settings, session_factory, cut)
    with pytest.raises(LLMCallError) as caught:
        client.call(request())
    assert caught.value.status == "truncated"
    [row] = rows(db)
    assert row.status == "truncated" and row.output == {"raw_text": '{"answer": "It wor'}
    assert row.tokens_out == 45


def test_output_that_fails_the_schema_is_logged_as_invalid(
    settings: Settings, session_factory: sessionmaker[Session], db: Session
) -> None:
    bad = message(parsed_output=None, content=[SimpleNamespace(type="text", text="not json")])
    client, _ = make_client(settings, session_factory, bad)
    with pytest.raises(LLMCallError) as caught:
        client.call(request())
    assert caught.value.status == "invalid_output"
    [row] = rows(db)
    assert row.status == "invalid_output" and row.output == {"raw_text": "not json"}


def _http_error(cls: type[anthropic.APIStatusError], status: int) -> anthropic.APIStatusError:
    http_request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, request=http_request, headers={"request-id": "req_err"})
    return cls("boom", response=response, body=None)


@pytest.mark.parametrize(
    ("error", "retryable", "fragment"),
    [
        (_http_error(anthropic.RateLimitError, 429), True, "rate_limited"),
        (_http_error(anthropic.InternalServerError, 500), True, "http_500"),
        (_http_error(anthropic.BadRequestError, 400), False, "http_400"),
        (
            anthropic.APIConnectionError(
                request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
            ),
            True,
            "connection",
        ),
    ],
)
def test_api_errors_are_logged_and_classified(
    settings: Settings,
    session_factory: sessionmaker[Session],
    db: Session,
    error: Exception,
    retryable: bool,
    fragment: str,
) -> None:
    client, _ = make_client(settings, session_factory, error)
    with pytest.raises(LLMCallError) as caught:
        client.call(request())
    assert caught.value.status == "error" and caught.value.retryable is retryable
    [row] = rows(db)
    assert row.status == "error" and row.error is not None and fragment in row.error
    assert row.output is None and row.tokens_in == 0


def test_unregistered_prompt_version_never_reaches_the_sdk_or_the_log(
    settings: Settings, session_factory: sessionmaker[Session], db: Session
) -> None:
    client, fake = make_client(settings, session_factory, message())
    with pytest.raises(UnregisteredPromptError):
        client.call(request(prompt_version="v99"))
    assert fake.calls == []
    assert rows(db) == []


def test_empty_content_is_rejected_by_the_request_type() -> None:
    with pytest.raises(ValueError):
        request(content=[])


def test_cost_is_logged_at_the_configured_prices_with_cache_factors(
    settings: Settings, session_factory: sessionmaker[Session], db: Session
) -> None:
    usage = SimpleNamespace(
        input_tokens=1000,
        output_tokens=200,
        cache_read_input_tokens=40_000,
        cache_creation_input_tokens=8000,
    )
    client, _ = make_client(settings, session_factory, message(usage=usage))
    response = client.call(request())
    [row] = rows(db)
    assert (row.tokens_in, row.cache_read_tokens, row.cache_write_tokens) == (1000, 40_000, 8000)
    expected = (1000 * 10 + 40_000 * 10 * 0.025 + 8000 * 10 * 1.25 + 200 * 50) / 1e6
    assert float(row.cost_usd) == pytest.approx(expected)
    assert response.cost_usd == row.cost_usd and row.mode == "sync" and row.batch_id is None


def extract_request(**overrides: Any) -> LLMRequest[SmokeResult]:
    """A request on a prompt that extends another (extract/key_dates extends extract/v1
    in the tender packs; here the core pair is enough)."""
    return request(
        prompt_name="smoke_child",
        content=[PdfPart(data_b64="QUJD", title="a.pdf"), TextPart(text="Fields: x")],
        **overrides,
    )


@pytest.fixture()
def child_prompt_root(tmp_path: Any) -> Any:
    header = "---\npurpose: test\ninputs: test\noutput_schema: test\nknown_failure_modes: none\n"
    (tmp_path / "smoke_parent").mkdir()
    (tmp_path / "smoke_parent" / "v1.md").write_text(header + "---\nShared rules.\n")
    (tmp_path / "smoke_child").mkdir()
    (tmp_path / "smoke_child" / "v1.md").write_text(
        header + "extends: smoke_parent/v1\n---\nRules of this group.\n"
    )
    return tmp_path


def test_cached_documents_end_a_prefix_that_holds_only_what_calls_share(
    settings: Settings, session_factory: sessionmaker[Session], db: Session, child_prompt_root: Any
) -> None:
    fake = FakeMessages(message())
    sdk = cast(anthropic.Anthropic, SimpleNamespace(messages=fake))
    client = LLMClient(settings, session_factory, sdk=sdk, prompt_roots=(child_prompt_root,))

    client.call(extract_request())
    client.call(extract_request(cache_documents=True))
    client.call(extract_request(cache_documents=True, cache_ttl="1h"))

    plain, cached, hour = fake.calls
    assert plain["system"] == "Shared rules.\n\nRules of this group."
    assert [b["type"] for b in plain["messages"][0]["content"]] == ["document", "text"]
    assert "cache_control" not in plain["messages"][0]["content"][0]

    assert cached["system"] == "Shared rules."
    document, own, fields = cached["messages"][0]["content"]
    assert document["cache_control"] == {"type": "ephemeral"}
    assert own == {"type": "text", "text": "Rules of this group."}
    assert fields["text"] == "Fields: x"
    assert hour["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    plain_hash, cached_hash, hour_hash = [row.input_hash for row in rows(db)]
    assert plain_hash != cached_hash and cached_hash == hour_hash


def test_logged_returns_an_identical_call_of_the_same_run_without_calling(
    settings: Settings, session_factory: sessionmaker[Session], db: Session
) -> None:
    client, fake = make_client(settings, session_factory, message())
    assert client.logged(request()) is None  # no run: nothing to look up
    run = _run(db)
    first = client.call(request(extraction_run_id=run))
    again = client.logged(request(extraction_run_id=run))
    assert again is not None and again.call_log_id == first.call_log_id
    assert again.parsed == first.parsed and len(fake.calls) == 1
    assert client.logged(request(extraction_run_id=run, content=[TextPart(text="Other")])) is None


def _run(db: Session) -> str:
    from core.models import Document, ExtractionRun

    document = Document(
        tenant_id="ergplan",
        created_by="pytest",
        sha256="0" * 64,
        filename="a.pdf",
        mime="application/pdf",
        storage_path="a.pdf",
        status="parsed",
    )
    db.add(document)
    db.flush()
    run = ExtractionRun(
        tenant_id="ergplan",
        created_by="pytest",
        document_id=document.id,
        object_type="document",
        object_id=document.id,
        schema_name="s",
        schema_version="v1",
        prompt_version="v1",
        model="claude-fable-5-1",
    )
    db.add(run)
    db.commit()
    return run.id


class FakeBatches:
    def __init__(self, results: list[Any], ended: bool = True) -> None:
        self.results_list, self.ended = results, ended
        self.created: list[Any] = []

    def create(self, requests: Any) -> Any:
        self.created.append(requests)
        return SimpleNamespace(id="msgbatch_1")

    def retrieve(self, batch_id: str) -> Any:
        return SimpleNamespace(processing_status="ended" if self.ended else "in_progress")

    def results(self, batch_id: str) -> Any:
        return self.results_list


def test_a_batch_is_submitted_with_the_schema_and_collected_into_the_call_log(
    settings: Settings, session_factory: sessionmaker[Session], db: Session
) -> None:
    from core.models import LLMBatch

    good, bad = request(), request(content=[TextPart(text="Second question.")])
    batches = FakeBatches([])
    sdk = cast(anthropic.Anthropic, SimpleNamespace(messages=SimpleNamespace(batches=batches)))
    client = LLMClient(settings, session_factory, sdk=sdk)

    batch_id = client.submit_batch([good, bad, good], created_by="pytest")

    [sent] = batches.created
    assert len(sent) == 2  # the repeated request is sent once
    assert sent[0]["custom_id"] == client.input_hash(good)[:40]
    params = sent[0]["params"]
    assert params["model"] == "claude-fable-5-1" and "connectivity check" in params["system"]
    schema = params["output_config"]["format"]
    assert schema["type"] == "json_schema" and "answer" in schema["schema"]["properties"]
    row = db.scalars(select(LLMBatch)).one()
    assert (row.status, row.request_count, row.provider_batch_id) == ("submitted", 2, "msgbatch_1")
    assert rows(db) == []

    batches.ended = False
    assert client.collect_batch(batch_id, [good, bad]) is False and rows(db) == []

    batches.ended = True
    usage = SimpleNamespace(
        input_tokens=1000,
        output_tokens=100,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=4000,
        cache_creation=SimpleNamespace(ephemeral_1h_input_tokens=4000),
    )
    text = SmokeResult(answer="From the batch.", saw_document=False, quote=None).model_dump_json()
    batches.results_list = [
        SimpleNamespace(
            custom_id=client.input_hash(bad)[:40],
            result=SimpleNamespace(type="errored", error="overloaded"),
        ),
        SimpleNamespace(
            custom_id=client.input_hash(good)[:40],
            result=SimpleNamespace(
                type="succeeded",
                message=SimpleNamespace(
                    model="claude-fable-5-1",
                    stop_reason="end_turn",
                    usage=usage,
                    content=[SimpleNamespace(type="text", text=text)],
                ),
            ),
        ),
    ]
    assert client.collect_batch(batch_id, [good, bad]) is True
    by_status = {row.status: row for row in rows(db)}
    assert set(by_status) == {"ok", "error"}
    ok = by_status["ok"]
    assert ok.mode == "batch" and ok.batch_id == "msgbatch_1"
    assert ok.output is not None and ok.output["answer"] == "From the batch."
    # Half price, with the cache written for an hour at twice the input price.
    assert float(ok.cost_usd) == pytest.approx((1000 * 10 + 4000 * 20 + 100 * 50) / 1e6 / 2)
    assert by_status["error"].error == "batch_errored: overloaded"
    db.expire_all()
    assert db.scalars(select(LLMBatch)).one().status == "collected"
    # Collecting again reads nothing twice.
    assert client.collect_batch(batch_id, [good, bad]) is True and len(rows(db)) == 2
