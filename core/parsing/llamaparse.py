"""LlamaParse as an optional parsing layer (Stage 7, Block 2 a): off by default; a document
leaves the VM only for a tender whose record says `parser_llamaparse`, and every page it
read says `llamaparse`.

LlamaCloud's parsing API is asynchronous: upload the file, poll the job, fetch the JSON
result, whose pages carry `items` (text, heading, table) with `bBox` and the page size.
The items become LayerPages the same way Docling's do. Its output is used only where quotes
resolve against page boxes, which is what the layer shape guarantees: a page's text is the
items joined, each character boxed inside its item.

Not exercised against the live service in this build (no key); the mapping is tested on
the documented response shape and the client raises LlamaParseUnavailable on anything else.
"""

import time
from dataclasses import dataclass
from typing import Any

import httpx

from core.parsing.layers import LayerPage, TextItem

UPLOAD_PATH = "/api/v1/parsing/upload"
JOB_PATH = "/api/v1/parsing/job/{job_id}"
RESULT_PATH = "/api/v1/parsing/job/{job_id}/result/json"


class LlamaParseUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class LlamaParseResult:
    pages: dict[int, LayerPage]
    seconds: float
    job_id: str
    detail: dict[str, Any]


class LlamaParseClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.cloud.llamaindex.ai",
        timeout_seconds: float = 900.0,
        poll_seconds: float = 3.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise LlamaParseUnavailable("llamaparse: no API key")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
            transport=transport,
        )
        self._timeout = timeout_seconds
        self._poll = poll_seconds

    def convert(self, pdf: bytes, *, filename: str = "pages.pdf") -> LlamaParseResult:
        started = time.monotonic()
        try:
            upload = self._client.post(
                UPLOAD_PATH,
                files={"file": (filename, pdf, "application/pdf")},
                data={"result_type": "json", "parsing_mode": "parse_page_with_layout_agent"},
            )
            if upload.status_code >= 300:
                raise LlamaParseUnavailable(f"llamaparse: upload HTTP {upload.status_code}")
            job_id = str(upload.json().get("id") or "")
            if not job_id:
                raise LlamaParseUnavailable("llamaparse: upload answered without a job id")
            while True:
                status = self._client.get(JOB_PATH.format(job_id=job_id))
                state = str(status.json().get("status") or "").upper()
                if state == "SUCCESS":
                    break
                if state in ("ERROR", "CANCELLED"):
                    raise LlamaParseUnavailable(f"llamaparse: job {job_id} {state}")
                if time.monotonic() - started > self._timeout:
                    raise LlamaParseUnavailable(f"llamaparse: job {job_id} timed out")
                time.sleep(self._poll)
            result = self._client.get(RESULT_PATH.format(job_id=job_id))
            if result.status_code >= 300:
                raise LlamaParseUnavailable(f"llamaparse: result HTTP {result.status_code}")
            payload = result.json()
        except httpx.HTTPError as exc:
            raise LlamaParseUnavailable(f"llamaparse: {type(exc).__name__}: {exc}") from exc
        return LlamaParseResult(
            pages=pages_from_result(payload),
            seconds=round(time.monotonic() - started, 2),
            job_id=job_id,
            detail={"job_metadata": payload.get("job_metadata") or {}},
        )


def pages_from_result(payload: dict[str, Any]) -> dict[int, LayerPage]:
    """LayerPages from LlamaParse's JSON result: `pages[].items[]` with `bBox` {x, y, w, h}
    in page units from the top-left, `pages[].width/height`."""
    pages: dict[int, LayerPage] = {}
    for page in payload.get("pages") or []:
        page_no = int(page.get("page") or len(pages) + 1)
        width = float(page.get("width") or 0.0)
        height = float(page.get("height") or 0.0)
        items: list[TextItem] = []
        for item in page.get("items") or []:
            kind = str(item.get("type") or "text")
            text = _item_text(item, kind)
            if not text:
                continue
            box = item.get("bBox") or {}
            try:
                x, y, w, h = (float(box[k]) for k in ("x", "y", "w", "h"))
                placed = [round(x, 2), round(y, 2), round(x + w, 2), round(y + h, 2)]
            except (KeyError, TypeError, ValueError):
                placed = None
            items.append(TextItem(text, placed, kind))
        counts: dict[str, int] = {}
        for entry in items:
            counts[entry.kind] = counts.get(entry.kind, 0) + 1
        pages[page_no] = LayerPage(page_no, width, height, items, {"items": counts})
    return pages


def _item_text(item: dict[str, Any], kind: str) -> str:
    if kind == "table":
        rows = item.get("rows") or []
        cells = [" ".join(str(c).split()) for row in rows for c in row if str(c).strip()]
        return "\n".join(cells)
    return " ".join(str(item.get("value") or item.get("md") or "").split())
