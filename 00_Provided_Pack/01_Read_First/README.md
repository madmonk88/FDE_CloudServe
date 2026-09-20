# Forward Deployed AI Engineering — Capstone Project

## An intelligent customer support system for CloudServe Solutions

**This is an individual project. The submission deadline is 13 September at 23:59.**

**The deliverable is working software.** Before anything else is marked, your repository is
checked out onto a machine that is not yours and your harness is asked to process the full
validation set unattended. `01_Read_First/02_Build_Specification.docx` defines exactly what
that means, criterion by criterion.

**It costs nothing.** Every tool is free or open source and the model providers have free
tiers sufficient for this work. No part of the marking advantages a student who pays for
extra capacity.

This file is the walkthrough. It explains what the project is, what order to do things in,
and what each document in the pack is for. Before you start, read
`00_PROJECT_INSTRUCTIONS.docx` for the rules, the deadline and the submission format, then
`01_Read_First/00_Start_Here.docx` for orientation. This file sits alongside both.

---

## What the project is

A software company called CloudServe Solutions has a support function that is failing. They
receive more than five hundred tickets a week across four channels, they take between eight
and twelve hours to reply when their own service agreement promises two, and fewer than half
of their tickets are resolved without being passed to somebody else. Their customer
satisfaction has fallen to 3.2 out of 5 and their renewal conversations have started going
badly.

They have asked you to build them a chatbot.

That is the request. It is not the job. The job is to work out what is actually going wrong
inside that support function, design something that addresses it, build that thing, prove
that it works, and be able to defend every decision you took along the way. Most of the marks
in this capstone sit on that second sentence rather than the first.

---

## How the three weeks are structured

The project moves through six stages. Each stage produces something, and that something is
the input to the stage that follows. This is deliberate: it makes it very difficult to skip
the understanding and go straight to the code, which is the most common way projects of this
kind go wrong.

| Stage | What you produce | When |
|-------|------------------|------|
| One — Discovery | A completed discovery workbook: interviews, evidence, a problem statement | Week one, days one to three |
| Two — Requirements | A product requirements document, version one | Week one, days four and five |
| Three — Prompt library | Specifications and a versioned prompt library, written from the requirements | Week two, days one and two |
| Four — Sprint plan | A backlog with estimates, owners and a definition of done for each item | Week two, day one |
| Five — Build and revision | A working system, evaluation results, and a revised requirements document | Week two into week three |
| Six — Submission | Video, report, workbooks with effort log, and source code | Week three |

You are required to revise your requirements document at least once during the build, and to
record what changed and why. This is not a penalty for getting it wrong the first time.
Requirements that survive three weeks of contact with real code without a single amendment
almost always mean that nobody was reading them.

---

## What to do, in order

### Before you write any code

Start by reading. It will feel like a delay and it is not.

1. Read `01_Read_First/00_Start_Here.docx`. It takes about fifteen minutes and it explains
   how everything fits together.
2. Read `01_Read_First/01_Project_Brief.docx` properly. Allow two to three hours. Do not
   skim the sections on evaluation and governance, because those are where most teams lose
   marks.
3. Skim `04_Submission/Submission_Guide.docx` so that you know what the finish line looks
   like. Several of its requirements cannot be satisfied retrospectively — the video needs a
   live demonstration, and the effort log needs entries throughout rather than a summary
   written from memory on the final afternoon.
4. Read `01_Read_First/02_Build_Specification.docx`. It lists the twelve acceptance criteria
   your software is tested against and the daily checkpoints for week two. This is the
   document you will return to most often once building starts.
5. Work through `03_Reference/Setup_Guide.docx` until you can install the packages and get a
   response back from the model provider on your own machine. Do this on day one. Every hour
   you delay it becomes an hour lost later, usually at the worst possible moment.

### Week one, which is about understanding rather than building

5. Open `02_Stage_Workbooks/Stage_1_Discovery_Workbook.docx` and fill it in. This means
   actually interviewing your stakeholders, actually reading the ticket data, and writing
   down what you found rather than what you assumed you would find.
6. Look for patterns across your evidence. Pay particular attention to how many of the
   incoming tickets are already answered somewhere in CloudServe's own documentation, because
   if that number is high the problem is not a shortage of answers but a failure to deliver
   them, and that is a different problem with a different solution.
7. Write your problem statement in the last section of the workbook, and then take it back to
   somebody you interviewed and ask whether they recognise it. If they hesitate, something in
   your framing is off, and finding that out now is very much cheaper than finding it out in
   week three.
8. Write version one of your requirements using
   `02_Stage_Workbooks/Stage_2_PRD_Template.docx`. Every requirement must reference the piece
   of discovery evidence that produced it.

### Week two, which is about building and measuring

9. Turn your requirements into specifications and prompts using
   `02_Stage_Workbooks/Stage_3_Prompt_Library.docx`. Prompts are design artefacts, not
   throwaway strings, and they get version control like everything else.
10. Plan the sprint in `02_Stage_Workbooks/Stage_4_Sprint_Plan.docx`. Every item gets exactly
    one owner and a definition of done written before the work starts.
11. Build the pipeline, the retrieval layer, the agents and the guardrails, working to the
    daily checkpoints in the Build Specification. Build the evaluation harness early rather
    than late, because leaving it until the end means discovering your results too late to
    act on them.
12. **Run the full validation set end to end, unattended, before week two closes.** This is
    the gate. Systems that work fine one ticket at a time routinely collapse on the fortieth,
    and you want to find that out in week two rather than week three.
13. Record the results honestly, including the ones you did not want.
14. Revise your requirements document and complete
    `02_Stage_Workbooks/Stage_5_PRD_Revision_Log.docx`. By now you will know what version one
    got wrong.

### Week three, which is about trust and presentation

15. Complete `03_Reference/Governance_Framework.docx`, including the risk register, the
    fairness audit and the incident procedure.
16. Set up monitoring and the continuous integration pipeline.
17. Record the video, write the report, and finish the effort log.
18. Package everything in the format the submission guide specifies, and check it against the
    final checklist the day before you submit rather than on the day itself.

---

## What is in the pack

### `01_Read_First`

`00_Start_Here.docx` is your orientation. It explains the project, the structure, the
contents of the pack and how the marks are distributed. Fifteen minutes.

`01_Project_Brief.docx` is the core document. The client situation, the architecture you are
designing, how the system decides when to answer and when to escalate, the data you have been
given, every target you are held to, the governance obligations, the technical constraints,
and a closing section on the things teams misunderstand every cohort. This is the document you
will return to most often.

`README.md` is this file.

### `02_Stage_Workbooks`

Five workbooks, one per stage, each consisting largely of tables for you to complete. They are
designed to be filled in rather than read, and the completed versions go into your submission
as appendices.

The discovery workbook covers who you spoke to, what the ticket data shows, where agent time
actually goes, what the client counts as success, what data exists and under what constraints,
and finally the problem statement that follows from all of it.

The PRD template covers document control, the problem, the user groups, functional and
non-functional requirements with traceability back to your evidence, what is deliberately out
of scope, your assumptions and what happens if they are wrong, and your success measures.

The prompt library covers the conversion of each requirement into a specification, a register
in which every prompt is recorded with its version and purpose, a checklist of what makes a
prompt worth keeping, and a traceability check you complete before moving on.

The sprint plan covers your realistic capacity week by week, the backlog with estimates and
dependencies, a day-by-day plan for weeks two and three, an explicit decision about what you
will drop if you run out of time, and a record of your daily check-ins.

The revision log is where you record what your requirements got wrong, which assumptions
failed, what you decided not to change and why, and a short reflection that will form part of
your final report.

### `03_Reference`

`Setup_Guide.docx` walks through the Python environment, model access and how to store a key
without committing it, the vector store, the decision log database, monitoring with Prometheus
and Grafana, continuous integration with GitHub Actions, the project structure to adopt, and
the errors previous cohorts have most often hit.

`Evaluation_Framework.docx` sets out the three tiers of measurement, every metric with the
code to calculate it, the targets, how to run an evaluation properly, and why the hidden
test set has to be protected.

`Governance_Framework.docx` covers decision logging with the minimum record schema, the risk
register, the fairness audit, the guardrails and what each one blocks, the incident response
procedure, and the kill switch.

### `04_Submission`

`Submission_Guide.docx` gives the exact format for all four parts of the submission: the
twenty-minute video with its required structure, the report with its prescribed section order,
the workbooks and effort log, and the source code repository with the checks that will be run
against it. It ends with a checklist to work through the day before you submit.

`Effort_Log.docx` is where you record what you worked on and how long it took, stage by stage,
along with a comparison of your estimates against reality.

### `05_Datasets`

`Stakeholder_Interviews.docx` holds transcripts of five conversations: the Head of Support,
a tier one agent, a tier two engineer, the technical writer who owns the documentation, and a
customer. CloudServe is fictional, so these transcripts are your primary discovery evidence.
Read all five before you write anything. They disagree with each other in at least three
places, and the ticket data will tell you who is right.

`Dataset_Guide.docx` documents every field in every file. Read it before you load anything.

`development_tickets.json` holds 500 labelled tickets. Each one carries channel, customer
tier, region, language fluency, timestamps, and a labels block giving intent, urgency,
expected routing, whether it is answerable from the documentation, and which documents a
correct answer should cite. There is also a history block recording what actually happened
when a human handled it, which is your baseline. Use this set however you like.

`validation_tickets.json` holds 80 tickets in the same format. Use them to check yourself as
often as you want.

`ground_truth_responses.json` holds 200 reference answers written by senior agents, each with
the documents it should cite, the points a correct answer must cover, and claims it must not
make.

`documentation.json` holds the 29 knowledge base articles that form the corpus your retrieval
layer searches.

**The set your grade depends on is not in your pack.** After submission, your evaluation
harness is run against a hidden set of 120 tickets drawn from the same population, using the
same schema. You will not see it beforehand. This has one practical consequence you must act
on: your harness has to take an input path and an output path as arguments rather than
pointing at a filename you hardcoded, because it will be pointed at a file you have never
seen. A harness that only works against your own copy of the data cannot be run at all, and
that is the most common avoidable failure in this assessment.

It also means there is nothing to gain from tuning until a number looks good. The set you can
see is not the set that decides your grade, so the honest path and the effective path happen
to be the same one.

### `06_Configuration`

`requirements.txt` is the pinned dependency list. `.env.example` is the template for your
environment variables, containing placeholder values only.

---

## How you will be marked

Before any of this applies, the gate must clear: your system processes the full validation
set unattended, from a clean checkout, on a machine that is not yours. The gate has three
outcomes rather than two — it runs cleanly, it runs but needs intervention, or it will not
start at all. Only the last carries a serious consequence, and even then you are given one
48-hour window to fix setup and documentation, because three weeks of legitimate work should
not be lost to a missing package pin. If the model provider is unavailable while your work is
being assessed, that is never counted against you.

| Area | Weight | What earns the marks |
|------|--------|----------------------|
| Implementation | 35% | A system meeting the twelve acceptance criteria, built sensibly, readable and runnable by someone else |
| Evaluation | 20% | Honest measurement against the data, business outcomes alongside technical ones, results interpreted rather than listed |
| Discovery and problem framing | 15% | Evidence gathered first hand, and a problem statement that follows from it |
| Requirements and traceability | 10% | Requirements specific enough to build from, with a visible chain to the code |
| Governance and risk | 10% | Decisions logged, risks assessed with real mitigations, fairness tested |
| Communication | 10% | A video and report a non-technical stakeholder could follow, with every claim explained rather than asserted |

The software is the deliverable and it carries the largest share. The documents are not an
alternative to building it; they are what make it worth trusting once it runs.

---

## The mistakes that cost teams the most

**Building before understanding.** The architecture always seems obvious on the first
morning. The teams who do best spend three days almost entirely on discovery and then build
faster, because they are not rewriting components they misunderstood.

**Treating the requirements document as paperwork.** It is not a formality standing between
you and the interesting part. It decides what the interesting part turns out to be.

**Reporting accuracy and stopping.** A classification figure on its own tells the client
nothing they can act on. Carry it through to what changed for the business, and say how
confident you are in the number.

**Leaving governance until the final afternoon.** Governance added at the end is always
shallow, because the design decisions that would have made it meaningful were taken weeks
earlier. Decide in week one what your decision log will record.

**Underestimating the video.** Twenty minutes of clear explanation is harder than it sounds,
and the first attempt always overruns and exposes the parts you cannot yet explain cleanly.
Record a first version by the middle of your final week so there is time for a second.

**Writing the effort log from memory.** It will be inaccurate, and it will show every stage
landing implausibly close to its estimate. Fill it in every second day; it takes two minutes
and it supplies the material for your reflection section.

---

## Getting help

For anything technical, start with the troubleshooting section at the end of the setup guide.
It covers the errors previous cohorts have hit most often, and roughly half of all setup
problems turn out to be a virtual environment that is not active in the terminal you are
using.

For anything about the project itself, the project brief is the authoritative document. Its
final section deals specifically with the points teams misunderstand.

Useful documentation:

- LangChain — https://python.langchain.com/
- LangGraph — https://langchain-ai.github.io/langgraph/
- Chroma — https://www.trychroma.com/
- OpenRouter — https://openrouter.ai/
- FastAPI — https://fastapi.tiangolo.com/
- Prometheus — https://prometheus.io/
- Grafana — https://grafana.com/
- GitHub Actions — https://docs.github.com/en/actions

---

## Dates to hold onto

| Milestone | By when |
|-----------|---------|
| Discovery workbook and requirements v1 complete | End of week one |
| **Gate cleared:** full validation set processed unattended | End of week two |
| Evaluation run complete and requirements revised | End of week two |
| Governance, report, video and packaging complete | End of week three |
| **Submission uploaded** | **13 September, 23:59** |

---

## One last thing

The client asked for a chatbot. Somewhere in your discovery you will find the thing they
should have asked for instead. Finding it, being able to show the evidence for it, and
building something that addresses it is the whole point of this exercise.

Good luck.
