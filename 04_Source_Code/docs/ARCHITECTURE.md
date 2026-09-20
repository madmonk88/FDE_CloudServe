# Architecture

## The shape of the system

```
   email ─┐
   chat ──┤                                            ┌──────────────┐
   docs ──┼──▶ 1 INGEST ──▶ 2 CLASSIFY ──▶ 3 RETRIEVE ─┤              │
   forum ─┘     normalise    intent,         hybrid    │  4 GENERATE  │
                one shape    urgency,        search    │  grounded    │
                             calibrated      over 29   │  draft +     │
                             confidence      articles  │  citations   │
                                                       └──────┬───────┘
                                                              │
                                                    ┌─────────▼─────────┐
                                                    │   5 VALIDATE      │
                                                    │   four guardrails │
                                                    │   that can block  │
                                                    └─────────┬─────────┘
                                                              │
                                                    ┌─────────▼─────────┐
                                                    │   6 ROUTE         │
                                                    │   ordered rules,  │
                                                    │   first match     │
                                                    └─────────┬─────────┘
                                               ┌──────────────┴──────────────┐
                                               ▼                             ▼
                                     send to customer              human queue, carrying
                                     with citations                draft + sources + the
                                                                   reason it did not send
                                               └──────────────┬──────────────┘
                                                              ▼
                        decision log (SQLite) · metrics report · documentation gap list
```

Three concerns cut across all six components rather than sitting at the end of
them: the decision log, the guardrails, and degraded operation. Each is built
in from the first commit, because all three are the kind of thing that becomes
decorative if bolted on later.

## Why generation runs before routing

The ordering above is not the obvious one. The natural instinct is to route
first and only generate when the routing says to answer, which would save the
model calls spent on drafts that are never sent.

It is wrong here, because one of the routing conditions is *how well the draft
is grounded in what was retrieved*, and that cannot be known until the draft
exists. A system that routes first can check that retrieval found something; it
cannot check that the answer it would have written is actually supported.

The apparently wasted drafts are not wasted either. A draft that does not get
sent travels with the escalation, where an agent uses it as a starting point.
Daniel, the tier two engineer, put it plainly in discovery: *"I do not need it
to be right. I need it to show its working."*

## The three layers

```
  ┌──────────────────────────────────────────────────────────┐
  │  INTERFACE      api.py · harness.py                      │
  ├──────────────────────────────────────────────────────────┤
  │  DOMAIN         ingest · classify · retrieve · generate   │
  │                 guardrails · route · pipeline · models   │
  ├──────────────────────────────────────────────────────────┤
  │  INFRASTRUCTURE llm/provider.py · decision_log.py        │
  │                 (model provider, vector store, SQLite)   │
  └──────────────────────────────────────────────────────────┘
```

The domain layer never imports a provider SDK and never opens a database
connection. That is what makes the whole system testable without a network,
which is why the test suite runs with no API key — and why the suite is
itself the standing proof that acceptance criterion A11 holds.

## Where each decision lives

| Decision | File | Defended in |
|---|---|---|
| Channel normalisation and tolerant field mapping | `src/ingest.py` | Report §4.2 |
| Chunking strategy | `src/retrieve.py` | Report §4.3 |
| Hybrid dense + lexical scoring | `src/retrieve.py` | Report §4.3 |
| Absolute rather than per-query score scale | `src/retrieve.py` | Revision log, change 6 |
| Confidence calibration | `src/calibration.py` | Report §5.2 |
| Answerability prediction | `src/answerability.py` | Report §5.2 |
| The routing policy | `src/route.py` | Report §4.5 |
| Guardrails | `src/guardrails.py` | Report §6 |
| Provider failure handling | `src/llm/provider.py` | Report §4.7 |
| Decision log schema | `src/decision_log.py` | Governance framework §3 |

Every tunable number is in `src/config.py`, with the reason for its value in a
comment beside it. A number you cannot find is a number you cannot justify.

## The part that is unusual

Most of this architecture is conventional retrieval-augmented generation. One
part is not, and it is where the design work actually went.

**The routing policy was recovered from the client's data rather than
designed.** `development_tickets.json` labels every ticket with
`expected_route`. Treating that as a target and searching for the simplest
rule that reproduces it yields a three-clause policy that matches 500 of 500
development tickets and 80 of 80 validation tickets, with validation held out
during the derivation. `python -m scripts.derive_policy` reproduces it.

That result relocates the engineering problem. The policy is not where
judgement is needed. One of its three inputs — whether the documentation can
answer the ticket — is a label during development and an unknown at serving
time, and it decides more routing outcomes than the other two combined. So the
real problem is predicting answerability, and `src/answerability.py` explains
why the obvious approach (threshold the retrieval score) is not good enough:
measured, it separates answerable from unanswerable tickets with an AUC of
about 0.58, because a feature request is not unanswerable for want of a
topically similar passage.

## Failure modes designed against

| Failure | What happens |
|---|---|
| Model provider unreachable | Circuit breaker opens; rules-based classification, lexical retrieval, everything escalates with context. The fallback's confidence is capped *below* the routing threshold by construction, so a degraded run cannot auto-answer. |
| Embedding model unavailable | Retrieval degrades to lexical-only and says so in the run log and the metrics. |
| Retrieval finds nothing relevant | Returns an empty list. The router escalates and records a documentation gap. |
| A ticket breaks the pipeline | Caught per ticket, logged, escalated, run continues. No ticket is silently dropped. |
| The process is killed mid-run | Results flush every 10 tickets; `--resume` continues. |
| A ticket tries to redirect the system | Structural channel separation, plus an output scan as defence in depth. |
| The decision log write fails | Logged loudly, run continues. Logging must not be able to fail a good ticket. |

## What is deliberately absent

No fine-tuning: retrieval quality dominates model quality on a 29-article
corpus, and the free-tier constraint rules it out anyway. No agent framework
with autonomous tool selection: the routing decision must be deterministic for
A5, and a planner choosing its own path is the opposite of that. No learning
from past replies: the tier two engineer's warning in discovery was explicit —
personal snippet files contain answers that were correct two years ago, and
learning from them would scale up a mistake.
