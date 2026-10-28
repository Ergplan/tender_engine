"""The composite reliability figures (Block 7 b) read from the result files, and the two
sentences they allow."""

import json
from pathlib import Path

from evals.reliability import NO_EVAL, NO_QUERY_EVAL, NO_UNSEEN, composite, markdown


def _eval_file(root: Path, stamp: str, accuracy: float, tenant: str = "ergplan") -> None:
    (root / f"{stamp}-{tenant}-latest.json").write_text(
        json.dumps(
            {
                "made_at": f"{stamp}+00:00",
                "tenant_id": tenant,
                "prompt": None,
                "summary": {
                    "scored": 200,
                    "value_correct": round(200 * accuracy),
                    "value_accuracy": accuracy,
                    "evidence_scored": 150,
                    "evidence_correct": 150,
                    "evidence_accuracy": 1.0,
                    "by_critical": {"critical": {"n": 40, "accuracy": 0.99}},
                    "high_confidence_misses": [{"field_path": "a"}, {"field_path": "b"}],
                },
                "scores": [{"slug": "t1"}, {"slug": "t2"}, {"slug": "t2"}, {"slug": "t3"}],
            }
        ),
        encoding="utf-8",
    )


def test_without_any_file_every_statement_says_what_is_missing(tmp_path: Path) -> None:
    report = composite("ergplan", tmp_path)
    assert report.in_sample is None and report.unseen is None
    assert report.query_eval.run is False
    assert report.statements == [NO_EVAL, NO_UNSEEN, NO_QUERY_EVAL]
    assert "| Question eval | not run |" in "\n".join(markdown(report))


def test_the_latest_plain_eval_of_the_tenant_is_the_in_sample_figure(tmp_path: Path) -> None:
    _eval_file(tmp_path, "20261001T000000Z", 0.90)
    _eval_file(tmp_path, "20261024T000000Z", 0.975)
    _eval_file(tmp_path, "20261025T000000Z", 0.50, tenant="other")
    # A prompt experiment is not the baseline.
    (tmp_path / "20261026T000000Z-ergplan-latest.json").write_text(
        json.dumps({"tenant_id": "ergplan", "prompt": "x/v9", "summary": {"value_accuracy": 0.1}}),
        encoding="utf-8",
    )
    report = composite("ergplan", tmp_path)
    assert report.in_sample is not None
    assert report.in_sample.accuracy == 0.975 and report.in_sample.tenders == 3
    assert report.in_sample.critical_accuracy == 0.99
    assert report.in_sample.high_confidence_misses == 2
    assert report.statements[0] == "97.5% field accuracy on 3 human-reviewed tenders (in-sample)"


def test_the_unseen_rate_counts_complete_tenders_only_and_claims_no_accuracy(
    tmp_path: Path,
) -> None:
    (tmp_path / "20261027T005911Z-blind-check.json").write_text(
        json.dumps(
            {
                "generated": "2026-10-27T00:59:11+00:00",
                "tenders": [
                    {
                        "slug": "a",
                        "complete": True,
                        "answered": 80,
                        "located": 80,
                        "rules": {"rules_run": 100, "passed": 99},
                        "unlocated_high": [],
                    },
                    {
                        "slug": "b",
                        "complete": True,
                        "answered": 20,
                        "located": 19,
                        "rules": {"rules_run": 50, "passed": 50},
                        "unlocated_high": ["x"],
                    },
                    {
                        "slug": "c",
                        "complete": False,
                        "answered": 10,
                        "located": 5,
                        "rules": {"rules_run": 10, "passed": 1},
                        "unlocated_high": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    report = composite("ergplan", tmp_path)
    assert report.unseen is not None
    assert report.unseen.tenders == ["a", "b", "c"] and report.unseen.complete == ["a", "b"]
    assert report.unseen.values == 100 and report.unseen.located == 99
    assert report.unseen.evidence_location_rate == 0.99
    assert report.unseen.rule_pass_rate == round(149 / 150, 4)
    assert report.unseen.unlocated_at_high_confidence == 1
    assert report.statements[1] == (
        "99.0% evidence location on 2 unseen tenders (99 of 100 values located on the page "
        "they cite; no accuracy claim)"
    )
    assert "accuracy" not in report.statements[1].replace("no accuracy claim", "")


def test_the_question_eval_is_reported_when_it_has_run(tmp_path: Path) -> None:
    (tmp_path / "ask-eval-20261029T000000Z.json").write_text(
        json.dumps(
            {
                "made_at": "2026-10-29T00:00:00+00:00",
                "summary": {
                    "questions": 50,
                    "accuracy": 0.9,
                    "critical_accuracy": 0.95,
                    "citations_total": 120,
                    "citation_resolution_rate": 0.975,
                },
            }
        ),
        encoding="utf-8",
    )
    report = composite("ergplan", tmp_path)
    assert report.query_eval.run and report.query_eval.questions == 50
    assert report.statements[2].startswith("Question eval: 90.0% of 50 questions")
    assert "| Question eval, citations resolved | 97.5% | 120 |" in "\n".join(markdown(report))
