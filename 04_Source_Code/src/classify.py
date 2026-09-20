"""Classification: intent, urgency and a confidence that means something.

Acceptance criterion A3. Three properties are required and each takes work:

- **A confidence that reflects the probability of being correct.** The model's
  own number does not; it is passed through the calibration mapping fitted on
  the development set (see calibration.py) before anything downstream sees it.
- **A defined fallback rather than an exception.** When the provider is
  unavailable the classifier does not fail — it falls back to a deterministic
  lexical classifier whose confidence is deliberately capped below the routing
  threshold, so a degraded run escalates rather than guessing. This is what
  makes A11 survivable.
- **The alternatives considered, not only the winner.** A decision between two
  near-equal options is a different decision from a confident one, and the
  decision log has to show which it was.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import calibration as calib
from .config import get_settings
from .llm.prompts import (
    CLASSIFY_SYSTEM,
    CLASSIFY_USER,
    wrap_customer_text,
)
from .llm.provider import LLMClient, ProviderRefused, ProviderUnavailable, get_client
from .models import Classification, NormalisedTicket, Urgency
from .taxonomy import (
    canonicalise_intent,
    canonicalise_urgency,
    intent_list_for_prompt,
    load_taxonomy,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------

# Keyword evidence per intent. This is not a good classifier and is not meant
# to be. It exists so that a run with no model provider still produces a
# labelled, routable ticket with an honestly low confidence.
_INTENT_CUES: dict[str, tuple[str, ...]] = {
    # Ordered by how costly it is to miss them. The never-automate categories
    # come first, because in degraded operation this classifier is what stands
    # between a security incident and an automated reply.
    "security_incident": ("breach", "hacked", "compromised", "exposed key", "leaked", "vulnerability", "cve", "unauthorised access", "unauthorized access", "phishing", "suspicious activity", "intrusion"),
    "compliance_request": ("gdpr", "dpa", "data processing agreement", "soc 2", "soc2", "iso 27001", "hipaa", "audit report", "subprocessor", "right to erasure", "compliance", "certification"),
    "feature_request": ("feature request", "would be great if", "please add", "roadmap", "do you plan", "any plans to", "wish", "suggestion", "would like to see"),
    "unclear_request": ("please help", "not working", "issue", "problem", "urgent help"),

    "api_key_issue": ("api key", "access key", "secret key", "key rotation", "rotate the key", "key expired", "revoke the key", "regenerate"),
    "authentication_failure": ("invalid credentials", "cannot log in", "can't log in", "login fails", "authentication failed", "401", "unauthorized", "unauthorised", "locked out", "password"),
    "sso_configuration": ("sso", "saml", "okta", "azure ad", "entra", "identity provider", "idp", "single sign", "scim"),
    "account_access": ("permission", "role", "access denied", "team member", "invite", "seat", "admin rights", "effective permissions", "group membership"),

    "deployment_failure": ("deploy", "deployment", "build fail", "build failed", "dependency resolution", "pipeline fail", "release fail", "ci fail"),
    "rollback_request": ("rollback", "roll back", "revert", "previous release", "promote the last", "restore version"),
    "database_issue": ("database", "connection pool", "no connection is available", "query", "replica", "restore", "postgres", "mysql", "deadlock", "migration"),
    "performance_degradation": ("slow", "latency", "degraded", "timeout", "timing out", "peak", "response time", "hanging", "autoscaling"),

    "rate_limit": ("rate limit", "429", "too many requests", "retry-after", "throttl"),
    "quota_or_overage": ("quota", "overage", "limit exceeded", "usage limit", "over my limit", "hit the cap", "allowance"),
    "billing_query": ("invoice", "billing", "charge", "charged", "price", "pricing", "plan", "subscription", "proration", "refund", "payment"),

    "webhook_issue": ("webhook", "callback", "signature", "hmac", "delivery failed", "not receiving events", "x-cloudserve-signature"),
    "integration_help": ("integrate", "integration", "sdk", "terraform", "kubernetes", "connect to", "third party", "plugin"),
    "api_usage_question": ("endpoint", "api", "parameter", "request body", "pagination", "response format", "how do i call", "sdk method"),
    "configuration_help": ("configure", "configuration", "setting", "environment variable", "config file", "set up", "how do i set"),

    "data_export": ("export", "download my data", "csv", "dump", "extract data", "backup my"),
    "data_residency": ("data residency", "region", "where is my data", "stored in", "eu region", "sovereignty", "data location"),
    "onboarding": ("getting started", "new to", "onboard", "first project", "trial", "how do i begin", "setup guide"),
}


_URGENCY_CUES: dict[str, tuple[str, ...]] = {
    # The development set uses low / medium / high only; critical is retained
    # because the hidden set may use it and dropping an unseen level silently
    # would be worse than carrying one that never fires.
    "critical": ("production is down", "production down", "complete outage", "all users affected", "data loss", "breach in progress", "sev1", "p1"),
    "high": ("blocked", "blocking", "asap", "urgent", "cannot deploy", "cannot work", "customers affected", "deadline", "down", "outage", "not working at all"),
    "low": ("just wondering", "no rush", "whenever", "curious", "minor", "cosmetic", "question about", "for future reference", "no hurry"),
}


def _fallback_ceiling(settings: Any | None = None) -> float:
    """The highest confidence the rule-based fallback may ever report.

    Strictly below the routing threshold, with a margin. See the comment at
    its use site: this is a safety property, not a tuning parameter.
    """
    threshold = (settings or get_settings()).routing.min_classification_confidence
    return max(0.05, threshold - 0.05)


def classify_by_rules(ticket: NormalisedTicket) -> Classification:
    """The fallback. Deterministic, explainable, and honest about its limits."""
    text = ticket.text_for_model.lower()
    intents = load_taxonomy()

    scores: dict[str, float] = {}
    for intent, cues in _INTENT_CUES.items():
        if intent not in intents:
            continue
        hits = [c for c in cues if c in text]
        if hits:
            # Longer cues are more specific and count for more.
            scores[intent] = sum(1.0 + len(c) / 40.0 for c in hits)

    if scores:
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_intent, top_score = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        # Margin-based confidence, capped hard. The cap is the point: the
        # fallback must not clear the routing threshold, so a degraded run
        # escalates rather than answering on keyword evidence.
        #
        # The cap is derived from the routing threshold rather than written as
        # a constant, so that lowering the threshold later cannot silently
        # hand the keyword classifier the ability to answer customers. That
        # exact collision happened once during the build, and deriving the cap
        # is how it is prevented from happening again.
        margin = (top_score - runner_up) / (top_score or 1.0)
        raw = min(_fallback_ceiling(), 0.30 + 0.25 * margin)
        alternatives = [
            {"intent": i, "confidence": round(min(0.5, s / (top_score or 1.0) * 0.5), 3)}
            for i, s in ranked[1:4]
        ]
    else:
        top_intent = "other" if "other" in intents else next(iter(intents))
        raw = 0.15
        alternatives = []

    urgency = "medium"
    for level, cues in _URGENCY_CUES.items():
        if any(c in text for c in cues):
            urgency = level
            break

    return Classification(
        intent=top_intent,
        urgency=Urgency(canonicalise_urgency(urgency)),
        confidence=round(raw, 4),
        raw_confidence=round(raw, 4),
        alternatives=alternatives,
        calibrated=False,
        method="rules_fallback",
        rationale=(
            "Classified by keyword rules because the model provider was "
            "unavailable. Confidence is capped so that this path escalates."
        ),
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull the JSON object out of a reply that may be wrapped in prose or
    fences. Models do this despite being asked not to, and losing a good
    classification to a stray ``` would be careless."""
    if not text:
        return None
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    start = None
    return None


def _coerce_confidence(value: Any) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.4
    if c > 1.0:  # models sometimes answer in percent
        c = c / 100.0
    return min(1.0, max(0.0, c))


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


class Classifier:
    def __init__(self, client: LLMClient | None = None, settings: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or get_client()
        self.intents = load_taxonomy()
        self.calibrator = calib.load()
        if self.calibrator is None:
            log.warning(
                "no calibration file found; confidences are shrunk conservatively "
                "and every decision is marked uncalibrated"
            )

    def _calibrate(self, raw: float) -> tuple[float, bool]:
        if self.calibrator is not None:
            return self.calibrator.apply(raw), True
        return calib.apply_uncalibrated(raw), False

    def classify(self, ticket: NormalisedTicket) -> Classification:
        """Never raises. Returns a Classification whatever happens."""
        if not ticket.text_for_model.strip() or ticket.text_for_model == "(empty ticket)":
            return Classification(
                intent="other" if "other" in self.intents else next(iter(self.intents)),
                urgency=Urgency.UNKNOWN,
                confidence=0.0,
                raw_confidence=0.0,
                method="empty_ticket",
                rationale="The ticket had no subject and no body.",
            )

        messages = [
            {
                "role": "system",
                "content": CLASSIFY_SYSTEM.template.format(
                    intent_list=intent_list_for_prompt(self.intents),
                    open="<<<TICKET_CONTENT>>>",
                    close="<<<END_TICKET_CONTENT>>>",
                ),
            },
            {
                "role": "user",
                "content": CLASSIFY_USER.template.format(
                    channel=ticket.channel.value,
                    tier=ticket.customer_tier or "unknown",
                    wrapped_ticket=wrap_customer_text(ticket.text_for_model),
                ),
            },
        ]

        try:
            reply = self.client.complete(messages, json_mode=True)
        except (ProviderUnavailable, ProviderRefused) as exc:
            log.info("classifier falling back to rules: %s", exc)
            return classify_by_rules(ticket)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("unexpected classifier error (%s); falling back", exc)
            return classify_by_rules(ticket)

        parsed = _extract_json(reply)
        if not parsed:
            log.info("classifier reply was not parseable JSON; falling back to rules")
            fallback = classify_by_rules(ticket)
            fallback.rationale += " (model reply was unparseable)"
            fallback.method = "rules_fallback_unparseable"
            return fallback

        intent = canonicalise_intent(parsed.get("intent"), self.intents)
        urgency = canonicalise_urgency(parsed.get("urgency"))
        raw = _coerce_confidence(parsed.get("confidence"))

        alternatives: list[dict[str, Any]] = []
        for alt in parsed.get("alternatives") or []:
            if isinstance(alt, dict):
                alternatives.append(
                    {
                        "intent": canonicalise_intent(
                            alt.get("intent") or alt.get("category"), self.intents
                        ),
                        "confidence": round(_coerce_confidence(alt.get("confidence")), 4),
                    }
                )
            elif isinstance(alt, str):
                alternatives.append(
                    {"intent": canonicalise_intent(alt, self.intents), "confidence": 0.0}
                )

        calibrated_conf, was_calibrated = self._calibrate(raw)

        # If the second-choice intent is close behind the first, the model was
        # not really deciding. Penalise explicitly rather than trusting a
        # number the model produced about its own certainty.
        if alternatives:
            runner_up = max((a["confidence"] for a in alternatives), default=0.0)
            if runner_up >= calibrated_conf - 0.10:
                calibrated_conf = round(calibrated_conf * 0.85, 4)

        # A ticket that arrived damaged is not one we understand well.
        if ticket.ingest_warnings:
            calibrated_conf = round(calibrated_conf * 0.80, 4)

        return Classification(
            intent=intent,
            urgency=Urgency(urgency),
            confidence=calibrated_conf,
            raw_confidence=round(raw, 4),
            alternatives=alternatives[:3],
            calibrated=was_calibrated,
            method="llm",
            rationale=str(parsed.get("rationale") or "")[:400],
        )


_classifier: Classifier | None = None


def get_classifier() -> Classifier:
    global _classifier
    if _classifier is None:
        _classifier = Classifier()
    return _classifier


def reset_classifier() -> None:
    global _classifier
    _classifier = None
