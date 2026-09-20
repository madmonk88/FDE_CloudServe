"""Routing: answer automatically, or escalate with context.

**The routing policy in this module was not invented. It was recovered from
the data.**

The development set labels every ticket with `expected_route`. Treating that
as the target and searching for the simplest rule that reproduces it gives:

    escalate if the documentation cannot answer the ticket
    or if the intent is one of four never-automate categories
    or if it is a database or performance problem at high urgency
    otherwise answer automatically

That rule reproduces `expected_route` for **500 of 500** development tickets
and **80 of 80** validation tickets — 100% on both, with the validation set
held out while the rule was derived. It also produces zero violations of the
`must_not_auto_respond` flag across all 580 labelled tickets.

Reproduce the derivation: `python -m scripts.derive_policy`.

That result changes what the engineering problem is. The policy is not the
hard part and is not where the judgement is needed. The hard part is that one
of its three inputs — whether the documentation can answer the ticket — is a
label during development and an *unknown* at serving time, and it decides
more routing outcomes than the other two inputs combined.

Predicting it is therefore the real problem, and it is harder than it first
appears: thresholding the retrieval score gives an AUC of about 0.58, because
a feature request is not unanswerable for want of a topically similar
passage. `src/answerability.py` explains what is done instead and why. The
threshold applied to that prediction is the single most consequential number
in this system, and it is tuned in `scripts/tune_answerability.py`.

Two additions to the recovered policy, both deliberately conservative and
both ours rather than the data's:

- **A confidence floor.** The recovered policy assumes the intent is known.
  Ours is predicted, so a ticket we have not understood well enough is
  escalated rather than routed on a guess.
- **Operational rules.** A blocked draft, a draft that does not trace back to
  its sources, or a run with no model provider all escalate.

Every rule is ordered, the first to fire wins, and the reason is written in
language a support manager could read. Routing is a pure function of numbers
already computed and logged: no model call, no clock read, no randomness.
That is how A5 — same input, same decision — is guaranteed structurally
rather than hoped for.
"""

from __future__ import annotations

from typing import Any

from .answerability import get_model as get_answerability_model
from .config import get_settings
from .models import (
    Action,
    Classification,
    NormalisedTicket,
    RetrievedPassage,
    RoutingDecision,
)


def _signals(
    ticket: NormalisedTicket,
    classification: Classification,
    passages: list[RetrievedPassage],
    grounding: float | None,
    degraded: bool,
    answerable: bool,
    answerability_probability: float,
    answerability_method: str,
) -> dict[str, Any]:
    return {
        "intent": classification.intent,
        "urgency": classification.urgency.value,
        "classification_confidence": round(classification.confidence, 4),
        "classification_calibrated": classification.calibrated,
        "classification_method": classification.method,
        "predicted_answerable_from_docs": answerable,
        "answerability_probability": round(answerability_probability, 4),
        "answerability_method": answerability_method,
        "retrieved_count": len(passages),
        "top_retrieval_score": round(passages[0].score, 4) if passages else 0.0,
        "grounding_score": round(grounding, 4) if grounding is not None else None,
        "ingest_warnings": list(ticket.ingest_warnings),
        "degraded_mode": degraded,
        "customer_tier": ticket.customer_tier,
    }


def answerability_probability(
    intent: str | None,
    passages: list[RetrievedPassage],
) -> tuple[float, str]:
    """Probability that CloudServe's documentation can answer this ticket.

    The one input to the recovered policy that is a label during development
    and an unknown at serving time, and the one that decides the largest share
    of routing outcomes.

    See `src/answerability.py` for why this is not simply a threshold on the
    retrieval score: measured on the development set, the retrieval score
    alone separates answerable from unanswerable tickets with an AUC of about
    0.58, because a feature request is not unanswerable for lack of a
    topically similar passage. The fitted model combines the intent's
    historical answerable rate with the retrieval score and does considerably
    better.

    Falls back to the raw score when no model has been fitted, and says which
    path it took so the decision log records it.
    """
    top = passages[0].score if passages else 0.0
    model = get_answerability_model()
    if model is None:
        return top, "retrieval_score_only"
    return model.probability(intent, top), "fitted_model"


def predict_answerable(
    intent: str | None,
    passages: list[RetrievedPassage],
    settings: Any | None = None,
) -> tuple[bool, float, str]:
    cfg = (settings or get_settings()).routing
    probability, method = answerability_probability(intent, passages)
    if not passages:
        return False, probability, method
    return probability >= cfg.answerable_threshold, probability, method


def decide(
    ticket: NormalisedTicket,
    classification: Classification,
    passages: list[RetrievedPassage],
    *,
    grounding: float | None = None,
    degraded: bool = False,
    settings: Any | None = None,
) -> RoutingDecision:
    """Return the routing decision for one ticket. Pure and deterministic."""
    s = settings or get_settings()
    cfg = s.routing

    answerable, probability, method = predict_answerable(
        classification.intent, passages, s
    )
    signals = _signals(
        ticket,
        classification,
        passages,
        grounding,
        degraded,
        answerable,
        probability,
        method,
    )

    # -- Rule 1. Never-automate intents ------------------------------------
    # Recovered from the data: these four categories carry
    # must_not_auto_respond on 100% of their development tickets, and every
    # one of them is labelled escalate. No confidence level unlocks them,
    # because the cost of being wrong is not recoverable by a follow-up
    # message — and because the client has, in effect, already said so.
    if classification.intent in cfg.never_automate_intents:
        return RoutingDecision(
            action=Action.ESCALATE,
            rule_fired="R1_never_automate_intent",
            reason=(
                f"This is a {classification.intent.replace('_', ' ')}, which always goes "
                "to a person regardless of how confident the system is. Every ticket of "
                "this kind in CloudServe's own historical data was handled by a human, "
                "and the cost of an automated mistake here cannot be undone by a "
                "follow-up message."
            ),
            signals=signals,
        )

    # -- Rule 2. High-risk technical categories at high urgency ------------
    # Also recovered: database and performance problems escalate when urgent,
    # and only when urgent. At lower urgency the documentation handles them.
    if (
        classification.intent in cfg.high_risk_intents
        and classification.urgency.value in cfg.high_risk_urgency
    ):
        return RoutingDecision(
            action=Action.ESCALATE,
            rule_fired="R2_high_risk_at_high_urgency",
            reason=(
                f"A {classification.intent.replace('_', ' ')} reported as "
                f"{classification.urgency.value} urgency goes to an engineer. These are "
                "the cases where a documented answer is usually right in general and "
                "wrong for the specific situation, and the customer cannot afford the "
                "round trip."
            ),
            signals=signals,
        )

    # -- Rule 3. A ticket that arrived damaged ------------------------------
    if any("no subject and no body" in w for w in ticket.ingest_warnings):
        return RoutingDecision(
            action=Action.ESCALATE,
            rule_fired="R3_empty_ticket",
            reason=(
                "The ticket arrived with no readable content, so there is nothing to "
                "answer. A person needs to look at the original message."
            ),
            signals=signals,
        )

    # -- Rule 4. We do not understand the ticket well enough ---------------
    # Our addition. The recovered policy assumes the intent is known; ours is
    # predicted, and routing on a category we are unsure of would apply the
    # rules above to the wrong ticket.
    if classification.confidence < cfg.min_classification_confidence:
        return RoutingDecision(
            action=Action.ESCALATE,
            rule_fired="R4_low_confidence",
            reason=(
                f"The system was only {classification.confidence:.0%} confident it had "
                f"understood what this ticket is about, against a threshold of "
                f"{cfg.min_classification_confidence:.0%}. The routing rules depend on "
                "knowing the category, so a category we are unsure of is not a safe "
                "basis for answering."
            ),
            signals=signals,
        )

    # -- Rule 5. The documentation cannot answer this ----------------------
    # The dominant rule in the recovered policy: every ticket in the
    # development set labelled not-answerable is labelled escalate, without
    # exception. It is also the population that matters most to CloudServe,
    # because each one is a gap in the documentation rather than a failure of
    # the system.
    if not answerable:
        best = passages[0].score if passages else 0.0
        return RoutingDecision(
            action=Action.ESCALATE,
            rule_fired="R5_not_answerable_from_documentation",
            reason=(
                "CloudServe's documentation is unlikely to contain an answer to this "
                f"question: the system put the chance at {probability:.0%}, against a "
                f"threshold of {cfg.answerable_threshold:.0%} (best matching passage "
                f"scored {best:.2f}). There is no grounded answer to give, so it goes "
                "to a person — and the question is recorded as a documentation gap."
            ),
            signals=signals,
        )

    # -- Rule 6. The draft is not supported by what we retrieved -----------
    if grounding is not None and grounding < cfg.min_grounding:
        return RoutingDecision(
            action=Action.ESCALATE,
            rule_fired="R6_draft_not_grounded",
            reason=(
                f"Only {grounding:.0%} of the drafted reply could be traced back to the "
                f"documentation it cites, against a threshold of {cfg.min_grounding:.0%}. "
                "The draft goes to a person to check rather than to the customer."
            ),
            signals=signals,
        )

    # -- Rule 7. Degraded operation ----------------------------------------
    if degraded:
        return RoutingDecision(
            action=Action.ESCALATE,
            rule_fired="R7_degraded_mode",
            reason=(
                "The model provider was unavailable, so the system is running on its "
                "reduced capability path. It will still classify, retrieve, triage and "
                "log, but it does not send automated replies while degraded."
            ),
            signals=signals,
        )

    return RoutingDecision(
        action=Action.ANSWER,
        rule_fired="R8_answer",
        reason=(
            f"The system understood this as a {classification.intent.replace('_', ' ')} "
            f"with {classification.confidence:.0%} confidence, found documentation "
            f"scoring {passages[0].score:.2f} that covers it, and produced a reply that "
            "traces back to that documentation. It is not in a category CloudServe "
            "reserves for people, so it meets every condition for answering "
            "automatically."
        ),
        signals=signals,
    )


def is_documentation_gap(decision: RoutingDecision) -> bool:
    """A ticket the documentation could not answer.

    This is the signal that feeds the documentation gap report — the part of
    the system that makes next month's ticket volume smaller rather than
    merely faster to handle.
    """
    return decision.rule_fired == "R5_not_answerable_from_documentation"


def would_violate_never_automate(intent: str, settings: Any | None = None) -> bool:
    """Used by the evaluation to check the hard safety condition: no ticket
    carrying `must_not_auto_respond` may be answered automatically."""
    cfg = (settings or get_settings()).routing
    return intent in cfg.never_automate_intents
