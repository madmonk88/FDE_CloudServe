"""Tune the answerability threshold — the most consequential number here.

    python -m scripts.tune_answerability

The routing policy recovered in `scripts/derive_policy.py` takes three
inputs. Two of them — intent and urgency — the classifier predicts. The
third, whether the documentation can answer the ticket, is a label during
development and an unknown at serving time, and it is the rule that decides
the largest share of routing decisions.

The system predicts it from retrieval: if the best passage clears a threshold,
the corpus covers the question. This script finds that threshold by sweeping
it against the `answerable_from_docs` label on the development set.

Two operating points are reported, and they are not the same number:

**Best F1** balances the two errors equally. It is the answer to "how well can
retrieval predict answerability", and it is the right number to quote when
describing the retriever.

**Minimum expected cost** weights the errors by what they cost CloudServe, and
it is the right number to actually deploy. Answering a ticket the
documentation cannot really answer produces a confident wrong reply to a
paying customer, an agent handling both the complaint and the original
question, and a mark against the satisfaction score renewals turn on.
Escalating one it could have answered costs a few agent minutes. Those are
assumed to stand at 8:1, and the sensitivity table shows how the threshold
moves if that assumption is wrong.

The script also reports end-to-end routing accuracy with the predicted
answerability substituted for the label, which isolates exactly how much
accuracy is lost by having to predict it.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import answerability as ans  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.ingest import load_tickets  # noqa: E402
from src.retrieve import Retriever, load_corpus  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("tune")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tune the answerability threshold.")
    parser.add_argument("--dev", type=Path, default=Path("data/development_tickets.json"))
    parser.add_argument("--val", type=Path, default=Path("data/validation_tickets.json"))
    parser.add_argument("--docs", type=Path, default=Path("data/documentation.json"))
    parser.add_argument(
        "--cost-ratio",
        type=float,
        default=8.0,
        help="Cost of answering an unanswerable ticket relative to escalating an "
        "answerable one. An assumption, not a measurement.",
    )
    args = parser.parse_args(argv)

    for p in (args.dev, args.docs):
        if not p.exists():
            print(f"no such file: {p}", file=sys.stderr)
            return 2

    settings = get_settings(refresh=True)
    policy_file = Path("storage/routing_policy.json")
    if policy_file.exists():
        policy = json.loads(policy_file.read_text(encoding="utf-8"))
    else:
        policy = {
            "never_automate_intents": list(settings.routing.never_automate_intents),
            "high_risk_intents": list(settings.routing.high_risk_intents),
            "high_risk_urgency": list(settings.routing.high_risk_urgency),
        }

    log.info("building the index over %s", args.docs.name)
    retriever = Retriever(chunks=load_corpus(args.docs))
    log.info("retriever: %s", retriever.stats)
    if not retriever.dense_available:
        log.warning(
            "DENSE RETRIEVAL IS UNAVAILABLE. The threshold found below is for "
            "lexical-only scoring and will NOT be right once embeddings work. "
            "Re-run this script on a machine that can download the embedding model."
        )

    # -- score every ticket ------------------------------------------------
    def score(path: Path) -> list[dict]:
        rows = []
        tickets = load_tickets(path)
        for i, ticket in enumerate(tickets, start=1):
            # Retrieve without a floor, so the sweep can see every score.
            passages = retriever.search(ticket.text_for_model, min_score=0.0)
            labels = ticket.labels or {}
            rows.append(
                {
                    "top_score": passages[0].score if passages else 0.0,
                    "top_doc": passages[0].doc_id if passages else None,
                    "retrieved_docs": [p.doc_id for p in passages],
                    "answerable": bool(labels.get("answerable_from_docs")),
                    "expected_docs": labels.get("expected_doc_ids") or [],
                    "intent": labels.get("intent"),
                    "urgency": labels.get("urgency"),
                    "expected_route": labels.get("expected_route"),
                    "must_not": bool(labels.get("must_not_auto_respond")),
                }
            )
            if i % 100 == 0:
                log.info("  scored %d/%d", i, len(tickets))
        return rows

    dev_rows = score(args.dev)
    val_rows = score(args.val) if args.val.exists() else []

    # -- fit the answerability model --------------------------------------
    # Fitted on development data only. The validation rows are scored with it
    # but never contribute to the fit.
    model = ans.fit(
        [r["intent"] for r in dev_rows],
        [r["top_score"] for r in dev_rows],
        [r["answerable"] for r in dev_rows],
        fitted_on=f"{args.dev.name} (n={len(dev_rows)})",
        dense_available=retriever.dense_available,
    )
    model_path = ans.save(model)
    for rows in (dev_rows, val_rows):
        for r in rows:
            r["p"] = model.probability(r["intent"], r["top_score"])

    score_auc = ans.auc_score(
        [r["top_score"] for r in dev_rows], [r["answerable"] for r in dev_rows]
    )
    prior_auc = ans.auc_score(
        [model.prior_for(r["intent"]) for r in dev_rows],
        [r["answerable"] for r in dev_rows],
    )

    print()
    print("Predicting answerability — what actually carries the signal")
    print("-" * 68)
    print(f"  retrieval score alone            AUC {score_auc:.3f}")
    print(f"  intent prior alone               AUC {prior_auc:.3f}")
    print(f"  fitted combination               AUC {model.auc:.3f}")
    print()
    print(f"  fitted weights: prior {model.w_prior:.3f}, retrieval {model.w_score:.3f}")
    if model.w_score < 0.2:
        print(
            "  The model has learned to lean on the intent rather than the retrieval\n"
            "  score. That is a finding about the retriever, not a bug: a feature\n"
            "  request is not unanswerable for want of a similar-looking passage."
        )
    print(f"  written to {model_path}")

    # -- how good is retrieval at all? ------------------------------------
    with_docs = [r for r in dev_rows if r["expected_docs"]]
    top1 = sum(1 for r in with_docs if r["top_doc"] in r["expected_docs"])
    topk = sum(
        1 for r in with_docs if set(r["retrieved_docs"]) & set(r["expected_docs"])
    )
    print()
    print("Retrieval quality against the expected documents")
    print("-" * 68)
    print(f"  tickets with an expected document   {len(with_docs)}")
    print(f"  correct document ranked first       {top1}  ({top1 / max(len(with_docs), 1):.1%})")
    print(f"  correct document in the top {settings.retrieval.top_k}        {topk}  ({topk / max(len(with_docs), 1):.1%})")

    # -- the sweep ---------------------------------------------------------
    answerable = [r for r in dev_rows if r["answerable"]]
    unanswerable = [r for r in dev_rows if not r["answerable"]]
    print()
    print(
        f"Threshold sweep on the predicted probability — {len(answerable)} answerable, "
        f"{len(unanswerable)} not, on {args.dev.name}"
    )
    print("-" * 68)
    print("  thresh   precision  recall     F1     wrong-auto  lost-auto   cost")

    best_f1 = (0.0, -1.0)
    best_cost = (0.0, float("inf"))
    rows_out = []

    for step in range(0, 101):
        threshold = step / 100.0
        tp = sum(1 for r in answerable if r["p"] >= threshold)
        fp = sum(1 for r in unanswerable if r["p"] >= threshold)
        fn = len(answerable) - tp
        precision = tp / (tp + fp) if (tp + fp) else 1.0
        recall = tp / len(answerable) if answerable else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        cost = args.cost_ratio * fp + fn

        rows_out.append((threshold, precision, recall, f1, fp, fn, cost))
        if f1 > best_f1[1]:
            best_f1 = (threshold, f1)
        if cost < best_cost[1]:
            best_cost = (threshold, cost)

    for threshold, precision, recall, f1, fp, fn, cost in rows_out[::5]:
        mark = ""
        if abs(threshold - best_f1[0]) < 1e-9:
            mark += "  <- best F1"
        if abs(threshold - best_cost[0]) < 1e-9:
            mark += "  <- min cost"
        print(
            f"  {threshold:5.2f}    {precision:7.1%}   {recall:6.1%}  {f1:6.3f}   "
            f"{fp:8d}   {fn:8d}  {cost:7.1f}{mark}"
        )

    print()
    print(f"  best F1            threshold {best_f1[0]:.2f}  (F1 {best_f1[1]:.3f})")
    print(f"  minimum cost       threshold {best_cost[0]:.2f}  at {args.cost_ratio:g}:1")

    print()
    print("  sensitivity to the cost ratio — the assumption this rests on:")
    print("    ratio   threshold   escalation rate it implies")
    for ratio in (2.0, 4.0, 6.0, 8.0, 12.0, 20.0):
        cheapest, cheapest_cost = 0.0, float("inf")
        for threshold, _, _, _, fp, fn, _ in rows_out:
            cost = ratio * fp + fn
            if cost < cheapest_cost:
                cheapest, cheapest_cost = threshold, cost
        escalated = sum(1 for r in dev_rows if r["p"] < cheapest) / len(dev_rows)
        print(f"    {ratio:5.0f}     {cheapest:.2f}        {escalated:.1%}")

    def route(row: dict, answerable_pred: bool) -> str:
        if not answerable_pred:
            return "escalate"
        if row["intent"] in policy["never_automate_intents"]:
            return "escalate"
        if (
            row["intent"] in policy["high_risk_intents"]
            and row["urgency"] in policy["high_risk_urgency"]
        ):
            return "escalate"
        return "auto_respond"

    # -- third operating point: reproduce CloudServe's own routing ---------
    # The cost sweep above optimises a ratio we assumed. This optimises
    # against something we were actually given: `expected_route`, which is
    # CloudServe's own decision about each ticket. It is the least
    # assumption-laden target available, and it is the one the evaluation
    # scores routing against.
    def route_rows(rows: list[dict], threshold: float) -> tuple[int, int]:
        correct = unsafe = 0
        for r in rows:
            predicted = route(r, r["p"] >= threshold)
            correct += predicted == r["expected_route"]
            if r["must_not"] and predicted == "auto_respond":
                unsafe += 1
        return correct, unsafe

    best_routing = (0.0, -1)
    routing_curve = []
    for step in range(0, 101):
        threshold = step / 100.0
        correct, unsafe = route_rows(dev_rows, threshold)
        routing_curve.append((threshold, correct, unsafe))
        # Tie-break towards the HIGHER threshold. Routing accuracy is flat
        # across a wide band here, and within that band a higher threshold
        # costs nothing and buys something: every ticket it pushes below the
        # line is flagged as a documentation gap. Taking the lowest threshold
        # in a tie would maximise routing accuracy and identify no gaps at
        # all, which optimises the measure at the expense of the point.
        if correct >= best_routing[1]:
            best_routing = (threshold, correct)

    print()
    print("Third operating point — reproducing CloudServe's own routing decisions")
    print("-" * 68)
    print("  thresh   routing accuracy (dev)   must-not violations")
    for threshold, correct, unsafe in routing_curve[::5]:
        mark = "  <- best" if abs(threshold - best_routing[0]) < 1e-9 else ""
        print(f"  {threshold:5.2f}    {correct:4d}/{len(dev_rows)} = {correct / len(dev_rows):5.1%}"
              f"          {unsafe:3d}{mark}")
    plateau = [t for t, c, _ in routing_curve if c == best_routing[1]]
    gaps_at_choice = sum(1 for r in dev_rows if r["p"] < best_routing[0])
    gaps_at_lowest = sum(1 for r in dev_rows if r["p"] < min(plateau))
    print()
    print(
        f"  routing accuracy is flat at {best_routing[1] / len(dev_rows):.1%} for every "
        f"threshold from {min(plateau):.2f} to {max(plateau):.2f}."
    )
    print(
        f"  Taking the top of that plateau ({best_routing[0]:.2f}) costs nothing in routing\n"
        f"  accuracy and flags {gaps_at_choice} documentation gaps; taking the bottom "
        f"({min(plateau):.2f})\n  would flag {gaps_at_lowest}. The documentation gap report is "
        "the output that\n  reduces future volume, so the top of the plateau is the right end of it."
    )

    print()
    print("The three candidate thresholds, and what each optimises")
    print("-" * 68)
    print(f"  {best_f1[0]:.2f}   best F1 on answerability          — describes the predictor")
    print(f"  {best_routing[0]:.2f}   reproduces CloudServe's routing   — fewest disagreements with the client")
    print(f"  {best_cost[0]:.2f}   minimum assumed cost at {args.cost_ratio:g}:1     — safest, escalates most")
    print()
    print("  The middle one is the default this system ships with. It optimises")
    print("  against a label CloudServe supplied rather than a cost ratio we")
    print("  assumed, and the safety condition holds at every threshold because")
    print("  the never-automate rule fires before this one is ever consulted.")
    if score_auc < 0.65:
        print()
        print("  CAVEAT, and it belongs in the report. The retrieval score is a weak")
        print(f"  answerability signal here (AUC {score_auc:.2f}), so almost all of the")
        print("  predictive power is coming from the intent prior. Routing accuracy is")
        print("  consequently flat across most of the threshold range: the predictor is")
        print("  barely beating the trivial baseline of assuming every ticket is")
        print("  answerable. This is a measured limitation of the retriever, not of the")
        print("  policy, and it is the first thing that should improve once dense")
        print("  retrieval is available.")

    # -- end-to-end routing with the predicted answerability ---------------
    chosen = best_routing[0]

    print()
    print(f"End-to-end routing at threshold {chosen:.2f}, with gold intent and urgency")
    print("-" * 68)
    print("  (this isolates what predicting answerability costs; the classifier")
    print("   adds its own error on top of this)")
    print()
    for name, rows in (("development", dev_rows), ("validation", val_rows)):
        if not rows:
            continue
        correct = 0
        unsafe = 0
        for r in rows:
            predicted = route(r, r["p"] >= chosen)
            correct += predicted == r["expected_route"]
            if r["must_not"] and predicted == "auto_respond":
                unsafe += 1
        print(
            f"  {name:<14} routing accuracy {correct}/{len(rows)} = "
            f"{correct / len(rows):.1%}   must-not violations {unsafe}"
        )

    # -- with the label, for comparison ------------------------------------
    print()
    print("  for comparison, the same policy with the answerability LABEL:")
    for name, rows in (("development", dev_rows), ("validation", val_rows)):
        if not rows:
            continue
        correct = sum(1 for r in rows if route(r, r["answerable"]) == r["expected_route"])
        print(f"  {name:<14} routing accuracy {correct}/{len(rows)} = {correct / len(rows):.1%}")

    print()
    print("=" * 68)
    print(f"Set this in .env:   ROUTE_ANSWERABLE_THRESHOLD={chosen:.2f}")
    print(
        f"  (use {best_cost[0]:.2f} instead if CloudServe would rather escalate more; "
        f"it raises\n   escalation to about "
        f"{sum(1 for r in dev_rows if r['p'] < best_cost[0]) / len(dev_rows):.0%} "
        "and reduces wrong automated answers further)"
    )
    if not retriever.dense_available:
        print()
        print(
            "WARNING: tuned with lexical-only retrieval. Re-run this on a machine\n"
            "where the embedding model downloads, and use that threshold instead."
        )
    print()

    out = Path("storage/answerability_tuning.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "chosen_threshold": chosen,
                "best_routing_threshold": best_routing[0],
                "best_cost_threshold": best_cost[0],
                "best_f1_threshold": best_f1[0],
                "best_f1": best_f1[1],
                "cost_ratio": args.cost_ratio,
                "dense_available": retriever.dense_available,
                "auc_retrieval_only": score_auc,
                "auc_intent_prior_only": prior_auc,
                "auc_fitted_model": model.auc,
                "retrieval_top1_accuracy": top1 / max(len(with_docs), 1),
                "retrieval_topk_accuracy": topk / max(len(with_docs), 1),
                "sweep": [
                    {"threshold": t, "precision": p, "recall": r, "f1": f}
                    for t, p, r, f, _, _, _ in rows_out
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"written to {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
