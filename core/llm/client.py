"""The only module that calls the Anthropic SDK.

One function, LLMClient.call: typed request in, typed response out, a registered prompt
version, SDK retries with backoff, and one llm_call_log row for every outcome.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings
from core.llm.registry import CORE_PROMPT_ROOT, Prompt, load_prompt
from core.models import LLMCallLog

CallStatus = Literal["ok", "refusal", "truncated", "invalid_output", "error"]


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


class LLMResponse[T: BaseModel](BaseModel):
    parsed: T
    call_log_id: str
    model: str
    prompt_name: str
    prompt_version: str
    tokens_in: int
    tokens_out: int
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

    def call[T: BaseModel](self, request: LLMRequest[T]) -> LLMResponse[T]:
        """Run one model call. Raises UnregisteredPromptError before any network use."""
        prompt = load_prompt(request.prompt_name, request.prompt_version, self._prompt_roots)
        model = self._settings.anthropic_model
        schema_name = f"{request.response_model.__module__}.{request.response_model.__qualname__}"
        input_hash = _input_hash(model, prompt, request)

        def log(status: CallStatus, **fields: Any) -> str:
            row = LLMCallLog(
                tenant_id=self._settings.tenant_id,
                created_by=request.created_by,
                prompt_name=prompt.name,
                prompt_version=prompt.version,
                output_schema=schema_name,
                model=fields.pop("model", model),
                input_hash=input_hash,
                status=status,
                is_fixture=request.is_fixture,
                **fields,
            )
            with self._session_factory() as session:
                session.add(row)
                session.commit()
                return row.id

        started = time.perf_counter()

        def elapsed_ms() -> int:
            return int((time.perf_counter() - started) * 1000)

        try:
            message = self._sdk.messages.parse(
                model=model,
                max_tokens=request.max_tokens or self._settings.llm_max_tokens,
                system=prompt.text,
                messages=[{"role": "user", "content": _content_blocks(request)}],
                output_format=request.response_model,
            )
        except anthropic.RateLimitError as exc:
            log_id = log("error", error=f"rate_limited: {exc.message}", latency_ms=elapsed_ms())
            raise LLMCallError("error", "rate limited after retries", log_id, True) from exc
        except anthropic.APIStatusError as exc:
            retryable = exc.status_code >= 500
            log_id = log(
                "error",
                error=f"http_{exc.status_code}: {exc.message}",
                request_id=exc.request_id,
                latency_ms=elapsed_ms(),
            )
            raise LLMCallError("error", f"HTTP {exc.status_code}", log_id, retryable) from exc
        except anthropic.APIConnectionError as exc:
            log_id = log("error", error=f"connection: {exc}", latency_ms=elapsed_ms())
            raise LLMCallError("error", "connection failed after retries", log_id, True) from exc

        usage = message.usage
        common: dict[str, Any] = {
            "model": message.model,
            "stop_reason": message.stop_reason,
            "request_id": message._request_id,
            "tokens_in": usage.input_tokens,
            "tokens_out": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_input_tokens or 0,
            "latency_ms": elapsed_ms(),
        }
        raw_text = "".join(block.text for block in message.content if block.type == "text")

        if message.stop_reason == "refusal":
            details = message.stop_details
            reason = f"{details.category}: {details.explanation}" if details else "no details"
            log_id = log("refusal", error=reason, **common)
            raise LLMCallError("refusal", reason, log_id, False)
        if message.stop_reason == "max_tokens":
            log_id = log("truncated", output={"raw_text": raw_text}, **common)
            raise LLMCallError("truncated", "output hit max_tokens", log_id, False)
        parsed = message.parsed_output
        if parsed is None:
            log_id = log("invalid_output", output={"raw_text": raw_text}, **common)
            raise LLMCallError("invalid_output", "output did not match the schema", log_id, False)

        log_id = log("ok", output=parsed.model_dump(mode="json"), **common)
        return LLMResponse[T](
            parsed=parsed,
            call_log_id=log_id,
            model=message.model,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            tokens_in=usage.input_tokens,
            tokens_out=usage.output_tokens,
            latency_ms=common["latency_ms"],
            stop_reason=message.stop_reason,
        )


def _content_blocks(request: LLMRequest[Any]) -> list[Any]:
    """Documents first, then text, as the API recommends for PDF input."""
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
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
