"""The independent reviewer (operating rule 15) runs on a model other than the builder's,
through core/llm with a registered prompt, and renders the checklist with every finding's
file and line."""

from core.config import Settings
from core.llm.registry import load_prompt
from scripts.independent_review import (
    EXCLUDED,
    PROMPT_NAME,
    PROMPT_VERSION,
    Finding,
    ReviewReport,
    Section,
    render,
    review_settings,
)


def test_the_checklist_is_a_registered_prompt_with_the_five_questions() -> None:
    prompt = load_prompt(PROMPT_NAME, PROMPT_VERSION)
    assert prompt.header["output_schema"] == "scripts.independent_review.ReviewReport"
    for marker in ("(a)", "(b)", "(c)", "(d)", "(e)", "Do not praise"):
        assert marker in prompt.text


def test_the_reviewer_is_another_model_at_its_own_prices() -> None:
    builder = Settings(_env_file=None)
    settings = review_settings(builder)
    assert settings.anthropic_model == builder.review_model == "claude-opus-5-5"
    assert not settings.anthropic_model.startswith("claude-fable")
    assert settings.anthropic_model != builder.anthropic_model
    assert (settings.llm_price_in_per_mtok, settings.llm_price_out_per_mtok) == (
        builder.review_price_in_per_mtok,
        builder.review_price_out_per_mtok,
    )
    assert "evals/gold/" in EXCLUDED and "uv.lock" in EXCLUDED


def test_render_names_every_finding_with_file_and_line() -> None:
    defect = Finding(
        file="api/v1/tenders/ask.py", line=42, text="route without a test", code_defect=True
    )
    note = Finding(
        file="docs/reports/X.md", text="a claim the diff cannot prove", code_defect=False
    )
    report = ReviewReport(
        a=Section(text="All upheld."),
        b=Section(text="One route lacks a test.", findings=[defect]),
        c=Section(text="All audited."),
        d=Section(text="Regenerates."),
        e=Section(text="One claim.", findings=[note]),
        code_defects=[defect],
        no_new_code_defect=False,
    )
    text = render(report)
    assert "## (b) Endpoints and their tests" in text
    assert "FINDINGS: 1\n1. api/v1/tenders/ask.py:42 — route without a test (code defect)" in text
    assert "docs/reports/X.md — a claim the diff cannot prove (not a code defect)" in text
    assert text.count("FINDINGS: none") == 3
    assert text.rstrip().endswith("NO NEW CODE DEFECT: no")
