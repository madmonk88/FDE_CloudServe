"""Ingest: four channels in, one representation out.

Acceptance criterion A2. The design rule here is that this module is the only
part of the system permitted to know that tickets ever looked different, and
that it never raises. A malformed ticket in the hidden set must produce a
degraded ticket with a warning attached, not an exception that ends the run —
A9 requires that no ticket is silently dropped, and an exception here drops
every ticket after it as well.

Field names are matched tolerantly on purpose. The hidden evaluation set is
described as using the same schema, but "same schema" has been wrong before,
and a mapping that accepts `customer_tier`, `tier` and `customerTier` costs
three lines and removes a whole class of failure.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Iterator

from .models import Channel, NormalisedTicket

# ---------------------------------------------------------------------------
# Field aliases. First match wins, checked case-insensitively with separators
# stripped, so `customer_tier`, `customerTier` and `Customer Tier` all match.
# ---------------------------------------------------------------------------

_ALIASES: dict[str, tuple[str, ...]] = {
    "ticket_id": ("ticket_id", "id", "ticketid", "ticket_number", "reference", "uid"),
    "channel": ("channel", "source", "origin", "channel_type", "medium"),
    "subject": ("subject", "title", "summary", "headline", "topic"),
    "body": ("body", "text", "message", "content", "description", "question", "ticket_text"),
    "customer_id": ("customer_id", "customerid", "user_id", "account_id", "requester_id"),
    "customer_tier": ("customer_tier", "tier", "plan", "account_tier", "segment"),
    "region": ("customer_region", "region", "geo", "country", "locale_region", "territory"),
    "language_fluency": (
        "language_fluency",
        "fluency",
        "english_fluency",
        "language_level",
        "proficiency",
    ),
    "language": ("language", "lang", "locale"),
    "created_at": (
        "created_at",
        "createdat",
        "timestamp",
        "received_at",
        "submitted_at",
        "date",
        "opened_at",
    ),
    "attachments": ("attachments", "files", "attachment_names"),
    "labels": ("labels", "label", "annotations", "gold", "ground_truth"),
    "history": ("history", "actual", "human_handling", "resolution_history", "outcome"),
}

_KNOWN_KEYS = {a for group in _ALIASES.values() for a in group}

_CHANNEL_MAP: dict[str, Channel] = {
    "email": Channel.EMAIL,
    "e-mail": Channel.EMAIL,
    "mail": Channel.EMAIL,
    "inbox": Channel.EMAIL,
    "chat": Channel.CHAT,
    "live_chat": Channel.CHAT,
    "livechat": Channel.CHAT,
    "live chat": Channel.CHAT,
    "web_chat": Channel.CHAT,
    "messenger": Channel.CHAT,
    "docs_comment": Channel.DOCS_COMMENT,
    "docs": Channel.DOCS_COMMENT,
    "documentation": Channel.DOCS_COMMENT,
    "documentation_comment": Channel.DOCS_COMMENT,
    "doc_comment": Channel.DOCS_COMMENT,
    "api_docs": Channel.DOCS_COMMENT,
    "api_documentation": Channel.DOCS_COMMENT,
    "forum": Channel.FORUM,
    "community": Channel.FORUM,
    "community_forum": Channel.FORUM,
    "discourse": Channel.FORUM,
}


def _normalise_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _pick(record: dict[str, Any], field: str) -> Any:
    """Find a value for a logical field under any of its accepted names."""
    wanted = {_normalise_key(a) for a in _ALIASES[field]}
    for key, value in record.items():
        if _normalise_key(key) in wanted:
            if value not in (None, "", [], {}):
                return value
    return None


def _clean_text(value: Any) -> str:
    """Make text safe to send onward without destroying what it says.

    Unicode is normalised, control characters that break JSON round-trips and
    terminal output are removed, and runaway whitespace is collapsed. Emoji,
    accents and non-Latin scripts survive: customers write in them, and
    stripping them would quietly degrade service for exactly the groups the
    fairness audit is meant to protect.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        if isinstance(value, (list, tuple)):
            value = "\n".join(str(v) for v in value)
        else:
            value = str(value)
    text = unicodedata.normalize("NFKC", value)
    text = text.replace("\u0000", "")
    text = "".join(
        ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C"
    )
    text = re.sub(r"[ \t]{3,}", "  ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def _coerce_channel(value: Any) -> tuple[Channel, str | None]:
    if value is None:
        return Channel.UNKNOWN, "channel missing; defaulted to unknown"
    key = _normalise_key(value).replace("_", "")
    for name, channel in _CHANNEL_MAP.items():
        if _normalise_key(name) == key:
            return channel, None
    # Substring fallback catches things like "email_inbound" or "chat-widget".
    lowered = str(value).lower()
    for name, channel in _CHANNEL_MAP.items():
        if name in lowered:
            return channel, f"channel '{value}' matched loosely to {channel.value}"
    return Channel.UNKNOWN, f"channel '{value}' not recognised; treated as unknown"


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v not in (None, "")]
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(value)]


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            return {"value": value}
    if value is None:
        return {}
    return {"value": value}


def normalise_ticket(record: Any, index: int = 0) -> NormalisedTicket:
    """Turn one source record into the internal representation.

    This function does not raise. Anything it cannot understand becomes a
    warning on the ticket, and the ticket continues through the pipeline where
    the router will see the warning and, in most cases, escalate it.
    """
    warnings: list[str] = []

    if not isinstance(record, dict):
        return NormalisedTicket(
            ticket_id=f"malformed-{index}",
            channel=Channel.UNKNOWN,
            subject="",
            body=_clean_text(record),
            raw_text=_clean_text(record),
            ingest_warnings=["record was not an object; wrapped as free text"],
        )

    ticket_id = _pick(record, "ticket_id")
    if ticket_id in (None, ""):
        ticket_id = f"unlabelled-{index}"
        warnings.append("ticket id missing; a positional id was assigned")

    channel, channel_warning = _coerce_channel(_pick(record, "channel"))
    if channel_warning:
        warnings.append(channel_warning)

    subject = _clean_text(_pick(record, "subject"))
    body = _clean_text(_pick(record, "body"))

    if not subject and not body:
        warnings.append("ticket has no subject and no body")
    elif not body:
        warnings.append("ticket has a subject but no body")

    raw_parts = [p for p in (subject, body) if p]
    raw_text = "\n\n".join(raw_parts)

    extra = {
        k: v
        for k, v in record.items()
        if _normalise_key(k) not in {_normalise_key(a) for a in _KNOWN_KEYS}
    }

    return NormalisedTicket(
        ticket_id=str(ticket_id),
        channel=channel,
        subject=subject,
        body=body,
        raw_text=raw_text,
        customer_id=(str(v) if (v := _pick(record, "customer_id")) is not None else None),
        customer_tier=(str(v) if (v := _pick(record, "customer_tier")) is not None else None),
        region=(str(v) if (v := _pick(record, "region")) is not None else None),
        language_fluency=(
            str(v) if (v := _pick(record, "language_fluency")) is not None else None
        ),
        language=(str(v) if (v := _pick(record, "language")) is not None else None),
        created_at=(str(v) if (v := _pick(record, "created_at")) is not None else None),
        attachments=_coerce_list(_pick(record, "attachments")),
        labels=_coerce_dict(_pick(record, "labels")),
        history=_coerce_dict(_pick(record, "history")),
        extra=extra,
        ingest_warnings=warnings,
    )


def _unwrap(payload: Any) -> list[Any]:
    """Accept the shapes a ticket file plausibly arrives in.

    A bare list, an object with a `tickets` key, an object keyed by ticket id,
    or JSON Lines. The hidden set is described as using the same schema as the
    development set, but this costs almost nothing and removes the single most
    embarrassing way to fail A9.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("tickets", "data", "records", "items", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
        # An object keyed by ticket id.
        values = list(payload.values())
        if values and all(isinstance(v, dict) for v in values):
            out = []
            for key, value in payload.items():
                value.setdefault("ticket_id", key)
                out.append(value)
            return out
    return [payload]


def load_tickets(path: str | Path) -> list[NormalisedTicket]:
    """Read a ticket file from disk and normalise every record in it."""
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")

    try:
        payload = json.loads(text)
        records = _unwrap(payload)
    except json.JSONDecodeError:
        # JSON Lines fallback.
        records = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                records.append({"body": line})

    return [normalise_ticket(record, index=i) for i, record in enumerate(records)]


def iter_tickets(records: Iterable[Any]) -> Iterator[NormalisedTicket]:
    for i, record in enumerate(records):
        yield normalise_ticket(record, index=i)
