"""Set the retrieval relevance floor from the data.

    python -m scripts.tune_retrieval_floor

The floor is the score below which retrieval returns *nothing at all*. The
build specification is explicit that returning something plausible but
irrelevant is worse than returning nothing, and it lists "retrieval that
returns something for every query regardless of relevance" under what does
not count as working.

This exists because that failure happened here. The floor had been set by eye
against a lexical-only score scale, in an environment where the embedding
model could not be downloaded. When dense retrieval became available the scale
changed underneath it and the floor stopped rejecting anything: every query,
including nonsense, returned five passages. The fix was to correct the cosine
scaling, and this script is how the floor gets set properly afterwards rather
than guessed again.

The measure that matters is not "does it find the right document" — it does,
94% of the time. It is the false retrieval rate: of the tickets the labels say
the documentation *cannot* answer, for how many did retrieval hand the
generator something anyway? Every one of those is material for a fluent,
confident, wrong reply.

Run it after any change to the embedding model, the chunking, or the hybrid
weight. All three move the scale.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings  # noqa: E402
from src.ingest import load_tickets  # noqa: E402
from src.retrieve import Retriever, load_corpus  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("floor")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tune the retrieval relevance floor.")
    parser.add_argument("--dev", type=Path, default=Path("data/development_tickets.json"))
    parser.add_argument("--docs", type=Path, default=Path("data/documentation.json"))
    parser.add_argument(
        "--max-false-retrieval",
        type=float,
        default=0.35,
        help="The highest acceptable share of unanswerable tickets for which "
        "retrieval still returns something. The floor is set to the lowest "
        "value meeting this, because a higher floor costs recall.",
    )
    args = parser.parse_args(argv)

    for p in (args.dev, args.docs):
        if not p.exists():
            print(f"no such file: {p}", file=sys.stderr)
            return 2

    settings = get_settings(refresh=True)
    retriever = Retriever(chunks=load_corpus(args.docs))
    log.info("retriever: %s", retriever.stats)
    if not retriever.dense_available:
        log.warning(
            "Dense retrieval is UNAVAILABLE, so this tunes the lexical-only scale. "
            "The value will be wrong once embeddings work. Re-run then."
        )

    tickets = load_tickets(args.dev)
    rows = []
    for i, ticket in enumerate(tickets, start=1):
        passages = retriever.search(ticket.text_for_model, min_score=0.0)
        labels = ticket.labels or {}
        rows.append(
            {
                "top": passages[0].score if passages else 0.0,
                "answerable": bool(labels.get("answerable_from_docs")),
            }
        )
        if i % 100 == 0:
            log.info("  scored %d/%d", i, len(tickets))

    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]

    print()
    print(f"Retrieval floor sweep — {len(answerable)} answerable, {len(unanswerable)} not")
    print(f"dense retrieval: {'available' if retriever.dense_available else 'UNAVAILABLE'}")
    print("-" * 70)
    print("  floor   kept (answerable)   returned anyway (unanswerable)   nothing")

    chosen = None
    for step in range(0, 61):
        floor = step / 100.0
        kept = sum(1 for r in answerable if r["top"] >= floor)
        false_hits = sum(1 for r in unanswerable if r["top"] >= floor)
        nothing = sum(1 for r in rows if r["top"] < floor)
        recall = kept / len(answerable) if answerable else 0.0
        false_rate = false_hits / len(unanswerable) if unanswerable else 0.0

        if chosen is None and false_rate <= args.max_false_retrieval:
            chosen = floor

        if step % 5 == 0:
            mark = "  <- chosen" if chosen is not None and abs(floor - chosen) < 1e-9 else ""
            print(
                f"  {floor:5.2f}     {kept:4d}  ({recall:5.1%})           "
                f"{false_hits:4d}  ({false_rate:5.1%})            {nothing:4d}{mark}"
            )

    if chosen is None:
        print()
        print(
            "No floor in the swept range gets the false retrieval rate under "
            f"{args.max_false_retrieval:.0%}.\nThat is a finding about the corpus, not a "
            "bug: many unanswerable tickets are topically\nclose to documented material. "
            "Report it and lean on the answerability model,\nwhich combines this score with "
            "the intent prior."
        )
        return 1

    kept = sum(1 for r in answerable if r["top"] >= chosen)
    false_hits = sum(1 for r in unanswerable if r["top"] >= chosen)
    print()
    print("=" * 70)
    print(f"Set this in .env:   RETRIEVAL_MIN_SCORE={chosen:.2f}")
    print(
        f"  keeps {kept}/{len(answerable)} ({kept / len(answerable):.1%}) of answerable tickets"
    )
    print(
        f"  returns something for {false_hits}/{len(unanswerable)} "
        f"({false_hits / len(unanswerable):.1%}) of unanswerable ones"
    )
    print()
    print(
        "Check it afterwards in the run's metrics.json under\n"
        "  technical.retrieval.false_retrieval_rate_on_unanswerable\n"
        "and technical.retrieval.returned_nothing. If the second is still zero,\n"
        "the floor is not doing its job."
    )
    print()

    out = Path("storage/retrieval_floor.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "chosen_floor": chosen,
                "dense_available": retriever.dense_available,
                "answerable": len(answerable),
                "unanswerable": len(unanswerable),
                "recall_at_floor": kept / len(answerable) if answerable else None,
                "false_retrieval_at_floor": (
                    false_hits / len(unanswerable) if unanswerable else None
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"written to {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
