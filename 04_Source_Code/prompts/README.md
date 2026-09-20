# Prompt library

Every prompt the system sends, as a versioned file. One file per prompt.

These files are the canonical text. `src/llm/prompts.py` loads them at import
and falls back to embedded defaults only if a file is missing, so editing a
prompt here changes the system's behaviour without touching code — and a
prompt change appears in the commit history as a prompt change rather than
buried inside a Python diff.

## The register

| File | ID | Version | Serves | Purpose |
|---|---|---|---|---|
| `p-classify-001.json` | P-CLASSIFY-001 | 1.2.0 | FR-02 | Assign intent and urgency with a confidence and the alternatives considered |
| `p-classify-user-001.json` | P-CLASSIFY-USER-001 | 1.0.0 | FR-02 | Carry the ticket to the classifier without mixing it into the instruction |
| `p-answer-001.json` | P-ANSWER-001 | 1.3.0 | FR-05, FR-06, NFR-03 | Draft a reply grounded only in the retrieved passages |
| `p-answer-user-001.json` | P-ANSWER-USER-001 | 1.0.0 | FR-05 | Carry the ticket to the generator, separated from the instruction |
| `p-escalate-001.json` | P-ESCALATE-001 | 1.1.0 | FR-08 | Write the handover note an agent reads before picking up an escalation |
| `p-judge-001.json` | P-JUDGE-001 | 1.0.0 | EV-04 | Score a draft against a senior agent's reference answer (evaluation only) |

`python -c "from src.llm.prompts import register_rows; print(register_rows())"`
emits this register in the shape the Stage 3 workbook table wants.

## Fields

| Field | Meaning |
|---|---|
| `id` | Stable identifier. Referenced from the PRD and the Stage 3 workbook. |
| `version` | Semantic. The minor number moves when the instruction changes in a way that changes behaviour. |
| `requirement` | The PRD requirement this prompt exists to satisfy. This is the traceability link. |
| `purpose` | One sentence: what the prompt is for. |
| `notes` | Why it is worded as it is, including what earlier versions got wrong. |
| `template` | The text, with `{placeholders}` filled by the caller. |

The `notes` field is the part worth reading. It records the failures that
produced each revision — for example, P-CLASSIFY-001 moved to 1.2.0 because
the first version returned 0.95 for nearly every ticket, which made the
routing threshold meaningless before calibration was applied.

## The rule every prompt observes

Customer text is never concatenated into an instruction. It travels in a
separate user message, inside the `<<<TICKET_CONTENT>>>` delimiter, and
`wrap_customer_text()` strips the delimiter from the customer's own text so it
cannot be closed early.

Asking a model politely not to be redirected is not a control. Separating the
channels is. The prompts also state the boundary in words, because defence in
depth costs nothing here, but the structural separation is what actually holds.

## Changing a prompt

1. Edit the `template` in the file.
2. Raise the `version`.
3. Add a line to `notes` saying what changed and what prompted it.
4. Run `python -m pytest tests/ -q`.
5. Re-run the evaluation before trusting the change — a prompt edit can move
   classification confidence, and confidence feeds the routing threshold.

Step 5 matters more than it looks. The prompt, the calibration mapping and the
routing threshold are coupled: changing the first invalidates the second,
which invalidates the third.
