"""Generate docs/FIELD-TRACE.md: the path of every field a reviewer sees, end to end.

  python -m scripts.gen_field_trace            write the file
  python -m scripts.gen_field_trace --check    exit 1 if the committed file differs

One row per field path, in review order. Everything in a row is read from the code: the
schema YAMLs (through the compiled catalog), the API's route registry, the ORM models, the
prompt files, the rule functions and the web sources. The command fails when a field has
no UI component, no route or no table, so the document cannot drift from the code.
"""

import importlib
import inspect
import re
import sys
from pathlib import Path
from typing import Any

from api.main import create_app
from api.middleware import audit, review_token
from core.config import Settings
from core.llm.registry import load_prompt
from core.models import Approval, Candidate, CanonicalFact, EvidenceSpan
from core.schemas import SchemaRegistry
from core.services.approve import ApprovalService
from core.services.extract import ExtractService
from tender.domain_packs.power import derivations
from tender.services import results_import, summary
from tender.services.packs import Catalog, TenderField, load_catalog

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "FIELD-TRACE.md"
WEB = ROOT / "web" / "src"
READ_ROUTE = ("GET", "/api/v1/tenders/{tender_id}/review")
AWARD_READ_ROUTE = ("GET", "/api/v1/awards/{award_id}/review")
WRITE_ROUTE = ("POST", "/api/v1/approvals")
PROMPT_VERSION = "v1"
AGENT_PROMPT = "agent_pass"
AGENT_PROMPT_VERSION = "v1"
_PATH = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")


class TraceError(RuntimeError):
    """A field cannot be traced end to end."""


def ui_components() -> dict[str, str]:
    """Value type -> the component and input that show and edit it, read from the web
    sources: every type the edit form or the formatter names."""
    card = WEB / "review" / "FieldCard.tsx"
    form = WEB / "review" / "EditForm.tsx"
    format_source = (WEB / "lib" / "format.ts").read_text(encoding="utf-8")
    form_source = form.read_text(encoding="utf-8")
    if not card.is_file() or 'data-testid="field-value"' not in card.read_text(encoding="utf-8"):
        raise TraceError("web/src/review/FieldCard.tsx does not render a field value")
    numbers = set(
        re.findall(
            r'"([a-z_]+)"', format_source.split("NUMBER_TYPES = new Set([")[1].split("])")[0]
        )
    )
    inputs = {"date": "date picker", "bool": "yes/no", "enum": "dropdown", "text": "text input"}
    known: dict[str, str] = {}
    for value_type, control in inputs.items():
        if f'type === "{value_type}"' in form_source:
            known[value_type] = control
    for value_type in numbers:
        known[value_type] = "number with unit"
    for value_type in ("long_text", "list_text", "record_list"):
        if f'"{value_type}"' in form_source:
            known[value_type] = "textarea"
    record = WEB / "review" / "RecordView.tsx"
    if record.is_file() and 'field.value_type === "record"' in form_source:
        known["record"] = "one input per key (shown by review/RecordView)"
    return known


def routes() -> set[tuple[str, str]]:
    """Every (method, path) the API serves, from its OpenAPI document."""
    app = create_app(Settings(_env_file=None), SchemaRegistry())  # type: ignore[call-arg]
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }


def rule_fields(catalog: Catalog) -> dict[str, list[str]]:
    """Field path -> the cross-field rules that concern it: a rule concerns the fields
    whose paths its module names and its source uses."""
    by_field: dict[str, list[str]] = {}
    for name, rule in sorted(catalog.cross_field_rules.items()):
        source = inspect.getsource(rule)
        module = inspect.getmodule(rule)
        for constant, value in vars(module).items():
            if not re.search(rf"\b{re.escape(constant)}\b", source):
                continue
            for path in _strings(value):
                if _PATH.match(path) and name not in by_field.setdefault(path, []):
                    by_field[path].append(name)
    return by_field


def run_rule_fields() -> dict[str, Any]:
    """Run rule -> the test of which fields it concerns, declared beside the rules in each
    pack (`RUN_RULE_FIELDS`). A run rule sees a whole run and names no field paths."""
    declared: dict[str, Any] = {}
    for pack in ("core", "power", "result"):
        module = importlib.import_module(f"tender.domain_packs.{pack}.validation")
        declared.update(module.RUN_RULE_FIELDS)
    return declared


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for key in value for item in _strings(key)]
    if isinstance(value, tuple | list):
        return [item for part in value for item in _strings(part)]
    return []


def _column(model: Any, name: str) -> str:
    if name not in model.__table__.columns:
        raise TraceError(f"table {model.__tablename__} has no column {name}")
    return f"{model.__tablename__}.{name}"


def build(catalog: Catalog | None = None) -> str:
    catalog = catalog or load_catalog()
    components = ui_components()
    registered = routes()
    for route in (READ_ROUTE, AWARD_READ_ROUTE, WRITE_ROUTE):
        if route not in registered:
            raise TraceError(f"the API has no route {route[0]} {route[1]}")
    allowed = {method for method, pattern in review_token.ALLOWED if pattern.match(WRITE_ROUTE[1])}
    if "POST" not in allowed or not callable(audit.install):
        raise TraceError("the review token does not reach POST /approvals")
    award_read = AWARD_READ_ROUTE[1].replace("{award_id}", "0" * 32)
    if not any(
        method == "GET" and pattern.match(award_read) for method, pattern in review_token.ALLOWED
    ):
        raise TraceError("the review token does not reach GET /awards/{award_id}/review")
    for owner, method in (
        (ExtractService, "extract"),
        (ExtractService, "import_candidate"),
        (ApprovalService, "approve"),
    ):
        if not callable(getattr(owner, method, None)):
            raise TraceError(f"{owner.__name__}.{method} does not exist")
    if not callable(getattr(results_import.ResultsImporter, "run", None)):
        raise TraceError("ResultsImporter.run does not exist")
    database = " → ".join(
        (
            _column(Candidate, "value"),
            _column(Approval, "final_value"),
            _column(CanonicalFact, "value"),
        )
    )
    evidence = ", ".join(
        _column(EvidenceSpan, name).replace("evidence_span.", "", 1 if index else 0)
        for index, name in enumerate(("page_no", "bbox", "char_start", "quote"))
    )
    cross = rule_fields(catalog)
    concerns = run_rule_fields()
    # The independent agent (Stage 5A) is asked for every field read from pages but the
    # summary; its findings go to agent_finding and never to a candidate or a fact.
    agent_prompt = load_prompt(AGENT_PROMPT, AGENT_PROMPT_VERSION, catalog.prompt_roots)
    agent_tag = (
        f"AGENT {agent_prompt.name} {agent_prompt.version} → agent_finding (never canonical)"
    )

    rows: dict[str, dict[str, Any]] = {}
    for tender_type in sorted(catalog.types):
        compiled = catalog.types[tender_type]
        sections = {section.name: section for section in compiled.sections}
        for field in compiled.fields:
            row = rows.setdefault(
                field.path,
                {
                    "field": field,
                    "types": [],
                    "order": (sections[field.section].order, field.review_order),
                    "prompt": sections[field.section].prompt,
                    "prompt_version": sections[field.section].prompt_version or PROMPT_VERSION,
                    "derived": sections[field.section].derived,
                    "imported": sections[field.section].imported,
                    "object_type": compiled.object_type,
                },
            )
            row["types"].append(tender_type)

    lines = [
        "# Field trace",
        "",
        "Generated by `make trace` (`scripts/gen_field_trace.py`) from the schema YAMLs, the "
        "API's route registry, the ORM models, the prompt files, the rule functions and the "
        "web sources. Never edited by hand; the `field_trace` check fails when this file "
        "differs from what the code gives.",
        "",
        f"Every field is served by `{READ_ROUTE[0]} {READ_ROUTE[1].replace('/api', '')}` and "
        f"written by `{WRITE_ROUTE[0]} {WRITE_ROUTE[1].replace('/api', '')}`, through the "
        "middleware `review_token` and `audit`. The candidate is produced by "
        "`core.services.extract.ExtractService.extract()` for the field's section, checked by "
        "`core.services.validate.ValidationService.validate()` and decided by "
        "`core.services.approve.ApprovalService.approve()`, the only writer of "
        f"`canonical_fact`. Database path of every field: {database}. Evidence: "
        f"{evidence}. The decision of a reviewer is the producer tagged HUMAN in every row. "
        "A field tagged DERIVED is written by `tender.services.derive.DerivedWriter.write()` "
        "from the decided fields its rule names (deterministic code under "
        "`tender/domain_packs/<pack>/derivations/`, no model call), with their evidence "
        "inherited; it is validated and decided like any other. A field tagged AGENT is also "
        "read by the independent agent pass (Stage 5A, `agent/`, a model of another family "
        "with the three tools read_pages, search_text and submit_finding): its finding is "
        "written to `agent_finding` by `agent.harness.Harness.submit_finding()` with "
        "evidence located on the cited page, for the three-way comparison, and never "
        "becomes a candidate or a canonical fact. A field tagged IMPORT (Stage 6, the "
        "`result` pack, object type `award`) is written by "
        "`tender.services.results_import.ResultsImporter.run()` from the named dataset and "
        "commit through `ExtractService.import_candidate()`, its quotes located on the page "
        "the dataset cites by core's resolver, with no model call; it is validated and "
        f"decided like any other, served by `{AWARD_READ_ROUTE[0]} "
        f"{AWARD_READ_ROUTE[1].replace('/api', '')}` through the same middleware and written "
        "by the same approval route.",
        "",
        f"{len(rows)} fields over {len(catalog.types)} types "
        f"({sum(1 for c in catalog.types.values() if c.object_type == 'tender')} tender types, "
        f"{sum(1 for c in catalog.types.values() if c.object_type != 'tender')} other).",
        "",
        "| Field | Tender types | UI (web/src) | Section and service | Producer | Rules |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    all_types = sorted(catalog.types)
    for path, row in sorted(rows.items(), key=lambda item: (item[1]["order"], item[0])):
        field: TenderField = row["field"]
        if field.value_type not in components:
            raise TraceError(f"{path}: no UI component for value type {field.value_type!r}")
        prompt = (
            None
            if row["derived"] or row["imported"]
            else load_prompt(row["prompt"], row["prompt_version"], catalog.prompt_roots)
        )
        rules = ["type", "evidence_located"]
        definition = catalog.types[row["types"][0]].schema.field(path)
        if definition.required:
            rules.append("required_present")
        if definition.validation.min is not None or definition.validation.max is not None:
            rules.append("range")
        if definition.validation.regex:
            rules.append("regex")
        rules += cross.get(path, [])
        for run_rule in catalog.types[row["types"][0]].schema.run_rules:
            if run_rule not in concerns:
                raise TraceError(f"run rule {run_rule!r} does not say which fields it concerns")
            if concerns[run_rule](definition):
                rules.append(run_rule)
        tender_types = [t for t in all_types if catalog.types[t].object_type == "tender"]
        types = (
            "all"
            if row["types"] == tender_types
            else ", ".join(
                f"{t} ({catalog.types[t].object_type})"
                if catalog.types[t].object_type != "tender"
                else t
                for t in row["types"]
            )
        )
        producer = f"LLM {prompt.name} {prompt.version}" if prompt else ""
        service = f"extract('{field.section}')"
        if row["derived"]:
            # Written by deterministic code from the decided fields it names; no model.
            rule = derivations.rule_for(path)
            producer = f"DERIVED {rule.module} {rule.version} from " + ", ".join(
                f"`{p}`" for p in rule.inputs
            )
            service = "tender.services.derive.DerivedWriter.write()"
        if row["imported"]:
            # Written by the importer from the dataset; no model, no agent pass.
            producer = (
                f"IMPORT {results_import.DATASET_NAME}@<commit> ({row['prompt']} "
                f"{row['prompt_version']})"
            )
            service = "tender.services.results_import.ResultsImporter.run()"
        if path == summary.SUMMARY_FIELD:
            # Written in a second pass from the record; the page-read summary feeds it.
            record = load_prompt(summary.PROMPT_NAME, summary.PROMPT_VERSION, catalog.prompt_roots)
            producer = f"LLM {record.name} {record.version} from the record (narrative: {producer})"
            service = "tender.services.summary.SummaryWriter.write()"
        elif not (row["derived"] or row["imported"]):
            producer = f"{producer}; {agent_tag}"
        lines.append(
            f"| `{path}` | {types} | review/FieldCard value ({field.value_type}); "
            f"review/EditForm {components[field.value_type]} | {field.section}: "
            f"{service} / approve() | {producer}; HUMAN approval | RULE {', '.join(rules)} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    try:
        text = build()
    except TraceError as exc:
        print(f"field trace: {exc}")
        return 1
    if "--check" in argv:
        committed = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if committed != text:
            print("docs/FIELD-TRACE.md is stale: run `make trace` and commit the result")
            return 1
        print(f"docs/FIELD-TRACE.md is current ({text.count(chr(10) + '| `')} fields)")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
