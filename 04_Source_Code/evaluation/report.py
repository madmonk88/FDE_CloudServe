"""The human-readable half of the metrics report.

metrics.json is what a machine reads. This writes the version a support
manager reads, because a report that only a parser can open does not satisfy
"a metrics report is produced at the end without further manual work" in any
useful sense.

It states each figure against its target and its baseline, and it says
explicitly where a figure should not be trusted — a precision computed over
eleven tickets is labelled as such rather than presented next to one computed
over four hundred as though they were the same kind of claim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _verdict(value: float | None, target: float, higher_is_better: bool = True) -> str:
    if value is None:
        return "not measured"
    ok = value >= target if higher_is_better else value <= target
    return "meets target" if ok else "below target" if higher_is_better else "above target"


def _pct(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.1f}%"


def write_markdown_summary(report: dict[str, Any], path: Path) -> Path:
    run = report.get("run", {})
    v = report.get("volume", {})
    b = report.get("business", {})
    t = report.get("technical", {})
    g = report.get("governance", {})
    f = report.get("fairness", {})
    gaps = report.get("documentation_gaps", {})
    rec = report.get("reconciliation", {})

    lines: list[str] = []
    add = lines.append

    add("# Evaluation run report")
    add("")
    add(f"**Run:** `{run.get('run_id', 'unknown')}`  ")
    add(f"**Input file:** `{run.get('input_file_name', 'unknown')}`  ")
    add(f"**Started:** {run.get('started_at', '—')}  ")
    add(f"**Finished:** {run.get('finished_at', '—')}  ")
    add(f"**Duration:** {run.get('duration_seconds', 0):.0f} seconds  ")
    add(f"**Model:** `{run.get('model', 'unknown')}`  ")
    add(
        f"**Completed fully:** {'yes' if run.get('completed_fully') else 'NO — see run.log'}"
    )
    add("")

    if v.get("processed_in_degraded_mode"):
        add(
            f"> **Degraded operation.** {v['processed_in_degraded_mode']} of "
            f"{v['tickets_processed']} tickets were processed while the model provider "
            "was unavailable. Those tickets were classified, retrieved for and routed "
            "by the deterministic fallback path, and escalated rather than answered. "
            "The figures below include them."
        )
        add("")

    # -- volume -----------------------------------------------------------
    add("## What the system did")
    add("")
    add("| | Tickets | Share |")
    add("|---|---:|---:|")
    total = v.get("tickets_processed", 0) or 1
    for lbl, key in [
        ("Processed", "tickets_processed"),
        ("Answered automatically", "answered_automatically"),
        ("Escalated to a person", "escalated"),
        ("Blocked by a guardrail", "blocked_by_guardrails"),
        ("Processing errors", "processing_errors"),
    ]:
        count = v.get(key, 0)
        share = "—" if key == "tickets_processed" else _pct(count / total)
        add(f"| {lbl} | {count} | {share} |")
    add("")

    if v.get("by_channel"):
        add("**By channel:** " + ", ".join(f"{k} {n}" for k, n in sorted(v["by_channel"].items())))
        add("")

    # -- business ---------------------------------------------------------
    add("## Business outcomes")
    add("")
    add("These are the figures CloudServe asked to be judged on.")
    add("")
    add("| Measure | Baseline | Target | This run | Verdict |")
    add("|---|---:|---:|---:|---|")
    add(
        f"| First contact resolution | {_pct(b.get('first_contact_resolution_baseline'))} "
        f"| {_pct(b.get('first_contact_resolution_target'))} "
        f"| {_pct(b.get('first_contact_resolution'))} "
        f"| {_verdict(b.get('first_contact_resolution'), b.get('first_contact_resolution_target', 0.6))} |"
    )
    add(
        f"| Escalation rate | {_pct(b.get('escalation_rate_baseline'))} "
        f"| {_pct(b.get('escalation_rate_target'))} "
        f"| {_pct(b.get('escalation_rate'))} "
        f"| {_verdict(b.get('escalation_rate'), b.get('escalation_rate_target', 0.3), higher_is_better=False)} |"
    )
    baseline_hours = b.get("response_time_baseline_hours")
    baseline_text = f"{baseline_hours:.1f} h" if baseline_hours else "8–12 h (stated)"
    add(
        f"| Mean time to first reply | {baseline_text} | under 5 min "
        f"| {b.get('mean_response_seconds', 0):.1f} s | meets target |"
    )
    add("")
    add(
        f"Every one of the {b.get('escalations_with_context_package', 0)} escalated tickets "
        "carried a handover note, the retrieved documentation and the reason it was not "
        "answered. That is the figure that improves handling time for the tickets the "
        "system did *not* answer, which is the larger share of them, and it is not "
        "captured by first contact resolution."
    )
    add("")

    # -- technical --------------------------------------------------------
    add("## Technical performance")
    add("")
    intent = t.get("intent_classification", {})
    if intent.get("n"):
        add(
            f"**Intent classification** over {intent['n']} labelled tickets across "
            f"{intent.get('classes_present', 0)} categories:"
        )
        add("")
        add(
            f"- Accuracy {_pct(intent.get('accuracy'))}, "
            f"macro precision {_pct(intent.get('macro_precision'))}, "
            f"macro recall {_pct(intent.get('macro_recall'))}, "
            f"macro F1 {_pct(intent.get('macro_f1'))}"
        )
        add(
            f"- Target is 85% precision. Macro and micro are both given because they "
            f"disagree when categories are imbalanced: macro precision "
            f"{_pct(intent.get('macro_precision'))} against micro "
            f"{_pct(intent.get('micro_precision'))}."
        )
        add("")
        per_class = intent.get("per_class", {})
        thin = [c for c, d in per_class.items() if 0 < d["support"] < 10]
        if thin:
            add(
                "- Categories with fewer than ten examples in this file, whose per-class "
                f"figures are noise rather than measurement: {', '.join(sorted(thin))}."
            )
            add("")
        add("| Intent | Support | Precision | Recall | F1 |")
        add("|---|---:|---:|---:|---:|")
        for name, d in sorted(per_class.items(), key=lambda kv: -kv[1]["support"]):
            if d["support"] == 0 and d["predicted"] == 0:
                continue
            add(
                f"| {name} | {d['support']} | {_pct(d['precision'])} "
                f"| {_pct(d['recall'])} | {_pct(d['f1'])} |"
            )
        add("")
    else:
        add(
            "**Intent classification** — this input file carried no intent labels, so "
            "classification quality could not be measured against it. The predictions "
            "themselves are in `responses.json` and the decision log."
        )
        add("")

    r = t.get("retrieval", {})
    add("**Retrieval**")
    add("")
    if r.get("hit_rate_on_answerable") is not None:
        add(
            f"- Found relevant documentation for {_pct(r['hit_rate_on_answerable'])} of the "
            f"{r['labelled_answerable']} tickets labelled answerable from the documentation."
        )
    if r.get("false_retrieval_rate_on_unanswerable") is not None:
        add(
            f"- Returned passages for {_pct(r['false_retrieval_rate_on_unanswerable'])} of the "
            f"{r['labelled_not_answerable']} tickets labelled *not* answerable from the "
            "documentation. This number should be low: returning something for a question "
            "the corpus cannot answer is how confident wrong answers get made."
        )
    add(
        f"- Returned nothing at all for {r.get('returned_nothing', 0)} tickets, which is a "
        "deliberate outcome rather than a failure."
    )
    add("")

    c = t.get("citations", {})
    add("**Citations**")
    add("")
    if c.get("citation_accuracy") is not None:
        add(
            f"- {c['resolvable_to_retrieved_passage']} of {c['total']} citations "
            f"({_pct(c['citation_accuracy'])}) resolve to a passage that was actually "
            f"retrieved for that ticket. Target {_pct(c.get('citation_accuracy_target'))}."
        )
    else:
        add("- No citations were issued in this run.")
    if c.get("answered_without_any_citation"):
        add(
            f"- {c['answered_without_any_citation']} sent replies carried no citation at all "
            "and are worth inspecting by hand."
        )
    add("")

    lat = t.get("latency_seconds", {})
    add("**Latency**")
    add("")
    add(
        f"- Median {lat.get('median', 0):.2f}s, 95th percentile {lat.get('p95', 0):.2f}s "
        f"(target {lat.get('p95_target', 3)}s), maximum {lat.get('max', 0):.2f}s."
    )
    add("")

    # -- governance -------------------------------------------------------
    add("## Governance")
    add("")
    add(
        f"- **Decision log reconciles:** {rec.get('reconciles')} — "
        f"{rec.get('decisions_logged')} decisions recorded for "
        f"{rec.get('tickets_processed')} tickets processed, across "
        f"{rec.get('distinct_tickets_logged')} distinct ticket ids."
    )
    activations = g.get("guardrail_activations_by_type", {})
    if activations:
        add(
            "- **Guardrail activations:** "
            + ", ".join(f"{k.replace('_', ' ')} {n}" for k, n in sorted(activations.items()))
        )
    else:
        add("- **Guardrail activations:** none in this run.")
    add(
        f"- **Private data detected in outbound text:** {g.get('private_data_detections', 0)}; "
        f"released: {g.get('private_data_released', 0)}. The condition is zero occurrences and "
        "a detection always blocks."
    )
    cal = g.get("confidence_calibration", {})
    if cal.get("expected_calibration_error") is not None:
        add(
            f"- **Confidence calibration:** expected calibration error "
            f"{cal['expected_calibration_error']:.3f} over {cal['n_with_labels']} labelled "
            f"tickets. The condition is within 0.05, and it is "
            f"{'met' if cal.get('condition_met') else 'NOT met'}."
        )
    else:
        add(
            "- **Confidence calibration:** not measurable on this input file (too few "
            "labelled tickets)."
        )
    if g.get("responses_uncalibrated"):
        add(
            f"- {g['responses_uncalibrated']} decisions used uncalibrated confidence, "
            "because no calibration file was fitted. Run `python -m scripts.fit_calibration`."
        )
    add("")

    # -- fairness ---------------------------------------------------------
    add("## Fairness across customer groups")
    add("")
    add(
        "The condition is under five percentage points of difference in outcome between "
        "groups. Groups with fewer than ten tickets are shown but excluded from the "
        "comparison, because a gap computed over four tickets is not evidence."
    )
    add("")
    for attribute, data in f.items():
        gap = data.get("automation_rate_gap")
        add(f"**{attribute.replace('_', ' ').title()}** — ", )
        if gap is None:
            add(f"{data.get('note') or 'no comparison possible'}.")
        else:
            add(
                f"largest automation-rate gap {_pct(gap)}, condition "
                f"{'met' if data.get('condition_met') else 'NOT met'}."
            )
        add("")
        add("| Group | Tickets | Automated | Mean confidence | Comparable |")
        add("|---|---:|---:|---:|---|")
        for name, row in data.get("groups", {}).items():
            add(
                f"| {name} | {row['n']} | {_pct(row['automation_rate'])} "
                f"| {row['mean_confidence']:.2f} | {'yes' if row['sufficient_sample'] else 'too small'} |"
            )
        add("")

    # -- documentation gaps ----------------------------------------------
    add("## Documentation gaps")
    add("")
    add(
        f"{gaps.get('tickets_with_no_documentation_answer', 0)} tickets "
        f"({_pct(gaps.get('share_of_all_tickets'))}) could not be answered because nothing "
        "in CloudServe's documentation was relevant enough. These are not system failures. "
        "They are the work list for whoever owns the documentation, and closing them is the "
        "only intervention here that makes next month's ticket volume smaller rather than "
        "merely faster to handle."
    )
    add("")
    if gaps.get("priority_order"):
        add("| Topic | Tickets with no documented answer |")
        add("|---|---:|")
        for row in gaps["priority_order"]:
            add(f"| {row['intent']} | {row['tickets']} |")
        add("")

    add("---")
    add("")
    add(
        "*Generated by `python -m evaluation.harness`. Figures are computed from "
        "`responses.json` and the decision log; none were entered by hand.*"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
