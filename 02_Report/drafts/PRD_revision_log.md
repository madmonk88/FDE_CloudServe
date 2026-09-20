# PRD revision log — v1.0 → v1.1

The project requires the requirements document to be revised at least once during the build,
with a record of what changed and why. This is that record, and it is assessed directly.

> **Note before you submit this.** Every change below corresponds to something visible in the
> delivered code — a prompt version number, a config value, a router rule. They are real
> revisions, not invented ones. **Check each against what you actually observed during your
> own build**, and cut any you did not see for yourself. A revision log that claims a
> discovery you did not make is worse than a shorter one that is true.

---

## Why anything changed at all

Requirements that survive three weeks of contact with real code without a single amendment
usually mean nobody was reading them. Five things changed here, and the pattern in them is
worth naming up front: **four of the five were places where v1 specified a capability but not
the failure mode**, and the build exposed the failure mode.

---

## Change 1 — Confidence needed calibrating, and v1 did not say so

**v1 said:** FR-02 required "a numeric confidence" attached to each classification.

**What the build showed:** the model returned 0.9 or higher for nearly every ticket, including
ones it got wrong. Stated confidence was a property of the model's prose style, not a
probability. Since FR-07 routes on that number, the routing threshold was comparing against a
quantity that did not mean what it appeared to mean — a threshold of 0.7 was, in practice, no
threshold at all.

**What changed:** FR-02 now requires confidence that "reflects the actual probability of being
correct", and NFR-08 was added as an explicit condition: stated confidence within five
percentage points of observed accuracy, measured as expected calibration error and reported
every run.

**What was built as a result:** `src/calibration.py` — an isotonic reliability mapping fitted
on the development set — and a change to prompt `P-CLASSIFY-001` (v1.1 → v1.2) adding an
explicit instruction to consider how separable the top two categories are before giving a
number.

**Why this was not obvious in week one:** "attach a confidence" reads like a complete
requirement. It is not, and the gap only becomes visible when you plot stated confidence
against observed accuracy — which nobody does until the classifier exists.

---

## Change 2 — The insufficient-context path had to be made explicit

**v1 said:** FR-05 required answers "grounded in the retrieved passages".

**What the build showed:** the model strongly preferred answering thinly over declining. Given
weak or partially relevant passages it produced a hedged, plausible reply rather than saying
the documentation did not cover the question. Those replies passed a naive grounding check,
because they were vague enough to be superficially similar to almost anything retrieved.

**What changed:** FR-05 now requires the system to state plainly when it does not know "rather
than filling the gap", as a positive requirement rather than an implication of grounding.

**What was built as a result:** the `INSUFFICIENT_CONTEXT` branch in prompt `P-ANSWER-001`
(v1.2 → v1.3), a router rule (R10) that treats a declined answer as an escalation, and the
recording of declining as a *success* of the design rather than a failure of the run.

---

## Change 3 — Degraded operation needed its own routing rule

**v1 said:** NFR-05 required the system to keep operating when the provider was unavailable.

**What the build showed:** it did keep operating — and that was the problem. With the fallback
rule-based classifier running, tickets that happened to score above the routing threshold were
eligible for an automated reply based on keyword matching alone. A system built to survive an
outage had quietly acquired the ability to speak to paying customers on the weakest evidence
it possesses, at exactly the moment nobody was watching.

**What changed:** NFR-05 now specifies *degraded*, not merely *continued*, operation, with
automated replies suspended while degraded.

**What was built as a result:** router rule R8; and, as defence in depth, the fallback
classifier's confidence is capped structurally below the routing threshold, so even if R8 were
removed the degraded path still could not auto-answer. `test_a3_degraded_confidence_stays_below_the_routing_threshold`
asserts the cap directly.

**This is the change I would highlight in the video.** It is the clearest case of v1
specifying a capability and omitting the failure mode, and it would have produced the worst
possible incident — bad answers sent during an outage.

---

## Change 4 — The documentation gap report was promoted from a by-product to a requirement

**v1 said:** nothing. Gaps were an implicit consequence of retrieval returning nothing.

**What the build showed:** the tickets that retrieval could not serve were the most
*informative* output the system produced. Every one is a question customers keep asking that
the documentation does not answer. Left as a by-product it would have been invisible; as a
first-class output it is the only thing in the project that reduces future volume rather than
handling existing volume faster.

**What changed:** FR-14 added, along with the documentation gap count as a business success
measure that CloudServe did not ask for.

**What was built as a result:** `documentation_gaps.json` written on every run, ordered by
frequency, with examples; and `is_documentation_gap()` in the router so the signal is
explicit rather than inferred from a rule name at reporting time.

---

## Change 5 — Retrieval scoring changed from dense-only to hybrid

**v1 said:** FR-03 required searching the corpus, with the stack naming embeddings.

**What the build showed:** pure dense retrieval missed tickets quoting exact tokens — error
codes, header names, endpoint paths, flag names. A customer writing `X-CloudServe-Signature`
or `429` uses the corpus's exact vocabulary, and embeddings wash out precisely those tokens by
mapping them into a semantic neighbourhood.

**What changed:** FR-03 unchanged in wording; the design decision beneath it changed, and
that is recorded here rather than being silently different from the document.

**What was built as a result:** hybrid scoring in `src/retrieve.py` — dense for paraphrase,
BM25 for exact tokens, weighted and combined — with a per-article cap of two chunks so one
long article cannot crowd out a second article that also bears on the question.

**A secondary benefit not anticipated:** the lexical half has no external dependency, so when
the embedding model cannot be downloaded the system degrades to lexical-only rather than
failing. That is now the documented behaviour in `NFR-05`.

---

## What did *not* change, and why

Recording rejected changes matters as much as recording accepted ones. Each of these was
considered during the build and deliberately left alone.

**The routing threshold was not raised after seeing the validation results.** Raising it would
have improved the apparent precision of automated answers by escalating more. It was set from
the cost argument on the development set and left there, because moving it after seeing
validation results is fitting to the validation set, and the point of the split is that this
is not done. The evaluation reports one run, on one date.

**Per-channel routing thresholds were not added.** It is tempting to answer more readily on
documentation comments, where questions are narrow and technical, than on email. It would
probably raise the automation rate. It was rejected because it creates a fairness problem that
the audit would then have to disentangle: customers who use different channels are not
randomly distributed, and a channel-varying threshold is an outcome difference by another
name. One threshold, defended once, is the stronger position.

**The intent taxonomy was not extended.** Several categories have too few examples in the
development set to measure. Adding finer categories would have made the classifier look more
sophisticated and made every per-class figure less reliable. The categories are those present
in the data, and the thin ones are labelled as noise in the report rather than averaged in
silently.

---

## Reflection

The five changes have one thing in common. In each case v1 specified **what the system should
do** and omitted **what it should do when that was not possible**. Retrieval that finds
nothing, a model that will not decline, a provider that disappears, a confidence that means
nothing — these are not edge cases in a support system, they are ordinary Tuesday.

If I wrote v1 again, I would add a column to the functional requirements table headed *"and
when it can't?"*, and refuse to sign off a requirement with that cell empty. Four of these
five revisions would have been caught in week one at the cost of about twenty minutes.

The second lesson is about measurement. Change 1 — the calibration problem — was invisible
until the number was plotted against reality. It would have passed every test I would
naturally have written, because the system was behaving exactly as specified; the
specification was wrong. Requirements expressed as conditions that can be checked against
observed behaviour (*"within five points of observed accuracy"*) are worth several times
requirements expressed as capabilities (*"attaches a confidence"*), and the difference costs
nothing at writing time.
