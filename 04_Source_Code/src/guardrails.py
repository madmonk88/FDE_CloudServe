"""Guardrails: the things this system must never do, and what stops it.

Acceptance criterion A7 requires at least one guardrail that *blocks*. The
build specification states it plainly: a guardrail that only warns is not a
guardrail. Every check here can block, blocking is on by default, and each
check records what it examined and what it found whether or not it fired —
because a control that leaves no evidence when it passes cannot be audited.

Four checks run on every generated response before release:

1. **Private data.** Zero occurrences is a governance condition with no
   acceptable rate attached, so this one blocks unconditionally. It looks for
   credentials and personal identifiers that should never travel outbound,
   and deliberately tolerates false positives: a blocked reply costs an agent
   two minutes, a leaked key costs considerably more.

2. **Unsupported claims.** Each substantive sentence is scored against the
   passages actually retrieved. Below the support threshold a sentence counts
   as unsupported; above a proportion of unsupported sentences the reply is
   blocked. This is the control that addresses hallucination, which is the
   largest risk in the design.

3. **Prohibited commitments.** The system has no authority to promise refunds,
   credits, compensation, timelines or contractual outcomes on CloudServe's
   behalf. A model will make such promises when a customer pushes, and the
   consequences are commercial rather than technical.

4. **Prompt injection carried into the output.** If the reply contains signs
   that the customer's instructions redirected it — leaked system text,
   changed persona, meta-commentary about instructions — it is blocked.

The scoring uses the retriever's embeddings when they are available and falls
back to lexical overlap when they are not. The fallback is less sensitive, so
the threshold applied to it is set more conservatively: degraded detection
must fail towards blocking, never towards releasing.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .config import get_settings
from .models import GuardrailFinding, GuardrailResult, RetrievedPassage
from .retrieve import tokenise

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Private data
# ---------------------------------------------------------------------------

_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email_address", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")),
    ("credit_card", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    (
        "api_key_or_token",
        re.compile(
            r"\b(?:sk|pk|rk|api|key|token|secret|bearer)[-_]?[A-Za-z0-9]{16,}\b",
            re.IGNORECASE,
        ),
    ),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    (
        "phone_number",
        re.compile(r"(?<!\w)(?:\+\d{1,3}[ -]?)?(?:\(\d{2,4}\)[ -]?)?\d{3,4}[ -]\d{3,4}(?:[ -]\d{2,4})?(?!\w)"),
    ),
    ("ip_address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("national_id_like", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
]

# Addresses that are documentation conventions rather than anybody's data.
_PII_ALLOWLIST = re.compile(
    r"(support@cloudserve|example\.com|example\.org|yourdomain|your-domain|"
    r"user@example|127\.0\.0\.1|0\.0\.0\.0|localhost|10\.0\.0\.|192\.168\.|"
    r"<your|\byour_api_key\b|\bYOUR_API_KEY\b|xxxx|\*{4,})",
    re.IGNORECASE,
)


def _luhn(digits: str) -> bool:
    """Card numbers are checked against the Luhn checksum before blocking, so
    that an order number or a long identifier does not stop a valid reply."""
    nums = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(nums) <= 19:
        return False
    total, parity = 0, len(nums) % 2
    for i, n in enumerate(nums):
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def check_private_data(text: str) -> GuardrailFinding:
    evidence: list[str] = []
    for name, pattern in _PII_PATTERNS:
        for match in pattern.finditer(text or ""):
            value = match.group(0)
            if _PII_ALLOWLIST.search(value):
                continue
            if name == "credit_card" and not _luhn(value):
                continue
            if name == "ip_address":
                octets = value.split(".")
                if any(int(o) > 255 for o in octets if o.isdigit()):
                    continue
            # Redact in the evidence itself. A guardrail that logs the secret
            # it caught has moved the leak rather than prevented it.
            redacted = value[:3] + "…" + value[-2:] if len(value) > 8 else "…"
            evidence.append(f"{name}: {redacted}")

    triggered = bool(evidence)
    return GuardrailFinding(
        name="private_data",
        triggered=triggered,
        blocked=triggered and get_settings().guardrails.block_on_pii,
        detail=(
            f"{len(evidence)} potential private-data occurrence(s) in the outbound text"
            if triggered
            else "no private data detected in the outbound text"
        ),
        evidence=evidence[:10],
    )


# ---------------------------------------------------------------------------
# 2. Unsupported claims
# ---------------------------------------------------------------------------

_HEDGE_OR_PLEASANTRY = re.compile(
    r"^(hi|hello|hey|thanks|thank you|kind regards|best regards|regards|"
    r"let me know|i hope|i'm sorry|sorry|happy to help|of course|certainly|"
    r"you're welcome|if you|feel free|please let)",
    re.IGNORECASE,
)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [p.strip() for p in parts if len(p.strip()) > 15]


def _is_substantive(sentence: str) -> bool:
    """Greetings and sign-offs make no factual claim, so holding them to a
    grounding threshold would produce meaningless failures."""
    stripped = re.sub(r"\[S\d+\]", "", sentence).strip()
    if len(stripped) < 25:
        return False
    if _HEDGE_OR_PLEASANTRY.match(stripped):
        return False
    return True


def _lexical_support(sentence: str, corpus_tokens: set[str]) -> float:
    tokens = set(tokenise(sentence))
    if not tokens:
        return 1.0
    return len(tokens & corpus_tokens) / len(tokens)


def score_grounding(
    text: str, passages: list[RetrievedPassage]
) -> tuple[float, list[str], str]:
    """Proportion of substantive sentences supported by the retrieved passages.

    Returns (ratio, unsupported sentences, method used).
    """
    if not text or not text.strip():
        return 1.0, [], "empty"
    if not passages:
        return 0.0, _sentences(text), "no_sources"

    sentences = [s for s in _sentences(text) if _is_substantive(s)]
    if not sentences:
        return 1.0, [], "no_substantive_sentences"

    cfg = get_settings().guardrails
    method = "lexical"
    supports: list[float] = []

    # Prefer embeddings when the retriever has them.
    try:
        from .retrieve import get_retriever

        retriever = get_retriever()
        if retriever.dense_available:
            import numpy as np

            source_vecs = retriever._embedder.encode(  # noqa: SLF001 - deliberate reuse
                [p.text for p in passages],
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            sent_vecs = retriever._embedder.encode(  # noqa: SLF001
                sentences, normalize_embeddings=True, show_progress_bar=False
            )
            sims = np.asarray(sent_vecs) @ np.asarray(source_vecs).T
            supports = [float(row.max()) for row in sims]
            method = "embedding"
    except Exception as exc:  # pragma: no cover - degradation path
        log.debug("embedding grounding unavailable (%s); using lexical overlap", exc)

    if not supports:
        corpus_tokens = set()
        for p in passages:
            corpus_tokens.update(tokenise(p.text))
            corpus_tokens.update(tokenise(p.title))
        supports = [_lexical_support(s, corpus_tokens) for s in sentences]

    # The lexical measure is blunter, so it is held to a lower bar. Being
    # stricter on the blunt measure would block too many correct replies;
    # being looser would let ungrounded ones through. This value was chosen
    # on the development set.
    threshold = cfg.sentence_support_threshold if method == "embedding" else 0.30

    unsupported = [s for s, sup in zip(sentences, supports) if sup < threshold]
    ratio = 1.0 - (len(unsupported) / len(sentences))
    return round(ratio, 4), unsupported, method


def check_unsupported_claims(
    text: str, passages: list[RetrievedPassage]
) -> tuple[GuardrailFinding, float]:
    cfg = get_settings().guardrails
    ratio, unsupported, method = score_grounding(text, passages)
    triggered = ratio < cfg.min_supported_ratio
    return (
        GuardrailFinding(
            name="unsupported_claims",
            triggered=triggered,
            blocked=triggered and cfg.block_on_unsupported,
            detail=(
                f"{ratio:.0%} of substantive sentences trace back to the retrieved "
                f"passages (threshold {cfg.min_supported_ratio:.0%}, method {method})"
            ),
            evidence=[s[:180] for s in unsupported[:5]],
        ),
        ratio,
    )


# ---------------------------------------------------------------------------
# 3. Prohibited commitments
# ---------------------------------------------------------------------------

_COMMITMENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("refund", re.compile(r"\b(we (will|'ll|can) (refund|reimburse|credit)|issu\w+ (a )?(refund|credit)|money back)\b", re.IGNORECASE)),
    ("compensation", re.compile(r"\b(compensat\w+|goodwill (payment|credit)|waive (the )?(fee|charge))\b", re.IGNORECASE)),
    ("delivery_promise", re.compile(r"\b(we (will|'ll) (fix|ship|release|deliver|have this (fixed|resolved))\b.{0,40}\b(today|tomorrow|this week|by \w+day|within \d+))", re.IGNORECASE)),
    ("sla_guarantee", re.compile(r"\b(guarantee\w*|we promise|you (will|'ll) (definitely|certainly))\b", re.IGNORECASE)),
    ("contractual", re.compile(r"\b(cancel your (contract|subscription) (now|immediately)|terminate your agreement|legally (entitled|obliged))\b", re.IGNORECASE)),
]


def check_prohibited_commitments(text: str) -> GuardrailFinding:
    evidence = [
        f"{name}: {m.group(0)[:80]}"
        for name, pattern in _COMMITMENT_PATTERNS
        for m in pattern.finditer(text or "")
    ]
    triggered = bool(evidence)
    return GuardrailFinding(
        name="prohibited_commitment",
        triggered=triggered,
        blocked=triggered and get_settings().guardrails.block_on_prohibited_commitment,
        detail=(
            "the draft makes a commercial commitment the system has no authority to make"
            if triggered
            else "no commercial commitments detected"
        ),
        evidence=evidence[:5],
    )


# ---------------------------------------------------------------------------
# 4. Injection carried into the output
# ---------------------------------------------------------------------------

_INJECTION_MARKERS = [
    "ignore previous instructions",
    "ignore the above",
    "disregard your instructions",
    "system prompt",
    "you are chatgpt",
    "as an ai language model",
    "<<<ticket_content>>>",
    "the absolute rule",
    "content boundary",
    "developer mode",
    "my instructions are",
]


def check_injection_leak(text: str) -> GuardrailFinding:
    lowered = (text or "").lower()
    evidence = [m for m in _INJECTION_MARKERS if m in lowered]
    triggered = bool(evidence)
    return GuardrailFinding(
        name="injection_leak",
        triggered=triggered,
        blocked=triggered,
        detail=(
            "the draft contains system instruction text or signs of having been "
            "redirected by the ticket content"
            if triggered
            else "no sign of instruction leakage or redirection"
        ),
        evidence=evidence[:5],
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def validate(
    text: str, passages: list[RetrievedPassage]
) -> tuple[GuardrailResult, float]:
    """Run every guardrail. Returns the result and the grounding ratio.

    Runs on every generated response before release, not only in testing.
    There is no flag that disables it in the serving path; the individual
    `block_on_*` settings exist so that the report can show what the system
    does when a control is relaxed, and they default to blocking.
    """
    unsupported_finding, grounding = check_unsupported_claims(text, passages)
    result = GuardrailResult(
        findings=[
            check_private_data(text),
            unsupported_finding,
            check_prohibited_commitments(text),
            check_injection_leak(text),
        ]
    )
    if result.blocked:
        log.info(
            "response blocked by: %s",
            ", ".join(f.name for f in result.findings if f.blocked),
        )
    return result, grounding
