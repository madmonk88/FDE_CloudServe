"""The internal representation.

One shape for a ticket regardless of which of the four channels it arrived
through, and one shape for the record of what the system decided about it.

These objects are the contract between components. Ingest is the only place
that knows a ticket ever looked different; nothing downstream has a branch on
channel except where channel genuinely changes the behaviour (response length,
latency budget), and where it does, that branch is explicit and named.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Channel(str, Enum):
    EMAIL = "email"
    CHAT = "chat"
    DOCS_COMMENT = "docs_comment"
    FORUM = "forum"
    UNKNOWN = "unknown"


class Urgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class Action(str, Enum):
    ANSWER = "answer"
    ESCALATE = "escalate"
    BLOCKED = "blocked"


@dataclass
class NormalisedTicket:
    """A ticket, after ingest, in the one shape the rest of the system uses."""

    ticket_id: str
    channel: Channel
    subject: str
    body: str
    # The original text is preserved verbatim alongside the cleaned body,
    # because the cleaning is lossy and the audit trail must show what the
    # customer actually wrote.
    raw_text: str
    customer_id: str | None = None
    customer_tier: str | None = None
    region: str | None = None
    language_fluency: str | None = None
    language: str | None = None
    created_at: str | None = None
    attachments: list[str] = field(default_factory=list)
    # Labels supplied with the development and validation sets. Present during
    # evaluation, absent in production. Nothing in the pipeline reads these —
    # only the harness does, after the fact.
    labels: dict[str, Any] = field(default_factory=dict)
    history: dict[str, Any] = field(default_factory=dict)
    # Anything the source file carried that we did not map. Kept so that a
    # field we did not anticipate in the hidden set is not silently lost.
    extra: dict[str, Any] = field(default_factory=dict)
    ingest_warnings: list[str] = field(default_factory=list)

    @property
    def text_for_model(self) -> str:
        """The customer's words, and only the customer's words."""
        subject = (self.subject or "").strip()
        body = (self.body or "").strip()
        if subject and body:
            return f"{subject}\n\n{body}"
        return subject or body or "(empty ticket)"

    @property
    def latency_budget_seconds(self) -> float:
        """Channel does change one thing legitimately: how long we may take.

        A live chat customer abandons the conversation; an email customer does
        not notice three extra seconds. This is the only place channel is
        allowed to alter behaviour by default.
        """
        return {
            Channel.CHAT: 3.0,
            Channel.DOCS_COMMENT: 10.0,
            Channel.FORUM: 15.0,
            Channel.EMAIL: 20.0,
        }.get(self.channel, 10.0)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["channel"] = self.channel.value
        return d


@dataclass
class RetrievedPassage:
    """A passage from the documentation corpus, with the identity needed to
    resolve it back to the real article. A6 is checked by following the
    citation, so a citation that cannot be resolved is a defect."""

    chunk_id: str
    doc_id: str
    title: str
    text: str
    score: float
    section: str | None = None
    url: str | None = None
    dense_score: float | None = None
    lexical_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Classification:
    intent: str
    urgency: Urgency
    confidence: float
    # What else it considered, and how strongly. The build spec asks for the
    # alternatives rather than only the winner, because a decision between two
    # near-equal options is a different decision from a confident one.
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    raw_confidence: float | None = None
    calibrated: bool = False
    method: str = "llm"
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["urgency"] = self.urgency.value
        return d


@dataclass
class RoutingDecision:
    action: Action
    reason: str
    # The numbers the decision was taken on, recorded so that the decision can
    # be recomputed months later and shown to be the same one.
    signals: dict[str, Any] = field(default_factory=dict)
    rule_fired: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["action"] = self.action.value
        return d


@dataclass
class GeneratedResponse:
    text: str
    citations: list[str] = field(default_factory=list)
    claims_without_support: list[str] = field(default_factory=list)
    admitted_uncertainty: bool = False
    grounding_score: float = 0.0
    method: str = "llm"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GuardrailFinding:
    name: str
    triggered: bool
    blocked: bool
    detail: str = ""
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GuardrailResult:
    """Every guardrail records what it checked and what it found, whether or
    not it blocked. A guardrail that only speaks up when it fires leaves no
    evidence that it ran at all."""

    findings: list[GuardrailFinding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.blocked for f in self.findings)

    @property
    def triggered_names(self) -> list[str]:
        return [f.name for f in self.findings if f.triggered]

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass
class TicketOutcome:
    """Everything the system did about one ticket. This is what gets written to
    the decision log and what the harness scores."""

    ticket_id: str
    channel: str
    action: str
    response_text: str | None
    citations: list[str]
    classification: dict[str, Any]
    routing: dict[str, Any]
    guardrails: dict[str, Any]
    retrieved: list[dict[str, Any]]
    escalation_package: dict[str, Any] | None
    latency_seconds: float
    degraded: bool
    error: str | None = None
    run_id: str = "adhoc"
    processed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
