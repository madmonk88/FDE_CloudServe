"""Predicting whether the documentation can answer a ticket.

This is the hinge of the whole system, and it deserves explaining.

The routing policy recovered from CloudServe's labelled data (see
`src/route.py`) has three inputs. Two of them — intent and urgency — the
classifier predicts. The third is `answerable_from_docs`, and it decides more
routing outcomes than the other two combined: every ticket in the development
set that the documentation cannot answer is labelled escalate, without a
single exception.

It is also a label that exists only during development. At serving time the
system has to predict it, and how well it predicts it sets the ceiling on
routing accuracy.

**The obvious approach does not work well enough.** The natural instinct is to
threshold the retrieval score: if nothing scores highly, the corpus cannot
answer the question. Measured on the development set, the top retrieval score
separates answerable from unanswerable tickets with an AUC of about 0.58 using
lexical retrieval alone — barely better than a coin toss. The reason is
visible once you look at which tickets are unanswerable: a feature request or
an unclear message is not unanswerable because the corpus lacks the topic. It
is unanswerable because *no documentation could answer it*. Retrieval happily
finds topically related passages for both.

**The intent carries most of the signal.** The probability that a ticket is
answerable varies enormously by category — from 0.05 for feature requests to
0.92 for API usage questions — and intent alone reaches an AUC of about 0.76.

So the predictor here combines both, as a logistic model over two features:
the intent's historical answerable rate, and the best retrieval score. The
weights are fitted on the development set rather than chosen, which means the
model discovers how much to trust retrieval rather than being told. That
matters practically: with lexical-only retrieval it leans on the prior, and
when dense embeddings are available the retrieval term earns more weight
automatically, with no code change.

The output is a probability, which is what makes the cost-based threshold
sweep in `scripts/tune_answerability.py` meaningful — a threshold on a
calibrated probability has an interpretation, and a threshold on a raw
similarity score does not.

Fit it with `python -m scripts.fit_answerability`.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .config import get_settings

log = logging.getLogger(__name__)


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


@dataclass
class AnswerabilityModel:
    """Intent priors plus a two-feature logistic model."""

    intent_prior: dict[str, float] = field(default_factory=dict)
    base_rate: float = 0.7
    # weights for [logit(prior), retrieval score] and the bias
    w_prior: float = 1.0
    w_score: float = 0.0
    bias: float = 0.0
    fitted_on: str = "not fitted"
    n_samples: int = 0
    dense_available: bool = False
    auc: float | None = None

    # -- prediction --------------------------------------------------------

    def prior_for(self, intent: str | None) -> float:
        """The historical answerable rate for this intent.

        An unseen intent falls back to the overall base rate rather than to
        zero or one, because an unfamiliar category is a reason for
        uncertainty, not for confidence in either direction.
        """
        if not intent:
            return self.base_rate
        return self.intent_prior.get(intent, self.base_rate)

    def probability(self, intent: str | None, top_score: float) -> float:
        z = (
            self.bias
            + self.w_prior * _logit(self.prior_for(intent))
            + self.w_score * float(top_score)
        )
        return round(_sigmoid(z), 4)

    # -- persistence -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_prior": self.intent_prior,
            "base_rate": self.base_rate,
            "w_prior": self.w_prior,
            "w_score": self.w_score,
            "bias": self.bias,
            "fitted_on": self.fitted_on,
            "n_samples": self.n_samples,
            "dense_available": self.dense_available,
            "auc": self.auc,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AnswerabilityModel":
        return cls(
            intent_prior=dict(d.get("intent_prior", {})),
            base_rate=float(d.get("base_rate", 0.7)),
            w_prior=float(d.get("w_prior", 1.0)),
            w_score=float(d.get("w_score", 0.0)),
            bias=float(d.get("bias", 0.0)),
            fitted_on=str(d.get("fitted_on", "unknown")),
            n_samples=int(d.get("n_samples", 0)),
            dense_available=bool(d.get("dense_available", False)),
            auc=d.get("auc"),
        )


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------


def auc_score(scores: Sequence[float], labels: Sequence[bool]) -> float:
    """Area under the ROC curve, computed by rank rather than by sampling."""
    pairs = sorted(zip(scores, labels))
    n_pos = sum(1 for _, y in pairs if y)
    n_neg = len(pairs) - n_pos
    if not n_pos or not n_neg:
        return 0.5
    # Average ranks, so ties contribute 0.5 as they should.
    ranks: list[float] = [0.0] * len(pairs)
    i = 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[k] = average
        i = j + 1
    rank_sum = sum(r for r, (_, y) in zip(ranks, pairs) if y)
    return round((rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg), 4)


def fit(
    intents: Sequence[str | None],
    scores: Sequence[float],
    answerable: Sequence[bool],
    *,
    fitted_on: str = "development set",
    dense_available: bool = False,
    epochs: int = 4000,
    learning_rate: float = 0.08,
    l2: float = 0.01,
) -> AnswerabilityModel:
    """Fit intent priors and the logistic blend.

    Plain gradient descent on two features. There is no scikit-learn
    dependency for the same reason the BM25 implementation is local: a
    dependency that can fail to install on the assessing machine is a risk
    taken for very little, and this model has two weights.
    """
    if len(intents) != len(scores) != len(answerable):
        raise ValueError("inputs must be the same length")
    if len(intents) < 50:
        raise ValueError(f"only {len(intents)} samples; too few to fit")

    base_rate = sum(1 for a in answerable if a) / len(answerable)

    # Laplace-smoothed per-intent rates. Smoothing matters: a category with
    # four examples, all answerable, is not evidence of a rate of 1.0, and an
    # unsmoothed prior would drive the logit to infinity.
    counts: dict[str, list[int]] = {}
    for intent, a in zip(intents, answerable):
        key = intent or "__unknown__"
        row = counts.setdefault(key, [0, 0])
        row[0] += int(bool(a))
        row[1] += 1
    intent_prior = {k: (v[0] + 1) / (v[1] + 2) for k, v in counts.items()}

    features = [
        (_logit(intent_prior.get(i or "__unknown__", base_rate)), float(s))
        for i, s in zip(intents, scores)
    ]
    targets = [1.0 if a else 0.0 for a in answerable]
    n = len(targets)

    w_prior, w_score, bias = 1.0, 0.0, 0.0
    for _ in range(epochs):
        g_prior = g_score = g_bias = 0.0
        for (f_prior, f_score), y in zip(features, targets):
            error = _sigmoid(bias + w_prior * f_prior + w_score * f_score) - y
            g_prior += error * f_prior
            g_score += error * f_score
            g_bias += error
        w_prior -= learning_rate * (g_prior / n + l2 * w_prior)
        w_score -= learning_rate * (g_score / n + l2 * w_score)
        bias -= learning_rate * (g_bias / n)

    model = AnswerabilityModel(
        intent_prior=intent_prior,
        base_rate=round(base_rate, 4),
        w_prior=round(w_prior, 5),
        w_score=round(w_score, 5),
        bias=round(bias, 5),
        fitted_on=fitted_on,
        n_samples=n,
        dense_available=dense_available,
    )
    model.auc = auc_score(
        [model.probability(i, s) for i, s in zip(intents, scores)], answerable
    )
    log.info(
        "answerability model fitted on %d samples: AUC %.3f "
        "(w_prior %.3f, w_score %.3f)",
        n,
        model.auc,
        model.w_prior,
        model.w_score,
    )
    return model


def save(model: AnswerabilityModel, path: Path | None = None) -> Path:
    path = Path(path or get_settings().paths.storage_dir / "answerability.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model.to_dict(), indent=2), encoding="utf-8")
    return path


def load(path: Path | None = None) -> AnswerabilityModel | None:
    settings = get_settings()
    path = Path(path or settings.paths.storage_dir / "answerability.json")
    if not path.exists():
        # Committed fallback, for a clean checkout where storage/ is empty.
        path = settings.paths.root / "fitted" / "answerability.json"
    if not path.exists():
        return None
    try:
        return AnswerabilityModel.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:  # pragma: no cover
        log.warning("answerability model unreadable (%s); falling back to score only", exc)
        return None


_model: AnswerabilityModel | None = None
_loaded = False


def get_model() -> AnswerabilityModel | None:
    global _model, _loaded
    if not _loaded:
        _model = load()
        _loaded = True
        if _model is None:
            log.warning(
                "no answerability model fitted; the router falls back to a raw "
                "retrieval-score threshold, which is a materially weaker predictor. "
                "Run: python -m scripts.fit_answerability"
            )
    return _model


def reset_model() -> None:
    global _model, _loaded
    _model, _loaded = None, False
