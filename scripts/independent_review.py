"""Independent stage review (operating rule 15).

  make review STAGE=7 RANGE=stage-7-block-5-start..HEAD PROMPT=docs/COMPLETION-PLAN.md
  python -m scripts.independent_review --stage 1
  python -m scripts.independent_review --stage 4 --range 9cbd0e9^..9cbd0e9 \\
      --prompt-file docs/reports/stage-4-artifacts/derived-sections-prompt.md

Sends exactly three things to a model other than the builder's, in a fresh context: the
stage diff (git diff stage-N-start..HEAD), CLAUDE.md and the stage prompt from
docs/MASTER-PROMPT.md (or the file named). The draft stage report is part of the diff.
Prints the reviewer's answer to the fixed checklist as Markdown.

The reviewer is `REVIEW_MODEL` (Claude Opus 5.5 since the owner's decision of 2026-10-25,
no OpenAI) and the call goes through `core.llm` like every other model call (operating
rule 8), so the review's cost is in `llm_call_log` (prompt `independent_review/v1`,
`created_by = independent_review`). The checklist is the registered prompt.

Work added to a closed stage on the owner's instruction (an addendum) is reviewed the same
way over its own commits: `--range` names the diff and `--prompt-file` the instruction that
stands in for the stage prompt.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, Field

import agent.models  # noqa: F401  (registers every table on Base.metadata)
import tender.models  # noqa: F401
from core.config import Settings
from core.db import make_engine, make_session_factory
from core.llm.client import LLMCallError, LLMClient, LLMRequest, TextPart

ROOT = Path(__file__).resolve().parents[1]
PROMPT_NAME = "independent_review"
PROMPT_VERSION = "v1"
ACTOR = "independent_review"
# Generated or locked files: large, and not something a reviewer can judge. Gold records
# and scored results are data the owner's reviews produced, not code; the released schema
# snapshots are locked copies of the live YAMLs, which the diff shows.
EXCLUDED = (
    "uv.lock",
    "web/package-lock.json",
    "web/src/api/openapi.json",
    "web/src/api/schema.d.ts",
    "evals/gold/",
    "evals/results/",
    "tender/domain_packs/power/released/",
)
SECTIONS = (
    ("a", "Invariants"),
    ("b", "Endpoints and their tests"),
    ("c", "Audited writes"),
    ("d", "FIELD-TRACE.md"),
    ("e", "Report claims the code does not support"),
)


class Finding(BaseModel):
    file: str
    line: int | None = None
    text: str
    code_defect: bool = Field(
        description="true when a change to the code resolves it; false for by-design "
        "behaviour, a statement a diff cannot prove, or a decision pending from the owner"
    )


class Section(BaseModel):
    text: str
    findings: list[Finding] = []


class ReviewReport(BaseModel):
    a: Section
    b: Section
    c: Section
    d: Section
    e: Section
    code_defects: list[Finding] = []
    no_new_code_defect: bool


def stage_prompt(stage: str) -> str:
    text = (ROOT / "docs" / "MASTER-PROMPT.md").read_text()
    match = re.search(rf"^## Stage {stage} prompt.*?(?=^## Stage \d|\Z)", text, re.M | re.S)
    if match is None:
        raise SystemExit(f"no 'Stage {stage} prompt' section in docs/MASTER-PROMPT.md")
    return match.group(0)


def stage_diff(git_range: str) -> str:
    excludes = [f":!{path}" for path in EXCLUDED]
    return subprocess.check_output(
        ["git", "diff", git_range, "--", ".", *excludes], cwd=ROOT, text=True
    )


def review_settings(settings: Settings) -> Settings:
    """The builder's settings with the reviewer's model and prices in place."""
    return settings.model_copy(
        update={
            "anthropic_model": settings.review_model,
            "llm_price_in_per_mtok": settings.review_price_in_per_mtok,
            "llm_price_out_per_mtok": settings.review_price_out_per_mtok,
            # Cache reads are a twentieth of input on Opus 5.5 ($0.20 of $4.00).
            "llm_cache_read_factor": 0.05,
        }
    )


def render(report: ReviewReport) -> str:
    lines: list[str] = []
    for key, title in SECTIONS:
        section: Section = getattr(report, key)
        lines.append(f"## ({key}) {title}\n\n{section.text.strip()}\n")
        if section.findings:
            lines.append(f"FINDINGS: {len(section.findings)}")
            lines.extend(_finding(n, f) for n, f in enumerate(section.findings, 1))
        else:
            lines.append("FINDINGS: none")
        lines.append("")
    lines.append("## Code defects\n")
    if report.code_defects:
        lines.extend(_finding(n, f) for n, f in enumerate(report.code_defects, 1))
    else:
        lines.append("none")
    lines.append(f"\nNO NEW CODE DEFECT: {'yes' if report.no_new_code_defect else 'no'}")
    return "\n".join(lines)


def _finding(n: int, finding: Finding) -> str:
    where = finding.file + (f":{finding.line}" if finding.line else "")
    kind = "code defect" if finding.code_defect else "not a code defect"
    return f"{n}. {where} — {finding.text} ({kind})"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--model", help="the reviewer model; default REVIEW_MODEL")
    parser.add_argument("--range", help="git range to review instead of stage-N-start..HEAD")
    parser.add_argument(
        "--prompt-file", type=Path, help="the instruction to review against, not the stage prompt"
    )
    args = parser.parse_args()
    settings = Settings()
    if args.model:
        settings = settings.model_copy(update={"review_model": args.model})
    settings = review_settings(settings)
    if settings.review_model.startswith("claude-fable"):
        raise SystemExit("the reviewer must not be the builder's model")
    git_range = args.range or f"stage-{args.stage}-start..HEAD"
    prompt = args.prompt_file.read_text() if args.prompt_file else stage_prompt(args.stage)
    diff = stage_diff(git_range)
    if not diff.strip():
        raise SystemExit(f"git diff {git_range} is empty")
    inputs = (
        f"# Input 1: CLAUDE.md\n\n{(ROOT / 'CLAUDE.md').read_text()}\n\n"
        f"# Input 2: the stage prompt\n\n{prompt}\n\n"
        f"# Input 3: git diff {git_range}\n\n{diff}"
    )
    session_factory = make_session_factory(make_engine(settings), settings.tenant_id)
    llm = LLMClient(settings, session_factory)
    try:
        response = llm.call(
            LLMRequest[ReviewReport](
                prompt_name=PROMPT_NAME,
                prompt_version=PROMPT_VERSION,
                content=[TextPart(text=inputs)],
                response_model=ReviewReport,
                created_by=ACTOR,
                max_tokens=32000,
            )
        )
    except LLMCallError as exc:
        print(f"reviewer call failed: {exc} (llm_call_log {exc.call_log_id})")
        return 1
    print(
        f"reviewer: {response.model}  range: {git_range}  input chars: {len(inputs)}  "
        f"tokens in/out: {response.tokens_in}/{response.tokens_out}  "
        f"cost: USD {response.cost_usd}  llm_call_log: {response.call_log_id}\n"
    )
    print(render(response.parsed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
