"""The intent taxonomy.

The categories are not invented. They are derived from the labels present in
the development set by `python -m scripts.build_taxonomy`, written to
storage/taxonomy.json, and read from there at runtime.

This matters more than it looks. A classifier whose categories do not match
the labels in the evaluation data cannot score above zero on precision and
recall no matter how well it reasons, and hardcoding a plausible-looking list
is the way that failure happens. The fallback list below is used only when no
taxonomy file exists, so that the system still runs on a machine where the
development data is absent.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .config import get_settings

log = logging.getLogger(__name__)

FALLBACK_INTENTS: dict[str, str] = {
    "technical_issue": "something is broken, erroring or behaving unexpectedly",
    "how_to": "the customer wants to know how to do something with the product",
    "account_access": "login, permissions, API keys, SSO or user management",
    "billing_question": "an enquiry about charges, invoices, plans or usage limits",
    "billing_dispute": "the customer disputes a charge or wants money back",
    "feature_request": "the customer wants something the product does not do",
    "integration": "connecting CloudServe to another system or tool",
    "performance": "the product is slow, throttled or hitting limits",
    "security_incident": "a suspected breach, exposed credential or vulnerability",
    "data_loss": "data is missing, corrupted or deleted",
    "cancellation": "the customer intends to downgrade, cancel or not renew",
    "complaint": "dissatisfaction with the service or with support itself",
    "documentation": "the documentation is wrong, unclear or incomplete",
    "other": "does not fit any category above",
}

URGENCIES = ["low", "medium", "high", "critical"]


def _taxonomy_path() -> Path:
    """Where the taxonomy is written by scripts/build_taxonomy.py."""
    return get_settings().paths.storage_dir / "taxonomy.json"


def _taxonomy_source() -> Path:
    """Where to READ the taxonomy from.

    `storage/` first, because that is where a fresh fit lands. Then
    `fitted/`, which is committed to the repository.

    That second location matters more than it looks. `storage/` is
    gitignored, so on a clean checkout it is empty — and an assessor
    following the README is not going to run the fitting scripts first.
    Without this fallback the system silently classifies into the built-in
    placeholder categories instead of the 22 the data is labelled with, which
    does not crash, does not warn loudly enough, and scores near zero on
    precision. It happened on the first live run.
    """
    path = _taxonomy_path()
    if path.exists():
        return path
    return get_settings().paths.root / "fitted" / "taxonomy.json"


def load_taxonomy() -> dict[str, str]:
    path = _taxonomy_source()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            intents = data.get("intents")
            if isinstance(intents, dict) and intents:
                return intents
            if isinstance(intents, list) and intents:
                return {i: "" for i in intents}
        except Exception as exc:  # pragma: no cover
            log.warning("taxonomy file unreadable (%s); using fallback", exc)
    log.warning(
        "NO TAXONOMY FILE FOUND (looked in storage/ and fitted/). Falling back "
        "to %d placeholder categories, which will NOT match the labels in the "
        "evaluation data and will score near zero on intent precision. "
        "Run: python -m scripts.build_taxonomy",
        len(FALLBACK_INTENTS),
    )
    return dict(FALLBACK_INTENTS)


def save_taxonomy(intents: dict[str, str], source: str) -> Path:
    path = _taxonomy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"intents": intents, "derived_from": source}, indent=2),
        encoding="utf-8",
    )
    return path


def intent_list_for_prompt(intents: dict[str, str] | None = None) -> str:
    intents = intents or load_taxonomy()
    return "\n".join(
        f"- {name}: {desc}" if desc else f"- {name}" for name, desc in intents.items()
    )


def canonicalise_intent(value: Any, intents: dict[str, str] | None = None) -> str:
    """Map whatever the model said onto a category that exists.

    Models return `billing` when the category is `billing_question`, and
    `Technical Issue` when it is `technical_issue`. Silently dropping those to
    `other` would understate the classifier badly.
    """
    intents = intents or load_taxonomy()
    if value is None:
        return "other" if "other" in intents else next(iter(intents))

    raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if raw in intents:
        return raw

    squashed = raw.replace("_", "")
    for name in intents:
        if name.replace("_", "") == squashed:
            return name
    # Prefix match: `billing` -> `billing_question`.
    candidates = [n for n in intents if n.startswith(raw) or raw.startswith(n)]
    if candidates:
        return sorted(candidates, key=len)[0]
    # Containment, longest match wins.
    candidates = [n for n in intents if raw in n or n in raw]
    if candidates:
        return sorted(candidates, key=len, reverse=True)[0]
    return "other" if "other" in intents else next(iter(intents))


def canonicalise_urgency(value: Any) -> str:
    if value is None:
        return "medium"
    raw = str(value).strip().lower()
    if raw in URGENCIES:
        return raw
    mapping = {
        "p0": "critical", "p1": "high", "p2": "medium", "p3": "low",
        "urgent": "critical", "severe": "critical", "blocker": "critical",
        "important": "high", "normal": "medium", "standard": "medium",
        "minor": "low", "trivial": "low", "1": "low", "2": "medium",
        "3": "high", "4": "critical",
    }
    return mapping.get(raw, "medium")
