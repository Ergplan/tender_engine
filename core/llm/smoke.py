"""Output schema for the smoke prompt (core/llm/prompts/smoke/v1.md)."""

from pydantic import BaseModel


class SmokeResult(BaseModel):
    answer: str
    saw_document: bool
    quote: str | None
