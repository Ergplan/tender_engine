"""Scores candidates against gold records, field by field.

  python -m evals.runner                     score every gold tender's latest candidates
  python -m evals.runner --only slug,slug
  python -m evals.runner --prompt commercial/v3   read that section again on every gold tender
                                             with that prompt version, wait, then score it

Match rules by value type: exact for enums, whole numbers, booleans and times; dates equal
after parsing (so "12.03.2026" and "2026-03-12" match); decimals, money, percentages and
capacities within 0.5%; text by normalised exact match, with a fuzzy score reported but not
counted; long text is left to human judgement; a record is scored key by key with these
rules. Evidence is scored apart from the value: did the candidate cite a page the reviewer
accepted? Results go to evals/results/<id>.json and a markdown table.
"""

import argparse
import json
import math
import re
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.schemas import FieldDef, KeyDef, SchemaRegistry
from core.services.review_state import ReviewStateService
from evals.gold import GoldField, GoldRecord, load_all
from tender.models import Tender
from tender.services.packs import Catalog

RESULTS_ROOT = Path(__file__).resolve().parent / "results"
TOLERANCE = 0.005
Outcome = Literal[
    "correct", "correct_abstention", "wrong_value", "format", "missing", "extra", "needs_judgement"
]
MISSES = ("wrong_value", "format", "missing", "extra")
EXACT_KINDS = {"integer", "boolean"}
EXACT_TYPES = {"enum", "time", "int", "bool", "duration_months"}


class CandidateUnderTest(BaseModel):
    id: str | None = None
    value: Any
    confidence: float = 0.0
    pages: list[int] = []
    prompt_name: str | None = None
    prompt_version: str | None = None


class FieldScore(BaseModel):
    slug: str
    tender_type: str
    issuing_agency: str
    field_path: str
    section: str
    value_type: str
    required: bool
    outcome: Outcome
    gold_value: Any
    candidate_value: Any
    fuzzy: float | None = None
    evidence_ok: bool | None = None
    gold_pages: list[int] = []
    candidate_pages: list[int] = []
    key_outcomes: dict[str, str] | None = None
    prompt_name: str | None = None
    prompt_version: str | None = None

    @property
    def counted(self) -> bool:
        return self.outcome != "needs_judgement"

    @property
    def correct(self) -> bool:
        return self.outcome in ("correct", "correct_abstention")


def normalise_text(value: Any) -> str:
    text = re.sub(r"[^\w\s]", "", str(value).casefold())
    return " ".join(text.split())


def _numbers_match(a: float, b: float) -> bool:
    if a == b:
        return True
    return math.isclose(a, b, rel_tol=TOLERANCE, abs_tol=1e-9)


def match_scalar(
    value_type: str, kind: str, gold: Any, candidate: Any
) -> tuple[Outcome, float | None]:
    """The outcome for two coerced scalar values of one type."""
    if value_type == "long_text":
        return "needs_judgement", None
    if value_type in EXACT_TYPES or kind in EXACT_KINDS:
        return ("correct" if gold == candidate else "wrong_value"), None
    if value_type == "date":
        return ("correct" if str(gold) == str(candidate) else "wrong_value"), None
    if kind == "number":
        try:
            ok = _numbers_match(float(gold), float(candidate))
        except (TypeError, ValueError):
            ok = False
        return ("correct" if ok else "wrong_value"), None
    # A list of text is compared without regard to order; a repeated item must be repeated.
    if kind == "string_list" or isinstance(gold, list) or isinstance(candidate, list):
        g = sorted(normalise_text(x) for x in (gold if isinstance(gold, list) else [gold]))
        c = sorted(
            normalise_text(x) for x in (candidate if isinstance(candidate, list) else [candidate])
        )
        return ("correct" if g == c else "wrong_value"), None
    left, right = normalise_text(gold), normalise_text(candidate)
    score = float(fuzz.token_sort_ratio(left, right)) if left and right else 0.0
    if left == right:
        return "correct", score
    if str(gold).strip() == str(candidate).strip():
        return "correct", score
    return "wrong_value", score


def match_record(
    keys: list[KeyDef], registry: SchemaRegistry, gold: Any, candidate: Any
) -> tuple[Outcome, dict[str, str]]:
    """Key by key. The record is correct when every key the reviewer kept matches and the
    candidate states no key the reviewer left out; a list of records is compared item by
    item in order."""
    outcomes: dict[str, str] = {}
    if isinstance(gold, list) or isinstance(candidate, list):
        g_items = gold if isinstance(gold, list) else [gold]
        c_items = candidate if isinstance(candidate, list) else [candidate]
        if len(g_items) != len(c_items):
            return "wrong_value", {"items": f"{len(c_items)} given, {len(g_items)} in gold"}
        overall: Outcome = "correct"
        for index, (g_item, c_item) in enumerate(zip(g_items, c_items, strict=True)):
            outcome, keyed = match_record(keys, registry, g_item, c_item)
            outcomes.update({f"{index + 1}.{k}": v for k, v in keyed.items()})
            if outcome != "correct":
                overall = "wrong_value"
        return overall, outcomes
    g = gold if isinstance(gold, dict) else {}
    c = candidate if isinstance(candidate, dict) else {}
    for key in keys:
        gv, cv = g.get(key.name), c.get(key.name)
        if gv is None and cv is None:
            continue
        if gv is None:
            outcomes[key.name] = "extra"
        elif cv is None:
            outcomes[key.name] = "missing"
        elif key.keys:
            outcome, nested = match_record(key.keys, registry, gv, cv)
            outcomes[key.name] = outcome
        else:
            kind = registry.value_types.get(key.value_type).json_kind
            outcomes[key.name], _ = match_scalar(key.value_type, kind, gv, cv)
    overall_ok = all(v == "correct" for v in outcomes.values())
    return ("correct" if overall_ok else "wrong_value"), outcomes


def score_field(
    record: GoldRecord,
    field: GoldField,
    definition: FieldDef,
    registry: SchemaRegistry,
    candidate: CandidateUnderTest | None,
) -> FieldScore | None:
    """None when the gold field carries no decision."""
    if field.decision is None:
        return None
    base = {
        "slug": record.slug,
        "tender_type": record.tender_type,
        "issuing_agency": record.issuing_agency,
        "field_path": field.field_path,
        "section": field.section,
        "value_type": field.value_type,
        "required": field.required,
        "gold_value": field.final_value,
        "candidate_value": candidate.value if candidate else None,
        "gold_pages": field.evidence_pages,
        "candidate_pages": candidate.pages if candidate else [],
        "prompt_name": candidate.prompt_name if candidate else None,
        "prompt_version": candidate.prompt_version if candidate else None,
    }
    has_candidate = candidate is not None and candidate.value is not None
    if field.decision == "not_in_document":
        outcome: Outcome = "extra" if has_candidate else "correct_abstention"
        return FieldScore(outcome=outcome, **base)
    if not has_candidate:
        return FieldScore(outcome="missing", **base)
    assert candidate is not None
    try:
        gold_value = registry.value_types.coerce(field.final_value, definition)
    except ValueError:
        gold_value = field.final_value
    try:
        candidate_value = registry.value_types.coerce(candidate.value, definition)
    except ValueError:
        # The candidate is not even of the right type: a wrong value, unless it reads the
        # same once normalised, which is a matter of form.
        outcome = (
            "format"
            if normalise_text(candidate.value) == normalise_text(field.final_value)
            else "wrong_value"
        )
        return FieldScore(outcome=outcome, evidence_ok=_evidence_ok(field, candidate), **base)
    key_outcomes = None
    fuzzy = None
    if definition.keys:
        outcome, key_outcomes = match_record(definition.keys, registry, gold_value, candidate_value)
    else:
        kind = registry.value_types.get(field.value_type).json_kind
        outcome, fuzzy = match_scalar(field.value_type, kind, gold_value, candidate_value)
        if outcome == "wrong_value" and normalise_text(gold_value) == normalise_text(
            candidate_value
        ):
            outcome = "format"
    return FieldScore(
        outcome=outcome,
        fuzzy=fuzzy,
        key_outcomes=key_outcomes,
        evidence_ok=_evidence_ok(field, candidate),
        **base,
    )


def _evidence_ok(field: GoldField, candidate: CandidateUnderTest) -> bool | None:
    if not field.evidence_pages:
        return None
    return bool(set(candidate.pages) & set(field.evidence_pages))


def score_record(
    record: GoldRecord,
    candidates: dict[str, CandidateUnderTest],
    catalog: Catalog,
    registry: SchemaRegistry,
    only_sections: set[str] | None = None,
) -> list[FieldScore]:
    compiled = catalog.get(record.tender_type)
    scores = []
    for field in record.fields:
        if only_sections is not None and field.section not in only_sections:
            continue
        try:
            definition = compiled.schema.field(field.field_path)
        except KeyError:
            continue
        score = score_field(record, field, definition, registry, candidates.get(field.field_path))
        if score is not None:
            scores.append(score)
    return scores


def candidates_in_review(
    session: Session, review_state: ReviewStateService, record: GoldRecord
) -> dict[str, CandidateUnderTest]:
    """The reading each field shows now, at the version the gold record was reviewed at."""
    state = review_state.for_object(session, "tender", record.tender_id, record.reviewed_version)
    found: dict[str, CandidateUnderTest] = {}
    for field in state.fields:
        if field.candidate is None:
            continue
        found[field.field_path] = CandidateUnderTest(
            id=field.candidate.id,
            value=field.candidate.value,
            confidence=field.candidate.confidence,
            pages=sorted({e.page_no for e in field.candidate.evidence}),
            prompt_name=field.candidate.prompt_name,
            prompt_version=field.candidate.prompt_version,
        )
    return found


def candidates_of_runs(
    session: Session, tenant_id: str, run_ids: list[str]
) -> dict[str, CandidateUnderTest]:
    """The reviewable readings the named runs produced, one per field (the most confident
    of a field read in several windows): what a prompt evaluation scores."""
    from core.models import Candidate, EvidenceSpan
    from core.models.extraction import REVIEWABLE_STATUSES

    rows = list(
        session.scalars(
            select(Candidate).where(
                Candidate.tenant_id == tenant_id,
                Candidate.extraction_run_id.in_(run_ids),
                Candidate.status.in_((*REVIEWABLE_STATUSES, "not_found")),
            )
        )
    )
    pages: dict[str, set[int]] = {c.id: set() for c in rows}
    for span in session.scalars(
        select(EvidenceSpan).where(
            EvidenceSpan.tenant_id == tenant_id, EvidenceSpan.candidate_id.in_(list(pages))
        )
    ):
        pages[span.candidate_id].add(span.page_no)
    found: dict[str, CandidateUnderTest] = {}
    for c in sorted(rows, key=lambda c: (c.value is not None, c.confidence, c.id)):
        found[c.field_path] = CandidateUnderTest(
            id=c.id,
            value=c.value,
            confidence=c.confidence,
            pages=sorted(pages[c.id]),
            prompt_name=c.prompt_name,
            prompt_version=c.prompt_version,
        )
    return found


class PromptRunsFailed(RuntimeError):
    pass


def queue_prompt_runs(
    session: Session, tenders: Any, records: list[GoldRecord], section: str, version: str
) -> dict[str, list[str]]:
    """Read one section again on every gold tender with the named prompt version. Returns
    the run ids queued per tender slug."""
    queued: dict[str, list[str]] = {}
    for record in records:
        tender = session.scalar(
            select(Tender).where(
                Tender.id == record.tender_id, Tender.tenant_id == record.tenant_id
            )
        )
        if tender is None:
            raise LookupError(f"{record.slug}: tender {record.tender_id} not found")
        runs = tenders.start_extraction(
            session,
            tender,
            version_no=record.reviewed_version,
            created_by="evals",
            groups=[section],
            mode="batch",
            prompt_overrides={section: version},
        )
        queued[record.slug] = [run.id for run in runs]
    if not any(queued.values()):
        raise LookupError(f"no run queued: no gold tender has a section {section!r}")
    return queued


def finished_runs(session: Session, tenant_id: str, run_ids: list[str]) -> bool:
    """True once none of the runs is queued or running; raises if one failed."""
    from core.models import ExtractionRun

    statuses = dict(
        session.execute(
            select(ExtractionRun.id, ExtractionRun.status).where(
                ExtractionRun.tenant_id == tenant_id, ExtractionRun.id.in_(run_ids)
            )
        ).all()
    )
    failed = sorted(run_id for run_id, status in statuses.items() if status == "failed")
    if failed:
        raise PromptRunsFailed(f"run(s) failed: {', '.join(failed)}")
    return not any(status in ("queued", "running") for status in statuses.values())


class Summary(BaseModel):
    """Accuracy per field path, per tender type, per section, and the misses."""

    scored: int
    value_correct: int
    value_accuracy: float | None
    evidence_scored: int
    evidence_correct: int
    evidence_accuracy: float | None
    needs_judgement: int
    by_field: dict[str, dict[str, Any]]
    by_type: dict[str, dict[str, Any]]
    by_section: dict[str, dict[str, Any]]
    by_type_field: dict[str, dict[str, dict[str, Any]]]
    misses: list[dict[str, Any]]


def _bucket() -> dict[str, Any]:
    return {"n": 0, "correct": 0, "evidence_n": 0, "evidence_correct": 0, "misses": 0}


def _add(bucket: dict[str, Any], score: FieldScore) -> None:
    bucket["n"] += 1
    bucket["correct"] += int(score.correct)
    if not score.correct:
        bucket["misses"] += 1
    if score.evidence_ok is not None:
        bucket["evidence_n"] += 1
        bucket["evidence_correct"] += int(score.evidence_ok)


def _finish(bucket: dict[str, Any]) -> dict[str, Any]:
    bucket["accuracy"] = round(bucket["correct"] / bucket["n"], 4) if bucket["n"] else None
    bucket["evidence_accuracy"] = (
        round(bucket["evidence_correct"] / bucket["evidence_n"], 4)
        if bucket["evidence_n"]
        else None
    )
    return bucket


def summarise(scores: list[FieldScore]) -> Summary:
    counted = [s for s in scores if s.counted]
    by_field: dict[str, dict[str, Any]] = defaultdict(_bucket)
    by_type: dict[str, dict[str, Any]] = defaultdict(_bucket)
    by_section: dict[str, dict[str, Any]] = defaultdict(_bucket)
    by_type_field: dict[str, dict[str, dict[str, Any]]] = defaultdict(lambda: defaultdict(_bucket))
    for score in counted:
        _add(by_field[score.field_path], score)
        _add(by_type[score.tender_type], score)
        _add(by_section[score.section], score)
        _add(by_type_field[score.tender_type][score.field_path], score)
    evidence = [s for s in counted if s.evidence_ok is not None]
    return Summary(
        scored=len(counted),
        value_correct=sum(1 for s in counted if s.correct),
        value_accuracy=round(sum(1 for s in counted if s.correct) / len(counted), 4)
        if counted
        else None,
        evidence_scored=len(evidence),
        evidence_correct=sum(1 for s in evidence if s.evidence_ok),
        evidence_accuracy=round(sum(1 for s in evidence if s.evidence_ok) / len(evidence), 4)
        if evidence
        else None,
        needs_judgement=sum(1 for s in scores if not s.counted),
        by_field={k: _finish(v) for k, v in sorted(by_field.items())},
        by_type={k: _finish(v) for k, v in sorted(by_type.items())},
        by_section={k: _finish(v) for k, v in sorted(by_section.items())},
        by_type_field={
            t: {f: _finish(v) for f, v in sorted(fields.items())}
            for t, fields in sorted(by_type_field.items())
        },
        misses=[
            {
                "slug": s.slug,
                "tender_type": s.tender_type,
                "field_path": s.field_path,
                "outcome": s.outcome,
                "gold": s.gold_value,
                "candidate": s.candidate_value,
                "fuzzy": s.fuzzy,
                "keys": s.key_outcomes,
                "evidence_ok": s.evidence_ok,
            }
            for s in counted
            if not s.correct
        ],
    )


def markdown_table(summary: Summary) -> str:
    lines = [
        "| Tender type | Field | Accuracy | n | Evidence accuracy |",
        "| --- | --- | --- | --- | --- |",
    ]
    for tender_type, fields in summary.by_type_field.items():
        for path, bucket in fields.items():
            acc = f"{bucket['accuracy'] * 100:.0f}%" if bucket["accuracy"] is not None else "-"
            ev = (
                f"{bucket['evidence_accuracy'] * 100:.0f}%"
                if bucket["evidence_accuracy"] is not None
                else "-"
            )
            lines.append(f"| {tender_type} | `{path}` | {acc} | {bucket['n']} | {ev} |")
    lines.append("")
    lines.append("| Tender | Field | Outcome | Candidate | Gold |")
    lines.append("| --- | --- | --- | --- | --- |")
    for miss in summary.misses:
        lines.append(
            f"| {miss['slug']} | `{miss['field_path']}` | {miss['outcome']} | "
            f"{_cell(miss['candidate'])} | {_cell(miss['gold'])} |"
        )
    return "\n".join(lines) + "\n"


def _cell(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    text = " ".join(text.split()).replace("|", "\\|")
    return text[:80] + ("…" if len(text) > 80 else "")


def write_results(
    scores: list[FieldScore], *, label: str, root: Path | None = None, prompt: str | None = None
) -> tuple[Path, Summary]:
    root = root or RESULTS_ROOT
    root.mkdir(parents=True, exist_ok=True)
    summary = summarise(scores)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = root / f"{stamp}-{label}.json"
    path.write_text(
        json.dumps(
            {
                "made_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "label": label,
                "prompt": prompt,
                "summary": summary.model_dump(),
                "scores": [s.model_dump() for s in scores],
            },
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path, summary


def _services() -> tuple[Any, Any, Any, Any]:
    from core.config import Settings
    from core.db import make_engine, make_session_factory
    from core.llm.client import LLMClient
    from core.services.extract import ExtractService
    from core.storage import make_storage
    from tender.services.packs import build_registry
    from tender.services.tenders import TenderService

    settings = Settings()
    registry, catalog = build_registry()
    session_factory = make_session_factory(make_engine(settings))
    llm = LLMClient(settings, session_factory, prompt_roots=catalog.prompt_roots)
    extract = ExtractService(llm, make_storage(settings), registry, settings)
    return (
        settings,
        session_factory,
        (registry, catalog),
        TenderService(catalog, extract, settings.tenant_id),
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--prompt", default="", help="section/vN: read that section again")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args(argv[1:])
    settings, session_factory, (registry, catalog), tenders = _services()
    review_state = ReviewStateService(registry, settings.tenant_id)
    only = {s for s in args.only.split(",") if s}
    records = [r for r in load_all(settings.tenant_id) if not only or r.slug in only]
    if not records:
        print("no gold records; run make gold first")
        return 1
    sections: set[str] | None = None
    queued: dict[str, list[str]] = {}
    if args.prompt:
        section, version = args.prompt.split("/", 1)
        sections = {section}
        with session_factory() as session:
            queued = queue_prompt_runs(session, tenders, records, section, version)
            session.commit()
        for slug, run_ids in queued.items():
            print(f"{slug}: {len(run_ids)} run(s) queued with {args.prompt}")
        _wait(session_factory, settings.tenant_id, sum(queued.values(), []), args.timeout)
    scores: list[FieldScore] = []
    with session_factory() as session:
        for record in records:
            # A prompt evaluation scores what the queued runs read, nothing else; a plain
            # evaluation scores the reading now in review at the reviewed version.
            found = (
                candidates_of_runs(session, settings.tenant_id, queued[record.slug])
                if args.prompt
                else candidates_in_review(session, review_state, record)
            )
            scores += score_record(record, found, catalog, registry, sections)
    label = (args.prompt.replace("/", "-") if args.prompt else "latest") + (
        "-" + "-".join(sorted(only)) if only else ""
    )
    path, summary = write_results(scores, label=label, prompt=args.prompt or None)
    print(f"wrote {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}")
    print(
        f"value accuracy {summary.value_accuracy} on {summary.scored} fields; evidence "
        f"accuracy {summary.evidence_accuracy} on {summary.evidence_scored}; "
        f"{summary.needs_judgement} need human judgement; {len(summary.misses)} misses"
    )
    print(markdown_table(summary))
    return 0


def _wait(session_factory: Any, tenant_id: str, run_ids: list[str], timeout: int) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with session_factory() as session:
            if finished_runs(session, tenant_id, run_ids):
                return
        time.sleep(10)
    raise SystemExit("the runs did not finish in time")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
