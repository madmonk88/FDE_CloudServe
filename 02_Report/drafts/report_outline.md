# Project report — CloudServe Support Intelligence

**Author:** Bala · **Date:** *[date]* · **Target length:** 20–30 pages, submitted as PDF

> **How to use this.** Sections marked **[WRITTEN]** are complete prose you can use largely as
> is — they describe the system that was actually built, so they are true regardless of what
> your numbers come out at. Sections marked **[NEEDS YOUR NUMBERS]** have the argument
> structured and the sentences framed, with `[...]` where a figure from your
> `evaluation/results/metrics.md` goes. Sections marked **[YOURS]** only you can write.
>
> Write sections 5 and 6 first. They carry the most marks and they are the ones that get
> rushed.

---

## 1. Executive summary — [NEEDS YOUR NUMBERS]

*One page. A non-technical reader should finish it knowing what was wrong, what was built, and
whether it worked.*

Frame it in this order:

> CloudServe Solutions asked for a chatbot for a support function receiving over 500 tickets a
> week, replying in 8–12 hours against a 2-hour commitment, and resolving 42% on first contact.
>
> Discovery found three distinct problems rather than one. A chatbot addresses one of them and
> is actively harmful applied to another. What was built instead is a triage and deflection
> layer with a documentation feedback loop: it answers questions the documentation can already
> answer, escalates the rest with context assembled, and produces a prioritised record of what
> the documentation is missing.
>
> Over the validation set of *[n]* tickets, first contact resolution reached *[x]%* against a
> 42% baseline and a 60% target, escalation *[x]%* against 58% and 30%, and 95th-percentile
> processing latency *[x]s* against a 3s target. *[n]* tickets were identified as questions the
> documentation cannot answer — the work list that reduces future volume rather than handling
> it faster.
>
> The largest limitation is *[your honest answer — likely the grounding check measuring
> similarity rather than entailment]*.

---

## 2. Discovery and problem framing — [YOURS]

*Target 3–4 pages. Worth 15%.*

**2.1 Method.** Who you interviewed, what you analysed, in what order. Be specific about the
ticket-data analysis — it is what settles the disagreements between interviews.

**2.2 What the evidence showed.** Three to five findings. Each one: the finding, the evidence
that produced it, and the number.

The one that matters most: the share of incoming tickets already answerable from CloudServe's
own documentation. Give the number, say how you computed it, and say what it means — that this
is a delivery failure rather than a knowledge failure.

**2.3 Where the interviews disagreed.** The pack says they disagree in at least three places
and that the ticket data settles it. Name the disagreements and say which way the data fell.
This is the paragraph that demonstrates you did discovery rather than reading transcripts.

**2.4 Problem statement.** The one in `PRD_v1.md` §2.3, or your own. Then the paragraph on why
the obvious answer was wrong — which is where the "forward deployed" distinction gets
demonstrated rather than claimed.

---

## 3. Requirements and traceability — [WRITTEN, needs your evidence ids]

*Target 2–3 pages. Worth 10%.*

Summarise `PRD_v1.md`: the requirements, the evidence each came from, and the chain forward
into code and tests. Do not reproduce the full tables — put those in the appendix and use a
worked example in the body instead:

> Taking one requirement end to end: discovery found that *[n]%* of tickets are not answerable
> from the existing documentation (evidence `E-02`). That produced FR-04, requiring retrieval
> to return nothing rather than something irrelevant, and FR-14, requiring those tickets to be
> recorded as documentation gaps. FR-04 is implemented as the relevance floor in
> `src/retrieve.py` and verified by
> `test_a4_threshold_returns_nothing_for_an_irrelevant_query`. FR-14 is implemented in
> `evaluation/metrics.py::_documentation_gaps` and produces `documentation_gaps.json` on every
> run.

Then summarise the revision: what v1 got wrong and what changed. `PRD_Revision_Log.md` has the
detail; the report needs the shape of it and the reflection.

---

## 4. The system — [WRITTEN]

*Target 4–5 pages. Part of the 35% implementation mark.*

**4.1 Architecture.** Six components in sequence — ingest, classify, retrieve, generate,
validate, route — over three cross-cutting concerns: the decision log, the guardrails, and
degraded operation. Use the diagram from the README.

Explain the one ordering choice that is not obvious: generation runs *before* routing is
finalised, because the routing decision depends on how well the draft is grounded in what was
retrieved, which cannot be known until the draft exists. A draft that does not get sent is not
wasted — it travels with the escalation.

**4.2 Ingest.** Four channels, one representation. Ingest is the only component that knows
tickets ever looked different. Channel is allowed to change exactly one downstream behaviour —
the latency budget and response length — because a live chat customer abandons the
conversation and an email customer does not notice three extra seconds. Ingest never raises:
a malformed ticket becomes a degraded ticket with a warning attached, because an exception
here would drop every ticket after it as well.

**4.3 Retrieval.** Three decisions to defend:

*Chunking.* Split on heading boundaries, then pack to ~900 characters, with every chunk
carrying its article title and section heading as a prefix. Chunking without that prefix is
the most common way retrieval quality is silently lost: a paragraph saying "set this to false"
is useless once separated from the heading naming the setting.

*Hybrid scoring.* Dense embeddings handle paraphrase, because customers do not use CloudServe's
vocabulary. Lexical BM25 handles exact tokens — error codes, endpoint paths, header names —
which customers quote verbatim and which embeddings wash out by mapping them into a semantic
neighbourhood. Neither alone is adequate for a support corpus.

*A floor that returns nothing.* Retrieving something plausible but irrelevant is worse than
retrieving nothing, because it hands the generator material to be fluent and wrong about.

**4.4 Classification and calibration.** See §5.2 — this is a result, not just a component.

**4.5 Routing.** Nine ordered rules, first match wins. Ordering makes every reason
unambiguous and puts the non-negotiable rules above the measured ones, so no threshold sweep
can produce a system that auto-answers a security incident. Routing is a pure function of
numbers already computed and logged: no model call, no clock read, no randomness. That is how
A5 is guaranteed structurally rather than hoped for.

**4.6 Generation and guardrails.** Citations are resolved and validated, not trusted: markers
pointing at sources that were not supplied are discarded and counted. Four guardrails run on
every response before release and each can block — a guardrail that only warns is not a
guardrail. Each records what it checked and what it found whether or not it fired, because a
control that leaves no evidence when it passes cannot be audited.

Prompt injection is handled structurally, not by instruction: instructions and sources go in
the system message, customer text in a separate user message inside a delimiter the customer
cannot close. Asking a model politely not to be redirected is not a control; separating the
channels is.

**4.7 Failure handling.** Cache, self-imposed rate limit, backoff with jitter, circuit breaker.
With no provider the system classifies by rules, retrieves lexically, routes, logs and
escalates with full context. The fallback classifier's confidence is capped below the routing
threshold by design, so a degraded system can never auto-answer. It loses the automation; it
keeps the triage.

---

## 5. Evaluation — [NEEDS YOUR NUMBERS]

*Target 5–6 pages. Worth 20% — the second largest block, and the one where marks are most
often left on the table by reporting figures without interpreting them.*

**5.1 Method.** State plainly: thresholds and calibration fitted on the development set only;
the validation set run once, on *[date]*; the hidden set never seen. Say why that matters —
evaluating repeatedly and adjusting after each run measures how well you fitted those tickets,
not how the system handles unseen ones.

**5.2 Calibration.** Report expected calibration error before and after. Then the
interpretation:

> Raw stated confidence averaged *[x]* against an observed accuracy of *[y]*, an expected
> calibration error of *[z]*. After fitting, ECE fell to *[z']*. This matters beyond the
> governance condition: the routing threshold compares against this number, so before
> calibration a threshold of 0.70 was not the decision boundary it appeared to be.

**5.3 Business outcomes.** FCR, escalation rate, response time, against baseline and target.
Then the honesty paragraph — this is the one that earns the marks:

> Time to first reply as measured here is processing latency, not CloudServe's end-to-end time
> to first reply, because escalated tickets still queue for a human. What improves for those
> is agent handling time: every escalation arrives with a drafted summary, the relevant
> documentation retrieved and an explicit statement of what the system was unsure about. I
> have not measured that improvement, because it requires agent handling times before and
> after, which I do not have. It is the most important number this evaluation cannot supply,
> and it applies to *[x]%* of tickets rather than the *[y]%* that were automated.

**5.4 Technical performance.** Classification precision and recall per class, retrieval hit
rate, citation accuracy, latency. Report macro *and* micro and explain why they differ — macro
says how the system does on a typical category, micro on a typical ticket, and they disagree
loudly when categories are imbalanced, which support intents always are.

State which per-class figures are noise:

> *[These]* categories had fewer than ten examples in the validation set. Their per-class
> precision figures are reported for completeness but are not measurement, and they are
> excluded from the macro average rather than being averaged in silently.

**5.5 Retrieval, honestly.** Report both numbers: hit rate on tickets labelled answerable, and
the rate at which passages were returned for tickets labelled *not* answerable. The second is
the one that matters and the one most reports omit — a retriever that always returns something
scores perfectly on hit rate and is worthless.

**5.6 What the evaluation does not cover.** Answer quality was measured by grounding and
citation resolution, which are proxies. Grounding is similarity, not entailment: a sentence can
score well against a passage that does not actually support it. No human read a sample of sent
answers. Customer satisfaction could not be measured at all — the 4.0 target is unverifiable
from this evaluation and should not be claimed.

---

## 6. Governance and risk — [WRITTEN]

*Target 3–4 pages. Worth 10%.*

Summarise `GOVERNANCE.md`: the five things the system must never do and the mechanism enforcing
each; the risk register with the two risks whose residual rating is genuinely Medium and why;
the decision log schema and the reconciliation check the system runs on itself; the fairness
audit method, its sample-size handling and its stated limits; the incident procedure and the
kill switch.

Two paragraphs worth writing out in full rather than summarising:

*On the kill switch.* Turning automation off does not take support offline — every ticket is
still classified, retrieved for, triaged and logged, and goes to a human with context. That is
what makes it usable in practice: nobody has to weigh "should I stop this?" against "will
support collapse?", which is the hesitation that turns a five-minute incident into an hour.

*On fairness.* The attribute that matters most is language fluency. A retrieval-based system
disadvantages customers writing in a second language structurally rather than incidentally:
their phrasing matches the documentation's vocabulary less closely, retrieval scores lower,
more of their tickets fall below the threshold. It will not show up unless someone looks for
it, which is why the audit runs on every evaluation rather than as a separate exercise.

---

## 7. Limitations and what I would do next — [WRITTEN, adjust to taste]

*Target 1–2 pages. This section is where confident reports become trustworthy ones.*

Six, ordered by how much they matter:

1. **Grounding measures similarity, not entailment.** A sentence can score well against a
   passage that does not support it. Claim-level entailment checking would close it.
2. **No human review of sent answers.** A wrong answer is currently found by complaint rather
   than by audit. Sampling 5% weekly would change that.
3. **Calibration is fitted once** on development data and will drift as the ticket mix changes.
4. **Log retention is stated policy, not a running job.** Customer text accumulates. This is a
   compliance obligation rather than an engineering preference, and it is the first thing I
   would build next.
5. **The kill switch is in-process and unauthenticated** — fine for an assessment on
   localhost, not for production.
6. **Monitoring exposes metrics but no alerts are configured.** A metric nobody is paged on is
   a metric nobody reads.

Then close on the thing that matters most:

> If CloudServe implemented one recommendation from this project, it would not be the
> automation. It would be to staff the documentation gap list. Every entry is a question their
> customers keep asking that their documentation does not answer, and closing those is the only
> intervention here that makes next month's volume smaller rather than merely faster to handle.
> The automation makes the current volume cheaper; the feedback loop makes it shrink.

---

## 8. Reflection — [YOURS]

*1 page. Draw on the effort log — that is what it is for.*

Where estimates were wrong and why. What you would do differently. The pattern in your
revision log is a good spine: v1 specified what the system should do and omitted what it
should do when that was not possible, and four of five revisions came from that single gap.

Be honest about the timeline. An assessor reading an effort log that shows every stage landing
implausibly close to its estimate learns something you did not intend to tell them.

---

## Appendices

- **A.** Stage 1 discovery workbook
- **B.** PRD v1.0 and v1.1
- **C.** PRD revision log
- **D.** Prompt library (`src/llm/prompts.py`; `register_rows()` emits the register table)
- **E.** Sprint plan
- **F.** Effort log
- **G.** Full metrics report (`evaluation/results/metrics.md`)
- **H.** Documentation gap list (`documentation_gaps.json`)
- **I.** Risk register (from the governance framework)

---

## Drafting order, given the time you have

1. **§5 Evaluation** — needs your run, carries 20%, and everything else can reference it
2. **§2 Discovery** — 15%, and only you can write it
3. **§6 Governance** — 10%, mostly assembly from `GOVERNANCE.md`
4. **§4 The system** — 4–5 pages, largely written above
5. **§1 Executive summary** — write it last, when you know what it summarises
6. **§7, §8** — short, and §7 is nearly done

**The two paragraphs that will move your mark most**, if you write nothing else carefully: the
honesty paragraph in §5.3 about what the latency figure does not mean, and the closing
paragraph of §7 about the documentation gap list. The first demonstrates you understand your
own evaluation's limits; the second demonstrates you understood the client's problem better
than the client did. Those two behaviours are what the whole capstone is testing.
