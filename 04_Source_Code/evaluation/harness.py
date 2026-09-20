"""The evaluation harness — the single command the whole project turns on.

    python -m evaluation.harness --input <tickets.json> --output <directory>

Acceptance criteria A9 and A10. The input path is an argument, never a
constant, because this will be pointed at a file of 120 tickets that does not
exist yet on any machine. The build specification names a harness that only
works against its author's copy of the data as the most common avoidable
failure in the assessment.

What this file is built to survive:

- A ticket that breaks the pipeline. Caught per ticket; the run continues.
- The model provider disappearing mid-run. The pipeline degrades to its
  deterministic path and every subsequent ticket escalates with context.
- The process being killed. Results are flushed to disk every 10 tickets, so
  a run that dies at ticket 96 of 120 leaves 96 results and a partial report
  rather than nothing.
- Being run twice. `--resume` picks up where the previous attempt stopped.

It never prompts, never waits for input, and exits zero when it has processed
every ticket it was given.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow `python -m evaluation.harness` from a clean checkout without install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings  # noqa: E402
from src.decision_log import DecisionLog  # noqa: E402
from src.ingest import load_tickets  # noqa: E402
from src.models import TicketOutcome  # noqa: E402
from src.pipeline import SupportPipeline  # noqa: E402
from evaluation.metrics import build_report  # noqa: E402
from evaluation.report import write_markdown_summary  # noqa: E402

log = logging.getLogger("harness")

FLUSH_EVERY = 10

_stop_requested = False


def _handle_signal(signum, frame):  # pragma: no cover - signal path
    global _stop_requested
    _stop_requested = True
    log.warning("signal %s received; finishing the current ticket then stopping cleanly", signum)


def _setup_logging(output_dir: Path, verbose: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    handlers.append(logging.FileHandler(output_dir / "run.log", encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    # These libraries are chatty at INFO and drown the run log.
    for noisy in ("httpx", "httpcore", "urllib3", "sentence_transformers", "chromadb"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _write_json(path: Path, payload: Any) -> None:
    """Write atomically, so a kill during the write cannot leave a truncated
    file that looks like a valid result."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _load_completed(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {r["ticket_id"]: r for r in data if isinstance(r, dict) and "ticket_id" in r}
    except Exception:
        return {}


def run(
    input_path: Path,
    output_dir: Path,
    *,
    limit: int | None = None,
    resume: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    started_wall = time.time()
    started_iso = datetime.now(timezone.utc).isoformat()
    run_id = run_id or f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    os.environ["RUN_ID"] = run_id

    settings = get_settings(refresh=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info("run %s starting", run_id)
    log.info("input:  %s", input_path)
    log.info("output: %s", output_dir)

    # ---- load ----------------------------------------------------------
    tickets = load_tickets(input_path)
    if limit:
        tickets = tickets[:limit]
    log.info("%d tickets loaded", len(tickets))
    if not tickets:
        log.error("no tickets found in %s", input_path)

    warned = sum(1 for t in tickets if t.ingest_warnings)
    if warned:
        log.info("%d ticket(s) carried ingest warnings and were kept", warned)

    # ---- build the system ----------------------------------------------
    decision_log = DecisionLog()
    decision_log.start_run(run_id, str(input_path), str(output_dir), started_iso)

    build_started = time.perf_counter()
    pipeline = SupportPipeline(decision_log=decision_log, run_id=run_id)
    log.info("system ready in %.1fs: %s", time.perf_counter() - build_started, pipeline.stats)

    responses_path = output_dir / "responses.json"
    completed = _load_completed(responses_path) if resume else {}
    if completed:
        log.info("resuming: %d ticket(s) already processed", len(completed))

    results: list[dict[str, Any]] = list(completed.values())
    outcomes: list[TicketOutcome] = []

    # Rebuild outcome objects for already-completed tickets so the metrics
    # cover the whole set rather than only this attempt.
    for record in completed.values():
        try:
            outcomes.append(TicketOutcome(**record))
        except Exception:
            pass

    todo = [t for t in tickets if t.ticket_id not in completed]

    # ---- process -------------------------------------------------------
    for i, ticket in enumerate(todo, start=1):
        if _stop_requested:
            log.warning("stopping early at %d/%d on request", i - 1, len(todo))
            break

        outcome = pipeline.process(ticket)
        outcomes.append(outcome)
        results.append(outcome.to_dict())

        if i % FLUSH_EVERY == 0 or i == len(todo):
            _write_json(responses_path, results)
            elapsed = time.time() - started_wall
            rate = i / elapsed if elapsed else 0.0
            remaining = (len(todo) - i) / rate if rate else 0.0
            log.info(
                "%d/%d processed (%.1f tickets/min, ~%.0fs remaining)",
                i,
                len(todo),
                rate * 60,
                remaining,
            )

    _write_json(responses_path, results)

    # ---- reconcile and report ------------------------------------------
    finished_iso = datetime.now(timezone.utc).isoformat()
    duration = time.time() - started_wall

    reconciliation = decision_log.reconcile(run_id, len(outcomes))
    if not reconciliation["reconciles"]:
        log.warning(
            "decision log does not reconcile: %d decisions for %d tickets",
            reconciliation["decisions_logged"],
            reconciliation["tickets_processed"],
        )

    run_meta = {
        "run_id": run_id,
        "started_at": started_iso,
        "finished_at": finished_iso,
        "duration_seconds": round(duration, 2),
        "input_file": str(input_path),
        "input_file_name": input_path.name,
        "output_directory": str(output_dir),
        "tickets_in_file": len(tickets),
        "tickets_processed": len(outcomes),
        "completed_fully": len(outcomes) == len(tickets),
        "model": settings.model.model,
        "provider": settings.model.provider,
        "system": pipeline.stats,
        "thresholds": {
            "answerable_threshold": settings.routing.answerable_threshold,
            "min_classification_confidence": settings.routing.min_classification_confidence,
            "min_grounding": settings.routing.min_grounding,
            "retrieval_min_score": settings.retrieval.min_score,
            "never_automate_intents": list(settings.routing.never_automate_intents),
            "high_risk_intents": list(settings.routing.high_risk_intents),
        },
    }

    report = build_report(
        tickets, outcomes, reconciliation=reconciliation, run_meta=run_meta
    )

    _write_json(output_dir / "metrics.json", report)
    write_markdown_summary(report, output_dir / "metrics.md")
    _write_json(
        output_dir / "documentation_gaps.json", report.get("documentation_gaps", {})
    )

    decision_log.finish_run(
        run_id,
        finished_iso,
        len(outcomes),
        notes=f"{len(outcomes)}/{len(tickets)} tickets; {duration:.0f}s",
    )

    # ---- say what happened ---------------------------------------------
    v = report["volume"]
    b = report["business"]
    log.info("-" * 68)
    log.info("run %s complete in %.0fs", run_id, duration)
    log.info(
        "  %d processed | %d answered | %d escalated | %d blocked | %d errors",
        v["tickets_processed"],
        v["answered_automatically"],
        v["escalated"],
        v["blocked_by_guardrails"],
        v["processing_errors"],
    )
    log.info(
        "  first contact resolution %.1f%% (target 60%%, baseline 42%%)",
        b["first_contact_resolution"] * 100,
    )
    log.info(
        "  escalation rate %.1f%% (target 30%%, baseline 58%%)",
        b["escalation_rate"] * 100,
    )
    log.info(
        "  p95 latency %.2fs (target 3s)",
        report["technical"]["latency_seconds"]["p95"],
    )
    log.info(
        "  decision log reconciles: %s (%d rows)",
        reconciliation["reconciles"],
        reconciliation["decisions_logged"],
    )
    log.info(
        "  documentation gaps found: %d",
        report["documentation_gaps"]["tickets_with_no_documentation_answer"],
    )
    if v["processed_in_degraded_mode"]:
        log.info(
            "  NOTE: %d ticket(s) processed with the model provider unavailable",
            v["processed_in_degraded_mode"],
        )
    log.info("  written to %s", output_dir)
    log.info("-" * 68)

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.harness",
        description="Process a file of support tickets end to end and write a metrics report.",
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to the ticket file to process (JSON array, JSON Lines, or an "
        "object containing a list of tickets).",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Directory to write responses.json, metrics.json, metrics.md and run.log into.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N tickets.")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip tickets already present in the output directory's responses.json.",
    )
    parser.add_argument("--run-id", default=None, help="Override the generated run identifier.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    args = parser.parse_args(argv)

    _setup_logging(args.output, args.verbose)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    if not args.input.exists():
        log.error("input file does not exist: %s", args.input)
        return 2

    try:
        report = run(
            args.input,
            args.output,
            limit=args.limit,
            resume=args.resume,
            run_id=args.run_id,
        )
    except Exception:
        log.exception("the run failed before it could complete")
        return 1

    return 0 if report["run"]["completed_fully"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
