# Governance framework

**System:** CloudServe Support Intelligence
**Owner:** Bala (Forward Deployed AI Engineering capstone)
**Status:** pre-deployment. Nothing in this system has spoken to a real customer.

This document covers the five things the brief requires: a risk register with named
mitigations and accountable owners, decision logging with its schema, a fairness audit with
its method and sample size, an incident procedure specific enough to follow at two in the
morning, and a stated position on what the system must never do together with the mechanism
that enforces it.

One principle runs through all of it. The question that separates governance from theatre is
*what would have to go wrong for this system to harm a real customer, and what in the design
would actually stop it?* Wherever the honest answer is "the model is usually reliable", that
is a hope rather than a control, and it is marked as such below.

---

## 1. What this system must never do

Five absolute positions. Each one has a mechanism, and each mechanism is a line of code
rather than an instruction to the model.

| # | The system must never… | Mechanism | Where |
|---|---|---|---|
| N1 | Send a factual claim that is not supported by the retrieved documentation | `unsupported_claims` guardrail: sentence-level grounding scored against the passages actually retrieved; blocks below threshold | `src/guardrails.py` |
| N2 | Include private data — credentials, keys, card numbers, personal identifiers — in an outbound reply | `private_data` guardrail; blocks unconditionally; evidence is redacted in the log itself | `src/guardrails.py` |
| N3 | Commit CloudServe commercially — refunds, credits, compensation, delivery dates, guarantees | `prohibited_commitment` guardrail; blocks | `src/guardrails.py` |
| N4 | Auto-answer a security incident, data loss, billing dispute, cancellation, legal matter or complaint | Rule R1 in the router; fires before any threshold is consulted, so no confidence level unlocks it | `src/route.py` |
| N5 | Be redirected by instructions embedded in a customer's ticket | Structural separation: instructions and sources in the system message, customer text in a separate user message inside a delimiter the customer cannot close; plus the `injection_leak` guardrail as defence in depth | `src/llm/prompts.py`, `src/guardrails.py` |

**Why these are mechanisms rather than prompt instructions.** A prompt instruction is a
request; the model complies most of the time. N1 through N5 are conditions that must hold
every time, so each is enforced in code that runs after the model has produced its output and
before anything is released. The prompts also carry these rules, because defence in depth is
cheaper than choosing, but the prompts are not what makes the conditions true.

---

## 2. Risk register

Likelihood and impact are assessed for a deployment at CloudServe's stated scale — roughly
500 tickets a week across four channels, with automated replies going to paying business
customers without a human reading them first.

| ID | Risk | Likelihood | Impact | Rating | Mitigation | Residual | Owner |
|---|---|---|---|---|---|---|---|
| R01 | The system sends a confident, fluent answer that is factually wrong | High without controls | High | **Critical** | Grounding guardrail blocks ungrounded drafts (N1); retrieval returns nothing rather than something irrelevant; routing requires both classification confidence and retrieval support; citations resolved against retrieved passages | Medium — grounding is a similarity measure, not a truth measure, and a sentence can be similar to a passage that does not actually support it | Engineering owner |
| R02 | Customer personal data leaks into an outbound reply or into logs | Medium | High | **Critical** | PII guardrail blocks unconditionally; detections redacted before being written to evidence; zero occurrences is a condition, not a target | Low | Engineering owner |
| R03 | Prompt injection via ticket content redirects the system | Medium — this is a public support channel, so it will be attempted | High | **Critical** | Structural channel separation (N5); delimiter injection-proofed; output scanned for leakage; protected intents unreachable by routing | Low–Medium — no injection defence is complete | Engineering owner |
| R04 | The system commits CloudServe to a refund or a delivery date | Medium — models comply with pushy customers | High | **High** | Commitment guardrail (N3); billing disputes and cancellations never auto-answer (N4) | Low | Support lead |
| R05 | Quality differs systematically across customer groups | Medium — likely for customers writing in a second language, whose phrasing matches the documentation's vocabulary less well | High | **High** | Fairness audit per run across tier, region and fluency; condition is under 5 points of difference; reported in every metrics run | Medium — the audit detects, it does not prevent | Support lead |
| R06 | Stated confidence does not reflect actual accuracy, so the routing threshold means nothing | High without calibration | High | **High** | Isotonic calibration fitted on the development set; ECE reported every run; uncalibrated decisions flagged in the log | Low–Medium — calibration fitted on development data may drift | Engineering owner |
| R07 | Model provider outage stops support entirely | High — free tiers throttle and degrade | Medium | **High** | Circuit breaker, cache, backoff with jitter, self-imposed rate limit; deterministic fallback classifies, retrieves, routes and escalates with context; fallback confidence capped below the routing threshold | Low — service degrades to triage-only, never stops | Engineering owner |
| R08 | Ticket volume grows and the documentation gap widens rather than closing | Medium | Medium | **Medium** | Documentation gap report produced every run and ordered by frequency; this is the feedback loop that reduces future volume | Medium — depends on someone acting on the report | Technical writer |
| R09 | The system escalates so much that it saves nobody any work | Medium | Medium | **Medium** | Threshold chosen on expected cost with a sensitivity table; escalations carry context packages, so even 100% escalation improves handling time | Low | Support lead |
| R10 | The decision log is incomplete, so a bad answer cannot be explained afterwards | Low | High | **Medium** | Failures logged as well as successes; reconciliation run automatically at the end of every run and reported | Low | Engineering owner |
| R11 | Agents stop reading escalations carefully because the draft is usually right | Medium | Medium | **Medium** | Escalation note states explicitly what the system was *unsure about*, not only what it concluded; blocked drafts are labelled as blocked | Medium — this is a human factors risk that code cannot close | Support lead |
| R12 | Evaluation figures are tuned against the test set until they look good | Low | High | **Medium** | Validation set used once; evaluation date and run count reported; calibration and thresholds fitted only on development data | Low | Engineering owner |

**On R01 and R11.** These are the two where the residual risk is genuinely Medium and no
further code closes them. R01 is bounded by the nature of similarity-based grounding: a
sentence can score well against a passage that does not actually support it. R11 is a human
factors risk — automation complacency — and the honest mitigation is operational, not
technical: sample audited escalations weekly, and report the sample size.

---

## 2a. What the evaluation actually found

A risk register written before a system runs is a set of predictions. This section records
which of them the evaluation confirmed, because a register that is never checked against
reality is a filing exercise.

**Confirmed, and worse than assessed.**

R06 (stated confidence does not reflect actual accuracy) was rated High before mitigation and
the mitigation did not fully work. Measured expected calibration error was 0.545 uncalibrated
and 0.144 after fitting, against a condition of 0.05. The direction is right and the magnitude
is not. Thirty-one of eighty decisions in the final run used uncalibrated confidence because
they ran on the degraded path, which has no calibration mapping — a gap in the mitigation that
was not anticipated when the risk was written.

R05 (quality differs systematically across customer groups) was rated High and the audit found
gaps on all three attributes: 24.8 percentage points across customer tier, 7.8 across language
fluency and 6.9 across region, against a condition of five. Part of that is uneven degradation
during the run, but the tier gap is too large to attribute to that alone. This is now a
finding rather than a risk, and it is the one to act on first.

**Confirmed, and the mitigation held.**

R07 (model provider outage stops support entirely) occurred three times in different forms:
one provider retired the model, a second had no equivalent model available to the key, and the
third rate-limited to exhaustion mid-run. In every case the system degraded and completed.
Thirty-four of eighty tickets in the final run were processed on the deterministic path, and
every one of them escalated with a context package rather than being answered. Zero automated
replies came out of degraded operation, which is the property the mitigation claimed.

R02 (private data leaks into a reply) recorded zero detections and zero releases across every
run. The control has not been exercised in anger, so this is an absence of evidence rather
than evidence of absence.

**Not yet testable.**

R01 (the system answers confidently and incorrectly) remains the largest residual risk and the
evaluation cannot settle it. Grounding and citation resolution are proxies; no human read a
sample of sent replies. R11 (agents stop reading escalations) requires a deployment to observe
at all.

**A risk the register missed.**

Retrieval returning something for every query was not on the register, and it should have
been. The relevance floor was silently ineffective for an entire evaluation run: passages were
returned for 100 per cent of tickets the labels said were unanswerable, and the documentation
gap report — a named business output — came out empty without anything failing. It was caught
by a test rather than by the register.

The lesson for the register itself is that it listed risks about the system producing wrong
output and none about the system producing no output while appearing to work. A control that
fails open and silent is a category this register did not have.

## 3. Decision logging

### Why it is designed on day one

Governance added at the end is shallow, because the design decisions that would have made it
meaningful were taken weeks earlier. The decision log here is a first-class table with named
columns rather than a JSON blob, because a field that has to be parsed out of a blob is a
field nobody will ever query, and the point of this log is that someone unfamiliar with the
system can answer *why did it say that?* months later without reading any code.

### Schema

`storage/decisions.sqlite3`, table `decisions`. Every automated decision, one row.

| Field | What it holds | Why it is required |
|---|---|---|
| `run_id`, `ticket_id`, `processed_at` | identity and time | ties a decision to a run and a ticket |
| `channel`, `customer_tier`, `region` | who and where from | the fairness audit is computed from these |
| `input_text` | the ticket as the system saw it | **the input**: without it, a decision cannot be reconstructed |
| `predicted_intent`, `predicted_urgency` | **the prediction** | |
| `confidence`, `confidence_calibrated` | **the confidence**, and whether it was calibrated | a confidence with no calibration flag overclaims silently |
| `classification_method` | llm, rules fallback, empty ticket, pipeline error | distinguishes a degraded decision from a normal one |
| `alternatives` | what else was considered, with scores | a decision between two near-equal options is a different decision from a confident one |
| `sources_used`, `top_source_score`, `retrieved_count` | **the sources** | citations are verified against this |
| `action`, `rule_fired`, `reason` | **the action and the reason** | `reason` is written for a support manager, not an engineer |
| `response_text`, `citations` | what was actually sent | |
| `guardrails_triggered`, `guardrails_blocked`, `guardrail_detail` | what each control checked and found | controls that leave no evidence when they pass cannot be audited |
| `grounding_score` | how well the draft traced to its sources | |
| `latency_seconds`, `degraded`, `error` | operational context | |

### Reconciliation

A8 is checked by counting logged decisions against tickets processed. The system runs that
check on itself at the end of every run and publishes the answer in `metrics.json` under
`reconciliation`. Failed tickets are logged too — a log recording only successes would not
reconcile, and the gap would be immediately visible.

```sql
-- the check an assessor runs
SELECT run_id, COUNT(*) AS decisions, COUNT(DISTINCT ticket_id) AS tickets
FROM decisions GROUP BY run_id;

-- why did the system say that?
SELECT predicted_intent, confidence, sources_used, action, rule_fired, reason
FROM decisions WHERE ticket_id = ?;
```

### Retention and access

Decision rows contain customer ticket text and are therefore personal data. For a real
deployment: 90 days at full fidelity, then `input_text` and `response_text` redacted with the
decision metadata retained indefinitely for audit. Access restricted to the support lead and
the engineering owner. **This is a stated policy, not an implemented one** — the retention job
is not built, and saying so is more useful than implying otherwise.

---

## 4. Fairness audit

### Method

Every evaluation run computes outcome differences across three attributes carried by the
dataset. The method is in `evaluation/metrics.py`, function `_fairness`, and runs
automatically rather than as a separate exercise.

**Attributes compared**

- **Customer tier** — the commercial fairness question: do smaller customers get a worse
  service from the automation than enterprise ones?
- **Region** — geographic and, indirectly, timezone effects.
- **Language fluency** — *the one that matters most here.* A retrieval-based system
  disadvantages customers writing in a second language through no fault of their own: their
  phrasing matches the documentation's vocabulary less closely, so retrieval scores lower,
  so more of their tickets fall below the threshold and escalate. A system built on lexical
  similarity has this bias structurally, not incidentally, and it will not appear unless
  someone looks for it.

**Measures compared per group:** automation rate, mean calibrated confidence, mean grounding
score.

**Condition:** under five percentage points of difference between groups.

**Sample size handling.** Groups with fewer than ten tickets are reported but excluded from
the comparison and flagged `sufficient_sample: false`. A gap computed over four tickets is
not evidence, and quietly dropping small groups, or quietly treating them as evidence, are
both worse than saying which happened. The report states the denominator for every group.

### What the audit does not cover

Stated plainly, because an audit whose limits are not stated implies coverage it does not
have:

1. **It measures outcomes, not correctness by group.** Equal automation rates across groups
   are consistent with one group receiving worse *answers*. Measuring that needs per-group
   quality scoring against reference answers, which the ground truth set supports but which
   this audit does not yet do.
2. **It uses the attributes the dataset carries.** It cannot audit attributes that were never
   recorded.
3. **It is computed per run.** Drift between runs is not tracked.
4. **Fluency is a supplied label**, not a measurement, and its reliability is unknown.

### If the condition fails

A gap over five points is a finding, not a failure to hide. The response, in order: confirm
the gap is not a sample-size artefact; identify which stage produces it, by comparing
retrieval scores and confidence separately across groups; if retrieval is the cause, the fix
is corpus-side — the documentation needs the vocabulary customers actually use, which is a
documentation gap of a different kind; if classification is the cause, the calibration should
be refitted with the affected group adequately represented.

---

## 5. Incident response procedure

Written to be followed by someone who did not build the system, at two in the morning,
without access to an engineer.

### What counts as an incident

| Severity | Definition | Response time |
|---|---|---|
| **SEV1** | A wrong or harmful reply reached a customer; private data was released; the system is answering when it should be escalating | immediate |
| **SEV2** | Systematic quality degradation; the fairness condition breached; the decision log not reconciling | same working day |
| **SEV3** | Model provider outage; elevated escalation; latency breach | next working day |

A provider outage is **SEV3, not SEV1**, because the system is designed to survive it: it
degrades to triage-only and escalates everything with context. Support becomes slower, not
absent.

### SEV1: first five minutes

**Step 1. Stop the automation. Do this before diagnosing anything.**

```bash
curl -X POST http://127.0.0.1:8000/admin/kill-switch \
  -H 'Content-Type: application/json' \
  -d '{"enabled": false, "reason": "SEV1 — <one line on what you saw>"}'
```

Confirm it took effect:

```bash
curl -s http://127.0.0.1:8000/health | grep automation_enabled   # expect false
```

**What this does and does not do.** It stops automated replies being sent. It does *not* stop
the system: tickets still arrive, are still classified, retrieved for and logged, and every
one goes to the human queue with its context package attached. This is deliberate — losing
the automation is survivable, losing the triage is not. Nobody needs to weigh "should I take
it down?" against "will support collapse?", which is the hesitation that turns a five-minute
incident into an hour.

If the API is unreachable, set `AUTOMATION_ENABLED=false` in the environment and restart. If
that is not possible either, revoke the model provider API key — the system detects the
provider as unavailable and every ticket escalates.

**Step 2. Tell the support lead.** They need to know the human queue is about to grow.

**Step 3. Find out what the system did and why.**

```bash
sqlite3 storage/decisions.sqlite3 \
  "SELECT processed_at, predicted_intent, confidence, confidence_calibrated,
          sources_used, action, rule_fired, reason, guardrails_triggered, response_text
   FROM decisions WHERE ticket_id = '<ticket id>';"
```

The `reason` column is written in plain language. `sources_used` gives the chunk ids the
answer was based on; resolve them against the corpus to see whether the sources supported the
claim or whether grounding passed something it should not have.

**Step 4. Establish the blast radius.** How many other tickets went out on the same path?

```bash
sqlite3 storage/decisions.sqlite3 \
  "SELECT ticket_id, processed_at, response_text FROM decisions
   WHERE action = 'answer' AND predicted_intent = '<intent>'
     AND processed_at > '<incident window start>';"
```

**Step 5. Contain.** If customers received a wrong answer, the support lead sends corrections.
The ticket ids and the exact text sent are in the log.

### Before turning automation back on

All four, in order:

1. The cause is identified and either fixed or excluded — for example by adding the intent to
   `always_escalate_intents` in `src/config.py`, which takes effect on restart and cannot be
   bypassed by any threshold.
2. A test reproducing the failure exists in `tests/` and passes.
3. The full validation set has been re-run and its metrics compared against the previous run.
4. The support lead has agreed.

Then re-enable with a reason recorded, and watch `GET /metrics` for the first hour.

### Post-incident record

Within two working days: what happened, when it was detected and by whom, how long it ran,
how many customers were affected, the root cause, what was changed, and — the question that
matters most — **what would have caught this earlier**. That last answer becomes a test, a
metric or a guardrail, or it was not really an answer.

---

## 6. The kill switch

**What it is.** `POST /admin/kill-switch`, reachable by the support lead without a deployment,
an engineer, or a code change.

**Why it exists.** A system that speaks to paying customers without a human reading its output
first needs a way to be stopped by someone who is not an engineer, at any hour. If stopping it
requires a deployment, it will not be stopped quickly, and the incidents that need it most are
the ones happening at three in the morning.

**Its designed behaviour under failure.** Turning automation off degrades the system to
triage-only rather than stopping it. Classification, retrieval, routing and logging continue;
every ticket goes to the human queue carrying its draft, sources and reason. The decision to
use it is therefore never a decision to take support offline, which is what makes it usable in
practice rather than only in principle.

**Its limits, stated.** It is in-process. In a real deployment it must be a flag in shared
configuration that every instance reads, so that flipping it stops the fleet rather than one
process. It is also unauthenticated in this build, which is acceptable for an assessment on
localhost and would not be acceptable in production.

---

## 7. What is not implemented

Listing these is part of the governance, not an admission against it. A framework that claims
complete coverage is less trustworthy than one that says where it stops.

| Gap | Consequence | What would close it |
|---|---|---|
| Log retention and redaction are stated policy, not a running job | Customer text accumulates indefinitely | A scheduled redaction job over rows past 90 days |
| The kill switch is in-process and unauthenticated | Does not stop a fleet; anyone reaching the port can flip it | Shared configuration flag plus authentication |
| The fairness audit measures outcomes, not per-group answer quality | Equal automation rates could mask unequal answer quality | Per-group scoring against the ground truth reference answers |
| Calibration is fitted once, on development data | Drifts as ticket mix changes | Periodic refit against recently labelled tickets |
| Grounding is a similarity measure | A sentence can score well against a passage that does not support it | Claim-level entailment checking rather than sentence similarity |
| No human review queue for sampled *sent* answers | Wrong answers are found by complaint rather than by audit | Sample 5% of sent replies for weekly human review |
| Monitoring exposes metrics but no alerts are configured | Degradation is visible but nobody is told | Prometheus alert rules on escalation rate, guardrail blocks and provider availability |

The first and last of these are the two worth doing first if this were going further: the
retention job because it is a compliance obligation rather than an engineering preference,
and the alerting because a metric nobody is paged on is a metric nobody reads.
