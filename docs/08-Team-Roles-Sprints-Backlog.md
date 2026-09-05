# 08 — Team, Roles, Sprints & Backlog

> **Document:** How we actually run — the roster, why work is divided this way, our agile process, working agreements, the full prioritised backlog, per-sprint plans, per-person growth roadmaps, risks, and quality gates.
> **Project:** ClaimGuard AI — CSTAM-VELODOC Challenge ("Trustworthy Agentic Copilot for Healthcare Claim Pre-Validation")
> **Audience:** the team, operated by the **Head of Project**. This is the document the head of project runs the team from.
> **Status:** v1.1 · 2026-09-04 · aligned to the canonical task index of `07-Spec-Plan-Tasks.md`
> **Companion docs:** read `01` (domain primer) and `02` (problem) for vocabulary; `03` (requirements + traceability), `04` (architecture), `05` (data model & rules), `07` (spec & task plan) for the technical substance this document schedules.

**Task IDs.** This document uses the **canonical task index from `07`** (`local://task-index.md`): 104 tasks, scheme `XXX-NN` per epic — FND, ING, RUL, LLM, CAL, HIT, AUD, SEC, API, UI, DAT, EVL, BON, DEL. Owners and estimates in the backlog below are **identical to 07's index**; what this document adds is priority, sprint target, dependencies, status, the per-sprint execution plan, and the human logic (who grows into what, and how we review them). **Sprint numbering is 07's: nine sprints S0–S8**, S4 ends 1 Oct (Phase 1), S6 ends 20 Oct (Phase 2), S7 ends 1 Nov (Phase 3), S8 is pitch + event.

**How to read this document.** §1 is the roster and the assignment logic (the "requirements first, growth second" principle). §2 is the RACI-lite ownership matrix. §3 is the agile process we actually run — short, ceremony-light, tuned to a deadline. §4 is our working agreements including the *demo must never be flaky* rule. §5 is the full 104-item backlog with priorities. §6 is the nine-sprint plan from registration (5 Sept) to the event (14–15 Nov). §7 is a personal roadmap for each of the five people — the three beginners' sections are the core of this project as a *learning* project. §8 is the risk register. §9 is what the Head of Project actually checks at review time.

---

## 1. Team roster & the division-of-work principle

### 1.1 Roster

| Person | Role label | Strengths | Primary ownership | Expected to LEARN |
|---|---|---|---|---|
| **You (the user)** | **HeadOfProject** | Senior AI + tech + business; the only one who sees the whole picture; owns the pitch, the numbers, the trust story | **Infrastructure & repo ownership — repo structure, tooling/CI, Docker Compose, Temporal spike (see v2 note below)**; overall direction; the FHIR parser (ING-02); rule engine (co-build); the prompt contract & clinical-refusal contract (LLM-04, SEC-04); HITL routing policy (HIT-01); the benchmark seeds & ground truth (DAT-01/04); technical report & pitch; **reviews everyone's work** | Delegation at part-time velocity; letting beginners ship imperfect code and fixing it *forward*; statistical rigor sufficient to defend ECE/AUROC in front of a jury |
| **Senior software engineer** | **SeniorDev** | Production Python, FastAPI, SQL, CI; knows what "done" means; the safety rail of the team | Canonical model + resolvers; rule engine + most rule manifests; audit ledger & hash chain; API; OTel; security integration; evaluation harness runner | Coaching; explaining *why* a design constraint exists, not just what to type; FHIR R4 + CEL specifics; surviving a 246h share of the workload by delegating verification (this doc's job) |
| **Beginner — built a chatbot** | **B1-Chatbot** | LLM/API fluency (prompting, JSON in/out, rate limits, retries); not afraid of new SDKs | **LLM enrichment**: normalization (LLM-02) + explanation narrative (LLM-03) + caching/determinism (LLM-06); entity resolution (ING-07); rule test suite (RUL-13); Presidio + injection corpus (SEC-01/03); API docs + Postman + Newman (API-05); streaming API (API-07); nightly audit verification (AUD-04) | Deterministic code discipline (types, schemas, error handling); evidence-first output (no claims without citable pointers); *restraint* — the LLM enriches, it never decides |
| **Beginner — deep learning** | **B2-DeepLearning** | Model training intuition, metrics literacy, PyTorch/sklearn comfort; can read a paper | **Confidence & calibration — v2 scoped** (CAL-01 Platt-on-logprobs baseline; ECE + bootstrap CIs labelled pilot-scale; **CAL-06 conformal abstention retained**); explanation quality eval (LLM-07, RAGAS); **evaluation metrics (EVL-02…05/07) — now her PRIMARY lane**; **reviewer UI data-dense screens** (UI-01/03/05/07); active learning (HIT-04); fuzzing (SEC-06) | Deterministic evaluation engineering; owning a frontend surface (deliberate stretch); *calibration is an ML topic* — her curve-fitting instincts apply directly; writing a defensible benchmark report |
| **Beginner — computer vision** | **B3-ComputerVision** | Augmentation pipelines, image pipelines, annotation/label discipline; knows how to make a test set that is *fair* | **Mutation generator → 50-claim eval set (DAT-03/04) — her PRIMARY lane, promoted to P1**; **hand-crafted adversarial claims** (breaks benchmark circularity); reviewer UI screens (UI-02 intake/upload, UI-04 review queue, UI-06 audit viewer); demo videos (DEL-07). **BON-01/02 OCR+RAG is now DEFERRED — do not start it** | Frontend engineering (React/Next.js — deliberate stretch, see §7); structured-data mutation as an analogue of image augmentation; document-layout models for the OCR bonus (post-competition) |

### 1.2 Why the work is divided this way — requirements first, growth second

**The principle, stated explicitly:** we derive the task list from *what the project needs*, and only then do we assign people to tasks they can best grow into. The challenge's scoring is the requirements driver — Phase 1 MVP = 50 pts (ingestion & normalisation 15, deterministic + AI rule engine 15, explainability & structured output 10, audit log 10); Phase 2 = 30 (Macro F1 on a 50-claim set 15, HITL & escalation 10, privacy/security 5); Phase 3 = 10 (UI/UX); Phase 4 = 10 (pitch); bonuses +2 each. So the task list is *dictated* by those numbers (the 104-item index in 07), not by what our three beginners already know. Nobody's background is a job description. Where a task needs a beginner's existing strength (B1's LLM fluency, B2's metrics literacy, B3's augmentation instincts), we use it; where the project needs something none of them knows (B3 builds reviewer screens, B2 builds the evaluation dashboard), we assign it anyway and scaffold it.

**The mapping — project need → task → person → why:**

| Project need (from scoring) | Task(s) | Owner(s) | Why this person — growth rationale (be honest) |
|---|---|---|---|
| Ingestion & normalisation (15 pts) | ING-01/02/03 canonical model + parsers; **LLM-02 normalization** | HoP (ING-02), SeniorDev (ING-01/03), **B1 (LLM-02)** | Normalization is the *one* place the LLM may act, and B1 already speaks LLM — her chatbot experience becomes product architecture. Scaffolding: LLM-01 (structured-output plumbing, HoP+SD) defines the contract B1 fills; bounded retries → LLM_UNRELIABLE → HITL is the fallback she wires, not a blank page. Stretch: deterministic error handling and schema discipline. |
| Deterministic rule engine (15 pts) | RUL-01…12 (engine + 12 manifest rules); **RUL-13 table-driven test suite** | HoP + SD (engine, Coverage/Authorization manifests); **B1 (RUL-13)** | The engine and the high-stakes Coverage/Authorization rules belong to the seniors (liability core; AUTH-004/006/009 and COV-001/008 are the flagship-fixture and escalation-critical rules). B1 owns the *test suite* instead — she reads every rule carefully enough to break it, which is the fastest possible domain immersion, and her tests are the machine that keeps the deterministic core honest. |
| Explainability & structured output (10 pts) | LLM-03 explanation narrative; LLM-05 semantic cross-checks; LLM-06 determinism | **B1** (LLM-03/06), SD (LLM-05) | B1 writes reviewer-facing prose for *rules that already fired* — deterministic outcomes in, narrative out — the inverse of her chatbot instinct (no free response!). The syntactic-not-semantic cross-check (SD) is the safety net: her prose cannot invent a rule. |
| Audit log engine (10 pts) | AUD-01…07 | SD (ledger, hash chain, replay, query); **B1 (AUD-04 nightly verification)** | Non-negotiable correctness (append-only DB, fail-open semantics) is senior territory. B1 owns the nightly verification job — a cron + script against the hash chain — a first taste of operating a security-relevant system, fully reviewable. |
| Confidence/calibration (drives the 15-pt Macro F1 work) | CAL-02…08; LLM-07; EVL-02…05/07 | **B2** (CAL-02…05, 07, 08; EVL-02…05/07), SD (CAL-01/06) | Calibration is a genuine ML topic — Guo et al., Platt scaling, conformal prediction. B2's deep-learning background transfers almost directly; her stretch is defending the statistics to the jury (with confidence intervals, per doc 02's folklore discipline). |
| HITL & escalation (10 pts) | HIT-01…05 | HoP (policy), SD (persistence/queue), **B2 (HIT-04 active learning — bonus)** | Escalation policy is a trust/liability decision — the seniors own it. B2's active-learning-from-overrides is her chance to make the *human* the label source, closing the loop her calibration numbers describe. |
| Privacy/security/safety (5 pts) | SEC-01/03 (Presidio, injection corpus), SEC-02, SEC-04, SEC-05/06 | **B1 (SEC-01/03)**, SD (SEC-02/05), HoP (SEC-04), **B2 (SEC-06 fuzzing)** | SEC-01 makes B1 run Presidio around *her own* LLM lane — the PII guard is security she can feel. B2's fuzzing corpus is her first adversarial-engineering exposure: shear, reviewable, valuable. |
| UI/UX (Phase 3, 10 pts) | UI-01…08 | **B2 (UI-01/03/05/07/08)**, **B3 (UI-02/04/06/08)** | Nobody on the team is a frontend developer; the project *needs* a reviewer UI. We split the screens by affinity: B2 (metrics-driven) owns the data-dense screens — finding cards with confidence, evaluation dashboard, rule catalogue — where her calibration numbers must be *shown*; B3 (documents-in) owns intake/upload (where attachments arrive — her OCR world starts here), the review queue, and the audit viewer (evidence trail). Both stretch; scaffolding = SeniorDev's API contract + HoP's screen-by-screen reviews. |
| Benchmark 50-claim set + Macro F1 (15 pts) | DAT-03/04 (seeds + mutations), EVL-01…07 | **B3 (DAT-03/04)**, **B2 (EVL-02…05/07)**, SD (EVL-01/06) | Mutation generation is *augmentation for structured data* — B3's CV augmentation instincts apply almost one-to-one (perturb a correct claim, track the label you introduced). B2 owns metrics, bootstrap CIs, and the report. HoP co-owns the seeds to keep ground truth honest. |
| OCR/RAG attachment parsing (bonus, +2) | BON-01/02 | **B3 (OCR) + B1 (RAG)** | The *only* feature where both beginners' original hobbies are the requirements: B3's CV is the OCR/document-layout side, B1's chatbot is the RAG orchestration side. |
| Streaming API (bonus, +2) | API-07 | **B1** | WebSockets over the pipeline = chat-protocol territory for the chatbot builder; a natural extension of skills she already has. |
| Pitch (Phase 4, 10 pts + creative bonus) | DEL-08/09 | HoP leads, **B1 (deck assist)** | B1's LLM lane produced the demo's star moments (explanation narratives); she carries the "how the AI works" slide. |

**The honesty column:** three assignments are deliberate stretches — B2 into owning frontend screens (UI-01/03/05/07), B3 into frontend work before her OCR bonus arrives (UI-02/04/06), B1 into production data plumbing (ING-07) and adversarial test authoring (RUL-13, SEC-03). Each has scaffolding (SeniorDev's starter scaffold in the monorepo, a defined output contract, a named reviewer, a bounded blast radius — the *engine core*, the *audit store*, and the *escalation policy* are never owned by beginners), and each begins with the beginner reading the interfaces they will consume. We stretch people *behind* senior-maintained interfaces, never on top of them.

---

## 2. Ownership map (RACI-lite)

One **A** per row (the person whose neck is on the line), R = does the work, C = must be consulted before decisions, I = kept informed. "RACI-lite" = we collapse the matrix to the five of us and accept blanks as "no involvement this sprint".

| Area / component | HeadOfProject | SeniorDev | B1-Chatbot | B2-DeepLearning | B3-ComputerVision |
|---|---|---|---|---|---|
| **Repo / tooling / CI** | **A/R** (v2: infra is HoP-owned — repo structure, uv/ruff/pyright, Docker Compose, GitHub Actions) | C | I | I | I |
| Canonical data model | **A/R** (ING-02 + P0-1 alias contract) | **A/R** (ING-01/03…) | C (normalization contract consumer) | I | I |
| **Temporal / workflow orchestration** | **A/R** (thin workflows, 12 Sep gate, Postgres fallback) | C (activities consume his modules) | I | I | I |
| Rule engine (deterministic core) | **A** / R | R | R (RUL-13 test suite) | I | I |
| Rule catalogue (manifests, versioning) | C | **A** / R | R (RUL-13 tests) | I | I |
| LLM enrichment (normalize + explain) | **A** (boundary policy; LLM-04) | R (LLM-01/05 plumbing) | R | I | I |
| **Confidence / calibration** (v2: scoped down) | **A** (statistical truth = trust) | R (CAL-01/06 conformal threshold semantics) | I | **R** (CAL-01 Platt baseline, ECE + bootstrap CIs; **EVL-02…05/07 is now her primary lane**; ~~CAL-02/03 self-consistency + semantic entropy DEFERRED~~) | I |
| HITL / review routing | **A** (policy owner, HIT-01) | R (HIT-02/03/05) | I | R (HIT-04 active learning) | I |
| Audit (ledger, hash chain, OTel) | C | **A/R** | R (AUD-04 nightly verification) | I | I |
| Security / PII (Presidio, guardrails, RBAC) | **A** (SEC-04) | R (SEC-02/05) | R (SEC-01/03) | R (SEC-06 fuzzing) | I |
| API (REST, streaming, docs) | R (API-02) | **A** (API-01/03/04/06) | R (API-05/07) | I | I |
| UI (reviewer app, rule GUI) | C | **A** (rails/API contract) | I | R (UI-01/03/05/07/08) | R (UI-02/04/06/08) |
| Benchmark dataset (seeds, mutations, truth) | **A** / R (DAT-01/04) | C | R (DAT-01) | R (DAT-05 split) | R (DAT-03/04) |
| Evaluation harness (Macro F1, ECE/AUROC, CI regression) | **A** (numbers credibility) | R (EVL-01/06/09) | R (EVL-08 smoke) | R (EVL-02…05/07) | C |
| **Bonus features** (v2: ALL DEFERRED — cut #1) | **A** (decides if/when any bonus starts) | I | I (API-07 streaming: **do not start**) | I (BON-04: **do not start**) | I (BON-01/02 OCR+RAG: **do not start** — her lane is DAT-03/04 instead) |
| Deliverables / demo / pitch | **A** (DEL-01/06/08/09) | R (DEL-02/05/09) | R (DEL-03) | R (DEL-04) | R (DEL-07) |
> **v2 note (2026-09-05) — READ THIS BEFORE USING ANY ROSTER OR RACI ROW ABOVE.**
> This document was written against architecture v1. `09-ARCHITECTURE-V2-Decisions.md` now supersedes
> it for ownership. Four changes are already applied above; until §5 backlog, §6 sprints and §7
> roadmaps are fully re-cut, **the v2 rules below override any remaining v1 text in those sections.**
>
> 1. **Infrastructure & repo ownership moved to HeadOfProject.** "Repo / tooling / CI" is now **A/R =
>    HoP** (repo structure, uv/ruff/pyright, Docker Compose, GitHub Actions, and the Temporal spike).
>    SeniorDev is **C**. Reason (09 §A2): SD is the team's bottleneck at ~246h; owning infra would
>    compete with the core build. Infra is the lead's job.
> 2. **Temporal is HoP-owned, gated 12 Sep** (09 §A2). Thin workflows, fat activities, Postgres state
>    machine as fallback. It consumes **zero** SeniorDev capacity.
> 3. **Confidence/calibration scoped down** (09 §Part H cut #2). `CAL-02` self-consistency and
>    `CAL-03` semantic entropy are **DEFERRED post-competition** — they do not improve Macro F1, which
>    is the scored metric. B2 keeps `CAL-01` (Platt on logprobs), ECE **with bootstrap CIs** labelled
>    pilot-scale, `CAL-06` conformal abstention (valid at any n), and RAGAS. **Her primary lane is now
>    EVL-02…05/07 — the evaluation harness — which is worth 15 real points.**
> 4. **All bonus features deferred** (09 §Part H cut #1). B3's `BON-01/02` OCR+RAG, B1's `API-07`
>    streaming, and B2's `BON-04` are **NOT to be started**. B3's promoted P1 lane is
>    **DAT-03/04 — the 50-claim benchmark and mutation generator** (15 points), plus the new
>    hand-crafted adversarial claims that break the benchmark's circularity (05 §7.1).
>
> **If you read a task ID below that was cut, do not start it — check `07` §6.3 (v2 cut list) first.**

**Reading the matrix the way we use it:** the HeadOfProject holds **A** exactly where trust is at stake — rule-engine truth, calibration statistics, HITL policy, security posture, the competition deliverables, **and now infrastructure** (because infra is the thing everyone else stands on). SeniorDev holds **A** on the machinery of the product itself (canonical model, audit, API). Beginners hold **R** with growing scope, and their **A** arrives only after the MVP.

---

## 3. The agile process we actually run

### 3.1 Sprint length: **one week** — deliberately

Registration is 5 Sept; the MVP lands 1 Oct; Phase 2 on 20 Oct; the Phase 3 selection gate on 1 Nov; the event 14–15 Nov. That is 9 weeks, three distinct submission deadlines, and a part-time team (≈15–20 h/week/person). **One-week sprints** because: (a) each submission deadline is a *hard* demo — a two-week sprint would give us only one feedback loop before the MVP; (b) weekly demos force everyone to keep the pipeline runnable all the time, which is exactly the "demo must never be flaky" discipline we need; (c) beginners get a small, reviewable increment every Friday instead of a big reveal every fortnight — faster learning, smaller failures. Two-week ceremonies would buy ceremony time we don't have; we buy back ceremony time with short, async standups. Sprints run **Monday → Sunday** (S6 runs Mon 12 Oct → Tue 20 Oct to hit the Phase-2 deadline; S8 runs Mon 2 Nov → Thu 13 Nov, the event), with the demo + planning on Monday morning.

**Sprint calendar at a glance** (nine sprints, S0–S8 — numbering and dates identical to 07):

| Sprint | Dates | Theme (07's) | Hard gate |
|---|---|---|---|
| S0 | 5–6 Sep | Kickoff | Repo + channels live |
| S1 | 7–13 Sep | Foundation | CI green on a real fixture |
| S2 | 14–20 Sep | Engine core | Pipeline v0 lifetime demo |
| S3 | 21–27 Sep | Rules + LLM + API | All MVP components demoable |
| S4 | 28 Sep–1 Oct | MVP freeze + submission | **Phase 1 MVP due 1 Oct (50 pts)** |
| S5 | 5–11 Oct | Confidence + HITL | First ECE/AUROC + escalation demo |
| S6 | 12–20 Oct | Detection quality, Phase-2 freeze | **Phase 2 due 20 Oct (30 pts)** |
| S7 | 21 Oct–1 Nov | UI + deliverables, Phase-3 freeze | **Phase 3 due 1 Nov (10 pts)** |
| S8 | 2–13 Nov | Pitch + event | **Event 14–15 Nov** |

### 3.2 Ceremony schedule (weekly, at 17:00 Tunisia time unless moved on Discord)

| Ceremony | When | Duration | Attendees | Agenda |
|---|---|---|---|---|
| **Sprint planning** | Monday, right after the demo | 45 min | All five | Review demo, set sprint goal, commit the §6 per-person items, confirm dependencies, sanity-check capacity (≤20 h/person, SD flagged if >20) |
| **Standup** | Daily, async thread in Discord | ≤3 lines/person by 09:30 | All five | Done yesterday · Blocked (with what, for how long) · Today. **No meetings**: anything needing back-and-forth moves to a pairing call |
| **Mid-week check-in** | Wednesday | 15 min, optional | Anyone blocked or pairing | Unblock sessions; HoP and SeniorDev guarantee online 18:00–19:00 Wed (crunch sprints S2–S4: also Thursday 18:00) |
| **Sprint review / demo** | Monday, start of planning | 20 min | All five | Each person demos their committed increment from the *running system* (not a screenshot). The demo script lives in the repo. |
| **Retrospective** | Monday, after planning | 20 min | All five | 2 things that worked, 2 that didn't, 1 action item. Actions land in the backlog as `chore` tickets with an owner. |
| **Backlog grooming** | Friday, async | 20 min (asynchronous doc) | HoP + whoever owns the next sprint's items | Refine the next sprint's tickets: acceptance criteria, estimates, dependencies. Sprint N+2 is always groomed during sprint N. |

**Rationale in one line:** five people, three deadlines, part-time hours → the ceremonies exist to (re)sync reality weekly, not to fill time; everything that can be async is async.

### 3.3 Definition of Ready (a ticket enters a sprint only when…)

- ✅ ID (XXX-NN), epic, title, owner, estimate (hours), priority (P0–P3), sprint target are all filled in
- ✅ Acceptance criteria are *observable* ("CLM-0042 produces a COV-001 finding with a resolving pointer", not "decent coverage")
- ✅ Named reviewer; named dependency (or "none"); referenced fixtures/data exist
- ✅ The ticket says what it does *not* do (scope guard, especially for beginner tickets)

### 3.4 Definition of Done (a ticket leaves a sprint only when…)

- ✅ Code merged to `main` with green CI and an approving review (see §4)
- ✅ Unit tests cover the observable contract; evidence pointers in findings **resolve in code** (verified by a test, not by eye)
- ✅ API docs touched if the contract changed; demo-able from a fresh `docker compose up` in ≤ 2 minutes
- ✅ Conventions followed (§4); docs `01`–`08` updated if behaviour or terminology changed
- ✅ Demo increment recorded for Monday's review (one line in the demo script)

---

## 4. Working agreements

**Branches:** `feat/<XXX-NN>-<slug>` (e.g., `feat/LLM-02-normalize-service`), `fix/<XXX-NN>-<slug>`, `docs/`, `chore/`, `bench/`. One branch per ticket; branch off `main`; delete after merge.

**Commits:** [Conventional Commits](https://www.conventionalcommits.org/) — `type(scope): subject` with the ticket ID in the body, e.g. `feat(rules): add DUP-002 duplicate-line rule (RUL-09)`. Never "wip" or "fix" commits on `main`; small logical commits, rebase before merge.

**PR size:** a PR is reviewable in one sitting — **≤ 400 changed lines** or it must be split with an explicit plan (beginner tickets: aim ≤ 300). UI PRs may exceed only with screenshots.

**PR template contents (required fields):** What (1 paragraph) · Why (ticket link) · Test plan (what you ran, output) · Evidence: for any finding-affecting change, the fixture + output shown · Screenshots for UI · Risks/unknowns. The template lives in `.github/PULL_REQUEST_TEMPLATE.md` (FND-01).

**Review turnaround SLAs:** HeadOfProject reviews the three beginners' PRs within **24 h on weekdays, 36 h over weekends**; SeniorDev + HeadOfProject jointly review core PRs (RUL-*/ING-*/AUD-*/HIT-01 territory) within **12–24 h**. Core PRs need **both** approvals; beginner PRs need the HeadOfProject's approval (SeniorDev pre-reviews when HoP is stretched — the matrix's C/R split makes this safe). Reviewer comments are actionable: "change X because Y", never just "no".

**No one merges to `main` without: green CI AND an approving review.** Branch protection is enforced on GitHub (FND-02). Anyone — including the HeadOfProject — who breaks this rule buys the team pastries at the next demo.

**When blocked:** try 45 minutes solo → write the blocker (exact error, what you tried) into the Discord standup thread → ask a named buddy (every ticket has one) → **escalate to the HeadOfProject after 4 h of wall-clock blocking** (2 h if the blocker is on the critical path to a deadline). Blocked people must say so in standup *the day it happens*, never the day after. There is no shame in blocking — there is shame in hiding.

**How to ask for help:** post the error, your hypothesis, and what you tried — that turns "help me" into a reviewable artefact. Pairing calls are encouraged; the ground rule is that the *owner* drives the keyboard.

**Channels:** Discord for async chat (channels: `#standup`, `#blockers`, `#demo`, `#decisions`); GitHub for everything code-shaped; docs `01`–`08` for everything durable. Decisions that change architecture or the trust model get a one-paragraph note in `#decisions` and an ADR entry in `04`.

**Scope control (the anti-creep rule):** the backlog freezes 4 days before each submission deadline — no new P0/P1 work enters the sprint; new ideas go to an **Icebox** section and are triaged at the next grooming. If a Phase-1 idea arrives after 27 Sep, it waits for Phase 3. (This is what makes the deadlines holdable with a part-time team.)

**The demo must never be flaky — explicit rule.** (a) The demo always runs from a fresh checkout via `docker compose up` — pinned versions, no developer-only state; (b) the Monday demo script is the *same* script that will run at the event; (c) any demo path that touches the network (LLM API) has a **recorded-output fallback** (LLM-06 caching exists precisely for this) — the pipeline must reproduce identically from cached responses if the API is down at pitch time; (d) 3 full dry runs the day before any submission video; (e) if a demo fails once in rehearsal, it is *fixed*, not re-attempted until it passes twice in a row — a flaky demo is a brand failure, and a recorded video fallback is always staged for the live event (the "2-minute live demo" stays live: we demo the real system, with the video as the safety net). **Synthetic fixtures only — a demo that ever touches real patient data is a disqualifying incident.**

---

## 5. The backlog

Priorities: **P0 = required for the 1 Oct MVP** (and everything P0 makes non-negotiable), P1 = Phase 2 (by 20 Oct), P2 = Phase 3 + bonuses (by 1 Nov). Estimates in person-hours from 07's index (review time extra). Status: `todo` / `in-progress` / `review` / `done`.

### 5.1 Epics (07's canonical list)

| Epic | Code | What it covers | Tasks | Owner-hours |
|---|---|---|---|---|
| Foundation | FND | Repo, tooling, CI, compose, conventions, traceability | FND-01…08 | 30 |
| Ingest + normalize | ING | Canonical model, FHIR/CSV parsers, resolvers, provenance, ENV-001, entity resolution | ING-01…07 | 48 |
| Deterministic rule engine | RUL | Manifest schema, registry/versioning/hash-pinning, CEL, evidence pointers, severity, 12 rules, test suite | RUL-01…13 | 62 |
| LLM enrichment + explanation | LLM | Structured-output plumbing, normalization, explanation, prompt contract, cross-checks, caching, quality eval | LLM-01…07 | 48 |
| Confidence + calibration | CAL | Abstraction, self-consistency, semantic entropy, logprob features, Platt/isotonic, conformal, ECE/AUROC, CLI | CAL-01…08 | 39 |
| HITL | HIT | Three-tier routing + escalation, review model, override codes, active learning, queue | HIT-01…05 | 28 |
| Audit | AUD | Append-only schema/GRANTs, writer, hash chain, nightly verify, OTel traces, replay, query API | AUD-01…07 | 31 |
| Security / privacy / safety | SEC | Presidio, data-not-instructions, injection corpus, clinical-refusal, RBAC, fuzzing | SEC-01…06 | 28 |
| API | API | FastAPI skeleton, submit/get/review endpoints, OpenAPI+Postman+Newman, rate limit, streaming | API-01…07 | 33 |
| Reviewer UI | UI | Next.js scaffold, intake, finding cards, review queue, rule catalogue, audit viewer, eval dashboard, polish | UI-01…08 | 56 |
| Data + benchmark | DAT | 13 seed fixtures, FHIR anchors, mutation generator, 50-claim set, split | DAT-01…05 | 35 |
| Evaluation | EVL | Harness CLI, Macro F1 + per-family, bootstrap CIs, FP rate, RAGAS, CI regression, report, smoke, E2E | EVL-01…09 | 40 |
| Bonus | BON | OCR, RAG, dynamic rule API, rule GUI, crypto ledger | BON-01…05 | 42 |
| Deliverables | DEL | Diagrams, API pack, reports, security doc, tech report, videos, deck, rehearsal | DEL-01…09 | 41 |

**Total: 104 tasks, ≈ 561 h of owner work** (per 07; the difference from 575 h is the pair-shared hours in the index, which appear on two owners).

### 5.2 The backlog table

| ID | Title (short; full in 07) | Epic | Owner | Est. | Pri | Sprint | Depends on | Status |
|---|---|---|---|---|---|---|---|---|
| FND-01 | Repo scaffold + Python tooling (uv, ruff, mypy, pytest, pre-commit) | FND | SD | 6 | P0 | S1 | — | todo |
| FND-02 | Branching, commit & review conventions | FND | HoP | 2 | P0 | S1 | — | todo |
| FND-03 | CI pipeline lint/type/test/build | FND | SD | 4 | P0 | S1 | FND-01 | todo |
| FND-04 | Docker Compose stack + .env template | FND | SD | 4 | P0 | S1 | FND-01 | todo |
| FND-05 | DB baseline migrations (0001_schema.sql) | FND | SD | 5 | P0 | S2 | FND-04 | todo |
| FND-06 | Shared config, logging, error taxonomy | FND | SD | 4 | P0 | S1 | FND-01 | todo |
| FND-07 | OpenTelemetry foundation | FND | SD | 3 | P0 | S3 | FND-06 | todo |
| FND-08 | Traceability matrix (R1.x rows + task index) | FND | HoP | 2 | P0 | S1 | 03 | todo |
| ING-01 | Canonical claim models (canonical.py) | ING | HoP+SD | 8 | P0 | S1–2 | FND-01 | todo |
| ING-02 | FHIR R4 bundle parser → canonical | ING | HoP | 10 | P0 | S2 | ING-01 | todo |
| ING-03 | CSV ingestion + column contract | ING | SD | 6 | P0 | S2 | ING-01 | todo |
| ING-04 | Reference resolver (resolve.py) | ING | SD | 8 | P0 | S2 | ING-02 | todo |
| ING-05 | Provenance map (SourcePointer per field) | ING | SD | 6 | P0 | S3 | ING-02 | todo |
| ING-06 | Envelope guard ENV-001 (envelope.py) | ING | SD | 4 | P0 | S4 | ING-01 | todo |
| ING-07 | Entity resolution member/provider/coverage | ING | B1 (SD review) | 6 | P0 | S2 | ING-02 | todo |
| RUL-01 | Rule manifest schema + 12 rule YAMLs | RUL | HoP+SD | 6 | P0 | S2–3 | ING-01 | todo |
| RUL-02 | Registry + versioning + hash pinning | RUL | SD | 5 | P0 | S3 | RUL-01 | todo |
| RUL-03 | CEL evaluation (cel-python) | RUL | SD | 6 | P0 | S3 | RUL-01 | todo |
| RUL-04 | Evidence pointer resolver + verification (evidence.py) | RUL | SD+HoP | 5 | P0 | S3 | RUL-01 | todo |
| RUL-05 | Severity assignment (manifest-bound) | RUL | HoP | 3 | P0 | S3 | RUL-01 | todo |
| RUL-06 | Rule runner + pipeline skeleton | RUL | SD+HoP | 6 | P0 | S3 | RUL-02/03 | todo |
| RUL-07 | Coverage rules COV-001, COV-008 | RUL | SD | 6 | P0 | S3 | RUL-06 | todo |
| RUL-08 | Authorization rules AUTH-004/006/009 | RUL | SD | 8 | P0 | S4 | RUL-06 | todo |
| RUL-09 | Integrity rules DUP-002, INT-003 | RUL | SD | 6 | P0 | S4 | RUL-06 | todo |
| RUL-10 | Identity rules ID-002, ID-005 | RUL | SD | 4 | P0 | S4 | RUL-06 | todo |
| RUL-11 | Documentation rules DOC-004, ENC-001 | RUL | SD | 4 | P0 | S4 | RUL-06 | todo |
| RUL-12 | Envelope rule ENV-001 integration | RUL | SD | 3 | P0 | S4 | RUL-06, ING-06 | todo |
| RUL-13 | Table-driven rule test suite | RUL | B1 (SD review) | 6 | P0 | S4 | RUL-07…12 | todo |
| LLM-01 | Structured output plumbing (Pydantic AI/Instructor) | LLM | HoP+SD | 10 | P0 | S3 | ING-01 | todo |
| LLM-02 | LLM-assisted normalization | LLM | B1 (SD review) | 8 | P0 | S3 | LLM-01, ING-01 | todo |
| LLM-03 | Explanation narrative service | LLM | B1 (HoP review) | 10 | P0 | S3 | RUL-06, LLM-05 | todo |
| LLM-04 | Prompt contract + refusal blocks | LLM | HoP | 5 | P0 | S3 | LLM-01 | todo |
| LLM-05 | Semantic cross-checks (rule_id fired, pointers resolve) | LLM | SD | 5 | P0 | S3 | RUL-06 | todo |
| LLM-06 | Caching + determinism (temp 0, seed, prompt hash) | LLM | B1 | 4 | P0 | S3 | LLM-02 | todo |
| LLM-07 | Explanation quality eval (RAGAS faithfulness) | LLM | B2 (SD review) | 6 | P1 | S3–5 | LLM-03 | todo |
| CAL-01 | Confidence pipeline abstraction | CAL | SD+HoP | 6 | P1 | S5 | LLM-02, LLM-06 | todo |
| CAL-02 | Self-consistency sampling (K=3) | CAL | B2 (SD review) | 6 | P1 | S5 | CAL-01 | todo |
| CAL-03 | Semantic entropy | CAL | B2 | 5 | P1 | S5 | CAL-02 | todo |
| CAL-04 | Logprob features | CAL | B2 | 4 | P1 | S5 | CAL-02 | todo |
| CAL-05 | Platt/isotonic calibration | CAL | B2 | 6 | P1 | S6 | CAL-02…04 | todo |
| CAL-06 | Conformal abstention (alpha=0.05) | CAL | SD | 5 | P1 | S5 | CAL-05 | todo |
| CAL-07 | ECE/AUROC metrics + reliability diagram | CAL | B2 | 4 | P1 | S6 | CAL-05 | todo |
| CAL-08 | Calibration CLI + versioned artifact | CAL | B2 | 3 | P1 | S7 | CAL-05…07 | todo |
| HIT-01 | Three-tier routing + mandatory escalation | HIT | HoP | 5 | P1 | S5 | API-02 | todo |
| HIT-02 | Review task model + persistence | HIT | SD | 6 | P1 | S5 | FND-05 | todo |
| HIT-03 | Structured override reason codes | HIT | SD | 5 | P1 | S6 | HIT-02 | todo |
| HIT-04 | Active learning from overrides (bonus) | HIT | B2 | 8 | P2 | S7 | HIT-03 | todo |
| HIT-05 | Review queue service | HIT | SD | 4 | P1 | S6 | HIT-02, API-04 | todo |
| AUD-01 | Append-only audit_events schema + GRANTs | AUD | SD | 4 | P0 | S3 | FND-05 | todo |
| AUD-02 | Audit writer + event catalogue | AUD | SD | 5 | P0 | S4 | AUD-01 | todo |
| AUD-03 | SHA-256 hash chain | AUD | SD+HoP | 6 | P0 | S4 | AUD-02 | todo |
| AUD-04 | Nightly chain verification job | AUD | B1 (SD review) | 4 | P0 | S4 | AUD-03 | todo |
| AUD-05 | OTel per-claim traces | AUD | SD | 4 | P1 | S5 | FND-07 | todo |
| AUD-06 | Replay service | AUD | SD | 5 | P1 | S5 | AUD-02 | todo |
| AUD-07 | Audit query API | AUD | SD | 4 | P1 | S6 | AUD-06 | todo |
| SEC-01 | Presidio PII pipeline (pre/post) | SEC | B1 (SD review) | 6 | P0 | S2 | ING-01, LLM-01 | todo |
| SEC-02 | Data-not-instructions delimiters | SEC | SD | 4 | P0 | S3 | LLM-01 | todo |
| SEC-03 | Injection corpus + runner | SEC | B1 | 5 | P1 | S5 | SEC-01 | todo |
| SEC-04 | Clinical-refusal contract + tests | SEC | HoP | 4 | P0 | S3 | LLM-04 | todo |
| SEC-05 | RBAC | SEC | SD | 5 | P1 | S6 | API-02 | todo |
| SEC-06 | Malformed-input fuzzing | SEC | B2 | 4 | P1 | S6 | ING-01 | todo |
| API-01 | FastAPI skeleton + error envelope | API | SD | 5 | P0 | S2–3 | FND-06 | todo |
| API-02 | POST /claims submit endpoint | API | HoP+SD | 8 | P0 | S3 | API-01, ING-02, SEC-05 | todo |
| API-03 | GET claim/finding endpoints | API | SD | 4 | P0 | S3 | API-02 | todo |
| API-04 | Review & decision endpoints | API | SD | 4 | P1 | S5 | API-03, HIT-03 | todo |
| API-05 | OpenAPI + Postman collection + Newman CI | API | B1 | 5 | P0 | S3–4 | API-01…04 | todo |
| API-06 | Rate limiting | API | SD | 3 | P2 | S7 | API-02 | todo |
| API-07 | Streaming/WebSocket (bonus) | API | B1 | 8 | P2 | S7 | API-02 | todo |
| UI-01 | Next.js scaffold + design tokens + API client | UI | B2 | 6 | P1 | S1–2 | API-03 | todo |
| UI-02 | Intake/upload screen | UI | B3 | 8 | P1 | S2–3 | UI-01, API-02 | todo |
| UI-03 | Claim detail + finding cards + evidence chips | UI | B2 | 10 | P1 | S2–3 | UI-01 | todo |
| UI-04 | Review queue + decision dialog | UI | B3 | 8 | P1 | S5–6 | UI-01, API-04 | todo |
| UI-05 | Rule catalogue screen | UI | B2 | 6 | P2 | S8 | UI-01, BON-03 | todo |
| UI-06 | Audit viewer | UI | B3 | 6 | P2 | S6–7 | UI-01, AUD-07 | todo |
| UI-07 | Evaluation dashboard | UI | B2 | 6 | P2 | S7 | UI-01, EVL-07 | todo |
| UI-08 | Polish + a11y pass | UI | B2/B3 | 6 | P1 | S7 | UI-02…07 | todo |
| DAT-01 | 13 seed fixtures + manifest + CLM-0042 | DAT | HoP + B1 | 10 | P0 | S1–2 | ING-01 | todo |
| DAT-02 | FHIR structural anchors (HL7 examples) + golden tests | DAT | SD | 4 | P0 | S5 | ING-02 | todo |
| DAT-03 | Seeded mutation generator (16 recipes) | DAT | B3 (SD review) | 8 | P1 | S3–5 | DAT-01 | todo |
| DAT-04 | 50-claim benchmark dataset (BM-001…050) | DAT | HoP+B3 | 10 | P1 | S5–6 | DAT-03 | todo |
| DAT-05 | Train/dev/test split (grouped by seed) | DAT | B2 | 3 | P1 | S6 | DAT-04 | todo |
| EVL-01 | Harness runner CLI | EVL | SD | 6 | P1 | S6 | RUL-06, ING-02 | todo |
| EVL-02 | Macro F1 + per-family metrics | EVL | B2 | 5 | P1 | S6 | EVL-01, DAT-05 | todo |
| EVL-03 | Bootstrap CIs | EVL | B2 | 5 | P1 | S7 | EVL-02 | todo |
| EVL-04 | Clean-claim FP rate + severity agreement | EVL | B2 | 3 | P1 | S7 | EVL-02 | todo |
| EVL-05 | RAGAS faithfulness harness | EVL | B2 | 4 | P1 | S7 | LLM-07 | todo |
| EVL-06 | Regression gate in CI | EVL | SD | 4 | P1 | S7 | EVL-02…04 | todo |
| EVL-07 | Benchmark report generator | EVL | B2 | 4 | P1 | S7 | EVL-02…05 | todo |
| EVL-08 | Demo smoke test | EVL | B1 | 4 | P0 | S4 | EVL-01 | todo |
| EVL-09 | E2E CLM-0042 test | EVL | SD | 5 | P0 | S4 | RUL-06, DAT-01 | todo |
| BON-01 | Attachment OCR pipeline | BON | B3 (SD review) | 12 | P2 | S7 | UI-02, SEC-01 | todo |
| BON-02 | RAG over attachments | BON | B3+B1 | 10 | P2 | S7–8 | BON-01 | todo |
| BON-03 | Dynamic rule management API + dry-run | BON | SD | 8 | P2 | S7 | RUL-02 | todo |
| BON-04 | Rule admin GUI | BON | B2 | 4 | P2 | S8 | BON-03, UI-05 | todo |
| BON-05 | Crypto ledger (daily Merkle root + proofs) | BON | SD | 8 | P2 | S7–8 | AUD-03 | todo |
| DEL-01 | Architecture diagram | DEL | HoP | 3 | P0 | S2 | 04 | todo |
| DEL-02 | Data-flow diagram | DEL | SD | 3 | P0 | S4 | 04/05 | todo |
| DEL-03 | API docs pack (Swagger + quickstart) | DEL | B1 | 2 | P0 | S4 | API-05 | todo |
| DEL-04 | Performance/benchmark report | DEL | B2 | 4 | P1 | S7–8 | EVL-07 | todo |
| DEL-05 | Network/security documentation | DEL | SD | 5 | P1 | S6 | SEC-05 | todo |
| DEL-06 | Technical report | DEL | HoP | 6 | P1 | S7 | 04–08, EVL-07 | todo |
| DEL-07 | Demo videos (Phase 1/2/3 cuts) | DEL | B3 edit + HoP script | 6 | P0/P1 | S4/S6/S8 | EVL-08 | todo |
| DEL-08 | Pitch deck | DEL | HoP (+B1) | 8 | P1 | S8 | DEL-04 | todo |
| DEL-09 | Live demo rehearsal + freeze | DEL | HoP+SD | 4 | P1 | S8 | DEL-07 | todo |

**Icebox (not scheduled before 1 Nov):** payer-specific companion-guide fetch and diffing (post-event); multi-emirate rule packs; chatbot-style "ask the copilot" reviewer assistant; mobile reviewer view. *These are deliberately frozen out until after the selection gate.*

### 5.3 Loading — and the SeniorDev bottleneck (read this before §6)

Phase-1 P0 work (FND + ING + RUL + LLM-01…06 + AUD-01…04 + API-01…03/05 + SEC-01/02/04 + DAT-01/02 + EVL-08/09 + DEL-01…03) totals ≈ **285 h of owner work** across S1–S4 — four weeks × five people × ~17 h ≈ 340 h available, so the MVP *fits*, but only just. The structural problem 07's index exposes: **SeniorDev owns ≈ 246 h — the largest share by far** (the index concentrates infrastructure, audit, API and rule engine on one person, correctly). Doc 08 fixes this in scheduling, not by changing owners:

1. **HoP co-implements the core** (already indexed as shared on ING-01, RUL-01/04/06, LLM-01, CAL-01, AUD-03, API-02 — plus HoP owns ING-02, RUL-05, LLM-04, SEC-04, HIT-01 outright). The user's stated preference — "work the MAIN/CENTRAL parts together with the senior dev" — is exactly this.
2. **Beginners' underload is real** (B1 ≈ 50 h, B2 ≈ 65 h, B3 ≈ 40 h in the index) and is directed into pull-forward P1 work — UI-01/03 early (B2), UI-02 (B3), RUL-13/EVL-08 (B1) — plus review-shadowing: every beginner reads the PRs of the interfaces they consume (B2 reads EVL-01's PRs, B1 reads AUD-01…03's).
3. **Stretch items are droppable by contract** (§6 flags them); SD never commits beyond ~20 h/week without HoP pairing absorbing the rest.

Hours are planning fiction; **the Monday demo is the truth.** If the demo regresses, the sprint's stretch items are cut first, then the backlog freeze rule (§4) protects the deadline.

---

## 6. Sprint plan

Capacity model: part-time **15–20 h/week**; we plan on ~17 h nominal (beginners 15–18 h; SD flagged when >20 h; HoP absorbs 20–24 h in core sprints S2–S4). Sprints run Mon–Sun (S6: Mon 12 Oct–Tue 20 Oct; S8: Mon 2 Nov–Thu 13 Nov). Mondays carry demo + planning (≈ 1.5 h).

### Sprint 0 — 5–6 Sep (2 days) — "Kickoff"

- **Goal:** registered, connected, tooled. No code commits required beyond repo creation.
- **Committed:** all — registration; Discord + repo created; everyone installs Python 3.12+, Node 20+, Docker Desktop, VS Code; read `01` and `02` (start of DAT-01 context); HoP circulates 07 + this document for review; exam timetables onto the team calendar.
- **Demo:** repo exists with branch protection + a `README` linking docs 01–08. That is the demo.
- **Risks:** Windows toolchain friction (Docker Desktop vs WSL2) — one person per machine pair fixes installs before Monday.

### Sprint 1 — 7–13 Sep — "Foundation"

- **Goal:** repo + CI green; canonical model holds CLM-0042; fixtures catalogue started; reviewer scaffold renders claim list.
- **Committed per person (hours ≈):**

| Person | Items | Hours |
|---|---|---|
| HoP | ING-01 co-build (4) · FND-02 (2) · FND-08 (2) · DAT-01 seeds start (4) · first-review pass (3) | 15 |
| SD | FND-01 (6) · FND-03 (4) · FND-04 (4) · FND-06 (4) | 18 |
| B1 | DAT-01 with HoP (6) · read 01/02/03 + ING-02 PRs (2) · stretch: LLM-01 reading (2) | 10 |
| B2 | UI-01 scaffold (6, pull-forward P1) · read CAL papers: Guo et al., Angelopoulos & Bates (3) | 9 |
| B3 | UI-02 design (4) · DAT-03 mutation-recipe concept (6) — augmentation analogy doc | 10 |

- **Stretch:** ING-02 parser start (HoP); EVL-02 metric design notes (B2).
- **Demo:** fresh clone → `docker compose up` → CI green → CLM-0042 loads in a notebook → B2's scaffold renders the claim list.
- **Risks:** toolchain day-one roulette; LLM API keys and cost caps (free tier; token budget ~$0 this sprint; the cached-output path LLM-06 is the fallback, not an afterthought).

### Sprint 2 — 14–20 Sep — "Engine core"

- **Goal:** pipeline v0: Ingest→Normalize→Validate→Handoff runs on CLM-0042 with COV-001, AUTH-004, DUP-002 findings carrying severity and confidence.
- **Committed per person:**

| Person | Items | Hours |
|---|---|---|
| HoP | ING-02 FHIR parser (10) · ING-01 co-build (4) · DEL-01 diagram (3) | 17 |
| SD | FND-05 (5) · ING-03 (6) · ING-04 (8) · RUL-01 co-build (3) | 22 ⚠️ |
| B1 | ING-07 entity resolution (6) · SEC-01 Presidio pipeline (6) · DAT-01 finish (4) | 16 |
| B2 | UI-03 finding cards (10) · LLM-07 eval design notes (2) | 12 |
| B3 | UI-02 intake/upload (8) · DAT-03 recipe sets (6) | 14 |

- **Stretch:** API-01 skeleton (SD, +5 h); SEC-01 redaction tests (B1).
- **Demo:** pipeline v0 lifetime above, live on CLM-0042 (COV-001 0.99, AUTH-004 0.96 for the rule spike, DUP-002 0.88), pointers shown in B2's finding cards.
- **Risks:** LLM normalization quality (if a canonical field is wrong, findings lie — retry/LLM_UNRELIABLE fallback must be real by S3); pointer-schema drift between ING-01 and RUL-04 (the RUL-04 golden tests catch it).

### Sprint 3 — 21–27 Sep — "Rules + LLM + API" (crunch)

- **Goal:** all MVP components demoable: rule engine + coverage rules, LLM normalization + explanation, submit API, audit schema + writer, prompt contract + refusal blocks. **Backlog freeze begins 27 Sep.**
- **Committed per person:**

| Person | Items | Hours |
|---|---|---|
| HoP | LLM-01 co-build (5) · LLM-04 prompt contract + refusal blocks (5) · RUL-05 severity (3) · SEC-04 clinical-refusal tests (4) · RUL-08 pair (2) · reviews (3) | 22 ⚠️ |
| SD | RUL-02 (5) · RUL-03 CEL (6) · RUL-04 evidence pointers (3, pair) · RUL-07 COV rules (6) · AUD-01 schema+GRANTs (4) · FND-07 OTel foundation (3) | 27 ⚠️⚠️ |
| B1 | LLM-02 normalization (8) · LLM-03 explanation narrative (10) | 18 ⚠️ |
| B2 | LLM-07 RAGAS harness on LLM-03 outputs (6) · UI-03 finish (6) | 12 |
| B3 | UI-02 finish (6) · DAT-03 generator v1 (8) | 14 |
| SD's protection | ING-05, API-02 co-build, audit writer move to S4 by design; SEC-02 bundled into LLM-01/04 (delimiters + refusal in the same contract) | — |

- **Stretch (droppable):** ING-05 provenance map (SD); LLM-06 caching triage (B1).
- **Demo:** CLM-0042 end-to-end: findings + pointers + LLM explanation narrative + an audit event for the claim; B2's UI shows the full finding card with corrective action.
- **Risks:** SD is at 27 h — that is why Thursday 18:00 check-ins start this sprint and why AUD-02/03, RUL-08…12, ING-06 are *scheduled* for S4 rather than S3; audit fail-open semantics misimplemented (bug class: audit failure blocking the claim is prohibited); explanation drift (LLM-05 cross-checks exist exactly for this).

### Sprint 4 — 28 Sep–1 Oct — "MVP freeze + submission (due 1 Oct)"

- **Goal:** **submit Phase 1.** No new features (freeze from 27 Sep). Finish the audit chain, remaining rules, E2E test, smoke test, submission bundle. Phase-1 demo video cut (DEL-07).
- **Committed per person:**

| Person | Items | Hours |
|---|---|---|
| HoP | submission bundle lead (6) · RUL-08 pair (2) · AUD-03 co-build (3) · DEL-01/06 prep (2) · reviews (4) | 17 |
| SD | AUD-02 writer (5) · AUD-03 hash chain (3, pair) · RUL-08 AUTH-004 first, 006/009 by 20 Oct (4) · RUL-09…11 Integrity/Identity/Documentation (6) · RUL-12 ENV-001 integration (3) · ING-06 envelope (4) · EVL-09 E2E (5) · DEL-02 data-flow (3) | 23 ⚠️ |
| B1 | RUL-13 table-driven rule tests (6) · EVL-08 demo smoke (4) · DEL-03 API pack (2) · AUD-04 nightly verification (4) · Phase-1 video assist (2) | 18 ⚠️ |
| B2 | EVL-01 pair (3) · UI-01/03 polish (4) · LLM-07 finish (2) · CAL-01 co-build (3) | 12 |
| B3 | DEL-07 Phase-1 video edit (6) · UI-04 design (4) | 10 |

- **RUL-08 honest split:** AUTH-004 (the flagship fixture's signal) ships by 1 Oct; AUTH-006 and AUTH-009 (escalation-critical, so they still land early) by 20 Oct with the HITL tier — they are in the Phase-2 bundle, not the MVP.
- **Gate:** **G2 — Phase 1 submission, 1 Oct.** Bundle: repo, docs 01–08, Swagger/Postman, architecture + data-flow diagrams, demo video, benchmark report v0, audit verification output.
- **Risks:** last-week regressions — the Monday-demo discipline is the guard; anything unmerged by 27 Sep is cut, not rushed.

### Sprint 5 — 5–11 Oct — "Confidence + HITL"

- **Goal:** first ECE/AUROC numbers (B2), conformal abstention scaffold (SD), mandatory-escalation routing (HoP), review task model (SD), FHIR anchors (DAT-02).
- **Committed per person:**

| Person | Items | Hours |
|---|---|---|
| HoP | HIT-01 three-tier routing + mandatory escalation (5) · CAL-01 co-build (3) · SEC-04 verify (2) · reviews (4) | 14 |
| SD | CAL-01 co-build (3) · CAL-06 conformal α=0.05 (5) · HIT-02 review model + persistence (6) · AUD-05 OTel traces (4) · DAT-02 FHIR anchors (4) | 22 ⚠️ |
| B1 | SEC-03 injection corpus (5) · LLM-03 improvements after MVP feedback (4) · API-05 Newman CI (3) | 12 |
| B2 | CAL-02 self-consistency (6) · CAL-03 semantic entropy (5) · CAL-04 logprob features (4) · LLM-07 finish (2) | 17 |
| B3 | DAT-04 50-claim set with HoP (8) · UI-04 review queue (8) | 16 |

- **Stretch:** AUD-06 replay service (SD); EVL-02 metric skeleton (B2).
- **Demo:** reliability diagram with first ECE + a live AUTH-004 escalation that *cannot* be confidence-gated away; B3's review queue shows the HITL tier badges.
- **Risks:** calibration on ~50 claims is statistically thin — B2 reports bootstrap CIs and says so (the jury respects honesty; doc 02 §3.7 discipline).

### Sprint 6 — 12–20 Oct — "Detection quality + Phase-2 freeze + submission (due 20 Oct)"

- **Goal:** **submit Phase 2 (19–20 Oct):** Macro F1 on the 50-claim set, HITL + escalation complete, privacy/security section, network/security doc. **Freeze begins 16 Oct.**
- **Committed per person:**

| Person | Items | Hours |
|---|---|---|
| HoP | DAT-04 co-build (4) · EVL numbers review (2) · DEL-05 review (2) · Phase-2 bundle lead (6) | 14 |
| SD | HIT-03 override reason codes (5) · HIT-05 review queue service (4) · EVL-01 harness CLI (6) · SEC-05 RBAC (5) · AUD-07 audit query API (4) | 24 ⚠️ |
| B1 | EVL-08 re-run (2) · SEC-03 finish (2) · DEL-07 Phase-2 video assist (4) · API-05 final (2) | 10 |
| B2 | CAL-05 Platt/isotonic (6) · CAL-07 ECE/AUROC + reliability diagram (4) · EVL-02 Macro F1 + per-family (5) · DAT-05 split (3) | 18 ⚠️ |
| B3 | DAT-04 finish (4) · UI-06 audit viewer (6) | 10 |

- **RBAC honest flag:** SEC-05 (5 h) is the droppable item this sprint — the 5 privacy points are already protected by SEC-01/02/04 (landed S2/S3); RBAC slips to S7 if the F1 report needs the time.
- **Gate:** **G3 — Phase 2 submission, 20 Oct.** Bundle: benchmark report with Macro F1/ECE/AUROC + bootstrap CIs, HITL demo, network/security documentation.
- **Risks:** label correctness of the mutation set is the foundation of 15 pts — B3 and B2 hand-audit 10 random claims independently before submission; any disagreement → audit all labels (risk R7).

### Sprint 7 — 21 Oct–1 Nov — "UI + deliverables + Phase-3 freeze + submission (due 1 Nov)"

- **Goal:** **submit Phase 3 (selection gate):** polished UI/UX (UI-01…08), bonus features working, technical report, benchmark report generator, regression gate in CI. **Freeze begins 28 Oct.**
- **Committed per person:**

| Person | Items | Hours |
|---|---|---|
| HoP | DEL-06 technical report (6) · UI-08 review (2) · EVL-07 report review (2) · Phase-3 bundle (4) · reviews (4) | 18 |
| SD | EVL-06 regression gate (4) · BON-03 dynamic rule API (8) · BON-05 crypto ledger (8) | 20 ⚠️ |
| B1 | API-07 streaming/WebSocket (8) · DEL-03 final (2) | 10 |
| B2 | CAL-08 CLI + artifact (3) · EVL-03 bootstrap CIs (5) · EVL-04 FP rate + severity agreement (3) · EVL-07 report generator (4) · UI-08 polish (3) | 18 ⚠️ |
| B3 | BON-01 OCR pipeline (12) · UI-08 polish (3) | 15 |

- **Stretch:** HIT-04 active learning (B2, +8 h → S8 if pinched); BON-02 RAG start.
- **Gate:** **G4 — Phase 3 submission, 1 Nov.** Bundle: UI/UX polish (a11y, keyboard, empty/error states), technical report, final benchmark report, all docs.
- **Risks:** bonus scope swallowing Phase-3 polish — bonuses are P2 by definition; UI-08 (P1) outranks BON-01/05 under time pressure.

### Sprint 8 — 2–13 Nov — "Pitch + event (14–15 Nov)"

- **Goal:** **12-minute pitch (5 talk + 2 live demo + 5 Q&A)** at Hammamet; deck done by 5 Nov; two presenters named by 5 Nov; dry-runs 8 Nov and 12+13 Nov (on event hardware); contingency video staged; Q&A binder printed.
- **Committed per person:**

| Person | Items | Hours |
|---|---|---|
| HoP | DEL-08 pitch deck (8) · DEL-09 rehearsal lead (4) · creative-bonus option (2) | 14 |
| SD | DEL-09 demo hardening — pinned versions, cached-LLM replay (4) · BON-05 finish (2) · EVL-06 CI final (2) | 8 |
| B1 | DEL-08 assist — "how the AI works" slide (4) · BON-02 RAG pair (4) · Q&A binder (2) | 10 |
| B2 | UI-05 rule catalogue screen (6) · BON-04 rule admin GUI (4) · DEL-04 report final (4) | 14 |
| B3 | BON-02 RAG with B1 (6) · DEL-07 final pitch video (6) | 12 |

- **Risks:** venue Wi-Fi/AV — the demo must run offline (local model or cached outputs) by design (§4); presenter availability — understudies rehearse the live demo.

---

## 7. Per-person roadmap

### 7.1 HeadOfProject

- **Focus:** project truth — architecture, trust model, numbers, reviews. You carry the pitch's credibility: the sourced-statistic discipline of doc 02 is *your* standard, and the traceability matrix (FND-08) your load-bearing artefact.
- **Journey:** S1 conventions + seeds · S2 the FHIR parser (ING-02 — you own it, the hardest single parsing task on the team) · S3 prompt contract + refusal blocks + severity · S4 submit · S5 escalation policy (HIT-01) · S6 Phase-2 bundle · S7 technical report · S8 pitch.
- **Gain:** running a 5-person part-time team to a hard deadline; defending statistical claims (ECE/AUROC) as a *business* story; delegating without losing the thread; owning the parser makes you the domain expert the beginners come to.
- **Review:** you are reviewed by the jury — and by the team's retrospectives (the pastries rule applies to you too).

### 7.2 SeniorDev

- **Focus:** the machinery everyone stands on — CI, canonical model + resolvers, rule engine, audit, API, harness. You co-build the core with the HoP and are the beginners' safety rail.
- **Journey:** S1 repo+CI · S2 model/ingest/resolver · S3 engine (CEL, registry, evidence) + audit schema · S4 hash chain + remaining rules + E2E · S5 HITL persistence + conformal · S6 harness + RBAC · S7 regression gate + bonuses · S8 demo hardening.
- **Gain:** production discipline (audit fail-open, hash chains, OTel) in a domain with real liability semantics; coaching; running at ~20 h/week under a deadline without breaking the Monday demo.
- **Scaffolding (read first):** [FastAPI](https://fastapi.tiangolo.com/), [Pydantic v2](https://docs.pydantic.dev/), [FHIR R4 spec](https://hl7.org/fhir/R4/), [cel-python](https://github.com/cloud-custodian/cel-python), [RFC 6901 JSON Pointer](https://www.rfc-editor.org/rfc/rfc6901), [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/), [Docker Compose](https://docs.docker.com/compose/), [GitHub Actions](https://docs.github.com/en/actions).

### 7.3 B1-Chatbot — "the LLM lane, held on a leash"

- **Focus:** the two places the LLM is allowed to act — **normalization (LLM-02)** and **explanation (LLM-03)** — plus entity resolution (ING-07), the rule test suite (RUL-13), Presidio + the injection corpus (SEC-01/03), API docs/Postman/Newman (API-05), the streaming API (API-07), nightly audit verification (AUD-04), and the RAG bonus (BON-02).
- **Journey:** S1 fixtures (DAT-01) · S2 entity resolution + Presidio · S3 normalization + explanation — your two big services · S4 rule tests + smoke + audit verification · S5 injection corpus + explanation refinements · S6 Phase-2 video + docs · S7 streaming API · S8 pitch assist + Q&A binder.
- **What you'll actually learn:** your chatbot told the world what it wanted to say; this project teaches you the *un*-chatbot: typed outputs with schemas, retries with fallbacks, prose that must cite pointers, prompts as versioned contracts (LLM-04). The hardest part of LLM products is *restraint* — the compensating control is that the machine (LLM-05) checks your work before a human does. You'll also touch every deliverable (docs, videos, pitch), which is why you'll be the team member who can *talk* about the whole system.
- **The stretch (honest):** LLM-02/03 replace "make the model answer" with "make the model fill a contract correctly or say it can't" — the single most employable skill on this team. ING-07 (data plumbing) has no LLM in it at all; RUL-13 asks you to *break* rules on purpose. Both are deliberate: a claims copilot needs someone who loves correctness more than cleverness.
- **Scaffolding (read first):** [Instructor](https://python.useinstructor.com/) or [Pydantic AI](https://ai.pydantic.dev/) for structured outputs; [OpenAI structured outputs guide](https://platform.openai.com/docs/guides/structured-outputs); [self-consistency](https://arxiv.org/abs/2203.11171) (why 3 samples beat 1); [Semantic uncertainty (Kuhn et al.)](https://arxiv.org/abs/2302.09664) (read it together with B2 — it consumes *your* outputs); RFC 6901 (above); doc `01` §6 and `03` — knowing what a claim is makes your prompts good. Microsoft Presidio docs for SEC-01.
- **Review:** HoP reviews every PR (24 h SLA) with SD pre-reviewing contract boundaries. Your findings' pointers are *automatically* verified by LLM-05 — the machine reviews you first. RUL-13 must hurt when it catches a real rule bug; that is the review working.

### 7.4 B2-DeepLearning — "calibration: your domain, project-required"
- **Focus (v2):** **evaluation metrics are now your primary lane** — `EVL-02…05/07`: Macro F1 per rule with support counts, bootstrap 95% CIs, clean-claim FP rate as its own headline row, and the benchmark report (`DEL-04`). Plus **confidence/calibration, v2-scoped**: `CAL-01` Platt scaling on logprob features, ECE **with bootstrap CIs** labelled pilot-scale, and `CAL-06` conformal abstention (α=0.05). Plus explanation quality eval (`LLM-07`, RAGAS) and the **data-dense reviewer UI** (`UI-01/03/05/07`).
- **Journey (v2):** S1: UI scaffold + read Guo et al. & Angelopoulos-Bates · S2: finding cards · S3: RAGAS harness on real explanations · S4: `EVL-01` pairing + `CAL-01` co-build · S5: **evaluation harness — Macro F1, per-rule breakdown, bootstrap CIs** (this is the 15-point work) · S6: Platt + ECE/AUROC + clean-claim FP rate + report generator · S7: polish + final report · S8: rule GUI + pitch numbers.
- **DEFERRED — do not start:** `CAL-02` self-consistency and `CAL-03` semantic entropy. Cut because calibration does **not** improve Macro F1, which is the scored Phase-2 metric. Read the papers anyway if curious; they are not on the critical path.
- **What you'll actually learn:** your deep-learning background is curve-fitting; calibration is where that instinct becomes *trust engineering*. You'll learn conformal prediction (distribution-free, finite-sample guarantees — the honest cousin of your confidence intervals), RAGAS-style faithfulness evaluation (explanation quality is a *measurement*, not a vibe), and you'll report what a 50-claim dataset cannot support — with intervals. You also become the team's UI owner for data-dense screens, which forces you to design for the person who must *act* on your numbers.
- **The stretch (honest):** UI-01/03/05/07 — a frontend surface, owned by the ML person. That is the point: the challenge's "be usable" criterion belongs to the person who understands both the numbers and the reviewer's decision. Scaffolding: SD's API contract + starter scaffold; HoP's screen-by-screen review with screenshots. CAL-06 (conformal) is SD's — you implement the pipeline, SD owns the threshold semantics; that is a deliberate safety split.
- **Scaffolding (read first):** [Guo et al., On Calibration of Modern Neural Networks (ICML 2017)](https://proceedings.mlr.press/v70/guo17a.html); [A Gentle Introduction to Conformal Prediction (Angelopoulos & Bates)](https://arxiv.org/abs/2107.07511); [Semantic uncertainty (Kuhn et al.)](https://arxiv.org/abs/2302.09664); [sklearn calibration docs](https://scikit-learn.org/stable/modules/calibration.html); [Active Learning Survey (Settles 2009)](https://minds.wisconsin.edu/handle/1793/60660); doc `02` §3 (which numbers matter); Next.js + Tailwind docs (UI lane).
- **Review:** HoP owns calibration statistically — expect defence-mode reviews ("why this alpha", "what's the coverage of your intervals"). SD cross-checks your metrics plumbing (EVL-02 can be silently wrong in ways that look right). Your report is the jury's credibility artifact.

### 7.5 B3-ComputerVision — "reviewer screens first, then your real hobby"

- **Focus (v2):** **the 50-claim benchmark is now your primary lane, promoted to P1** — `DAT-03` mutation generator and `DAT-04` the 50-claim set, **plus the hand-crafted adversarial claims** that break the benchmark's circularity (see `05` §7.1: recipes written by the same person as the rules will share their blind spots). Plus reviewer UI screens (`UI-02` intake/upload, `UI-04` review queue, `UI-06` audit viewer) and demo videos (`DEL-07`).
- **Journey (v2):** S1: intake design + mutation-recipe concept · S2: intake/upload + recipe sets · S3: generator v1 · S4: Phase-1 video edit · S5: **50-claim set with HoP + hand-crafted adversarial cases** · S6: audit viewer + Phase-2 video · S7: **UI polish + benchmark regeneration and label hand-audit with B2** · S8: final pitch video.
- **DEFERRED — do not start:** `BON-01/02` OCR+RAG. All bonus features were cut first (each is +2 *after* the first 100 points, and zero Phase-1 points). Your CV skills are not idle — `DAT-03/04` is image augmentation applied to structured claims, which is genuinely your domain. The OCR bonus becomes available post-competition.
- **Scaffolding (read first):** [Next.js docs](https://nextjs.org/docs), [Tailwind](https://tailwindcss.com/docs), [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) and [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) for BON-01, [docTR](https://github.com/mindee/doctr) and [LayoutLM (Microsoft)](https://github.com/microsoft/unilm/tree/master/layoutlm) for document understanding, and a RAG walkthrough ([llamaindex](https://www.llamaindex.ai/) or [LangChain](https://python.langchain.com/docs/)) shared with B1. Doc `01` §6 — the attachment story (DOC-004) is your demo's hero moment; read `02` §5.1 to know why attachments break claims.
- **Review:** HoP reviews UI PRs with screenshots required (24 h SLA); SD reviews the integration points (BON-01 touches SEC-01's redaction). Your mutation *labels* are audited by B2 (hand cross-check before the Phase-2 submission, risk R7).

---

## 8. Risk register

| # | Risk | Likelihood | Impact | Mitigation | Trigger (act when…) |
|---|---|---|---|---|---|
| R1 | A beginner stalls (ticket slips 2+ days, standup silence) | High | Medium — task slips its sprint | Buddy system (every ticket has a named reviewer who can take over); 45-min solo rule then ask; re-scope the ticket down, never let it rot; pair session with SD within 24 h | No standup update for 1 day; or "blocked" status > 48 h without escalation |
| R2 | Someone disappears (illness, exam crunch) | Medium | High — critical-path tasks (AUD-*, RUL-*, ING-*) | Every P0/P1 ticket has a named backup reviewer who has read it; audit, rule engine and escalation are cross-trained (HoP + SD both know the designs); 20% capacity buffer built into §6; exam timetables on the team calendar from S0 | No communication for 48 h during a sprint; any missed deadline without notice |
| R3 | **SeniorDev overload** (≈246 h indexed over 8 sprints — the structural bottleneck) | High | High — the core stalls, everything queues | HoP co-implements exactly the indexed pair items (ING-01, RUL-01/04/06, LLM-01, CAL-01, AUD-03, API-02) + owns ING-02/RUL-05/LLM-04/HIT-01 outright; beginners pull forward P1 work (UI-01/03, EVL-08) instead of idle; stretch items droppable by contract; Thursday check-ins in crunch sprints; SD never commits >20 h/wk without saying so | SD's committed hours in any sprint > 22; any PR of SD's waiting > 12 h;
| R4 | Review bottleneck at the HeadOfProject | High | Medium — beginners idle waiting | SLAs (§4): 24 h weekday / 36 h weekend; SD pre-reviews beginners' PRs so HoP's review is a check, not a rewrite; HoP batches reviews into 2 fixed blocks/day; if the HoP is away, SD has approval rights on beginner PRs (documented exception) | PRs awaiting review > 36 h; any beginner has 2 PRs waiting |
| R5 | Scope creep (a shiny idea drowns the MVP) | High | High — misses 1 Oct | Backlog freeze 4 days before each deadline; Icebox is real; new P0/P1 needs 2 of 3 (HoP, SD, argument) to enter; "demoable Monday" is the filter — if it doesn't make Monday's demo better, it waits | Any ticket added to an active sprint after the freeze date |
| R6 | Exam clashes (Tunisian students, mid/late autumn) | Medium | Medium | Sprints S5–S7 overlap exam season: the 20% capacity buffer absorbs it; stretch items are droppable; HoP knows everyone's timetable by S0 | Exam week declared → sprint commits shrink by mutual consent, no blame |
| R7 | Mislabeled ground truth in the 50-claim set | Medium | High — Phase 2 Macro F1 is 15 pts | DAT-03 labels are generated *with* the mutator (label = injected defect), then hand-audited: B3+B2 independently label 10 random claims, agreement check before submission | Any disagreement found in the hand-audit → audit all labels before the Phase-2 bundle |
| R8 | Statistic credibility failure at pitch | Low | High — jury trust | Every slide number carries (source, year, URL) per doc 02 §3.7; the folklore list is a banned list; B1's Q&A binder (S8) carries the primary sources | Any number without a source found in deck review |
| R9 | The demo works "on my machine" only | Medium | High | The Monday demo **always** runs from a fresh clone via compose (§4); workspace discipline (no developer-only state in the repo) enforced from FND-01; LLM-06 caching makes the LLM path replayable | Any demo needing a manual setup step at review; LLM API unavailable during a dry run |

---

## 9. Review and quality gates — what the HeadOfProject actually checks

### 9.1 The standing checklist (every PR, before you approve)

- [ ] **Contract:** does this change what the pipeline promises (docs 03/05 contract: findings carry Claim ID, Rule ID, evidence, severity, confidence, corrective action)? If yes, docs and API surface updated in the same PR?
- [ ] **Safety:** does it adjudicate, diagnose, or recommend treatment? ("Review, don't adjudicate" — a one-word change can break this.) Does it touch PHI? Synthetic-only, always.
- [ ] **Determinism:** any LLM in the decision path? (It must not be.) Any non-determinism in rule outcomes (hashes, iteration order, time)? (LLM-06 checks this for the enrichment lane.)
- [ ] **Evidence:** every finding cites JSON Pointers that resolve *in code* — is there a test that verifies, not eyeballs (LLM-05/RUL-04)?
- [ ] **Tests:** does a test defend the observable behaviour and fail on a plausible bug? (Not source-text assertions.)
- [ ] **DoD completeness:** green CI, approving review, demo line updated, no dead code/comments left behind, branch deleted.

### 9.2 Per-artifact checklists

**Rule implementation (RUL-*):**
- [ ] Rule ID matches the catalogue; version + effective date present; hash-pinned in git (RUL-02)
- [ ] Outcome categories correct (pass/fail/abstain); severity correct for the family (RUL-05)
- [ ] Every evidence pointer in the rule's messages resolves against a *real* fixture; RUL-13 covers the rule with failing fixtures
- [ ] Determinism: same input → same output across runs
- [ ] Boundary cases tested: empty fields, missing references, dates at the edge (service date == coverage end date)
- [ ] No clinical inference hidden in the condition (COV/AUTH/INT/ID/DOC/ENV families only)

**LLM prompt / enrichment change (LLM-*, SEC-01/03):**
- [ ] The prompt cannot change a rule outcome (rules fire first; the LLM fills the schema contract or writes prose about rules that already fired)
- [ ] Structured output: JSON-schema mode; retry ≤ 3 with bounded fallback to LLM_UNRELIABLE → HITL; no unbounded loops
- [ ] PII: Presidio pre-prompt and post-response (SEC-01); SEC-03 injection corpus passes for the new prompt
- [ ] DATA-NOT-INSTRUCTIONS (SEC-02): attachments never enter the prompt as instructions; the prompt contract (LLM-04) is pinned in git and refuses clinical requests (SEC-04)
- [ ] Explanations cite only rules that actually fired (LLM-05 passes); LLM-07 faithfulness sampled
- [ ] Cost/rate limits: token budget per claim; failure mode is *degrade*, never *crash*; LLM-06 caching replayable for demos

**Test (any):**
- [ ] Tests the observable contract, not the implementation text
- [ ] Isolated + deterministic + full-suite safe; fixtures live in the catalogue (DAT-01), never inline
- [ ] For findings: asserts pointer resolution + rule_id membership + severity/confidence values

**UI screen (UI-*, B2/B3):**
- [ ] The six Phase-1 fields are visible on every finding card (Claim ID, Rule ID, evidence, severity, confidence, corrective action)
- [ ] Keyboard-navigable; readable at 200% zoom; no colour-only severity coding (UI-08 a11y)
- [ ] Empty/error states exist (no claim? no findings? API down?) — a reviewer must never stare at a spinner
- [ ] The claim package viewer shows *evidence* (pointers), not just verdicts
- [ ] Screenshots attached; state how the screen was reached (fixture + route)

**Doc change (01–08):**
- [ ] Every statistic carries (source URL, year) or is marked folklore/derived; no new numbers invented
- [ ] Vocabulary matches the glossary in `01` (signal, finding, claim package, quality gate, handoff, review-don't-adjudicate, copilot)
- [ ] Cross-links to sibling docs maintained; the doc's status line bumped

### 9.3 Quality gates (hard, calendar-bound — aligned with 07's sprint plan)

| Gate | When | What must be true |
|---|---|---|
| **G1 — MVP freeze** | 27 Sep (end of S3) | All P0 tickets merged-or-cut; pipeline demoable on CLM-0042 from fresh clone; backlog frozen |
| **G2 — Phase 1 submission** | 1 Oct (S4) | Submission bundle complete: repo, docs 01–08, Swagger/Postman (API-05/DEL-03), architecture + data-flow diagrams, demo video (DEL-07), benchmark report v0, audit verification output (AUD-04) |
| **G3 — Phase 2 submission** | 20 Oct (S6) | Macro F1 + ECE/AUROC report with bootstrap CIs and hand-audited labels (DAT-04/EVL-03); HITL escalation demo (HIT-01); privacy/security section (SEC-*); network/security documentation (DEL-05) |
| **G4 — Phase 3 submission** | 1 Nov (S7) | Selection gate: UI/UX polish (UI-08), technical report (DEL-06), benchmark report generator (EVL-07/DEL-04), regression gate in CI (EVL-06) |
| **G5 — Pitch ready** | 8 Nov (S8) | 12-minute pitch (5+2+5) runs twice at 12:00 flat; live demo passes 2 consecutive runs; Q&A binder printed |
| **G6 — Event** | 14–15 Nov | Contingency video staged; offline-capable demo verified on event hardware |

---

*End of document 08. The team runs from this document; the sprint tables in §6 are updated at every Monday planning, task IDs and owners stay aligned with 07's canonical index, and this file is the single source of truth for who does what, when, and why.*