# ClaimGuard AI — Team Roadmap

> **What this is:** the plan we work from, as a team. It explains *how* we work
> (methodology) and *what* each of us is building toward.
> **Read together with:** `docs/01-DOMAIN-Gulf-Claims-101.md` (how healthcare
> claims actually work) and `docs/03-Challenge-Decode-Requirements.md`
> (exactly what the challenge grades).
> **Your current AI labs are in
> [`TEAM-AI-LABS-2026-09-27.md`](TEAM-AI-LABS-2026-09-27.md)**. The earlier Sprint 1 brief remains
> in [`TEAM-TASKS.md`](TEAM-TASKS.md) as background.

---

## 1. What we are building — in 30 seconds

Clinics send claims to insurance companies. A surprising share get rejected for
**fixable, administrative mistakes**: coverage expired a week ago, a missing
pre-approval, the same MRI billed twice. The clinic only finds out weeks later,
then reworks everything by hand.

**ClaimGuard sits between the clinic and the insurer.** It reads a claim before
it is submitted, finds the mistakes that would get it rejected, explains each
one with the exact piece of evidence, and routes the uncertain cases to a human
reviewer. It **never** decides whether a claim gets paid — it makes the
problems *legible* so a person can act. That is the whole product:
"review, don't adjudicate."

We are building this for the CSTAM-VELODOC challenge (Velodoc / Amazit, Dubai),
and we aim to build it like a real product, not a homework project.

---

## 2. How to use this document

This is a **methodology roadmap, not a checklist of micro-tasks.** Each work
stream below gives you:

1. **Your mission** — the outcome you own.
2. **Start here** — the questions to research and understand *first*.
3. **What you build** — the concrete pieces, in order.
4. **Milestones** — what "done" looks like at each stage.
5. **Quality bar** — how to know your work is good.

The rule for every task you take on:

> **Understand it before you build it.** Every piece of this product sits in a
> real, regulated domain (healthcare + insurance + AI trust). A task done with
> understanding is worth ten done on autopilot — to the team, and to your own
> growth.

Each stream is sized so it can **start today**, from the repo as it exists now.
Data that the organizers may or may not provide is a dependency we do **not**
wait for: research, scraping, and building our own synthetic fixtures is part of
the work.

---

## 3. How we work — the team method

Every task goes through the same five stages. This is the discipline that keeps
five people moving in one direction.

### Stage 1 — Research (the default first step)
Before writing any code:
- Read the relevant doc(s): `01` (domain), `03` (requirements), `04`
  (architecture), `05` (data model / rules), `06` (specs).
- Find real external sources: official payer pages, HL7/FHIR docs, Velodoc's
  own claim lab ([veloclaim.app](https://veloclaim.app)), reputable industry
  writing.
- Answer: *what problem does this piece solve? who uses it? what could go
  wrong?*
- **Write down what you learned** — a short research note (see each stream's
  "start here"). The note is a deliverable, not a diary.

### Stage 2 — Design
Before implementing, write/describe the shape of the solution:
- What is the input? the output? the failure cases?
- Which existing pieces does it touch (see §7 repo map)?
- Sketch it in a few sentences or a small diagram. Share it with the team in
  the review channel before coding.

### Stage 3 — Implement
- Small commits, descriptive messages (§5).
- Follow what the repo already does (naming, structure, style) — we use
  `uv` + `ruff` (lint) + `pyright` (type checking) + `pytest`.
- If something is genuinely blocked, stop and ask (§5) — do not guess silently.

### Stage 4 — Prove it
- Every feature ships with at least one test that would fail without the
  feature.
- Run the local gates before asking for review:
  ```bash
  uv run ruff check .
  uv run ruff format --check .
  uv run pyright
  uv run pytest tests/ -q          # add -m "integration" if a live DB is up
  ```
- A screenshot or a short demo line for UI work.

### Stage 5 — Ship it (Pull Request)
- Push your branch, open a PR with the PR template (§5), request a review.
- Respond to feedback; the reviewer is making you better, not grading you.
- Only the reviewer merges. Main stays green — always.

---

## 4. The three work streams

> **Update — the mentor's data has arrived (17 Sep pack).** The streams below are
> the original direction and they are still the right way to think about the
> product, but **two things changed**: the labelled benchmark is supplied, so
> Stream C's "build our own fixtures and a mutation generator" work is no longer
> needed; and the engine now exists, so the streams become *measuring and
> verifying* work rather than building from zero.
>
> **Your current lab assignments are in
> [`TEAM-AI-LABS-2026-09-27.md`](TEAM-AI-LABS-2026-09-27.md)**. Treat the sections below as the
> background for why each field matters.

### Stream A — The Explainable AI layer

**Mission:** when a rule fires, a reviewer must understand *why* in plain
language, with proof. You own the AI that explains findings and the contract
that keeps that AI honest.

**Start here (research first):**
1. Explore Velodoc's claim lab — read the fixture "CLM-0042 / Sara / three
   problems" and how its signals are phrased (title, detail, rule, source,
   confidence, next action). That phrasing is our target.
2. Read `docs/04-Architecture.md` §6 (where the LLM is allowed to act — and
   where it must never act) and `docs/05` §1 (evidence / JSON pointers).
3. Research *structured output*: how do you force an AI to answer in an exact
   format and what breaks that guarantee? (OpenAI/Anthropic structured
   outputs, Pydantic AI.)
4. Research *what makes a healthcare explanation trustworthy* — the "review,
   don't adjudicate" boundary; why an AI must never sound like it is making a
   medical decision.

**What you build (in order):**
1. A **research note** answering the four questions above, with sources (URLs).
2. A **finding narrative template** — the exact shape of a good explanation
   (what it must state, what it must never state).
3. The **explanation service** — given a fired rule + its evidence, produce the
   reviewer-facing explanation.
4. The **verifier** — a check that an explanation only cites real evidence and
   never invents a rule.
5. **API documentation** — a Postman/Swagger package that anyone can follow.

**Milestones / deliverables:**
- [ ] M1: research note + sources
- [ ] M2: narrative template (reviewed with the lead)
- [ ] M3: working explanation service on one real fixture
- [ ] M4: verifier + tests
- [ ] M5: API docs

**Quality bar:** every explanation maps to a real rule id and a real evidence
pointer; nothing medical is ever asserted; the demo never looks flaky.

---

### Stream B — The Evaluation & Metrics layer

**Mission:** the jury grades our detection quality — and the numbers we show
them must be honest and defensible. You own the measurements.

**Start here (research first):**
1. Read `docs/03` §3 (scoring) and the phrase "Macro F1 balances precision and
   recall across finding types". Understand what each word means.
2. Read `docs/05` §7 (the 50-claim benchmark) and §8 (the evaluation harness).
3. Research: what is F1? precision? recall? macro vs micro averaging? Why does
   a system that flags *everything* score well on recall and uselessly on
   precision? Why does the "clean claim" false-positive rate matter?
4. Research *bootstrap confidence intervals* — why a number on 50 samples is
   not a single number, and how to report a range honestly.
5. Research where synthetic healthcare data comes from (e.g. Synthea, HL7's
   official FHIR example claims) — we may need to build our own test data.

**What you build (in order):**
1. A **research note** answering the five questions above, with sources.
2. A **benchmark dataset design proposal** — how to build 50 test claims with
   known answers (each with a seeded, one-defect "mutation" of a healthy
   claim), and how to split train/dev/test without leaking.
3. The **metrics module** — Macro F1, per-rule breakdown, clean-claim false
   positive rate, computed on a small toy set first.
4. The **bootstrap CI** — resample the claims, report honest ranges.
5. The **report generator + evaluation dashboard screen** — one page showing
   the numbers a jury can read.

**Milestones / deliverables:**
- [ ] M1: research note + sources
- [ ] M2: benchmark design proposal
- [ ] M3: metrics module on a toy set (hand-computed answer as the test)
- [ ] M4: bootstrap CIs + tests
- [ ] M5: report generator + dashboard screen

**Quality bar:** every number shown is reproducible (same run → same output);
no metric is reported without its method; the clean-claim false-positive rate
is displayed as prominently as the headline F1.

---

### Stream C — The Data & Documents layer

**Mission:** claims arrive as files (FHIR/CSV) plus attachments (PDFs, scans).
You own the data — the fixtures, the synthetic test data, and turning documents
into text the rest of the pipeline can read.

**Start here (research first):**
1. Read `docs/01` §5 (coding: ICD-10 / CPT) and §7 (FHIR, eClaimLink,
   standards) — know what a claim file actually contains.
2. Explore Velodoc's claim lab and **scrape what you can** (page content,
   fixture characteristics: payers, providers, the 13 scenarios). If a page is
   JS-rendered, use your browser's dev tools and document what you did.
3. Read `docs/05` §1 (the canonical model we map files into) and §7 (the
   mutation-generator idea).
4. Research: FHIR R4 Bundle structure (entry, resource, fullUrl, contained
   resources); how a "clean" claim looks; how to *deliberately break* a claim
   in one realistic way (coverage ended, duplicate line, missing attachment).
5. Research OCR for documents: pypdf (text layer), docTR / PaddleOCR
   (image-to-text), and why **any OCR text must be treated as untrusted data**
   (prompt injection — docs/04 §10).

**What you build (in order):**
1. A **research + scraping note** — what Velodoc's fixtures look like, what a
   FHIR claim contains, OCR options compared, all with sources.
2. A **fixture pack** — our own synthetic claim files (FHIR JSON) covering the
   six signal families, derived from what you learned. If Velodoc's data never
   arrives, ours must stand alone.
3. The **mutation generator** — take a healthy claim, inject exactly one
   realistic defect, record what was injected (this becomes the test's correct
   answer).
4. The **OCR pipeline** — PDF/image attachment → text, with a clear
   "found text / could not read" outcome.
5. The **intake/upload screen** — drag a claim (and attachments) into the
   system with clear feedback.

**Milestones / deliverables:**
- [ ] M1: research + scraping note (with the actual URLs/data you gathered)
- [ ] M2: fixture pack (≥ 13 claims, one per signal family, well-formed JSON)
- [ ] M3: mutation generator + tests (same seed → same mutant)
- [ ] M4: OCR pipeline on a sample PDF + tests
- [ ] M5: intake screen

**Quality bar:** every generated claim is schema-valid and its defect is
documented; every mutant is reproducible; OCR output is never fed onward
without being marked as untrusted text.

---

## 5. Shared ground rules

These apply to everyone, every day.

### Branches
- One branch per deliverable: `stream/<your-stream>/<short-name>`
  (e.g. `stream/a/explanation-template`). Create it off `main`, never commit
  directly to `main` except tiny doc/typo fixes with the lead's OK.

### Commits — be descriptive
Format (Conventional Commits):
```
<type>(<scope>): <short summary>

<body: what and why, not how>
```
- `type`: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`
- `scope`: the area, e.g. `narrative`, `benchmark`, `fixtures`, `ui`
- **The body answers: what changed and why** — a reviewer should understand the
  commit without asking you.
- Keep commits small and logical. One commit = one idea.
- Example:
  ```
  feat(narrative): add no-clinical-claim guard to explanation template

  The template must never assert a medical judgment; add a hard exclusion
  so reviewers see only administrative findings. Pairs with the verifier
  in the same stream.
  ```

### Pull requests
Open a PR with this template filled in (we keep the same shape every time):
```
## What
(1-2 sentences: what this PR does)

## Why
(why it exists — the problem it solves, not the code)

## How tested
(commands run, test names, screenshot for UI)

## Notes
(anything the reviewer should know; what you are unsure about)
```
- `git pull --rebase` before pushing to keep the branch clean.
- Request a review **after** the local gates pass (§3 Stage 4).
- The reviewer merges. Only the reviewer merges.

### Asking for help
- Blocked more than ~2 hours on the same thing? **Ask.** Write down exactly:
  the goal, what you tried, the error, and what you think the problem is.
- Use the team channel, not DMs, so everyone learns from the answer.

### Definition of done (for every deliverable)
- [ ] Understood (research note exists where required)
- [ ] Implemented in the repo, in the project's style
- [ ] Tested (at least one test that fails without the feature; gates green)
- [ ] Documented (docstring/note says what it does and why)
- [ ] Reviewed and merged on `main`

### Demos
- **Mondays:** short demo of the last milestone, from a clean state. If it
  cannot be shown, it isn't done.

---

## 6. Milestones calendar

| When | Team milestone |
|---|---|
| **This week (S1/S2)** | Research notes per stream; first synthetic fixtures; first narrative template; metrics toy set |
| **By 22 Sep** | All streams at M3: working explanation, metrics on real claims, mutation generator |
| **By 1 Oct — Phase 1 MVP** | Full pipeline demoable: claim in → findings with evidence → human review → audit trail |
| **By 20 Oct — Phase 2** | Benchmark numbers (Macro F1 + clean-claim FP) honest and reproduced |
| **By 1 Nov — Phase 3** | UI polished, docs + videos ready |
| **14–15 Nov — Finals** | Pitch + live demo |

The lead keeps the detailed sprint board; this roadmap is the shared truth of
*direction*.

---

## 7. Repo map — where things live

```
claimguard/
  canonical.py        the common claim shape (what every claim becomes)
  contracts.py        the official output format of a finding
  ingest/fhir.py      reads FHIR R4 claim files           <- Stream C touches
  ingest/resolve.py   links patient/provider/coverage     <- Stream C touches
  audit/chain.py      tamper-evident log                  (senior track)
  workflow/           Temporal orchestration              (senior track)
tests/                unit + integration tests
docs/01..06           domain / requirements / architecture / data model / specs
```

Your stream's start-here section tells you which files you will touch. When in
doubt about a piece, read its docstring first.

---

## 8. What we need from each other

- **Stream A** needs a fired rule + its evidence to explain → depends on the
  rules engine (senior track) — while that lands, use the repo's fixtures and
  the published Velodoc examples as your input.
- **Stream B** needs claims with known answers → provided by **Stream C**'s
  fixture pack and mutation generator. Coordinate on the format early (one
  shared `manifest.jsonl` shape — ask the lead for the agreed schema).
- **Stream C** needs nothing but a browser and the docs. Start first, the
  others lean on you.
- **Everyone** reads `docs/01` (§6 has five worked examples) at least once.

Work in the open, one thought at a time, and never wait silently for the
organizers' data — **we build our own.**
