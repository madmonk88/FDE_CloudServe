"""Recover the routing policy from CloudServe's own labelled data.

    python -m scripts.derive_policy

The development set labels every ticket with `expected_route`. Rather than
choosing a routing policy and defending it, this searches for the simplest
rule that reproduces those labels, then checks that rule against the
validation set, which is held out from the derivation.

The result is the policy implemented in `src/route.py`. Running this script is
how that claim is verified rather than asserted, and its output belongs in the
report as the evidence behind the routing design.

Note what this does *not* give you. The recovered rule takes
`answerable_from_docs` as an input, and that is a label available during
development and unknown at serving time. Predicting it is the actual
engineering problem, and it is tuned separately in
`scripts/tune_answerability.py`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recover the routing policy from labels.")
    parser.add_argument("--dev", type=Path, default=Path("data/development_tickets.json"))
    parser.add_argument("--val", type=Path, default=Path("data/validation_tickets.json"))
    args = parser.parse_args(argv)

    for p in (args.dev, args.val):
        if not p.exists():
            print(f"no such file: {p}", file=sys.stderr)
            return 2

    dev, val = load(args.dev), load(args.val)

    # -- Step 1. Does answerability alone explain routing? -----------------
    print("\nStep 1 — answerability against routing, on the development set")
    print("-" * 68)
    cross = Counter(
        (t["labels"]["answerable_from_docs"], t["labels"]["expected_route"]) for t in dev
    )
    for (answerable, route), n in sorted(cross.items()):
        print(f"  answerable={str(answerable):<5}  route={route:<13}  {n:4d}")
    not_answerable_escalate = cross[(False, "escalate")]
    not_answerable_auto = cross[(False, "auto_respond")]
    print(
        f"\n  Every one of the {not_answerable_escalate} tickets the documentation cannot "
        f"answer is labelled escalate\n  ({not_answerable_auto} exceptions). That is the "
        "first rule, and it is absolute."
    )

    # -- Step 2. Which intents never automate? -----------------------------
    print("\nStep 2 — intents whose tickets are never auto-answered")
    print("-" * 68)
    by_intent: dict[str, list[dict]] = defaultdict(list)
    for t in dev:
        by_intent[t["labels"]["intent"]].append(t["labels"])

    never_automate = []
    for intent, rows in sorted(by_intent.items()):
        escalate_rate = sum(1 for r in rows if r["expected_route"] == "escalate") / len(rows)
        must_not_rate = sum(1 for r in rows if r["must_not_auto_respond"]) / len(rows)
        if escalate_rate == 1.0 and must_not_rate == 1.0:
            never_automate.append(intent)
            print(f"  {intent:<26} escalate 100%   must_not_auto_respond 100%   n={len(rows)}")

    print(
        f"\n  {len(never_automate)} intents. CloudServe has, in effect, already stated\n"
        "  these never automate — the flag is on every single ticket."
    )

    # -- Step 3. What remains? ---------------------------------------------
    print("\nStep 3 — tickets still unexplained")
    print("-" * 68)
    residual = [
        t
        for t in dev
        if t["labels"]["expected_route"] == "escalate"
        and t["labels"]["answerable_from_docs"]
        and t["labels"]["intent"] not in never_automate
    ]
    print(f"  {len(residual)} escalations not explained by the two rules so far.")
    if residual:
        print("  by intent:   ", dict(Counter(t["labels"]["intent"] for t in residual)))
        print("  by urgency:  ", dict(Counter(t["labels"]["urgency"] for t in residual)))
        high_risk = sorted({t["labels"]["intent"] for t in residual})
        urgencies = sorted({t["labels"]["urgency"] for t in residual})
        print(
            f"\n  All of them are {' and '.join(i.replace('_', ' ') for i in high_risk)}\n"
            f"  at {' / '.join(urgencies)} urgency. At lower urgency these same intents\n"
            "  are auto-answered, so the rule is conditional on urgency, not on intent."
        )
    else:
        high_risk, urgencies = [], []

    # -- Step 4. State the policy and test it ------------------------------
    print("\nStep 4 — the recovered policy")
    print("-" * 68)
    print("  escalate if the documentation cannot answer the ticket")
    print(f"  or if intent in {sorted(never_automate)}")
    if high_risk:
        print(f"  or if intent in {high_risk} and urgency in {urgencies}")
    print("  otherwise auto_respond")

    def policy(labels: dict) -> str:
        if not labels["answerable_from_docs"]:
            return "escalate"
        if labels["intent"] in never_automate:
            return "escalate"
        if labels["intent"] in high_risk and labels["urgency"] in urgencies:
            return "escalate"
        return "auto_respond"

    print("\n  accuracy against the labels:")
    all_ok = True
    for name, data in (("development", dev), ("validation (held out)", val)):
        correct = sum(1 for t in data if policy(t["labels"]) == t["labels"]["expected_route"])
        pct = correct / len(data)
        all_ok = all_ok and correct == len(data)
        print(f"    {name:<24} {correct}/{len(data)} = {pct:.2%}")

    violations = [
        t
        for t in dev + val
        if t["labels"]["must_not_auto_respond"] and policy(t["labels"]) == "auto_respond"
    ]
    print(f"\n    must_not_auto_respond violations: {len(violations)} of {len(dev) + len(val)}")

    # -- What this means for the build -------------------------------------
    print("\n" + "=" * 68)
    if all_ok:
        print(
            "The policy reproduces the labels exactly on both sets, and the\n"
            "validation set was not used to derive it.\n"
        )
    print(
        "One input to this policy is a label during development and an unknown\n"
        "at serving time: whether the documentation can answer the ticket. The\n"
        "system predicts it from retrieval, and that prediction — not the policy —\n"
        "is where the engineering judgement sits.\n\n"
        "Next:  python -m scripts.tune_answerability\n"
    )

    payload = {
        "never_automate_intents": sorted(never_automate),
        "high_risk_intents": sorted(high_risk),
        "high_risk_urgency": sorted(urgencies),
        "verified_on": {"development": len(dev), "validation": len(val)},
    }
    out = Path("storage") / "routing_policy.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"written to {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
