"""The HTTP interface.

    python -m src.api

FastAPI is used because it generates its own documentation, which the test
procedure benefits from: an assessor submitting one ticket from each channel
can do it from /docs without writing a client.

The endpoints exist to satisfy the parts of the test procedure that are
interactive — submitting one ticket per channel, submitting a ticket
engineered to trigger a guardrail — and to provide the health and metrics
surfaces that monitoring scrapes. The unattended run does not go through here;
it goes through the harness, and both use the same pipeline object so there is
no second code path to keep in step.

A kill switch is included and is a deliberate governance decision rather than
a feature. The governance framework asks for a stated position on what the
system must never do and a mechanism that enforces it; a system that speaks to
customers without a human in the loop needs a way to be stopped by someone who
is not an engineer, at two in the morning, without a deployment.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from .config import get_settings
from .decision_log import get_decision_log
from .ingest import normalise_ticket
from .models import Action
from .pipeline import get_pipeline

log = logging.getLogger(__name__)

app = FastAPI(
    title="CloudServe Support Intelligence",
    description=(
        "Classifies, retrieves for, routes, answers and audits inbound support "
        "tickets from four channels."
    ),
    version="1.0.0",
)

_started_at = time.time()

# The kill switch. In-process here; in a real deployment this is a flag in the
# configuration store that every instance reads, so that flipping it stops the
# fleet rather than one process.
_AUTOMATION_ENABLED = {"value": os.getenv("AUTOMATION_ENABLED", "true").lower() != "false"}


class TicketRequest(BaseModel):
    ticket_id: str | None = Field(None, description="Optional; one is assigned if absent.")
    channel: str = Field("email", description="email, chat, docs_comment or forum")
    subject: str = ""
    body: str = ""
    customer_id: str | None = None
    customer_tier: str | None = None
    region: str | None = None
    language_fluency: str | None = None


class KillSwitchRequest(BaseModel):
    enabled: bool
    reason: str = Field(..., min_length=3, description="Recorded in the run notes.")


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness and readiness in one place, including whether the system is
    currently running degraded. Monitoring alerts on `degraded` rather than
    only on `status`, because a system answering nothing while returning 200
    is the failure mode that goes unnoticed."""
    pipeline = get_pipeline()
    client = pipeline.classifier.client
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - _started_at, 1),
        "automation_enabled": _AUTOMATION_ENABLED["value"],
        "model_provider_reachable": client.available,
        "degraded": not client.available,
        "retrieval": pipeline.retriever.stats,
        "calibrated": pipeline.classifier.calibrator is not None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/tickets")
def submit_ticket(request: TicketRequest) -> dict[str, Any]:
    """Process one ticket and return what the system decided and why."""
    if not _AUTOMATION_ENABLED["value"]:
        raise HTTPException(
            status_code=503,
            detail=(
                "Automation is disabled by the kill switch. Every ticket is going "
                "to the human queue until it is re-enabled."
            ),
        )

    ticket = normalise_ticket(request.model_dump(exclude_none=True))
    outcome = get_pipeline().process(ticket)

    return {
        "ticket_id": outcome.ticket_id,
        "action": outcome.action,
        "response": outcome.response_text,
        "citations": outcome.citations,
        "why": outcome.routing.get("reason"),
        "rule": outcome.routing.get("rule_fired"),
        "classification": outcome.classification,
        "sources": [
            {
                "chunk_id": r["chunk_id"],
                "doc_id": r["doc_id"],
                "title": r["title"],
                "score": r["score"],
            }
            for r in outcome.retrieved
        ],
        "guardrails": outcome.guardrails,
        "escalation_package": outcome.escalation_package,
        "latency_seconds": outcome.latency_seconds,
        "degraded": outcome.degraded,
    }


@app.get("/decisions/{ticket_id}")
def decision_for(ticket_id: str) -> dict[str, Any]:
    """Why did the system say that? The question the decision log exists to
    answer, exposed so it can be answered without opening the database."""
    rows = [r for r in get_decision_log().rows(limit=5000) if r["ticket_id"] == ticket_id]
    if not rows:
        raise HTTPException(status_code=404, detail=f"no decision recorded for {ticket_id}")
    return {"ticket_id": ticket_id, "decisions": rows}


@app.get("/metrics")
def prometheus_metrics() -> Response:
    """Prometheus exposition format, scraped by the monitoring stack."""
    log_db = get_decision_log()
    rows = log_db.rows(limit=20000)
    total = len(rows)
    answered = sum(1 for r in rows if r["action"] == Action.ANSWER.value)
    escalated = sum(1 for r in rows if r["action"] == Action.ESCALATE.value)
    blocked = sum(1 for r in rows if r["action"] == Action.BLOCKED.value)
    degraded = sum(1 for r in rows if r["degraded"])
    errors = sum(1 for r in rows if r["error"])
    latencies = sorted(r["latency_seconds"] or 0.0 for r in rows)
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0

    client = get_pipeline().classifier.client
    lines = [
        "# HELP cloudserve_tickets_total Tickets processed.",
        "# TYPE cloudserve_tickets_total counter",
        f"cloudserve_tickets_total {total}",
        "# HELP cloudserve_tickets_by_action Tickets by routing action.",
        "# TYPE cloudserve_tickets_by_action counter",
        f'cloudserve_tickets_by_action{{action="answer"}} {answered}',
        f'cloudserve_tickets_by_action{{action="escalate"}} {escalated}',
        f'cloudserve_tickets_by_action{{action="blocked"}} {blocked}',
        "# HELP cloudserve_degraded_total Tickets processed without the model provider.",
        "# TYPE cloudserve_degraded_total counter",
        f"cloudserve_degraded_total {degraded}",
        "# HELP cloudserve_errors_total Tickets that hit a processing error.",
        "# TYPE cloudserve_errors_total counter",
        f"cloudserve_errors_total {errors}",
        "# HELP cloudserve_latency_p95_seconds 95th percentile processing latency.",
        "# TYPE cloudserve_latency_p95_seconds gauge",
        f"cloudserve_latency_p95_seconds {p95:.4f}",
        "# HELP cloudserve_automation_enabled Kill switch state.",
        "# TYPE cloudserve_automation_enabled gauge",
        f"cloudserve_automation_enabled {1 if _AUTOMATION_ENABLED['value'] else 0}",
        "# HELP cloudserve_provider_available Model provider reachability.",
        "# TYPE cloudserve_provider_available gauge",
        f"cloudserve_provider_available {1 if client.available else 0}",
        "# HELP cloudserve_llm_cache_hits Cached model responses served.",
        "# TYPE cloudserve_llm_cache_hits counter",
        f"cloudserve_llm_cache_hits {client.cache.hits}",
    ]
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.post("/admin/kill-switch")
def kill_switch(request: KillSwitchRequest = Body(...)) -> dict[str, Any]:
    """Stop or resume automated replies.

    Turning automation off does not stop the system: tickets still arrive, are
    still classified, retrieved for and logged, and every one goes to the human
    queue with its context package attached. That is the correct behaviour for
    an incident — losing the automation is survivable, losing the triage is
    not.
    """
    previous = _AUTOMATION_ENABLED["value"]
    _AUTOMATION_ENABLED["value"] = request.enabled
    log.warning(
        "KILL SWITCH: automation %s -> %s. Reason: %s",
        "on" if previous else "off",
        "on" if request.enabled else "off",
        request.reason,
    )
    return {
        "automation_enabled": request.enabled,
        "previously": previous,
        "reason": request.reason,
        "changed_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    import uvicorn

    settings = get_settings()
    log.info("starting API with model %s", settings.model.model)
    uvicorn.run(
        app,
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "8000")),
        log_level="info",
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()
