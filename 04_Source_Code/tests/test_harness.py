"""A9 and A10: the unattended run and the metrics report it produces.

This runs the documented command against the fixture set and checks the
properties an assessor checks: every ticket accounted for, a metrics report
written without further manual work, and a decision log that reconciles.
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def test_a9_full_run_is_unattended_and_complete(tmp_path, monkeypatch):
    from evaluation.harness import main

    output = tmp_path / "results"
    exit_code = main(
        ["--input", str(FIXTURES / "tickets.json"), "--output", str(output)]
    )

    assert exit_code == 0, "the harness did not complete the full set"

    responses = json.loads((output / "responses.json").read_text())
    assert len(responses) == 10, "not every ticket produced a result"

    # Every ticket produced either a sent answer or a logged escalation.
    # None are silently dropped.
    for record in responses:
        assert record["action"] in {"answer", "escalate", "blocked"}
        assert record["routing"]["reason"]
        if record["action"] == "answer":
            assert record["response_text"]
        else:
            assert record["escalation_package"] is not None


def test_a9_input_path_is_an_argument_not_a_constant(tmp_path):
    """The harness will be pointed at a file that does not exist yet. This is
    the single most common avoidable failure in this assessment."""
    from evaluation.harness import main

    custom = tmp_path / "some-file-nobody-has-seen.json"
    custom.write_text(
        json.dumps([{"ticket_id": "X1", "channel": "email", "body": "How do I rotate a key?"}]),
        encoding="utf-8",
    )
    output = tmp_path / "out"
    assert main(["--input", str(custom), "--output", str(output)]) == 0
    assert json.loads((output / "responses.json").read_text())[0]["ticket_id"] == "X1"


def test_a9_missing_input_file_exits_cleanly(tmp_path):
    from evaluation.harness import main

    assert main(["--input", str(tmp_path / "nope.json"), "--output", str(tmp_path / "o")]) == 2


def test_a10_metrics_report_is_produced(tmp_path):
    from evaluation.harness import main

    output = tmp_path / "results"
    main(["--input", str(FIXTURES / "tickets.json"), "--output", str(output)])

    assert (output / "metrics.json").exists()
    assert (output / "metrics.md").exists()
    assert (output / "run.log").exists()

    report = json.loads((output / "metrics.json").read_text())

    # The four groups the build specification names.
    for group in ("volume", "business", "technical", "governance"):
        assert group in report

    assert report["volume"]["tickets_processed"] == 10
    assert (
        report["volume"]["answered_automatically"]
        + report["volume"]["escalated"]
        + report["volume"]["blocked_by_guardrails"]
        == 10
    ), "tickets must be fully accounted for across the three outcomes"

    assert "first_contact_resolution" in report["business"]
    assert "escalation_rate" in report["business"]
    assert "latency_seconds" in report["technical"]
    assert "p95" in report["technical"]["latency_seconds"]
    assert "guardrail_activations_by_type" in report["governance"]
    assert "fairness" in report
    assert "documentation_gaps" in report


def test_a10_decision_log_reconciles_in_the_report(tmp_path):
    from evaluation.harness import main

    output = tmp_path / "results"
    main(["--input", str(FIXTURES / "tickets.json"), "--output", str(output)])
    report = json.loads((output / "metrics.json").read_text())
    reconciliation = report["reconciliation"]
    assert reconciliation["tickets_processed"] == 10
    assert reconciliation["decisions_logged"] == 10
    assert reconciliation["reconciles"]


def test_a10_markdown_summary_is_readable(tmp_path):
    from evaluation.harness import main

    output = tmp_path / "results"
    main(["--input", str(FIXTURES / "tickets.json"), "--output", str(output)])
    text = (output / "metrics.md").read_text()
    for heading in (
        "# Evaluation run report",
        "## Business outcomes",
        "## Technical performance",
        "## Governance",
        "## Fairness across customer groups",
        "## Documentation gaps",
    ):
        assert heading in text


def test_resume_does_not_reprocess(tmp_path):
    from evaluation.harness import main

    output = tmp_path / "results"
    main(["--input", str(FIXTURES / "tickets.json"), "--output", str(output), "--limit", "4"])
    assert len(json.loads((output / "responses.json").read_text())) == 4

    main(["--input", str(FIXTURES / "tickets.json"), "--output", str(output), "--resume"])
    responses = json.loads((output / "responses.json").read_text())
    assert len(responses) == 10
    assert len({r["ticket_id"] for r in responses}) == 10
