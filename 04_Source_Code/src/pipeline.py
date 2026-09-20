"""The pipeline: ingest, classify, retrieve, route, generate, validate.

This is where the six components are wired together, and the whole file is
written around one requirement — A9, the unattended run over a file nobody
has seen. Everything else in the project is worth nothing if a single
malformed ticket can end the run.

So `process` catches everything. A ticket that fails for any reason at any
stage still produces an outcome with an action, a reason and a log row; it
escalates, which is the correct and safe behaviour when the system does not
know what happened. No ticket is dropped, and no exception propagates to the
loop that is feeding tickets in.

The order matters and is deliberate. Generation happens before routing is
finalised because the routing decision depends on how well the draft is
grounded, which cannot be known until the draft exists. Drafting a response
and then throwing it away is not waste: the draft travels with the escalation,
where an agent uses it as a starting point.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .classify import Classifier, get_classifier
from .config import get_settings
from .decision_log import DecisionLog, get_decision_log
from .generate import Generator, get_generator
from .guardrails import validate
from .models import (
    Action,
    Classification,
    GuardrailResult,
    NormalisedTicket,
    TicketOutcome,
    Urgency,
)
from .retrieve import Retriever, get_retriever
from .route import decide

log = logging.getLogger(__name__)


class SupportPipeline:
    def __init__(
        self,
        *,
        classifier: Classifier | None = None,
        retriever: Retriever | None = None,
        generator: Generator | None = None,
        decision_log: DecisionLog | None = None,
        settings: Any | None = None,
        run_id: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.classifier = classifier or get_classifier()
        self.retriever = retriever or get_retriever()
        self.generator = generator or get_generator()
        self.decision_log = decision_log or get_decision_log()
        self.run_id = run_id or self.settings.run_id

    # -----------------------------------------------------------------
    def process(self, ticket: NormalisedTicket) -> TicketOutcome:
        """Process one ticket. Returns an outcome under every circumstance."""
        started = time.perf_counter()
        degraded = False

        try:
            # 1. Classify -------------------------------------------------
            classification = self.classifier.classify(ticket)
            if classification.method.startswith("rules_fallback"):
                degraded = True

            # 2. Retrieve -------------------------------------------------
            # The query is the customer's text. Nothing is prepended: adding
            # the predicted intent was tried and made retrieval worse, because
            # it pulled every ticket towards the article that best matches the
            # category name rather than the question.
            passages = self.retriever.search(ticket.text_for_model)

            # 3. Generate -------------------------------------------------
            draft, gen_degraded = self.generator.draft(ticket, classification, passages)
            degraded = degraded or gen_degraded

            # 4. Validate -------------------------------------------------
            # Guardrails run on every generated response before release, not
            # only on the ones that are about to be sent.
            if draft is not None and draft.text:
                guardrail_result, grounding = validate(draft.text, passages)
                draft.grounding_score = grounding
            else:
                guardrail_result = GuardrailResult(findings=[])
                grounding = None

            # 5. Route ----------------------------------------------------
            decision = decide(
                ticket,
                classification,
                passages,
                grounding=grounding,
                degraded=degraded,
                settings=self.settings,
            )

            # The model declining to answer overrides a decision to answer.
            # It is the system working, not failing.
            if draft is not None and draft.admitted_uncertainty and decision.action == Action.ANSWER:
                decision.action = Action.ESCALATE
                decision.rule_fired = "R10_model_declined"
                decision.reason = (
                    "The system judged the documentation insufficient to answer this "
                    "question properly and declined to guess. It goes to a person."
                )

            # A blocked response is never sent, whatever routing decided.
            # The guardrail is the last word.
            if guardrail_result.blocked:
                blocked_by = ", ".join(
                    f.name.replace("_", " ") for f in guardrail_result.findings if f.blocked
                )
                decision.action = Action.BLOCKED
                decision.rule_fired = "R0_guardrail_block"
                decision.reason = (
                    f"The drafted reply was blocked before sending by the {blocked_by} "
                    "check, and the ticket was passed to a person instead."
                )

            # 6. Assemble the outcome -------------------------------------
            send = decision.action == Action.ANSWER and draft is not None and draft.text
            escalation = None
            if decision.action in (Action.ESCALATE, Action.BLOCKED):
                escalation = self.generator.escalation_note(
                    ticket, classification, passages, decision.reason
                )
                if draft is not None and draft.text:
                    escalation["draft_for_review"] = draft.text
                    escalation["draft_blocked"] = decision.action == Action.BLOCKED

            latency = time.perf_counter() - started

            outcome = TicketOutcome(
                ticket_id=ticket.ticket_id,
                channel=ticket.channel.value,
                action=decision.action.value,
                response_text=draft.text if send else None,
                citations=(draft.citations if draft else []),
                classification=classification.to_dict(),
                routing=decision.to_dict(),
                guardrails=guardrail_result.to_dict(),
                retrieved=[p.to_dict() for p in passages],
                escalation_package=escalation,
                latency_seconds=round(latency, 4),
                degraded=degraded,
                run_id=self.run_id,
            )

        except Exception as exc:  # noqa: BLE001 - this breadth is the point
            # A9 says no ticket is silently dropped. A ticket that breaks the
            # pipeline is logged, escalated and counted. The run continues.
            log.exception("pipeline failed on ticket %s", ticket.ticket_id)
            latency = time.perf_counter() - started
            outcome = TicketOutcome(
                ticket_id=ticket.ticket_id,
                channel=ticket.channel.value,
                action=Action.ESCALATE.value,
                response_text=None,
                citations=[],
                classification=Classification(
                    intent="other", urgency=Urgency.UNKNOWN, confidence=0.0,
                    method="pipeline_error",
                ).to_dict(),
                routing={
                    "action": Action.ESCALATE.value,
                    "rule_fired": "R11_pipeline_error",
                    "reason": (
                        "The system hit an unexpected error while processing this "
                        "ticket, so it was passed to a person. The error is recorded "
                        "against the ticket."
                    ),
                    "signals": {"error_type": type(exc).__name__},
                },
                guardrails={"blocked": False, "findings": []},
                retrieved=[],
                escalation_package={
                    "ticket_id": ticket.ticket_id,
                    "why_escalated": "processing error",
                    "note": "This ticket could not be processed automatically.",
                },
                latency_seconds=round(latency, 4),
                degraded=True,
                error=f"{type(exc).__name__}: {exc}",
                run_id=self.run_id,
            )

        # The log write is outside the try/except above and has its own
        # protection, so a logging failure cannot turn a good ticket into a
        # failed one.
        self.decision_log.record(outcome, ticket)
        return outcome

    # -----------------------------------------------------------------
    @property
    def stats(self) -> dict[str, Any]:
        return {
            "retrieval": self.retriever.stats,
            "model": self.classifier.client.stats,
            "calibrated": self.classifier.calibrator is not None,
            "run_id": self.run_id,
        }


_pipeline: SupportPipeline | None = None


def get_pipeline() -> SupportPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = SupportPipeline()
    return _pipeline


def reset_pipeline() -> None:
    global _pipeline
    _pipeline = None
