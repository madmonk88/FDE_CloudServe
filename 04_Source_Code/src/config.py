"""Central configuration.

Every tunable number in this system lives here rather than being scattered
through the code, because each one has to be defended in the report and a
number you cannot find is a number you cannot justify.

Values are read from the environment (see .env.example) and fall back to the
defaults below, which are the values determined from the development set.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # pragma: no cover - convenience only
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value == "" else value


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True)
class ModelSettings:
    """Model provider access.

    The provider is deliberately behind an interface. The brief names
    OpenRouter and Groq; both are OpenAI-compatible, so one client covers
    either, and swapping is an environment variable rather than a code change.
    """

    provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "groq"))
    # Either key name works. The pack's own template uses OPENROUTER_API_KEY,
    # so that name is kept for compatibility, but GROQ_API_KEY is accepted
    # too because writing a Groq key into a variable called OPENROUTER_ is
    # the kind of small confusion that wastes an evening.
    api_key: str = field(
        default_factory=lambda: _env("GROQ_API_KEY", "") or _env("OPENROUTER_API_KEY", "")
    )
    base_url: str = field(
        default_factory=lambda: _env("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    )
    model: str = field(
        default_factory=lambda: _env("LLM_MODEL", "llama-3.3-70b-versatile")
    )
    # Temperature zero is not a style choice. Acceptance criterion A5 requires
    # the same input to produce the same routing decision, and a non-zero
    # temperature makes that impossible to guarantee.
    temperature: float = field(default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.0))
    max_tokens: int = field(default_factory=lambda: _env_int("LLM_MAX_TOKENS", 900))
    timeout_seconds: float = field(default_factory=lambda: _env_float("LLM_TIMEOUT", 45.0))
    max_retries: int = field(default_factory=lambda: _env_int("LLM_MAX_RETRIES", 4))
    # Free tiers throttle. This is the ceiling we impose on ourselves so that
    # the provider does not have to impose it on us mid-run.
    requests_per_minute: int = field(default_factory=lambda: _env_int("LLM_RPM", 20))
    # After this many consecutive failures the circuit opens and the system
    # runs on its deterministic fallback path until the cooldown expires.
    circuit_breaker_threshold: int = field(
        default_factory=lambda: _env_int("LLM_CIRCUIT_THRESHOLD", 5)
    )
    circuit_breaker_cooldown: float = field(
        default_factory=lambda: _env_float("LLM_CIRCUIT_COOLDOWN", 60.0)
    )
    cache_enabled: bool = field(default_factory=lambda: _env_bool("LLM_CACHE", True))


@dataclass(frozen=True)
class RetrievalSettings:
    """Retrieval behaviour.

    `min_score` is the value below which we return nothing at all. The brief is
    explicit that returning something irrelevant is worse than returning
    nothing, so this threshold is the mechanism that enforces it. It was set
    from the development set: see scripts/tune_thresholds.py.
    """

    top_k: int = field(default_factory=lambda: _env_int("RETRIEVAL_TOP_K", 5))
    # On the corrected cosine scale an unrelated passage scores about 0.06
    # and a good match about 0.35. Tuned against the answerable_from_docs
    # label by scripts/tune_retrieval_floor.py.
    min_score: float = field(default_factory=lambda: _env_float("RETRIEVAL_MIN_SCORE", 0.18))
    chunk_target_chars: int = field(
        default_factory=lambda: _env_int("RETRIEVAL_CHUNK_CHARS", 900)
    )
    chunk_overlap_chars: int = field(
        default_factory=lambda: _env_int("RETRIEVAL_CHUNK_OVERLAP", 150)
    )
    embedding_model: str = field(
        default_factory=lambda: _env("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    )
    # Dense and lexical scores are combined. Dense retrieval handles paraphrase;
    # lexical retrieval handles the error codes and flag names that customers
    # quote verbatim and that embeddings routinely wash out.
    hybrid_dense_weight: float = field(
        default_factory=lambda: _env_float("RETRIEVAL_DENSE_WEIGHT", 0.65)
    )
    # BM25 score at which a passage counts as half relevant, used by the
    # saturating transform that keeps lexical scores absolute rather than
    # relative to the best result for that query. Set to the median best-match
    # score observed on the development set.
    lexical_saturation: float = field(
        default_factory=lambda: _env_float("RETRIEVAL_LEXICAL_SATURATION", 16.0)
    )
    index_dir: Path = field(default_factory=lambda: Path(_env("INDEX_DIR", str(ROOT / "storage" / "chroma"))))


@dataclass(frozen=True)
class RoutingSettings:
    """The routing policy.

    The brief says the thresholds are "yours to set and yours to defend". The
    defence offered here is that most of this policy was not set at all — it
    was recovered from CloudServe's own labelled data, and it reproduces
    `expected_route` on 500 of 500 development tickets and 80 of 80 validation
    tickets. See `src/route.py` and `python -m scripts.derive_policy`.

    Only two values below are genuinely chosen rather than recovered, and both
    are tuned against the development set:
    `answerable_threshold` and `min_classification_confidence`.
    """

    # The single most consequential number in the system. Above this score,
    # the documentation is treated as able to answer the ticket; below it, the
    # ticket escalates and is recorded as a documentation gap. Tuned against
    # the `answerable_from_docs` label:
    #   python -m scripts.tune_answerability
    answerable_threshold: float = field(
        default_factory=lambda: _env_float("ROUTE_ANSWERABLE_THRESHOLD", 0.58)
    )
    # Confidence in the intent classification below which we do not trust our
    # own understanding well enough to apply the policy. The policy's rules
    # key on intent, so an uncertain intent makes every rule below unreliable.
    min_classification_confidence: float = field(
        default_factory=lambda: _env_float("ROUTE_MIN_CLASS_CONF", 0.55)
    )
    # Grounding of the drafted answer in the retrieved passages.
    min_grounding: float = field(
        default_factory=lambda: _env_float("ROUTE_MIN_GROUNDING", 0.60)
    )

    # -- Recovered from the data, not chosen -------------------------------
    # Four intents carry `must_not_auto_respond` on 100% of their development
    # tickets and are labelled escalate without exception. CloudServe has, in
    # effect, already told us these never automate.
    never_automate_intents: tuple[str, ...] = (
        "compliance_request",
        "security_incident",
        "feature_request",
        "unclear_request",
    )
    # Two further intents escalate, but only at high urgency. At lower
    # urgency the documentation handles them and the labels say so.
    high_risk_intents: tuple[str, ...] = (
        "database_issue",
        "performance_degradation",
    )
    high_risk_urgency: tuple[str, ...] = ("high", "critical")


@dataclass(frozen=True)
class GuardrailSettings:
    """What the system must never do, and the mechanism that enforces it."""

    block_on_pii: bool = field(default_factory=lambda: _env_bool("GUARD_BLOCK_PII", True))
    block_on_unsupported: bool = field(
        default_factory=lambda: _env_bool("GUARD_BLOCK_UNSUPPORTED", True)
    )
    block_on_prohibited_commitment: bool = field(
        default_factory=lambda: _env_bool("GUARD_BLOCK_COMMITMENT", True)
    )
    # A sentence whose best support in the retrieved passages falls below this
    # is treated as unsupported.
    sentence_support_threshold: float = field(
        default_factory=lambda: _env_float("GUARD_SENTENCE_SUPPORT", 0.38)
    )
    # Proportion of substantive sentences that must be supported.
    min_supported_ratio: float = field(
        default_factory=lambda: _env_float("GUARD_MIN_SUPPORTED_RATIO", 0.70)
    )


@dataclass(frozen=True)
class Paths:
    root: Path = ROOT
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(ROOT / "data"))))
    storage_dir: Path = field(
        default_factory=lambda: Path(_env("STORAGE_DIR", str(ROOT / "storage")))
    )
    decision_log_db: Path = field(
        default_factory=lambda: Path(
            _env("DECISION_LOG_DB", str(ROOT / "storage" / "decisions.sqlite3"))
        )
    )
    llm_cache_dir: Path = field(
        default_factory=lambda: Path(
            _env("LLM_CACHE_DIR", str(ROOT / "storage" / "llm_cache"))
        )
    )
    calibration_file: Path = field(
        default_factory=lambda: Path(
            _env("CALIBRATION_FILE", str(ROOT / "storage" / "calibration.json"))
        )
    )
    documentation_file: Path = field(
        default_factory=lambda: Path(
            _env("DOCUMENTATION_FILE", str(ROOT / "data" / "documentation.json"))
        )
    )

    def ensure(self) -> None:
        for p in (self.storage_dir, self.llm_cache_dir, self.storage_dir / "chroma"):
            p.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Settings:
    model: ModelSettings = field(default_factory=ModelSettings)
    retrieval: RetrievalSettings = field(default_factory=RetrievalSettings)
    routing: RoutingSettings = field(default_factory=RoutingSettings)
    guardrails: GuardrailSettings = field(default_factory=GuardrailSettings)
    paths: Paths = field(default_factory=Paths)
    # Set by the harness so that every decision row can be traced to a run.
    run_id: str = field(default_factory=lambda: _env("RUN_ID", "adhoc"))


_settings: Settings | None = None


def get_settings(refresh: bool = False) -> Settings:
    global _settings
    if _settings is None or refresh:
        _settings = Settings()
        _settings.paths.ensure()
    return _settings
