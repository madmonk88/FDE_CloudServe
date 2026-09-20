"""Confidence calibration.

The governance conditions in the brief include this one: *stated confidence
within five percentage points of observed accuracy*. It is a condition rather
than a target — it either holds or it does not.

A language model asked how confident it is will say 0.9 about nearly
everything. Its stated confidence is a stylistic property of the text, not a
probability, and a system that reports it unmodified will fail this condition
while looking perfectly reasonable.

The fix is a reliability mapping fitted on the development set. Raw
confidences are placed in bins, the actual accuracy within each bin is
measured, and a monotone (isotonic) mapping from raw to calibrated confidence
is fitted using pool-adjacent-violators. At serving time the raw confidence is
looked up in that mapping.

`python -m scripts.fit_calibration` produces the file. If it is absent, the
system applies a documented conservative shrinkage instead and records in
every decision that the confidence was uncalibrated, so the report can say so
rather than quietly overclaiming.
"""

from __future__ import annotations

import json
import logging
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .config import get_settings

log = logging.getLogger(__name__)


def _pav(x: Sequence[float], y: Sequence[float], w: Sequence[float]) -> list[float]:
    """Pool adjacent violators: the smallest change to y that makes it
    monotonically non-decreasing, weighted by bin size."""
    values = list(y)
    weights = list(w)
    indices = list(range(len(values)))
    i = 0
    while i < len(values) - 1:
        if values[i] <= values[i + 1]:
            i += 1
            continue
        total_w = weights[i] + weights[i + 1]
        pooled = (values[i] * weights[i] + values[i + 1] * weights[i + 1]) / total_w
        values[i] = pooled
        weights[i] = total_w
        del values[i + 1]
        del weights[i + 1]
        del indices[i + 1]
        if i > 0:
            i -= 1
    # Expand back to the original length.
    out: list[float] = []
    pos = 0
    for k in range(len(x)):
        if pos + 1 < len(indices) and k >= indices[pos + 1]:
            pos += 1
        out.append(values[pos])
    return out


@dataclass
class Calibrator:
    """A fitted raw-confidence -> calibrated-confidence mapping."""

    breakpoints: list[float]
    values: list[float]
    n_samples: int
    fitted_on: str
    ece_before: float
    ece_after: float

    def apply(self, raw: float) -> float:
        if not self.breakpoints:
            return raw
        raw = min(1.0, max(0.0, float(raw)))
        i = bisect_right(self.breakpoints, raw) - 1
        i = min(max(i, 0), len(self.values) - 1)
        return round(min(1.0, max(0.0, self.values[i])), 4)

    def to_dict(self) -> dict:
        return {
            "breakpoints": self.breakpoints,
            "values": self.values,
            "n_samples": self.n_samples,
            "fitted_on": self.fitted_on,
            "ece_before": self.ece_before,
            "ece_after": self.ece_after,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Calibrator":
        return cls(
            breakpoints=list(d.get("breakpoints", [])),
            values=list(d.get("values", [])),
            n_samples=int(d.get("n_samples", 0)),
            fitted_on=str(d.get("fitted_on", "unknown")),
            ece_before=float(d.get("ece_before", 0.0)),
            ece_after=float(d.get("ece_after", 0.0)),
        )


def expected_calibration_error(
    confidences: Sequence[float], correct: Sequence[bool], bins: int = 10
) -> float:
    """Mean absolute gap between stated confidence and observed accuracy,
    weighted by bin population. This is the number the governance condition
    is really asking about: it must come out below 0.05."""
    if not confidences:
        return 0.0
    total = len(confidences)
    error = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [
            i
            for i, c in enumerate(confidences)
            if (c >= lo and c < hi) or (b == bins - 1 and c == 1.0)
        ]
        if not idx:
            continue
        avg_conf = sum(confidences[i] for i in idx) / len(idx)
        accuracy = sum(1 for i in idx if correct[i]) / len(idx)
        error += (len(idx) / total) * abs(avg_conf - accuracy)
    return round(error, 4)


def fit(
    confidences: Sequence[float],
    correct: Sequence[bool],
    *,
    bins: int = 10,
    fitted_on: str = "development set",
) -> Calibrator:
    if len(confidences) != len(correct):
        raise ValueError("confidences and correct must be the same length")
    if len(confidences) < 30:
        raise ValueError(
            f"only {len(confidences)} samples; calibration below 30 is noise"
        )

    ece_before = expected_calibration_error(confidences, correct, bins)

    breakpoints: list[float] = []
    observed: list[float] = []
    weights: list[float] = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [
            i
            for i, c in enumerate(confidences)
            if (c >= lo and c < hi) or (b == bins - 1 and c == 1.0)
        ]
        if not idx:
            continue
        breakpoints.append(lo)
        observed.append(sum(1 for i in idx if correct[i]) / len(idx))
        weights.append(float(len(idx)))

    values = _pav(breakpoints, observed, weights) if breakpoints else []

    calibrated = []
    tmp = Calibrator(breakpoints, values, len(confidences), fitted_on, ece_before, 0.0)
    for c in confidences:
        calibrated.append(tmp.apply(c))
    ece_after = expected_calibration_error(calibrated, correct, bins)

    log.info(
        "calibration fitted on %d samples: ECE %.4f -> %.4f",
        len(confidences),
        ece_before,
        ece_after,
    )
    return Calibrator(breakpoints, values, len(confidences), fitted_on, ece_before, ece_after)


def save(calibrator: Calibrator, path: Path | None = None) -> Path:
    path = Path(path or get_settings().paths.calibration_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calibrator.to_dict(), indent=2), encoding="utf-8")
    return path


def load(path: Path | None = None) -> Calibrator | None:
    settings = get_settings()
    path = Path(path or settings.paths.calibration_file)
    if not path.exists():
        # Committed fallback, for a clean checkout where storage/ is empty.
        path = settings.paths.root / "fitted" / "calibration.json"
    if not path.exists():
        return None
    try:
        return Calibrator.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:  # pragma: no cover
        log.warning("calibration file unreadable (%s); running uncalibrated", exc)
        return None


# The shrinkage applied when no calibration file exists. It pulls stated
# confidence towards the base rate rather than trusting it, which is the
# conservative direction: it causes more escalation, not more wrong answers.
UNCALIBRATED_SHRINKAGE = 0.80
UNCALIBRATED_CEILING = 0.85


def apply_uncalibrated(raw: float) -> float:
    return round(min(UNCALIBRATED_CEILING, float(raw) * UNCALIBRATED_SHRINKAGE), 4)
