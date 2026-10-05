"""The only module that calls the Anthropic SDK.

LLMClient.call: typed request in, typed response out, a registered prompt version, SDK
retries with backoff, and one llm_call_log row for every outcome.

Two ways to pay less for the same call:

- Prompt cache. A request with `cache_documents` marks its last document as the end of a
  prefix that other calls share. Everything before that mark must then be the same for
  those calls, so the system prompt is the part of the prompt they have in common
  (`Prompt.shared_text`) and the prompt's own text moves behind the document.
- Batch API. submit_batch hands calls nobody waits for to the provider; collect_batch
  writes the same llm_call_log row per call that `call` would have written.

LLMClient.logged returns the answer of an identical call the run has already been given.
"""

import hashlib
import json
import time
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

import anthropic
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings
from core.llm.pricing import call_cost
from core.llm.registry import CORE_PROMPT_ROOT, Prompt, load_prompt
from core.models import LLMBatch, LLMCallLog

CallStatus = Literal["ok", "refusal", "truncated", "invalid_output", "error"]
CallMode = Literal["sync", "batch"]


class TextPart(BaseModel):
    kind: Literal["text"] = "text"
    text: str


class PdfPart(BaseModel):
    """A PDF sent as native document input. data_b64 is base64 without newlines."""

    kind: Literal["pdf"] = "pdf"
    data_b64: str
    title: str | None = None


class LLMRequest[T: BaseModel](BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    prompt_name: str
    prompt_version: str
    content: list[TextPart | PdfPart] = Field(min_length=1)
    response_model: type[T]
    created_by: str
    max_tokens: int | None = None
    is_fixture: bool = False
    extraction_run_id: str | None = None
    output_schema_name: str | None = None
    # The documents are a prefix shared with other calls: cache them.
    cache_documents: bool = False
    cache_ttl: Literal["5m", "1h"] = "5m"


class LLMResponse[T: BaseModel](BaseModel):
    parsed: T
    call_log_id: str
    model: str
    prompt_name: str
    prompt_version: str
    tokens_in: int
    tokens_out: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    mode: CallMode = "sync"
    latency_ms: int
    stop_reason: str | None


class LLMCallError(RuntimeError):
    """The call did not produce a validated output. The log row is already written."""

    def __init__(self, status: CallStatus, message: str, call_log_id: str, retryable: bool):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.call_log_id = call_log_id
        self.retryable = retryable


class LLMClient:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        sdk: anthropic.Anthropic | None = None,
        prompt_roots: tuple[Path, ...] = (CORE_PROMPT_ROOT,),
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._prompt_roots = prompt_roots
        self._sdk = sdk or anthropic.Anthropic(
            api_key=settings.anthropic_api_key or None,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout_seconds,
        )

    @property
    def model(self) -> str:
        return self._settings.anthropic_model

    def prompt(self, name: str, version: str) -> Prompt:
        """Load a registered prompt, or raise UnregisteredPromptError."""
        return load_prompt(name, version, self._prompt_roots)

    def input_hash(self, request: LLMRequest[Any]) -> str:
        prompt = self.prompt(request.prompt_name, request.prompt_version)
        return _input_hash(self._settings.anthropic_model, prompt, request)

    def call[T: BaseModel](self, request: LLMRequest[T]) -> LLMResponse[T]:
        """Run one model call. Raises UnregisteredPromptError before any network use."""
        prompt = self.prompt(request.prompt_name, request.prompt_version)
        model = self._settings.anthropic_model
        input_hash = _input_hash(model, prompt, request)
        started = time.perf_counter()

        def elapsed_ms() -> int:
            return int((time.perf_counter() - started) * 1000)

        def failed(message: str, **fields: Any) -> str:
            return self._log(
                request,
                prompt,
                input_hash,
                "error",
                error=message,
                latency_ms=elapsed_ms(),
                **fields,
            )

        try:
            message = self._sdk.messages.parse(
                **_params(model, self._settings.llm_max_tokens, prompt, request),
                output_format=request.response_model,
            )
        except anthropic.RateLimitError as exc:
            log_id = failed(f"rate_limited: {exc.message}")
            raise LLMCallError("error", "rate limited after retries", log_id, True) from exc
        except anthropic.APIStatusError as exc:
            retryable = exc.status_code >= 500
            log_id = failed(f"http_{exc.status_code}: {exc.message}", request_id=exc.request_id)
            raise LLMCallError("error", f"HTTP {exc.status_code}", log_id, retryable) from exc
        except anthropic.APIConnectionError as exc:
            log_id = failed(f"connection: {exc}")
            raise LLMCallError("error", "connection failed after retries", log_id, True) from exc
        return self._outcome(
            request, prompt, input_hash, message, message.parsed_output, latency_ms=elapsed_ms()
        )

    def logged[T: BaseModel](self, request: LLMRequest[T]) -> LLMResponse[T] | None:
        """The answer of an identical call already made for the request's extraction run,
        if there is one: same model, prompt, schema and content. Nothing is sent or logged.
        This is how a run that was interrupted, or whose calls went through a batch,
        continues without paying twice."""
        if request.extraction_run_id is None:
            return None
        with self._session_factory() as session:
            row = session.scalars(
                select(LLMCallLog)
                .where(
                    LLMCallLog.tenant_id == self._settings.tenant_id,
                    LLMCallLog.extraction_run_id == request.extraction_run_id,
                    LLMCallLog.input_hash == self.input_hash(request),
                    LLMCallLog.status == "ok",
                )
                .order_by(LLMCallLog.created_at.desc())
                .limit(1)
            ).first()
            if row is None or row.output is None:
                return None
            try:
                parsed = request.response_model.model_validate(row.output)
            except ValidationError:
                return None
            return LLMResponse[T](
                parsed=parsed,
                call_log_id=row.id,
                model=row.model,
                prompt_name=row.prompt_name,
                prompt_version=row.prompt_version,
                tokens_in=row.tokens_in,
                tokens_out=row.tokens_out,
                cache_read_tokens=row.cache_read_tokens,
                cache_write_tokens=row.cache_write_tokens,
                cost_usd=row.cost_usd,
                mode=cast(CallMode, row.mode),
                latency_ms=row.latency_ms,
                stop_reason=row.stop_reason,
            )

    def submit_batch(
        self,
        requests: Sequence[LLMRequest[Any]],
        *,
        created_by: str,
        extraction_run_id: str | None = None,
        wave: int = 1,
    ) -> str:
        """Hand the calls to the batch API. Returns the id of the llm_batch row; the calls
        are logged when collect_batch reads their results."""
        model = self._settings.anthropic_model
        entries: dict[str, dict[str, Any]] = {}
        batch_requests = []
        for request in requests:
            prompt = self.prompt(request.prompt_name, request.prompt_version)
            input_hash = _input_hash(model, prompt, request)
            custom_id = input_hash[:40]
            if custom_id in entries:
                continue
            entries[custom_id] = {
                "input_hash": input_hash,
                "prompt_name": prompt.name,
                "prompt_version": prompt.version,
            }
            params = _params(model, self._settings.llm_max_tokens, prompt, request)
            params["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": anthropic.transform_schema(request.response_model),
                }
            }
            batch_requests.append({"custom_id": custom_id, "params": params})
        if not batch_requests:
            raise ValueError("a batch needs at least one request")
        batch = self._sdk.messages.batches.create(requests=cast(Any, batch_requests))
        row = LLMBatch(
            tenant_id=self._settings.tenant_id,
            created_by=created_by,
            extraction_run_id=extraction_run_id,
            provider_batch_id=batch.id,
            wave=wave,
            status="submitted",
            requests=entries,
            request_count=len(entries),
        )
        with self._session_factory() as session:
            session.add(row)
            session.commit()
            return row.id

    def collect_batch(self, batch_id: str, requests: Sequence[LLMRequest[Any]]) -> bool:
        """Read the results of a batch once the provider has finished it, and write one
        llm_call_log row per call. `requests` are the calls as they were submitted (they
        carry the response models). Returns False while the batch is still being worked
        on. A call that failed in the batch is logged as an error and is not retried here.
        A call of the batch that is already logged is not logged again."""
        with self._session_factory() as session:
            row = session.scalars(
                select(LLMBatch).where(
                    LLMBatch.id == batch_id, LLMBatch.tenant_id == self._settings.tenant_id
                )
            ).one()
            provider_id, entries, status = row.provider_batch_id, dict(row.requests), row.status
        if status == "collected":
            return True
        if self._sdk.messages.batches.retrieve(provider_id).processing_status != "ended":
            return False
        model = self._settings.anthropic_model
        by_id: dict[str, tuple[LLMRequest[Any], Prompt, str]] = {}
        for request in requests:
            prompt = self.prompt(request.prompt_name, request.prompt_version)
            input_hash = _input_hash(model, prompt, request)
            by_id[input_hash[:40]] = (request, prompt, input_hash)
        # A collection that was interrupted has logged some of the batch's calls already.
        with self._session_factory() as session:
            logged = set(
                session.scalars(
                    select(LLMCallLog.input_hash).where(
                        LLMCallLog.tenant_id == self._settings.tenant_id,
                        LLMCallLog.batch_id == provider_id,
                    )
                )
            )
        for item in self._sdk.messages.batches.results(provider_id):
            known = by_id.get(item.custom_id)
            if known is None or item.custom_id not in entries:
                continue
            request, prompt, input_hash = known
            if input_hash in logged:
                continue
            result = item.result
            if result.type != "succeeded":
                error = getattr(result, "error", None)
                self._log(
                    request,
                    prompt,
                    input_hash,
                    "error",
                    error=f"batch_{result.type}: {error}" if error else f"batch_{result.type}",
                    mode="batch",
                    batch_id=provider_id,
                )
                continue
            message = result.message
            text = "".join(block.text for block in message.content if block.type == "text")
            try:
                parsed = request.response_model.model_validate_json(text)
            except ValidationError:
                parsed = None
            try:
                self._outcome(
                    request, prompt, input_hash, message, parsed, mode="batch", batch_id=provider_id
                )
            except LLMCallError:
                # Logged; the caller sees that the call has no answer and decides.
                continue
        with self._session_factory() as session:
            session.execute(
                update(LLMBatch)
                .where(LLMBatch.id == batch_id, LLMBatch.tenant_id == self._settings.tenant_id)
                .values(status="collected")
            )
            session.commit()
        return True

    def _outcome[T: BaseModel](
        self,
        request: LLMRequest[T],
        prompt: Prompt,
        input_hash: str,
        message: Any,
        parsed: T | None,
        *,
        mode: CallMode = "sync",
        batch_id: str | None = None,
        latency_ms: int = 0,
    ) -> LLMResponse[T]:
        """Log what came back and return it, or raise LLMCallError. The same for a call
        that was waited for and for one read from a batch."""
        usage = message.usage
        cache_read = getattr(usage, "cache_read_input_tokens", None) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", None) or 0
        write_1h = getattr(getattr(usage, "cache_creation", None), "ephemeral_1h_input_tokens", 0)
        cost = call_cost(
            self._settings,
            tokens_in=usage.input_tokens,
            tokens_out=usage.output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            cache_write_1h_tokens=min(write_1h or 0, cache_write),
            batch=mode == "batch",
        )
        common: dict[str, Any] = {
            "model": message.model,
            "stop_reason": message.stop_reason,
            "request_id": getattr(message, "_request_id", None),
            "tokens_in": usage.input_tokens,
            "tokens_out": usage.output_tokens,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "cost_usd": cost,
            "mode": mode,
            "batch_id": batch_id,
            "latency_ms": latency_ms,
        }
        raw_text = "".join(block.text for block in message.content if block.type == "text")

        def log(status: CallStatus, **fields: Any) -> str:
            return self._log(request, prompt, input_hash, status, **fields, **common)

        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            reason = f"{details.category}: {details.explanation}" if details else "no details"
            log_id = log("refusal", error=reason)
            raise LLMCallError("refusal", reason, log_id, False)
        if message.stop_reason == "max_tokens":
            log_id = log("truncated", output={"raw_text": raw_text})
            raise LLMCallError("truncated", "output hit max_tokens", log_id, False)
        if parsed is None:
            log_id = log("invalid_output", output={"raw_text": raw_text})
            raise LLMCallError("invalid_output", "output did not match the schema", log_id, False)

        log_id = log("ok", output=parsed.model_dump(mode="json"))
        return LLMResponse[T](
            parsed=parsed,
            call_log_id=log_id,
            model=message.model,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            tokens_in=usage.input_tokens,
            tokens_out=usage.output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            cost_usd=cost,
            mode=mode,
            latency_ms=latency_ms,
            stop_reason=message.stop_reason,
        )

    def _log(
        self,
        request: LLMRequest[Any],
        prompt: Prompt,
        input_hash: str,
        status: CallStatus,
        **fields: Any,
    ) -> str:
        row = LLMCallLog(
            tenant_id=self._settings.tenant_id,
            created_by=request.created_by,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            output_schema=request.output_schema_name
            or f"{request.response_model.__module__}.{request.response_model.__qualname__}",
            model=fields.pop("model", self._settings.anthropic_model),
            input_hash=input_hash,
            status=status,
            is_fixture=request.is_fixture,
            extraction_run_id=request.extraction_run_id,
            **fields,
        )
        with self._session_factory() as session:
            session.add(row)
            session.commit()
            return row.id


def _params(
    model: str, default_max_tokens: int, prompt: Prompt, request: LLMRequest[Any]
) -> dict[str, Any]:
    """The request as the API takes it, the same for a call and for a batch entry."""
    shared = request.cache_documents and bool(prompt.own_text)
    return {
        "model": model,
        "max_tokens": request.max_tokens or default_max_tokens,
        "system": prompt.shared_text if shared else prompt.text,
        "messages": [{"role": "user", "content": _content_blocks(request, prompt)}],
    }


def _content_blocks(request: LLMRequest[Any], prompt: Prompt) -> list[Any]:
    """Documents first, then text, as the API recommends for PDF input. With
    cache_documents the last document closes the cached prefix, and the prompt's own text
    (which differs between the calls that share the prefix) follows it."""
    blocks: list[Any] = []
    for part in request.content:
        if isinstance(part, PdfPart):
            block: dict[str, Any] = {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": part.data_b64,
                },
            }
            if part.title:
                block["title"] = part.title
            blocks.append(block)
    if request.cache_documents and blocks:
        control: dict[str, str] = {"type": "ephemeral"}
        if request.cache_ttl == "1h":
            control["ttl"] = "1h"
        blocks[-1]["cache_control"] = control
        if prompt.own_text:
            blocks.append({"type": "text", "text": prompt.own_text})
    blocks.extend({"type": "text", "text": p.text} for p in request.content if p.kind == "text")
    return blocks


def _input_hash(model: str, prompt: Prompt, request: LLMRequest[Any]) -> str:
    """Stable hash of everything that determines the output; PDFs enter by their own hash."""
    parts = [
        p.text if isinstance(p, TextPart) else hashlib.sha256(p.data_b64.encode()).hexdigest()
        for p in request.content
    ]
    canonical = json.dumps(
        {
            "model": model,
            "prompt": [prompt.name, prompt.version, prompt.sha256],
            "schema": request.response_model.model_json_schema(),
            "content": parts,
            # The layout of the request differs when the documents are a cached prefix.
            **({"cache_documents": True} if request.cache_documents else {}),
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
