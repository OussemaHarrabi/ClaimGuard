# ClaimGuard AI — CSTAM-VELODOC

Trustworthy Agentic Copilot for Healthcare Claim Pre-Validation.

Challenge by **Velodoc (Amazit FZCO, Dubai)** for **CSTAM 3.0** — IEEE Computer Society ENET'Com, Hammamet, Tunisia.

Mentors: Dr. Wael Hilali (CTO) · Bilel Said (CEO)

---

## Dates — non-negotiable

| Milestone | Date |
|---|---|
| **Registration closes** | **5 Sept 2026** |
| Phase 1 — MVP (50 pts) | **1 Oct 2026** |
| Phase 2 — Integration & Testing (30 pts) | **20 Oct 2026** |
| Phase 3 — UI/UX & Docs (10 pts) — **selection gate** | **1 Nov 2026** |
| Finals — Pitching (10 pts) | **14–15 Nov 2026** |

Late submission: **−5 pts**. Pitch: max 2 members, English, 12 min (5 + 2 demo + 5 Q&A).

---

## The one-sentence idea

ClaimGuard sits **between claim creation and payer submission** — it catches the administrative
problems the payer would catch, quotes the exact rule and evidence, recommends the fix, and routes
uncertain cases to a human. **Review, don't adjudicate.**

---

## Documentation

Read in order.

| # | Document | What it's for | Who reads it first |
|---|---|---|---|
| 01 | [`docs/01-DOMAIN-Gulf-Claims-101.md`](docs/01-DOMAIN-Gulf-Claims-101.md) | Gulf/Dubai claims metier from zero | **The 3 beginners — start here** |
| 02 | [`docs/02-PROBLEMATIC-Impact.md`](docs/02-PROBLEMATIC-Impact.md) | The problem + all sourced statistics | Everyone |
| 02B | [`docs/02B-PITCH-Problem-Narrative.md`](docs/02B-PITCH-Problem-Narrative.md) | Pitch-ready version of 02 | Deck authors |
| 03 | [`docs/03-Challenge-Decode-Requirements.md`](docs/03-Challenge-Decode-Requirements.md) | Rules catalogue + **traceability matrix** | Head of project |
| 04 | [`docs/04-Architecture.md`](docs/04-Architecture.md) | Architecture, ADRs, tech choices | Head + Senior dev |
| 05 | [`docs/05-System-Design-Data-Model.md`](docs/05-System-Design-Data-Model.md) | Data model, SQL, rule YAML, API, benchmark | Implementers |
| 06 | [`docs/06-Cahier-Des-Charges.md`](docs/06-Cahier-Des-Charges.md) | FR-001–105, NFR-001–020, UC-01–10 | Head + reviewers |
| 09 | [`docs/09-ARCHITECTURE-V2-Decisions.md`](docs/09-ARCHITECTURE-V2-Decisions.md) | Architecture v2 decisions, ADRs, cut list | Head + Senior dev |
| — | [`TEAM-ROADMAP.md`](TEAM-ROADMAP.md) | **Team plan**: the three work streams, methodology, ground rules | **Whole team — start here** |

---

## Core design decisions

1. **Deterministic core, LLM at the edges.** A plain Python state machine decides. The LLM writes
   explanations *after* rules fire — it never sets a rule outcome, severity, or routing.
2. **Evidence-first.** Every finding cites a JSON Pointer that resolves in code. A finding that
   cannot cite resolving evidence is not emitted.
3. **Rules as data, not code.** Versioned YAML manifests with CEL conditions, hash-pinned in git.
4. **Confidence is measured, not asserted.** Deterministic rules are 1.0 by definition. LLM
   confidence goes through self-consistency → semantic entropy → Platt/isotonic → conformal
   abstention (α=0.05). We report ECE and AUROC.
5. **Audit from birth.** Append-only Postgres + SHA-256 hash chain + OpenTelemetry. Enough to
   reconstruct, never enough to leak.
6. **Review, don't adjudicate.** Never approves, denies, diagnoses, or advises treatment.
   Crossing the clinical boundary is a disqualifier, not a point loss.

---

## Team

| Role | Focus |
|---|---|
| **HeadOfProject** | Core architecture with SeniorDev; reviews all beginner work |
| **SeniorDev** | Repo/CI, canonical model, rule engine, audit ledger, API |
| **B1 — Chatbot** | LLM normalization + explanation, Presidio, API docs, streaming |
| **B2 — Deep Learning** | Confidence calibration, evaluation metrics, active learning, data-dense UI |
| **B3 — Computer Vision** | Attachment OCR/RAG, mutation generator, 50-claim benchmark, UI screens |

---

## House rules

- **Every statistic carries (source, year, URL) — or it does not go on a slide.**
- Banned folklore: `$262B denied`, `65% never resubmitted`, `30% waste`, `MISBAR`. See `02 §3.7`.
- Synthetic data only. No real member records.
- No merge to `main` without green CI and an approving review.
- The demo must never be flaky.
