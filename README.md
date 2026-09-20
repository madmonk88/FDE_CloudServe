# FDE Capstone — CloudServe Solutions

**Forward Deployed AI Engineering capstone. Individual submission by Balakumaran SV.**

An intelligent triage, deflection and escalation system for CloudServe Solutions'
customer support function.

CloudServe asked for a chatbot. This is not one, and
[`04_Source_Code/README.md`](04_Source_Code/README.md) explains why in detail.
The short version is that their incoming volume splits into three populations
needing three different things, a chatbot addresses one of them, and it is
actively dangerous applied to another.

---

## Running the system

**The runnable repository is [`04_Source_Code/`](04_Source_Code/).** Everything
an assessor needs is there, and its README is written for someone who has never
seen this project.

```bash
git clone https://github.com/madmonk88/FDE_CloudServe.git
cd FDE_CloudServe/04_Source_Code

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then set OPENROUTER_API_KEY
python -m scripts.verify_setup     # checks every assumption before you rely on it

# the single unattended command the project turns on
python -m evaluation.harness --input data/validation_tickets.json --output evaluation/results/

# the tests
python -m pytest tests/ -v
```

`--input` and `--output` are arguments, not defaults. The harness accepts any
file in the ticket schema, including one it has never seen.

---

## Repository layout

The four numbered folders are the submission structure mandated by
`00_Provided_Pack/04_Submission/Submission_Guide.docx`, in the prescribed order
and with the prescribed names.

| Folder | Contents | Status |
|---|---|---|
| [`01_Video/`](01_Video/) | The twenty-minute recording, or a link to it. Currently holds the shot-by-shot script. | script ready, not yet recorded |
| [`02_Report/`](02_Report/) | The report as a single PDF. `drafts/` holds the source material it is assembled from. | drafts complete, PDF pending |
| [`03_Workbooks/`](03_Workbooks/) | The five completed stage workbooks and the effort log. | Stage 1 complete; 2–5 pending |
| [`04_Source_Code/`](04_Source_Code/) | The complete runnable repository. | complete, 48 tests passing |
| [`00_Provided_Pack/`](00_Provided_Pack/) | The capstone pack exactly as supplied — brief, specifications, templates, datasets. | reference input |

`00_Provided_Pack/` is committed so the work is reproducible from a single
clone: the analysis scripts read the datasets, and the claims in the report can
be checked against the documents they came from. **It is not part of the
submission archive.** The submission guide is explicit that the archive
contains exactly four top-level folders, so `scripts/build_submission.py`
excludes it.

### Building the submission archive

```bash
python 04_Source_Code/scripts/build_submission.py
```

Produces `BalakumaranSV_Capstone_Submission.zip` containing exactly the four
mandated folders, and prints the final checklist from the submission guide with
each item marked against what is actually present.

---

## Where the work is

Reading order, if you want to follow the argument rather than the code:

1. **[`03_Workbooks/`](03_Workbooks/) — the discovery workbook.** The evidence,
   and five places where the stakeholder interviews disagree with each other or
   with the ticket data. Start here; everything else follows from it.
2. **[`02_Report/drafts/PRD_v1.md`](02_Report/drafts/PRD_v1.md)** — the
   requirements, each traced back to a discovery finding and forward to the code
   and the test that verifies it.
3. **[`04_Source_Code/docs/ARCHITECTURE.md`](04_Source_Code/docs/ARCHITECTURE.md)**
   — the system, and the one part of it that is unusual.
4. **[`02_Report/drafts/governance_framework.md`](02_Report/drafts/governance_framework.md)**
   — risk register, fairness audit, decision logging, incident procedure, kill
   switch, and a list of what is *not* implemented.
5. **[`02_Report/drafts/PRD_revision_log.md`](02_Report/drafts/PRD_revision_log.md)**
   — what version one got wrong.

## The three findings the project rests on

**Seven in ten tickets are answerable from documentation that already exists
and is already correct.** 71.4% of the 500 development tickets carry
`answerable_from_docs`. The technical writer diagnosed precisely why nobody
finds them: internal search matches article titles, and customers do not use
title vocabulary. This is a delivery problem, not a knowledge problem.

**107 tickets per 500 were escalated despite being answerable — 21.4% of
volume consuming 36.8% of all agent hours.** One fifth of the tickets, over a
third of the time, and none of them needed a second person. This is the largest
recoverable cost in the operation and nobody currently measures it.

**CloudServe's routing policy is recoverable from their own labels.** A
three-clause rule reproduces `expected_route` on 500/500 development tickets
and 80/80 validation tickets, with validation held out during the derivation,
and produces zero `must_not_auto_respond` violations across all 580.
`python -m scripts.derive_policy` reproduces the whole derivation.

---

## Declaration of AI tool use

Portions of this codebase and the accompanying documents were produced with AI
assistance (Claude). The data analysis, the recovered routing policy, the
threshold derivations and the evaluation figures are reproducible from the
scripts in `04_Source_Code/scripts/`, and every design decision is documented
with its reasoning in the file that implements it. Third-party libraries are
listed with pinned versions in `04_Source_Code/requirements.txt`.

See `04_Source_Code/README.md` for the full attribution section.
