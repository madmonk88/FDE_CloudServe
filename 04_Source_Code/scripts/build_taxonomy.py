"""Derive the intent taxonomy from the labels in the development set.

    python -m scripts.build_taxonomy --input data/development_tickets.json

The categories the classifier predicts must be the categories the evaluation
data is labelled with. Inventing a plausible-looking list instead is the
quiet way a classifier scores zero on precision while appearing to work.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.metrics import label  # noqa: E402
from src.ingest import load_tickets  # noqa: E402
from src.taxonomy import FALLBACK_INTENTS, save_taxonomy  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the intent taxonomy from labelled tickets.")
    parser.add_argument("--input", type=Path, default=Path("data/development_tickets.json"))
    parser.add_argument(
        "--min-count",
        type=int,
        default=3,
        help="Categories rarer than this are kept but flagged; they cannot be "
        "measured reliably.",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"no such file: {args.input}", file=sys.stderr)
        return 2

    tickets = load_tickets(args.input)
    counts: Counter[str] = Counter()
    for t in tickets:
        value = label(t, "intent")
        if value:
            counts[str(value).strip().lower().replace(" ", "_").replace("-", "_")] += 1

    if not counts:
        print(
            "No intent labels found in that file. Keeping the fallback taxonomy.\n"
            "Check the labels block field names against the dataset guide.",
            file=sys.stderr,
        )
        return 1

    intents = {}
    for name, count in counts.most_common():
        described = FALLBACK_INTENTS.get(name, "")
        intents[name] = described or f"observed {count} times in the development set"

    path = save_taxonomy(intents, source=str(args.input))

    print(f"{len(intents)} intent categories derived from {len(tickets)} tickets")
    print(f"written to {path}\n")
    for name, count in counts.most_common():
        flag = "  <- too rare to measure reliably" if count < args.min_count else ""
        print(f"  {count:5d}  {name}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
