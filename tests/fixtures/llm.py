"""A scripted stand-in for the Anthropic SDK. Tests never call the real model."""

import json
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
        # What the amendment map returns: a list of {clause, section, summary, page_no}.
        self.amendment_changes: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.messages = self
        # The batch API: batches[id] is the list of submitted requests. A batch reports
        # `ended` after `batch_polls` looks at it; `batch_failures` names custom ids whose
        # call errors inside the batch.
        self.batches = self
        self.submitted: dict[str, list[dict[str, Any]]] = {}
        self.batch_polls = 0
        self.batch_failures: set[str] = set()
        self._polled: dict[str, int] = {}
        # Pages already written to the cache, by the hash of the cached document.
        self._cached: set[str] = set()

    def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.before_call is not None:
            self.before_call(len(self.calls), kwargs)
        model = kwargs["output_format"]
        if model is SectionMapOutput:
            parsed = SectionMapOutput.model_validate({"sections": self.sections})
        elif model.__name__ == "AmendmentMapOutput":
            parsed = model.model_validate({"changes": self.amendment_changes})
        else:
            parsed = model.model_validate(
                {key: self.answers.get(key, NOT_FOUND) for key in model.model_fields}
            )
        return self._message(kwargs, parsed.model_dump_json(), parsed)

    def _message(self, params: dict[str, Any], text: str, parsed: Any) -> Any:
        """1,000 tokens of input; a document marked for the cache is 800 of them, written
        the first time it is seen and read after that."""
        read = written = written_1h = 0
        for block in params["messages"][0]["content"]:
            if block.get("cache_control"):
                key = block["source"]["data"]
                read, written = (800, 0) if key in self._cached else (0, 800)
                written_1h = written if block["cache_control"].get("ttl") == "1h" else 0
                self._cached.add(key)
        return SimpleNamespace(
            model="claude-fable-5-1",
            stop_reason="end_turn",
            stop_details=None,
            _request_id=f"req_fake_{len(self.calls)}",
            usage=SimpleNamespace(
                input_tokens=1000 - read - written,
                output_tokens=100,
                cache_read_input_tokens=read,
                cache_creation_input_tokens=written,
                cache_creation=SimpleNamespace(ephemeral_1h_input_tokens=written_1h),
            ),
            content=[SimpleNamespace(type="text", text=text)],
            parsed_output=parsed,
        )

    def create(self, requests: list[dict[str, Any]]) -> Any:
        batch_id = f"msgbatch_fake_{len(self.submitted) + 1}"
        self.submitted[batch_id] = list(requests)
        return SimpleNamespace(id=batch_id, processing_status="in_progress")

    def retrieve(self, batch_id: str) -> Any:
        self._polled[batch_id] = self._polled.get(batch_id, 0) + 1
        ended = self._polled[batch_id] > self.batch_polls
        return SimpleNamespace(id=batch_id, processing_status="ended" if ended else "in_progress")

    def results(self, batch_id: str) -> list[Any]:
        out = []
        for request in self.submitted[batch_id]:
            if request["custom_id"] in self.batch_failures:
                result = SimpleNamespace(type="errored", error="overloaded_error")
            else:
                keys = request["params"]["output_config"]["format"]["schema"]["properties"]
                text = json.dumps({key: self.answers.get(key, NOT_FOUND) for key in keys})
                result = SimpleNamespace(
                    type="succeeded", message=self._message(request["params"], text, None)
                )
            out.append(SimpleNamespace(custom_id=request["custom_id"], result=result))
        return out

    def extract_calls(self) -> list[dict[str, Any]]:
        return [
            call
            for call in self.calls
            if call["output_format"] is not SectionMapOutput
            and call["output_format"].__name__ != "AmendmentMapOutput"
        ]

    def as_sdk(self) -> anthropic.Anthropic:
        return cast(anthropic.Anthropic, self)
