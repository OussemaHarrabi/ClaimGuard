# 14 — Contribution log

> **Status:** Phase-1 submission document · written 2026-09-23.
> **What the pack asks for** (`ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack/docs/01_Challenge_Brief.md`,
> "Submission checklist"): *"A contribution log explaining team roles and the use of AI coding
> tools."*
> **What this document is:** how the team organised the work, who held which role, which artifacts
> each role produced, and an explicit declaration of how AI coding tools were used in this
> repository. Where I could not verify a claim from the repository itself, I say so.

---

## 1. How the team organised the work

The working method is written down in **`TEAM-ROADMAP.md`** §3 ("How we work — the team method") and
is the method actually followed:

| Stage | Practice |
|---|---|
| 1 · Research | Read the domain and requirements documents before writing code; write a short research note rather than a diary |
| 2 · Design | State input, output and failure cases; identify which existing pieces are touched; share the shape with the team before coding |
| 3 · Implement | Small conventional commits (`feat`/`fix`/`docs`/`test`/`refactor`/`chore` with a scope); follow the existing structure; `uv` + `ruff` + `pyright` + `pytest` |
| 4 · Prove it | Every feature ships with at least one test that would fail without it; run the local gates; a screenshot or a demo line for UI work |
| 5 · Ship | Push a branch, open a PR with the standard template, respond to review, reviewer merges |

**Branches and review.** `TEAM-ROADMAP.md` §5: one branch per deliverable
(`stream/<stream>/<short-name>`), a four-part PR template (*What / Why / How tested / Notes*),
`git pull --rebase` before pushing, and "only the reviewer merges".

**Sprint structure.** `TEAM-TASKS.md` (Sprint 1, written after the mentor's pack arrived) gives each
team member **one lab in their own field**, in their own folder — `team/b1-explanations/`,
`team/b2-evaluation/`, `team/b3-documents/` — with the rule *"you may READ everything, you may only
WRITE in your folder"*, a per-lab deliverable table, and a done-checklist. Its standing instruction is
the one this submission is written under:

> "**Never invent a number.** If you did not measure it, do not write it."

**Traceability.** The repo map and ownership split are in `TEAM-ROADMAP.md` §7; the graded contract is
fixed by `docs/10-ADR-Starter-Pack-Authority.md` (status **Accepted**, signed off by the
Head-of-Project on **2026-09-22**).

---

## 2. Who held which role

Roles as recorded in **`README.md`** §"Team" and **`TEAM-TASKS.md`**:

| Role | Focus as recorded | Artifacts in this repository |
|---|---|---|
| **HeadOfProject** | Core architecture with the senior developer; reviews all beginner work; owns the decision records | `docs/10-ADR-Starter-Pack-Authority.md` (owner, signed 2026-09-22); `docs/04-Architecture.md`, `docs/09-ARCHITECTURE-V2-Decisions.md`; `docs/03-Challenge-Decode-Requirements.md`; the `TEAM-ROADMAP.md` / `TEAM-TASKS.md` working method |
| **SeniorDev** | Repo and CI, canonical model, rule engine, audit ledger, API | `claimguard/edu/**` (engine, rules, evidence, policy, emit, run, intake, explain), `claimguard/review/**`, `claimguard/audit/chain.py`, `claimguard/db/migrations/**`, `scripts/edu_conformance.py`, `scripts/edu_report.py`, `tests/**`, `.github/workflows/ci.yml`, `pyproject.toml` |
| **B1 — Chatbot / language** | LLM normalization and explanation, API docs | Lab: `team/b1-explanations/` (scorecard generator, hand-filled 25-case scorecard, scorer, `FINDINGS.md`) per `TEAM-TASKS.md`. Engine-side explanation code is in `claimguard/edu/explain/**` |
| **B2 — Deep learning / evaluation** | Confidence calibration, evaluation metrics, data-dense UI | Lab: `team/b2-evaluation/` (loader, claim-level bootstrap intervals, abstention analysis, `FINDINGS.md`) per `TEAM-TASKS.md`; the measured numbers it works from are `docs/verification/EDU-EVALUATION-REPORT.md` |
| **B3 — Computer vision / documents** | Attachment OCR/RAG, data integrity | Lab: `team/b3-documents/` (attachment census over all three splits, FHIR gap check, `CENSUS.md`, `OCR_FEASIBILITY.md`) per `TEAM-TASKS.md`; the code claim it re-derives is `claimguard/edu/intake/fhir_source.py` |

**Honest note on the state of the tree.** The three `team/b*` lab folders are the beginner
assignments defined in `TEAM-TASKS.md`. **They were not present in this repository when this document
was written** (verified: `team/` absent from the working tree, 2026-09-23). The labs are separate
deliverables on their own branches, so this log records them as *assigned* work, not as shipped
artifacts.

---

## 3. Which artifacts this Phase-1 submission wave produced

| Artifact | Path | Owning workstream |
|---|---|---|
| Deterministic engine and the 15 rules | `claimguard/edu/**` | Engine workstream |
| Conformance harness and evaluation generator | `scripts/edu_conformance.py`, `scripts/edu_report.py` | Verification workstream |
| Reviewer API and persistence | `claimguard/review/app.py`, `store.py`, `models.py`, `audit_events.py` | Reviewer workstream |
| Reviewer interface | `claimguard/review/ui/**` (`index.html`, `app.js`, `styles.css`, `render.mjs`), served at `GET /review` by the existing FastAPI app | Interface workstream |
| Packaging and launch paths | `claimguard/cli/**` (console script `claimguard`), `Makefile`, `.env.example`, `Dockerfile`, `docker-compose.yml`, `README.md` | Packaging workstream |
| Demo kit | `scripts/sample_run.py`, `docs/15-Demo-Script.md`, `docs/verification/REPRODUCIBLE-SAMPLE-RUN.md` | Demo workstream |
| Submission documents | `docs/11-Architecture-and-Dataflow.md`, `docs/12-Privacy-and-Security-Note.md`, `docs/13-Technical-Report.md`, `docs/14-Contribution-Log.md` | Documentation workstream (this document) |
| Verification evidence | `docs/verification/EDU-EVALUATION-REPORT.md`, `docs/verification/EDU-PACK-CONFORMANCE.md` | Verification workstream |

---

## 4. How AI coding tools were used — declaration

The pack requires this to be declared rather than implied
(`ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack/docs/09_Work_Plan_and_Templates.md`,
`ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack/templates/Final_Submission_Checklist.md`: *"A contribution log
explaining team roles and the use of AI coding tools"*).

### 4.1 What was used

* **Large language model coding agents**, run through a terminal coding harness, were used for the
  implementation, verification tooling and documentation in this repository — including the engine
  package, the reviewer API, the intake projections, the conformance harness, the reviewer interface,
  the packaging paths, the demo kit and these four documents.
* **No model was used inside the graded decision path.** The rule engine is plain Python; the AI
  explanation layer is optional, is not called for a passing rule, and cannot change a status
  (`docs/11-Architecture-and-Dataflow.md` §6).
* **No API key, token or mentor-only file was given to any tool**: the pack is gitignored and the
  model credential is environment-only (`docs/12-Privacy-and-Security-Note.md` §8).

### 4.2 How it was used, and what stayed human

| Activity | Who |
|---|---|
| Scope, grading contract and architecture decisions | **Human lead.** `docs/10-ADR-Starter-Pack-Authority.md` is *"signed off by the Head-of-Project, 2026-09-22"*; the ADR text records the reasoning, the superseded plan and the open questions dispatched to the mentor |
| Direction, acceptance and rejection of each change | **Human lead**, per the five-stage method in `TEAM-ROADMAP.md` §3 |
| Writing code, tests, tooling and documents | **AI agents under the lead's direction**, in small reviewable steps |
| Running the graded gates | **Commands, not assertions**: the mentor's own strict scorer plus an independent harness (`scripts/edu_conformance.py`) |
| The numbers in the submission | **Only measured values.** Every figure in `docs/13-Technical-Report.md` is copied from `docs/verification/EDU-EVALUATION-REPORT.md` or `docs/verification/EDU-PACK-CONFORMANCE.md` with its section named; measurements taken during the documentation work carry the command that produced them |
| Signing off the submission | **Human lead** |

### 4.3 What the git history does and does not show

Verified on 2026-09-23:

```bash
git log --format='%an <%ae>' | sort -u    # one author: Oussema Harrabi <oussema.harrabi@supcom.tn>
git log --format='%B' | grep -ci 'co-authored-by'   # 0
```

* Every commit carries a single human author/committer identity, and **no commit carries a
  `Co-authored-by` trailer**. Per-commit attribution of AI assistance therefore **cannot be
  reconstructed from git**; that is exactly why it is declared here instead.
* The commit messages do record *what* changed and *why* in the team's conventional-commit format
  (for example `fix(edu): preserve concurrent uncertainty in FAIL explanations`,
  `fix(ci): make the pack-graded checks skip instead of failing without the pack`).
* **I could not verify** who typed any individual line, how much wall-clock time any step took, or
  which specific agent produced which file. Any table claiming per-file authorship would be an
  invention.

### 4.4 The rules applied to AI assistance in this repository

1. **No number without a command.** Anything measured is reproducible by the command printed beside
   it; anything not measured is stated as unmeasured or omitted.
2. **The oracle decides, not the author.** Acceptance for the deterministic core is the mentor's
   scorer exiting 0 with `status_accuracy 1.0000` on all three public splits, plus the independent
   second opinion — a green CI run is explicitly *not* sufficient (`docs/10-ADR-Starter-Pack-Authority.md`
   §2.2, §5).
3. **Uncertainty is written down.** Each submission document has a section listing what its author
   could not verify (`docs/11-Architecture-and-Dataflow.md` §9.3,
   `docs/12-Privacy-and-Security-Note.md` §9.2, `docs/13-Technical-Report.md` §7).
4. **Disagreements between sources are disclosed, not smoothed.** Example: the development-split
   evidence-pointer count is reported as 20300 in one verification document and 20270 in the other,
   and `docs/13-Technical-Report.md` §4.2 says so rather than picking one.
5. **AI never decides a claim.** Review, don't adjudicate; no clinical statement; no payer submission;
   no approval, denial, pricing or payment field exists in the result contract.
6. **Synthetic data only.** No real patient record is present, and the pack is never edited.

---

## 5. What could not be verified for this log

* The `team/b1-explanations/`, `team/b2-evaluation/` and `team/b3-documents/` lab folders
  (`TEAM-TASKS.md`) are **absent from this repository** at the time of writing; the log records them
  as assigned, not delivered.
* The recorded **demo video** and the **pitch deck** are required by the submission checklist but are
  not files in this repository; this log makes no claim about them.
* Per-file or per-person attribution of work is **not reconstructible** from the git history (§4.3).
* No time-tracking, velocity or effort figure is reported, because none was recorded.
