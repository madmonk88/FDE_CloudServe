# Product Requirements Document — v1.0

**Product:** CloudServe Support Intelligence
**Client:** CloudServe Solutions
**Author:** Bala
**Status:** v1.0, superseded during the build — see the revision log

> **How to use this document.** Every requirement carries an evidence reference in the form
> `E-nn`. Those references point at rows in the Stage 1 discovery workbook. **Where you see
> `E-nn`, replace it with your real evidence id once you have filled the discovery workbook**
> — the traceability marks are awarded for the chain being real, and an assessor picks a
> requirement at random and asks which evidence produced it.
>
> The `Implemented in` and `Verified by` columns already point at real files and real tests in
> the delivered system; those are accurate as written.

---

## 1. Document control

| | |
|---|---|
| Version | 1.0 |
| Date | *[date you wrote v1]* |
| Author | Bala |
| Based on | Stage 1 discovery workbook |
| Revised by | v1.1 — see `Stage_5_PRD_Revision_Log` |

**Version history**

| Version | Date | Change | Why |
|---|---|---|---|
| 1.0 | *[date]* | First version, written from discovery | — |
| 1.1 | *[date]* | *[see revision log]* | Contact with the build |

---

## 2. The problem

### 2.1 What CloudServe asked for

A chatbot for their support function.

### 2.2 What the evidence shows the problem to be

CloudServe's support function receives over 500 tickets a week across four channels. First
reply takes 8–12 hours against a contractual 2 hours. First contact resolution is 42%.
Satisfaction has fallen to 3.2/5, and two experienced agents left last quarter citing
workload.

Discovery shows this is **not one problem but three**, and they require different solutions:

| Population | What it needs | Evidence |
|---|---|---|
| Questions already answered in CloudServe's documentation | Delivery, not knowledge. The answer exists; the customer did not find it. | `E-01` *[your ticket-data analysis of `answerable_from_docs`]* |
| Questions the documentation cannot answer | The answer does not exist. Automating here produces fluent, ungrounded, confident error. The correct output is a documentation gap, not a reply. | `E-02` |
| Genuinely complex tickets | A person, reached faster and with context already assembled. | `E-03` *[tier two engineer interview]* |

A chatbot addresses the first population only, and is actively harmful applied to the second.

### 2.3 Problem statement

> CloudServe's support function is slow because too much agent time is spent re-answering
> questions their documentation already answers, and because the tickets that genuinely need
> a person arrive without the context needed to act on them. The result is an 8–12 hour first
> reply against a 2-hour commitment, 42% first contact resolution, and rising attrition.
>
> The constraint is not the volume of questions. It is that answers which already exist are
> not reaching customers, that questions with no documented answer are not being fed back to
> the people who write the documentation, and that triage is being done by hand.

### 2.4 What follows from that framing

The system is a **triage and deflection layer with a documentation feedback loop**. It
deflects what the documentation can answer, escalates the rest with context assembled, and
produces a prioritised record of what the documentation is missing — the only output that
reduces future volume rather than merely handling it faster.

---

## 3. Users

| User | What they need | Success looks like |
|---|---|---|
| **Customer** | A correct answer quickly, or a fast handover to a person who already understands the problem | Answer in seconds for documented questions; no wrong answers; no silent dead ends |
| **Tier one agent** | Fewer repetitive tickets; the ones they get arriving pre-triaged | Time spent on problems that need judgement, not on re-typing documented answers |
| **Tier two engineer** | Escalations arriving with context, classification and sources already attached | Less time reconstructing what the customer wants |
| **Head of support** | Measurable movement on FCR, response time and satisfaction; confidence the system will not embarrass them | Metrics per run, a decision log they can query, a kill switch they can use |
| **Technical writer** | To know which questions the documentation fails to answer | A prioritised gap list produced automatically, not gathered anecdotally |

---

## 4. Functional requirements

| ID | Requirement | Evidence | Priority | Implemented in | Verified by |
|---|---|---|---|---|---|
| FR-01 | Accept tickets from email, live chat, documentation comments and the community forum, and normalise them into one internal representation that preserves the original text and the channel | `E-04` | Must | `src/ingest.py` | `test_a2_*` |
| FR-02 | Assign an intent and an urgency to every ticket with a numeric confidence that reflects the actual probability of being correct, recording the alternatives considered | `E-05` | Must | `src/classify.py`, `src/calibration.py` | `test_a3_*` |
| FR-03 | Search the documentation corpus and return ranked passages whose identifiers resolve to real articles | `E-01` | Must | `src/retrieve.py` | `test_a4_retrieval_returns_resolvable_passages` |
| FR-04 | Return no passages at all when nothing clears the relevance threshold | `E-02` | Must | `src/retrieve.py` | `test_a4_threshold_returns_nothing_for_an_irrelevant_query` |
| FR-05 | Draft replies grounded only in the retrieved passages, stating plainly when the documentation is insufficient rather than filling the gap | `E-02`, `E-06` | Must | `src/generate.py`, prompt `P-ANSWER-001` | `test_a6_*` |
| FR-06 | Attach citations that resolve to the passages actually retrieved for that ticket | `E-06` | Must | `src/generate.py` | `test_a6_citations_resolve_to_retrieved_passages` |
| FR-07 | Decide between answering and escalating using thresholds determined from data, deterministically, recording the reason in language a support manager can read | `E-07` | Must | `src/route.py` | `test_a5_*` |
| FR-08 | Attach to every escalation a drafted summary, the retrieved sources, the classification and an explicit statement of what the system was unsure about | `E-03` | Must | `src/generate.py::escalation_note` | `test_a9_full_run_is_unattended_and_complete` |
| FR-09 | Validate every generated response before release and block, not warn, on private data, unsupported claims, commercial commitments or instruction leakage | `E-08` | Must | `src/guardrails.py` | `test_a7_*` |
| FR-10 | Never auto-answer security incidents, data loss, billing disputes, cancellations, legal matters or complaints, at any confidence level | `E-09` | Must | `src/route.py` rule R1 | `test_a5_protected_intents_never_auto_answer` |
| FR-11 | Write every automated decision to a persistent log carrying the input, prediction, confidence, sources, action and reason | `E-10` | Must | `src/decision_log.py` | `test_a8_*` |
| FR-12 | Process a file of tickets end to end, unattended, from a single command taking an input and an output path | `E-11` | Must | `evaluation/harness.py` | `test_a9_*` |
| FR-13 | Produce a metrics report at the end of a run without further manual work, covering volume, business, technical and governance measures | `E-11` | Must | `evaluation/metrics.py`, `report.py` | `test_a10_*` |
| FR-14 | Produce a prioritised list of questions the documentation could not answer | `E-02` | Must | `evaluation/metrics.py::_documentation_gaps` | `test_a10_metrics_report_is_produced` |
| FR-15 | Compare outcomes across customer tier, region and language fluency, reporting sample sizes | `E-12` | Must | `evaluation/metrics.py::_fairness` | `test_a10_metrics_report_is_produced` |
| FR-16 | Provide a means to stop automated replies without a code change, while continuing to classify, triage and log | `E-09` | Should | `src/api.py::kill_switch` | *manual* |
| FR-17 | Expose health and operational metrics for monitoring | `E-10` | Should | `src/api.py` | *manual* |

---

## 5. Non-functional requirements

| ID | Requirement | Target | Evidence | Implemented in | Verified by |
|---|---|---|---|---|---|
| NFR-01 | Response latency, 95th percentile | under 3s | `E-13` *[live chat abandonment]* | channel latency budgets, `src/models.py` | `metrics.technical.latency_seconds.p95` |
| NFR-02 | Intent classification precision | 85% or better | `E-05` | `src/classify.py` | `metrics.technical.intent_classification` |
| NFR-03 | Hallucination rate | 5% or lower | `E-06` | `src/guardrails.py` | `metrics.technical.grounding` |
| NFR-04 | Citation accuracy | 95% or better | `E-06` | `src/generate.py` | `metrics.technical.citations` |
| NFR-05 | Continue operating when the model provider is unavailable, throttling or timing out | no crash; degraded operation | `E-14` | `src/llm/provider.py` | `test_a11_*` |
| NFR-06 | Private data in outbound responses | zero occurrences | `E-08` | `src/guardrails.py` | `test_a7_private_data_blocks` |
| NFR-07 | Difference in outcome quality between customer groups | under 5 percentage points | `E-12` | `evaluation/metrics.py` | `metrics.fairness` |
| NFR-08 | Stated confidence against observed accuracy | within 5 percentage points | `E-05` | `src/calibration.py` | `metrics.governance.confidence_calibration` |
| NFR-09 | Decision log coverage | complete; every decision reconstructable | `E-10` | `src/decision_log.py` | `metrics.reconciliation.reconciles` |
| NFR-10 | Run from a clean checkout on a machine that is not the author's | works from the README alone | build spec | `README.md`, `scripts/verify_setup.py` | *clean-checkout rehearsal* |
| NFR-11 | Operating cost | zero — free tiers only | build spec | caching, rate limiting, `src/llm/provider.py` | *provider dashboard* |
| NFR-12 | No credential in committed source | zero | brief §9 | `.gitignore`, `.env.example` | CI credential scan |

---

## 6. Business success measures

The measures CloudServe is judged on, and which this system must move.

| Measure | Baseline | Target | How it is calculated |
|---|---|---|---|
| First contact resolution | 42% | 60%+ | tickets closed without escalation ÷ total |
| Escalation rate | 58% | 30% or lower | tickets passed to a human ÷ total |
| Time to first reply | 8–12 hours | under 5 minutes | mean interval between arrival and reply |
| Customer satisfaction | 3.2/5 | 4.0+ | mean rating across reviewed responses |
| Repeat contacts | not measured | halved | same customer, same issue, within 7 days |

**A measure this system introduces that CloudServe did not ask for:**

| Measure | Why it matters |
|---|---|
| Documentation gap count and priority order | Every entry is a question customers keep asking that the documentation does not answer. Closing them reduces *future* volume. Every other measure above only makes existing volume move faster. |

**A caveat that belongs in the report.** Time to first reply as measured by this system is
processing latency, not CloudServe's end-to-end time to first reply, because escalated tickets
still queue for a human. What improves for those is agent handling time, which cannot be
measured without before-and-after agent timings. This is the most important number the
evaluation cannot supply, and it should be stated rather than glossed.

---

## 7. Out of scope

Stated explicitly, because scope that is not written down is scope that is argued about later.

| Not building | Why |
|---|---|
| A customer-facing chat widget | The deliverable is the decision and delivery layer. CloudServe's existing channels are the front end. |
| Automated documentation *writing* | The system identifies gaps; a human writes the articles. Generating documentation from tickets would compound errors into the corpus the whole system grounds on. |
| Multilingual response generation | Detected as a fairness concern, not solved. Tickets in other languages are classified and escalated, and the gap is recorded. |
| Ticketing system integration | No target system specified. The harness and the API are the integration points. |
| Fine-tuning a model | Prohibited by the free-tier constraint, and retrieval quality dominates model quality on a corpus this size. |
| Automated actions on customer accounts | The system answers questions. It does not refund, provision, reset or cancel. See N3 and N4 in the governance framework. |
| Real-time documentation index updates | The corpus is re-indexed on start. A live corpus would need incremental indexing. |

---

## 8. Assumptions, and what happens if they are wrong

The section that separates a PRD from a wish list.

| # | Assumption | If it is wrong | How we would find out |
|---|---|---|---|
| A1 | A wrong automated answer costs roughly **8×** an unnecessary escalation | The routing threshold is wrong. The sensitivity table in `scripts/tune_thresholds.py` shows exactly how the threshold moves for ratios from 2:1 to 20:1 — re-running with the true ratio resets it in one step | Ask the head of support what a complaint actually costs to handle |
| A2 | A substantial share of tickets are answerable from the existing documentation | The deflection premise fails and the system becomes a triage tool only — still valuable, but the business case changes shape | Measured directly from the `answerable_from_docs` labels |
| A3 | The documentation corpus is broadly accurate | Grounded answers propagate documented errors with a citation attached, which is *worse* than an ungrounded guess because it carries authority | Sample audit of sent answers against reality |
| A4 | Confidence calibrated on development data holds on unseen tickets | Thresholds drift and the system either over-answers or over-escalates | ECE recomputed on every run and reported |
| A5 | The hidden set uses the same schema as the development set | Ingest fails. Mitigated by tolerant field mapping and a loader that accepts several file shapes | The run either produces tickets or does not, visibly, in the first log lines |
| A6 | Free-tier capacity suffices for a full run | The run cannot complete. Mitigated by caching, rate limiting and backoff | Provider dashboard; 429 counts in the run log |
| A7 | Agents will read escalation notes rather than trusting drafts blindly | Automation complacency: a wrong draft gets sent by a human instead of by the system | Sample audit of escalations; see risk R11 |

---

## 9. Traceability

The chain an assessor follows: **evidence → requirement → prompt or component → test**.

| Evidence | Requirement | Built as | Verified by |
|---|---|---|---|
| `E-01` share answerable from docs | FR-03 | `src/retrieve.py` | `test_a4_retrieval_finds_the_right_article` |
| `E-02` share *not* answerable | FR-04, FR-05, FR-14 | relevance floor; `P-ANSWER-001` insufficient-context branch; gap report | `test_a4_threshold_returns_nothing_for_an_irrelevant_query` |
| `E-03` agent time reconstructing context | FR-08 | `P-ESCALATE-001`, `escalation_note` | `test_a9_full_run_is_unattended_and_complete` |
| `E-04` four channels behave differently | FR-01 | `src/ingest.py`, channel latency budgets | `test_a2_all_four_channels_normalise` |
| `E-05` intent distribution and ambiguity | FR-02, NFR-02, NFR-08 | `P-CLASSIFY-001`, `src/calibration.py` | `test_a3_*` |
| `E-06` cost of a wrong answer | FR-05, FR-06, NFR-03, NFR-04 | grounding guardrail, citation resolution | `test_a7_ungrounded_text_blocks` |
| `E-07` escalation cost vs wrong-answer cost | FR-07 | `scripts/tune_thresholds.py`, `src/route.py` | `test_a5_same_input_gives_the_same_decision` |
| `E-08` sensitive content in tickets | FR-09, NFR-06 | `src/guardrails.py` | `test_a7_private_data_blocks` |
| `E-09` irreversible-decision categories | FR-10, FR-16 | router rule R1, kill switch | `test_a5_protected_intents_never_auto_answer` |
| `E-10` audit and accountability needs | FR-11, FR-17, NFR-09 | `src/decision_log.py` | `test_a8_every_ticket_produces_a_log_row` |
| `E-11` volume and unattended operation | FR-12, FR-13 | `evaluation/harness.py` | `test_a9_*`, `test_a10_*` |
| `E-12` customer group differences | FR-15, NFR-07 | `evaluation/metrics.py::_fairness` | `metrics.fairness` |
| `E-13` live chat abandonment | NFR-01 | per-channel latency budgets and response length | `metrics.technical.latency_seconds` |
| `E-14` provider reliability | NFR-05 | `src/llm/provider.py` | `test_a11_*` |

**Prompt register** — every prompt, its version and the requirement it serves, is in
`src/llm/prompts.py`. Keeping it in code rather than in a document means the register and the
strings the system actually sends cannot drift apart. `prompts.register_rows()` emits it in
the shape the Stage 3 workbook table wants.

---

## 10. Acceptance criteria for v1

v1 is complete when all twelve build-specification criteria pass, the full validation set
processes unattended in one command, the decision log reconciles, at least one guardrail
demonstrably blocks, and the metrics report is produced without manual work.

Mapping from acceptance criterion to requirement:

| A# | Requirement |
|---|---|
| A1 | NFR-10 |
| A2 | FR-01 |
| A3 | FR-02 |
| A4 | FR-03 |
| A5 | FR-07 |
| A6 | FR-06 |
| A7 | FR-09 |
| A8 | FR-11 |
| A9 | FR-12 |
| A10 | FR-13 |
| A11 | NFR-05 |
| A12 | *test suite* |
