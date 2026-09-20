"""Fit the confidence calibration mapping on the development set.

    python -m scripts.fit_calibration --input data/development_tickets.json --sample 200

The governance condition is that stated confidence lands within five
percentage points of observed accuracy. A model's own stated confidence does
not; this fits the mapping that makes it do so, and prints the before and
after so the report can quote both.

This runs the classifier over labelled tickets, which costs model calls. The
cache means running it twice costs nothing the second time, and --sample keeps
the first run inside a free tier.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.metrics import label  # noqa: E402
from src import calibration as calib  # noqa: E402
from src.classify import Classifier  # noqa: E402
from src.ingest import load_tickets  # noqa: E402
from src.taxonomy import canonicalise_intent  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("fit_calibration")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fit confidence calibration.")
    parser.add_argument("--input", type=Path, default=Path("data/development_tickets.json"))
    parser.add_argument(
        "--sample",
        type=int,
        default=200,
        help="How many labelled tickets to classify. 150-250 is enough for a "
        "ten-bin reliability curve and stays inside a free tier.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Sampling seed, for reproducibility.")
    parser.add_argument("--bins", type=int, default=10)
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"no such file: {args.input}", file=sys.stderr)
        return 2

    tickets = [t for t in load_tickets(args.input) if label(t, "intent")]
    if len(tickets) < 30:
        print(
            f"only {len(tickets)} labelled tickets found; calibration below 30 samples "
            "is noise. Leaving the system uncalibrated, which it reports honestly.",
            file=sys.stderr,
        )
        return 1

    random.seed(args.seed)
    sample = random.sample(tickets, min(args.sample, len(tickets)))
    log.info("classifying %d tickets (cached calls are free)", len(sample))

    # Fit on raw model confidence, not on the shrunk value, so the mapping is
    # independent of whether a previous calibration file existed.
    classifier = Classifier()
    classifier.calibrator = None

    confidences: list[float] = []
    correct: list[bool] = []
    fallbacks = 0

    for i, ticket in enumerate(sample, start=1):
        result = classifier.classify(ticket)
        if result.method.startswith("rules_fallback"):
            fallbacks += 1
            continue
        raw = result.raw_confidence if result.raw_confidence is not None else result.confidence
        confidences.append(float(raw))
        correct.append(canonicalise_intent(label(ticket, "intent")) == result.intent)
        if i % 25 == 0:
            log.info("  %d/%d", i, len(sample))

    if fallbacks:
        log.warning(
            "%d ticket(s) fell back to the rule classifier (provider unavailable) and "
            "were excluded from the fit",
            fallbacks,
        )

    if len(confidences) < 30:
        print(
            f"only {len(confidences)} usable classifications; not fitting. "
            "Check the model provider is reachable.",
            file=sys.stderr,
        )
        return 1

    calibrator = calib.fit(
        confidences, correct, bins=args.bins, fitted_on=f"{args.input.name} (n={len(confidences)})"
    )
    path = calib.save(calibrator)

    accuracy = sum(correct) / len(correct)
    print()
    print(f"fitted on {len(confidences)} classifications from {args.input.name}")
    print(f"observed accuracy:            {accuracy:.3f}")
    print(f"mean stated confidence:       {sum(confidences) / len(confidences):.3f}")
    print(f"expected calibration error:   {calibrator.ece_before:.4f}  (before)")
    print(f"                              {calibrator.ece_after:.4f}  (after)")
    print(f"condition (<= 0.05):          {'MET' if calibrator.ece_after <= 0.05 else 'NOT MET'}")
    print(f"written to {path}")
    print()
    print("reliability curve:")
    print("  raw confidence -> calibrated")
    for bp, value in zip(calibrator.breakpoints, calibrator.values):
        print(f"  {bp:.1f}-{bp + 1 / args.bins:.1f}        -> {value:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
