"""Independent stage review (operating rule 15).

  python -m scripts.independent_review --stage 1 [--model gpt-4-turbo]

Sends exactly three things to a model from a different family than the builder, in a fresh
context: the stage diff (git diff stage-N-start..HEAD), CLAUDE.md and the stage prompt from
docs/MASTER-PROMPT.md. The draft stage report is part of the diff. Prints the reviewer's
answer to the fixed checklist. This is build tooling, not an application LLM call, so it
does not go through core/llm/.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Generated or locked files: large, and not something a reviewer can judge.
EXCLUDED = ("uv.lock", "web/src/api/openapi.json", "web/src/api/schema.d.ts")
CHECKLIST = """You are an independent reviewer of one stage of a software build. You have no
other context than the three inputs below. Answer this fixed checklist and nothing else.

(a) For every non-negotiable invariant in CLAUDE.md: is it upheld by the stage diff? Cite the
    file and line that upholds it, or state the violation with file and line.
(b) Does every API endpoint added in the diff have a test? List each endpoint with its test,
    or name the endpoint without one.
(c) Does every write to candidate, approval, canonical_fact, tender_version and feedback go
    through the audit log? Cite each write and its audit call, or name the write without one.
(d) Does `make trace` regenerate FIELD-TRACE.md without diff? If the stage has no make trace
    yet, answer "not applicable" and say why.
(e) List every claim in the draft stage report (docs/reports/STAGE-N-REPORT.md in the diff)
    that the code in the diff does not support.

Rules: judge only what the inputs show. Do not praise. Do not suggest improvements outside
the checklist. For each of (a) to (e) end with one line: "FINDINGS: none" or
"FINDINGS: <count>" followed by a numbered list, each with file and line."""


def stage_prompt(stage: str) -> str:
    text = (ROOT / "docs" / "MASTER-PROMPT.md").read_text()
    match = re.search(rf"^## Stage {stage} prompt.*?(?=^## Stage \d|\Z)", text, re.M | re.S)
    if match is None:
        raise SystemExit(f"no 'Stage {stage} prompt' section in docs/MASTER-PROMPT.md")
    return match.group(0)


def stage_diff(stage: str) -> str:
    excludes = [f":!{path}" for path in EXCLUDED]
    return subprocess.check_output(
        ["git", "diff", f"stage-{stage}-start..HEAD", "--", ".", *excludes], cwd=ROOT, text=True
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--model", default="gpt-4-turbo")
    args = parser.parse_args()
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY is not set")
    user = (
        f"# Input 1: CLAUDE.md\n\n{(ROOT / 'CLAUDE.md').read_text()}\n\n"
        f"# Input 2: the stage prompt\n\n{stage_prompt(args.stage)}\n\n"
        f"# Input 3: git diff stage-{args.stage}-start..HEAD\n\n{stage_diff(args.stage)}"
    )
    body = {
        "model": args.model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": CHECKLIST},
            {"role": "user", "content": user},
        ],
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            answer = json.load(response)
    except urllib.error.HTTPError as exc:
        print(f"reviewer call failed: HTTP {exc.code}: {exc.read().decode()[:800]}")
        return 1
    usage = answer.get("usage", {})
    print(
        f"reviewer: {answer.get('model')}  input chars: {len(user)}  "
        f"tokens in/out: {usage.get('prompt_tokens')}/{usage.get('completion_tokens')}\n"
    )
    print(answer["choices"][0]["message"]["content"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
