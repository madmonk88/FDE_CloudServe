"""Choose the routing threshold from data, and from an explicit cost ratio.

    python -m scripts.tune_thresholds --input data/development_tickets.json

The brief says the thresholds are "yours to set and yours to defend". The
defence offered here is an economic one rather than a statistical one, because
the client's question is not "what maximises F1" but "what does this cost us".

The argument:

A wrong automated answer costs CloudServe a customer who received something
incorrect, an agent who now handles both the complaint and the original
question, and a mark against a satisfaction score that renewal conversations
turn on. An unnecessary escalation costs a few minutes of agent time on a
ticket that could have been deflected.

Those are not equal, and the ratio between them — not an accuracy curve — is
what should decide the threshold. This script sweeps the confidence threshold
across the development set, computes expected cost at each point under a
stated ratio, and reports the minimum. Changing the ratio changes the answer,
which is the point: the number is a business decision made explicitly rather
than an engineering default adopted silently.

The default ratio of 8:1 is a stated assumption, not a measurement. It belongs
in the PRD's assumptions table with a note on what happens if it is wrong, and
the sensitivity table this script prints is the evidence for that note.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.metrics import _as_bool, label  # noqa: E402
from src.classify import Classifier  # noqa: E402
from src.ingest import load_tickets  # noqa: E402
from src.retrieve import get_retriever  # noqa: E402
from src.taxonomy import canonicalise_intent  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("tune")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sweep the routing threshold.")
    parser.add_argument("--input", type=Path, default=Path("data/development_tickets.json"))
    parser.add_argument("--sample", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--cost-ratio",
        type=float,
        default=8.0,
        help="Cost of one wrong automated answer relative to one unnecessary "
        "escalation. The default of 8 is an assumption, not a measurement.",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"no such file: {args.input}", file=sys.stderr)
        return 2

    tickets = [t for t in load_tickets(args.input) if label(t, "intent")]
    random.seed(args.seed)
    sample = random.sample(tickets, min(args.sample, len(tickets)))

    classifier = Classifier()
    retriever = get_retriever()

    log.info("scoring %d tickets", len(sample))
    rows = []
    for i, ticket in enumerate(sample, start=1):
        result = classifier.classify(ticket)
        passages = retriever.search(ticket.text_for_model)
        gold_intent = canonicalise_intent(label(ticket, "intent"))
        answerable = _as_bool(label(ticket, "answerable"))
        rows.append(
            {
                "confidence": result.confidence,
                "correct": result.intent == gold_intent,
                "top_score": passages[0].score if passages else 0.0,
                # A ticket is safe to auto-answer only if we understood it AND
                # the documentation can actually answer it. Where the label is
                # absent we fall back to whether retrieval found anything.
                "answerable": answerable if answerable is not None else bool(passages),
            }
        )
        if i % 25 == 0:
            log.info("  %d/%d", i, len(sample))

    print()
    print(f"cost of a wrong automated answer = {args.cost_ratio:g} x an unnecessary escalation")
    print()
    print("  thresh  automated  correct-auto  wrong-auto  deflection  expected cost")
    print("  " + "-" * 72)

    best = None
    for step in range(0, 21):
        threshold = step / 20.0
        automated = [r for r in rows if r["confidence"] >= threshold and r["answerable"]]
        wrong = sum(1 for r in automated if not r["correct"])
        right = len(automated) - wrong
        escalated_unnecessarily = sum(
            1 for r in rows if r["confidence"] < threshold and r["answerable"] and r["correct"]
        )
        cost = args.cost_ratio * wrong + 1.0 * escalated_unnecessarily
        deflection = len(automated) / len(rows) if rows else 0.0

        marker = ""
        if best is None or cost < best[1]:
            best = (threshold, cost)
            marker = ""
        print(
            f"  {threshold:5.2f}   {len(automated):8d}   {right:11d}   {wrong:9d}   "
            f"{deflection:9.1%}   {cost:12.1f}{marker}"
        )

    print()
    print(f"minimum expected cost at threshold {best[0]:.2f}")
    print()
    print("sensitivity to the cost ratio (the assumption this rests on):")
    print("  ratio   best threshold")
    for ratio in (2.0, 4.0, 6.0, 8.0, 12.0, 20.0):
        cheapest, cheapest_cost = None, None
        for step in range(0, 21):
            threshold = step / 20.0
            automated = [r for r in rows if r["confidence"] >= threshold and r["answerable"]]
            wrong = sum(1 for r in automated if not r["correct"])
            unnecessary = sum(
                1 for r in rows if r["confidence"] < threshold and r["answerable"] and r["correct"]
            )
            cost = ratio * wrong + unnecessary
            if cheapest_cost is None or cost < cheapest_cost:
                cheapest, cheapest_cost = threshold, cost
        print(f"  {ratio:5.0f}   {cheapest:.2f}")

    print()
    print(
        "Set ROUTE_MIN_CLASS_CONF in .env to the chosen value, and record the ratio\n"
        "you assumed and this table in the PRD's assumptions section."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
