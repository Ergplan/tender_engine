"""A scripted stand-in for the Anthropic SDK. Tests never call the real model."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

import anthropic

from core.services.section_map import SectionMapOutput

DEFAULT_SECTIONS = [
    {
        "start_page": 1,
        "end_page": 1,
        "heading": "MASTER SUPPLY AGREEMENT",
        "kind": "cover_and_notice",
        "confidence": 0.9,
    },
    {
        "start_page": 2,
        "end_page": 2,
        "heading": "SECTION 2: KEY DATES",
        "kind": "dates_and_schedule",
        "confidence": 0.9,
    },
    {
        "start_page": 3,
        "end_page": 3,
        "heading": "SECTION 3: SECURITY AND CAPACITY",
        "kind": "financial_security",
        "confidence": 0.9,
    },
]

# Answers keyed by field key. page_no is the position within the attached pages.
GOOD_ANSWERS: dict[str, dict[str, Any]] = {
    "agreement_number": {
        "value": "ACME/2026/001",
        "confidence": 0.95,
        "rationale": "Stated on the cover.",
        "evidence": [{"page_no": 1, "quote": "Agreement No. ACME/2026/001"}],
    },
    "issuer": {
        "value": "Acme Power Limited",
        "confidence": 0.9,
        "rationale": "Named as issuer.",
        "evidence": [{"page_no": 1, "quote": "Issued by Acme Power Limited, New Delhi."}],
    },
    "pre_bid_date": {
        "value": "12.03.2026",
        "confidence": 0.9,
        "rationale": "Pre-bid meeting clause.",
        "evidence": [{"page_no": 1, "quote": "The pre-bid meeting shall be held on 12.03.2026"}],
    },
    "bid_deadline": {
        "value": "2026-03-30",
        "confidence": 0.92,
        "rationale": "Submission clause.",
        "evidence": [{"page_no": 1, "quote": "Bids must be submitted on or before 30 March 2026"}],
    },
    "emd_per_mw": {
        "value": 928000,
        "confidence": 0.88,
        "rationale": "EMD clause.",
        "evidence": [
            {"page_no": 1, "quote": "The Earnest Money Deposit shall be INR 928000 per MW"}
        ],
    },
    "capacity_mw": {
        "value": 600,
        "confidence": 0.9,
        "rationale": "Capacity clause.",
        "evidence": [
            {"page_no": 1, "quote": "total contracted capacity under this agreement is 600 MW"}
        ],
    },
    "tenure_years": {
        "value": 25,
        "confidence": 0.85,
        "rationale": "Tenure clause.",
        "evidence": [{"page_no": 1, "quote": "remain in force for a tenure of 25 years"}],
    },
}
NOT_FOUND = {
    "value": None,
    "confidence": 0.0,
    "rationale": "Not stated on these pages.",
    "evidence": [],
}


class ScriptedSDK:
    """messages.parse() answers from `answers` (by field key) and `sections`.

    `before_call` may raise to simulate an API failure; it receives the call number
    (1-based) and the request kwargs.
    """

    def __init__(
        self,
        answers: dict[str, dict[str, Any]] | None = None,
        sections: list[dict[str, Any]] | None = None,
        before_call: Callable[[int, dict[str, Any]], None] | None = None,
    ) -> None:
        self.answers = dict(GOOD_ANSWERS if answers is None else answers)
        self.sections = DEFAULT_SECTIONS if sections is None else sections
        self.before_call = before_call
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.before_call is not None:
            self.before_call(len(self.calls), kwargs)
        model = kwargs["output_format"]
        if model is SectionMapOutput:
            parsed = SectionMapOutput.model_validate({"sections": self.sections})
        else:
            parsed = model.model_validate(
                {key: self.answers.get(key, NOT_FOUND) for key in model.model_fields}
            )
        return SimpleNamespace(
            model="claude-fable-5-1",
            stop_reason="end_turn",
            stop_details=None,
            _request_id=f"req_fake_{len(self.calls)}",
            usage=SimpleNamespace(input_tokens=1000, output_tokens=100, cache_read_input_tokens=0),
            content=[SimpleNamespace(type="text", text=parsed.model_dump_json())],
            parsed_output=parsed,
        )

    def extract_calls(self) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["output_format"] is not SectionMapOutput]

    def as_sdk(self) -> anthropic.Anthropic:
        return cast(anthropic.Anthropic, self)
