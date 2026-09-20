"""The decision log.

Acceptance criterion A8: every automated decision written to a persistent log
with the required fields, and the log must reconcile against the number of
tickets processed when it is opened and counted.

The brief specifies the minimum record: the input, the prediction, the
confidence, the sources used, the action taken and the reason for it. Those
are columns here rather than a JSON blob, because a field you have to parse
out of a blob is a field nobody will query, and the point of this log is that
someone unfamiliar with the system can answer "why did it say that?" months
later without reading any code.

Two design points worth defending in the report:

**It is written before the response is released, not after.** A log written
after sending has a window in which a response exists that the log does not
know about. Here the row is written as the last step of processing and the
outcome is what gets returned, so a crash mid-run leaves a log that is short,
never a log that is wrong.

**Failures are logged too.** A8 is checked by counting rows against tickets
processed. A log that records only the tickets that succeeded will not
reconcile, and the gap is visible immediately.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import get_settings
from .models import TicketOutcome

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id               TEXT    NOT NULL,
    ticket_id            TEXT    NOT NULL,
    processed_at         TEXT    NOT NULL,
    channel              TEXT    NOT NULL,
    customer_tier        TEXT,
    region               TEXT,

    -- the input the decision was taken on
    input_text           TEXT    NOT NULL,

    -- the prediction and how sure the system was
    predicted_intent     TEXT,
    predicted_urgency    TEXT,
    confidence           REAL,
    confidence_calibrated INTEGER NOT NULL DEFAULT 0,
    classification_method TEXT,
    alternatives         TEXT,

    -- what it consulted
    sources_used         TEXT,
    top_source_score     REAL,
    retrieved_count      INTEGER NOT NULL DEFAULT 0,

    -- what it did and why
    action               TEXT    NOT NULL,
    rule_fired           TEXT,
    reason               TEXT    NOT NULL,
    response_text        TEXT,
    citations            TEXT,

    -- controls
    guardrails_triggered TEXT,
    guardrails_blocked   INTEGER NOT NULL DEFAULT 0,
    guardrail_detail     TEXT,
    grounding_score      REAL,

    -- operations
    latency_seconds      REAL,
    degraded             INTEGER NOT NULL DEFAULT 0,
    error                TEXT
);

CREATE INDEX IF NOT EXISTS idx_decisions_run    ON decisions(run_id);
CREATE INDEX IF NOT EXISTS idx_decisions_ticket ON decisions(ticket_id);
CREATE INDEX IF NOT EXISTS idx_decisions_action ON decisions(action);

CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    input_path   TEXT,
    output_path  TEXT,
    ticket_count INTEGER,
    notes        TEXT
);
"""


class DecisionLog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or get_settings().paths.decision_log_db)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init()

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            # WAL keeps the log readable while a run is still writing to it,
            # which matters when someone wants to watch a long run progress.
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- writing -----------------------------------------------------------

    def record(self, outcome: TicketOutcome, ticket: Any | None = None) -> None:
        """Write one decision. Never raises: a logging failure must not end a
        run, but it must be visible, so it is logged loudly instead."""
        classification = outcome.classification or {}
        routing = outcome.routing or {}
        guardrails = outcome.guardrails or {}
        findings = guardrails.get("findings", [])

        row = (
            outcome.run_id,
            outcome.ticket_id,
            outcome.processed_at,
            outcome.channel,
            getattr(ticket, "customer_tier", None),
            getattr(ticket, "region", None),
            (getattr(ticket, "text_for_model", "") or "")[:8000],
            classification.get("intent"),
            classification.get("urgency"),
            classification.get("confidence"),
            1 if classification.get("calibrated") else 0,
            classification.get("method"),
            json.dumps(classification.get("alternatives") or [], ensure_ascii=False),
            json.dumps([r.get("chunk_id") for r in outcome.retrieved], ensure_ascii=False),
            (outcome.retrieved[0].get("score") if outcome.retrieved else None),
            len(outcome.retrieved),
            outcome.action,
            routing.get("rule_fired"),
            routing.get("reason", ""),
            outcome.response_text,
            json.dumps(outcome.citations, ensure_ascii=False),
            json.dumps([f["name"] for f in findings if f.get("triggered")], ensure_ascii=False),
            1 if guardrails.get("blocked") else 0,
            json.dumps(findings, ensure_ascii=False),
            (routing.get("signals") or {}).get("grounding_score"),
            outcome.latency_seconds,
            1 if outcome.degraded else 0,
            outcome.error,
        )

        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    """INSERT INTO decisions (
                        run_id, ticket_id, processed_at, channel, customer_tier, region,
                        input_text, predicted_intent, predicted_urgency, confidence,
                        confidence_calibrated, classification_method, alternatives,
                        sources_used, top_source_score, retrieved_count,
                        action, rule_fired, reason, response_text, citations,
                        guardrails_triggered, guardrails_blocked, guardrail_detail,
                        grounding_score, latency_seconds, degraded, error
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    row,
                )
        except Exception as exc:  # pragma: no cover - must not end the run
            log.error("DECISION LOG WRITE FAILED for ticket %s: %s", outcome.ticket_id, exc)

    def start_run(self, run_id: str, input_path: str, output_path: str, started_at: str) -> None:
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO runs (run_id, started_at, input_path, output_path) "
                    "VALUES (?,?,?,?)",
                    (run_id, started_at, input_path, output_path),
                )
        except Exception as exc:  # pragma: no cover
            log.error("could not open run record: %s", exc)

    def finish_run(self, run_id: str, finished_at: str, ticket_count: int, notes: str = "") -> None:
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "UPDATE runs SET finished_at=?, ticket_count=?, notes=? WHERE run_id=?",
                    (finished_at, ticket_count, notes, run_id),
                )
        except Exception as exc:  # pragma: no cover
            log.error("could not close run record: %s", exc)

    # -- reading -----------------------------------------------------------

    def count(self, run_id: str | None = None) -> int:
        with self._connect() as conn:
            if run_id:
                cur = conn.execute("SELECT COUNT(*) c FROM decisions WHERE run_id=?", (run_id,))
            else:
                cur = conn.execute("SELECT COUNT(*) c FROM decisions")
            return int(cur.fetchone()["c"])

    def rows(self, run_id: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if run_id:
                cur = conn.execute(
                    "SELECT * FROM decisions WHERE run_id=? ORDER BY id LIMIT ?",
                    (run_id, limit),
                )
            else:
                cur = conn.execute("SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

    def reconcile(self, run_id: str, tickets_processed: int) -> dict[str, Any]:
        """The check an assessor performs: do the logged decisions account for
        every ticket? The system performs it on itself at the end of every run
        and puts the answer in the metrics report."""
        with self._connect() as conn:
            logged = int(
                conn.execute(
                    "SELECT COUNT(*) c FROM decisions WHERE run_id=?", (run_id,)
                ).fetchone()["c"]
            )
            distinct = int(
                conn.execute(
                    "SELECT COUNT(DISTINCT ticket_id) c FROM decisions WHERE run_id=?",
                    (run_id,),
                ).fetchone()["c"]
            )
            by_action = {
                r["action"]: r["c"]
                for r in conn.execute(
                    "SELECT action, COUNT(*) c FROM decisions WHERE run_id=? GROUP BY action",
                    (run_id,),
                ).fetchall()
            }
        return {
            "run_id": run_id,
            "tickets_processed": tickets_processed,
            "decisions_logged": logged,
            "distinct_tickets_logged": distinct,
            "reconciles": logged == tickets_processed == distinct,
            "by_action": by_action,
        }


_log: DecisionLog | None = None


def get_decision_log() -> DecisionLog:
    global _log
    if _log is None:
        _log = DecisionLog()
    return _log


def reset_decision_log() -> None:
    global _log
    _log = None
