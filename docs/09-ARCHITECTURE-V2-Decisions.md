# 09 — ClaimGuard AI v2: Architecture Review, Decisions & Plan

> **Status:** v2.0 — supersedes the v1 architecture in `04` where the two conflict.
> **Date:** 2026-09-05 · **Owner:** HeadOfProject
> **Trigger:** full adversarial review + source-verified research against the competitive field
> (Nym Health, AKASA, CodaMetrix, Fathom, SmarterDx, Waystar, Optum/ClaimsXten-Lyric).

---

## 0. Verdict up front

**v1's foundations are right and we keep them.** Deterministic core, LLM at the edges,
evidence-first findings, rules-as-data, append-only audit, review-don't-adjudicate — all correct,
and all confirmed by the research as the *competitive* play, not a compromise.

**But v1 had two P0 implementation bugs that would have silently killed the rule engine,**
plus three unsound claims we must stop making. Those are fixed below.

**And v1 was under-ambitious on one axis that turns out to be our best wedge:**
per-payer rule *policy packs*. This is new in v2.

---

# PART A — The five decisions you asked for

## A1. Backend language: Python. Not TypeScript.

**Decision: Python 3.13 backend (FastAPI) + TypeScript frontend (Next.js 16).**

First, the correction: **FastAPI is a Python framework** — "TypeScript with FastAPI" cannot be
built. The real question is Python-backend vs TypeScript-backend.

**The TypeScript case, argued honestly.** One language across the team. Shared types with the
Next.js UI via Zod, no OpenAPI codegen. BullMQ, WebSockets, TanStack all native. For a team of
part-timers and three beginners, "learn one language" is a genuinely strong argument.

**Why it loses.** Our entire competitive moat is Python-only. Verified:

| Library | Why we need it | Language |
|---|---|---|
| Microsoft Presidio | PII/PHI redaction before any LLM call | **Python-only** (presidio-analyzer is a Python service; spaCy/transformers/stanza) |
| cel-python | Rule conditions (Google CEL) | **Pure Python** |
| scikit-learn | Platt scaling / isotonic calibration | Python, no JS equivalent |
| RAGAS | Narrative faithfulness scoring | Python |
| fhir.resources | FHIR R4 Pydantic models | Python |
| Pydantic AI | Typed LLM agents, validated output | Python (TS port of *Instructor* exists, not of Pydantic AI) |

A TypeScript backend does not remove Python — **it adds a second backend.** You'd run a Python
service for the moat plus a TS service for orchestration plus a TS UI: two runtimes, two type
systems, two CI pipelines, an IPC contract between them. The "one language" argument collapses on
inspection: with a Python backend the team still has exactly two languages (Python + TS) — the same
count as the "TS-only" split (TS + Python sidecar).

**What would change my mind:** a rubric that explicitly rewarded TypeScript, or a team that was
strong-TS/zero-Python. Neither holds.

Sources: [presidio-analyzer (PyPI)](https://pypi.org/project/presidio-analyzer/) ·
[cel-python (PyPI)](https://pypi.org/project/cel-python/) ·
[Pydantic AI](https://github.com/pydantic/pydantic-ai) ·
[Instructor](https://github.com/567-labs/instructor)

---

## A2. Temporal: GO — thin slice, owned by ME, gated 12 Sep

**Decision: adopt Temporal, as a deliberately thin orchestration layer, owned by the HeadOfProject
(not the senior dev), with a hard go/no-go gate on 12 Sep and a pre-designed Postgres fallback.**

**Why it's worth it.** Our HITL escalation means a claim can wait hours or days for a human. That
is the textbook durable-execution case, and Temporal gives us three things nothing else does:

1. **Durable waits that cost nothing.** `await workflow.wait_condition(...)` and
   `asyncio.sleep(days)` are durable timers — a claim waiting three days for a reviewer holds
   **zero threads, connections, or memory**. State lives server-side.
2. **Time-skipping tests.** `WorkflowEnvironment.start_time_skipping()` fast-forwards timers — a
   48-hour SLA escalation test runs in milliseconds. This is the single best testability win in
   the whole platform.
3. **Replay safety net.** The `Replayer` runs event histories through current workflow code and
   **fails CI on any non-determinism**.

**Why the ownership matters — this is the important part.** Our critic found the senior dev is the
bottleneck at ~246h (~31h/week, above the 15–20h assumption). Adding a new framework to *his* plate
would be reckless. **Temporal is infrastructure. You (the lead) already own the infra and repo
structure. So you own the Temporal spike.** It does not compete with the senior dev's capacity at
all. That reframing is what makes this a GO rather than a NO-GO.

**Why it's cheap now, specifically:** Pydantic AI ships **first-party durable execution** —
`uv add "pydantic-ai[temporal]"` then `TemporalDurability` / `PydanticAIWorkflow`, with
human-in-the-loop approval built in. Local dev is one binary: `temporal server start-dev`.

**Hard constraints (violating any of these = revert to fallback):**

| # | Constraint |
|---|---|
| 1 | **Thin workflows, fat activities.** ≤2 workflow types, no child workflows, no Nexus, no patching. All real logic in pure Python activities. Orchestration ≈ 100 lines. |
| 2 | **Postgres is the ONLY audit source of truth.** Temporal event history is orchestration state, never the audit. Never derive the audit trail from Temporal. |
| 3 | **Pass `claim_id`, never payloads.** Event history caps at 51,200 events / 50 MB. FHIR bundles and narratives go to Postgres from activities. |
| 4 | **Explicit retry policies on every activity.** The default retries *forever* — a deterministic bug becomes an infinite loop. |
| 5 | **No `datetime.now()`, `random`, `uuid`, threads, or network in workflow code.** The sandbox catches some; the Replayer catches the rest in CI. |

**The fallback (pre-designed, 1–2 days):** claims table already holds status; reviewer API already
exists; a worker polls `WHERE status='awaiting_review'`; SLA timeouts computed lazily or by a
10-line poller. Because activities are plain async functions taking and returning serializable
dataclasses (**never Temporal types**), cutting over rewrites ~100 lines of orchestration and
touches zero business logic.

**Gate (12 Sep):** a green spike — claim workflow with mocked activities + `approve` signal +
24h SLA timer + a time-skipping pytest, all green under the `Replayer` in CI. If it slips past
~1.5 days of your time, **cut to Postgres immediately.**

Sources: [Temporal Python workflows](https://docs.temporal.io/develop/python/workflows/basics) ·
[Timers](https://docs.temporal.io/develop/python/workflows/timers) ·
[Message passing / wait_condition](https://docs.temporal.io/develop/python/workflows/message-passing) ·
[Testing suite](https://docs.temporal.io/develop/python/best-practices/testing-suite) ·
[Execution limits](https://docs.temporal.io/workflow-execution/limits) ·
[LangGraph integration](https://docs.temporal.io/develop/python/integrations/langgraph) ·
[Temporal for AI](https://docs.temporal.io/ai)

---

## A3. Kubernetes: NO.

**Decision: Docker Compose. No k3s, no kind, no minikube. Helm charts deferred as a
post-competition product artifact.**

Bluntly: 5 part-timers, 4 weeks, one laptop. Nothing in our workload needs scheduling,
autoscaling, or a service mesh. Kubernetes would be a YAML and operational-knowledge money pit
with zero payoff this cycle.

**What we do instead:** `docker compose up` for api + worker + postgres + otel-lgtm + web. Keep
images small and 12-factor so a future Helm chart is **a week of work, not an architecture change**.
Containerisation is non-negotiable (it *is* the demo); orchestration is not.

---

## A4. Microservices: NO. Modular monolith with deliberate seams.

**Decision: one deployable Python service, internally split into strict modules.**

With 5 people and 4 weeks, a microservices split buys us network failures, distributed debugging,
and deployment overhead in exchange for nothing. The correct move is a **modular monolith whose
seams are drawn where a future split would go**:

| Module | Responsibility | Future service? |
|---|---|---|
| `ingest/` | FHIR/CSV parsing, reference resolution, canonical model | Rarely splits |
| `rules/` | YAML catalogue, CEL evaluation, evidence emission | **Splits first** (hot-reload, per-tenant) |
| `llm/` | Pydantic AI nodes, verifiers, caching | **Splits second** (different scaling, GPU) |
| `audit/` | Append-only writer, hash chain, verification | Splits third (compliance isolation) |
| `api/` | FastAPI routes — thin, no business logic | Stays the edge |
| `workers/` | Temporal activities calling the above | Already separate processes |

**The rule that makes the split cheap later:** modules communicate through explicit interfaces over
serializable dataclasses. No module reaches into another's tables. `llm/` never imports `rules/`
internals.

---

## A5. Observability: YES — one container, and it's a demo asset.

**Decision: OpenTelemetry Python SDK + Grafana `docker-otel-lgtm` (single image: OTel Collector +
Grafana + Loki + Mimir + Tempo).**

This is mostly **configuration, not code**, which is why it survives the "is it worth it for a
competition" test. And critically: **it is the audit/transparency demo.** Judges see trace-linked
logs of every rule firing and every LLM call, correlated by `trace_id`. That *is* the
"review, don't adjudicate — and prove it" story, made visible.

`OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`, Grafana on `:3000`. Persist via the `/data`
volume. Jaeger is moot — Tempo ships in lgtm.

Source: [Grafana docker-otel-lgtm](https://grafana.com/docs/opentelemetry/docker-lgtm/)

---

# PART B — The P0 bugs v1 shipped (fix these before writing any code)

These came out of the adversarial review. **The first two would have meant the rule engine fires
nothing at all — and it would have failed silently.**

## P0-1 · CEL conditions use camelCase; the payload produces snake_case

`to_rule_payload()` calls `model_dump(by_alias=False)` → `coverage.period_end`,
`product_or_service`, `anchor_date`. But every CEL condition in `05` §5.2 and `03` §2.4 references
**camelCase**: `payload.coverage.periodEnd`, `i.productOrService`, `payload.authorization.validFrom`.

**Result:** every rule silently fails to fire. COV-001, AUTH-006, DUP-002, INT-003, ENV-001 — dead
on arrival, with no error.

**Fix:** add Pydantic aliases (`period_end: date = Field(alias="periodEnd")`) to every canonical
model, then `model_dump(by_alias=True)`. Plus a **startup smoke test**: serialise CLM-0042 to the
dense payload and assert every CEL expression in the catalogue touches only resolvable keys.

## P0-2 · `to_rule_payload()` overwrites full objects with flat partials

The method builds an `env` dict and merges with `{**claim, **env}`. The `env` dict contains
`coverage` as a **flat dict with only `payerName`/`planName`** — which overwrites the full dumped
`Coverage` model, destroying `periodEnd`. Same for `patient` → `{memberId}` only.

**Result:** COV-001 can never see `coverage.periodEnd`. It was overwritten.

**Fix:** delete the `env` dict. `to_rule_payload()` becomes a pure `model_dump(by_alias=True)`
transformation of the whole model, plus the derived `anchorDate`. Never hand-build partial dicts
that collide with the full dump.

## P0-3 · Hash chain: DB trigger and Python compute different hashes

The Postgres trigger concatenates raw fields (`NEW.prev_hash || NEW.at::text || ...`). The Python
`chain_hash()` does `SHA256(prev_hash + "\x1f" + json.dumps(event, sort_keys=True))`. Different
serialisations.

**Result:** the two can never agree. Nightly verification passes (it uses the trigger logic), but
Python-side verification always reports broken links.

**Fix:** **one canonical serialisation, owned by the trigger** (it's in the same transaction). The
Python `verify()` must replicate the trigger logic character-for-character. Add an integration test
that inserts via Python and asserts the trigger hash matches.

## P1-4 · ENV-001/ENC-001 family: the fixture label wins (CORRECTED)

`Integrity` in the YAML (`05` §5.2), `Documentation / Clean` in `03` §2.4, `Documentation` in the
fixture table, `Clean` in `04`'s pipeline, `Clean` in `06`. Family drives severity, HITL
mandatory-escalation routing, UI colour, and metrics grouping.

**Fix (reversed from an earlier draft of this document):** for the 12 fixture-backed rules, the
family is **Velodoc's published fixture label**, not our internal taxonomy.

| Rule | Earlier internal choice | **Correct family** | Source |
|---|---|---|---|
| **ENV-001** | `Integrity` | **`Documentation`** | fixture CLM-0161 "Malformed claim envelope" |
| **ENC-001** | `Integrity` | **`Identity`** | fixture CLM-0168 "Unknown encounter" |

**Why the fixture wins.** Velodoc's 13 published fixtures are the **only externally-published,
externally-graded labels we possess**. Our internal taxonomy is ours to invent; theirs is what a
grader may compare our findings against. And we do **not** yet know whether the graded Macro F1 is
computed per rule family or per individual rule (`03` §8 mentor question 2). Matching the published
labels is therefore strictly safer: it costs nothing if scoring is per-rule, and protects us if it
is per-family.

**Authority hierarchy (state this everywhere):**
1. **Fixture-backed rules** → Velodoc's published fixture label wins. Always.
2. **Rules with no fixture** (our ADDED rules: PYR-001, AMT-001, ST-001, CLEAN-001, ID-001, LOC-001,
   plus catalogue rules R03/R04) → the YAML manifest is the single source of truth.

Update `03` §2.2/§2.4, `04` §4, `05` §5.2, and `06` §5.B.

## P1-5 · LLM normalization can silently suppress rules

LLM-02 fills nulls. If it hallucinates `authorization.reference`, then AUTH-004 ("is authorization
present?") sees a filled field and goes quiet. **The LLM has suppressed a rule outcome through the
normalization path** — exactly the thing our boundary table forbids.

**Fix — the baseline diff (this is the important one):**
1. Run rules on the **pre-LLM** canonical package → baseline finding set
2. Run normalization
3. Re-run rules → post-normalization set
4. **Any rule that fired in baseline but not after ⇒ emit `LLM_SUPPRESSED` and route to HITL**

Also tag every LLM-filled field `source_kind="llm"` so evidence pointers show the provenance.

## P1-6 · `emit()` silently drops; the cross-check gate expects to route

`emit()` drops findings whose pointer won't resolve. The cross-check gate expects to route them to
HITL. `emit()` runs first, so the gate is never reached — **a rule that fired correctly but was
mapped to a bad pointer vanishes with no audit record.**

**Fix:** `emit()` returns an enum — `EMITTED` / `SUPPRESSED(reason)` / `DEFERRED_TO_HITL`.
Suppression writes a `finding.suppressed` audit event with the rule_id and the bad pointer. Silent
drops are forbidden.

---

# PART C — Three claims we must stop making

The review caught us overselling. A technical jury (Velodoc's CTO is an ex-Bosch AI engineer) will
catch these too. Honesty scores better than a corrected over-claim.

| ❌ Stop saying | ✅ Say instead |
|---|---|
| "The hash chain proves tampering." | "The hash chain detects accidental corruption and unsophisticated tampering. Full tamper-evidence needs external anchoring (the crypto-ledger bonus). An attacker with DB write access can recompute the chain." |
| "We're calibrated (ECE ≤ 0.05)." | "Pilot-scale calibration on n≈50. Conformal abstention is **valid at any n** (tightness degrades, not validity). ECE is reported **with bootstrap CIs** and labelled pilot-scale. We never claim population-level calibration from 50 claims." |
| "Nobody does pre-submission validation." | "Clearinghouses and payer front-ends do pre-submission edits. Our wedge is **provider-side, payer-specific, and explanatory** — before the claim ever leaves the building." |

**Also — a citation correction.** Our docs cite "Groot et al. arXiv:2405.02917" for verbalized
confidence being broken. That ID is actually Valdenegro-Toro, *"Overconfidence is Key."* The
canonical study is **Miao et al., arXiv:2306.13063 (ICLR 2024)**. Fix this before it reaches a
slide — a mis-cited paper in front of a PhD jury is an unforced error.

---

# PART D — The new wedge: payer policy packs

This is the biggest v2 addition, and it came from the competitive research.

**The finding:** our own research identified the key incumbent failure mode as *"passes the
scrubber, dies at the payer."* Our critic then pointed out something uncomfortable: **our 15 rules
are equally generic, so we'd miss exactly the same payer-specific edits.**

But the research also found the gap nobody fills. Payers **publish** their front-door edit sets —
UHC publishes three stacked tiers (HIPAA Claim Edits, Smart Edits, Documentation Edits); Premera
publishes its ClaimsXten set via Availity; CMS publishes NCCI quarterly. **Nobody ships payer rules
as an open, versioned, diffable, testable artifact with provenance back to the payer's publication.**
The incumbents keep them proprietary by design.

**So we add a `payer` dimension to the rule catalogue:**

```yaml
id: COV-001
version: 3
family: Coverage
payer: "*"                     # baseline — applies to all payers

---
id: UHC-SMART-0142
version: 1
family: Documentation
payer: "UHC"                   # policy pack overlay
effective_from: "2026-02-01"
source:
  name: "UHC Smart Edits"
  url: "https://www.uhcprovider.com/..."
  retrieved: "2026-09-05"
overrides: null
```

The engine evaluates **baseline rules + the pack for the claim's payer**, and every finding names
the pack, version, and source URL that produced it. That converts "some rule fired" into *"UHC
Smart Edits edition 2026-02, edit 0142 fired — here is UHC's own page."*

**Why this is the right bet:** it's mostly schema and lifecycle discipline layered onto the
rules-as-data design we already have. Demo content for 2–3 real payers is public. And it directly
mirrors how the **$2.2B** incumbent operates — but transparently.

**Honest limit:** we can demo this, not ship 1,000+ payers. Say so.

Sources: [UHC claim edits](https://www.uhcprovider.com/en/resource-library/edi/edi-claim-edits-hipaa-ace-smart-edits.html) ·
[Optum/ClaimsXten duopoly analysis](https://www.onhealthcare.tech/p/how-optums-claims-editing-system-569)

---

# PART E — The v2 stack

| Layer | Choice | Why | Rejected |
|---|---|---|---|
| **Backend** | Python 3.13, FastAPI ≥0.141.1 | Moat is Python-only; 82/100 vs Litestar 73/100 for AI services | TypeScript/NestJS — adds a 2nd backend |
| **Tooling** | uv + ruff + pyright + pytest + pre-commit | One tool for install/venv/lock; ruff = lint+format; pyright zero-config | Poetry/PDM; mypy *and* pyright = two engines |
| **Data** | PostgreSQL 16, SQLAlchemy 2.0, Alembic, psycopg 3 | Mature typed async; raw SQL for append-only/trigger/hash-chain | SQLModel (two-model problem), Tortoise |
| **Rules** | cel-python v0.5, YAML manifests | Actively maintained (v0.5, 2026-01), CEL semantics + conformance suite, side-effect-free by spec | Hand-rolled evaluator; pyDMNrules (Excel-centric) |
| **LLM** | Pydantic AI (`pydantic-ai[temporal]`) | Typed validated output, OTel-native, UsageLimits caps, first-party durability + HITL | CrewAI/smolagents (autonomous loops); BAML (adds DSL) |
| **Orchestration** | Temporal (thin) → Postgres fallback | Durable HITL waits, time-skipping tests, replay CI gate | Celery (task queue, not orchestrator); LangGraph at MVP |
| **PII** | Presidio (own container — heavy NLP deps) | Python-native; **note: repo moved to `data-privacy-stack/presidio`** | Presidio-over-HTTP from TS |
| **Frontend** | Next.js 16 (App Router) + TS + Tailwind + shadcn/ui + TanStack Query v5 + Table v9 | Defaults are beginner-safe; Turbopack default | TanStack Router (overkill); Redux |
| **Observability** | OTel SDK + Grafana docker-otel-lgtm | One container; **is** the audit/transparency demo | Jaeger (Tempo ships in lgtm) |
| **Deploy** | Docker Compose | One-command demo | Kubernetes (deferred; Helm post-competition) |
| **CI** | GitHub Actions: ruff + pyright + pytest + Replayer | Free, standard | Self-hosted |

---

# PART F — Repo structure (your ownership)

```
claimguard/                          # repo root = C:/Users/oussa/oussema/CSTAM
├── README.md
├── docs/                            # 01-09, this file included
├── docker-compose.yml               # api, worker, postgres, otel-lgtm, web, temporal
├── .env.example
├── pyproject.toml                   # uv-managed
├── uv.lock
│
├── claimguard/                      # Python package — modular monolith
│   ├── contracts.py                 # Finding, Evidence, ExplanationStep, Override, AuditEvent
│   ├── canonical.py                 # CanonicalClaim + models WITH camelCase aliases (P0-1 fix)
│   ├── ingest/
│   │   ├── fhir.py                  # FHIR R4 bundle → canonical
│   │   ├── csv.py                   # CSV → canonical
│   │   └── resolve.py               # reference resolver (urn:uuid/oid/Type/id/#contained/absolute)
│   ├── rules/
│   │   ├── engine.py                # loads catalogue, binds payload, runs CEL
│   │   ├── registry.py              # versioning, hashing, effective dates
│   │   ├── envelope.py              # ENV-001 pre-pass
│   │   ├── packs/                   # ★ NEW: payer policy packs
│   │   │   ├── _baseline/           # payer: "*"
│   │   │   ├── UHC/
│   │   │   └── CMS-NCCI/
│   │   └── catalogue/               # COV-001.yaml, AUTH-006.yaml, ...
│   ├── llm/
│   │   ├── gateway.py               # ONE client; record/replay cassettes; prompt-hash cache
│   │   ├── narrative.py             # explanation node (post-rule only)
│   │   ├── normalize.py             # null-filling ONLY
│   │   └── verify.py                # ★ deterministic verifier after EVERY LLM node
│   ├── confidence/
│   │   ├── entropy.py               # semantic entropy
│   │   ├── calibrate.py             # Platt scaling
│   │   └── abstain.py               # conformal α=0.05
│   ├── workflow/                    # ★ NEW: Temporal (thin)
│   │   ├── activities.py            # fat, pure Python, explicit retries
│   │   └── claim_workflow.py        # ~100 lines, signals + durable timers
│   ├── audit/
│   │   ├── chain.py                 # MUST match the DB trigger byte-for-byte (P0-3 fix)
│   │   └── provenance.py            # ★ NEW: FHIR Provenance emission
│   ├── api/                         # FastAPI — thin
│   └── db/migrations/               # Alembic
│
├── web/                             # Next.js 16 frontend
├── tests/
└── benchmark/                       # mutation generator + 50-claim set + manifest.jsonl
```

---

# PART G — The verified agent topology

Agency is confined to **cognitive sub-tasks at versioned nodes**. The LLM never chooses the next
step — that's what makes it agentic *and* auditable.

```
Ingest → Normalize → Rules (15, deterministic) → Evidence resolve
                                                       ↓
                                            findings non-empty?
                                          ↙                    ↘
                                    LLM Narrative         Audit + Report
                                          ↓
                            Deterministic verifier ①   ← schema, enum, pointer,
                                          ↓               citation coverage, PII, clinical
                                    LLM Semantic Critic  ← DIFFERENT model
                                          ↓
                            Deterministic verifier ②   ← judge vs rule output
                                          ↓
                        Confidence: entropy → Platt → conformal α=0.05
                                          ↓
                              Route policy (set a priori)
                            ↙                          ↘
                    pass → Audit + Report        abstain → HITL (durable)
```

**Deterministic (100% of the decision):** ingest, normalize, rules, pointer resolution, both
verifiers, routing policy, calibration, audit.

**LLM (edges only):** narrative generator; semantic critic (different model — self-preference bias
is real: GPT-4 rates its own output higher, arXiv:2410.21819).

**Any verifier failure ⇒ mark `LLM_UNVERIFIED` and route to a human.** Never a verdict from an
unverified LLM claim.

**Demo determinism:** temperature 0 and prompt caching are **not** determinism — OpenAI states
verbatim that *"identical requests are not guaranteed to produce identical outputs."* The only hard
determinism is **record/replay cassettes** at the SDK boundary. Record once per claim, replay for
judges. The demo can never flake.

---

# PART H — Phases, DoD, and the cut list that protects the bottleneck

## Phases

> **v2 note (2026-09-05): sprint numbering is `07` §7's — the canonical plan.** An earlier draft of
> this table used a compressed S0–S8 label set that did **not** match `07`/`08`, which would have
> given the team two different week plans. `07` §7 and `08` §6 are authoritative for sprint dates
> and task placement. This table is now only a summary of *what each sprint is for*.
> Canonical: **S0** 5–6 Sep · **S1** 7–13 Sep · **S2** 14–20 Sep · **S3** 21–27 Sep (hard feature
> freeze 27 Sep) · **S4** 28 Sep–1 Oct (stabilisation + submit) · **S5** 5–11 Oct · **S6** 12–20 Oct
> · **S7** 21 Oct–1 Nov · **S8** 2–13 Nov · **Finals 14–15 Nov**.

| Sprint | Dates | Goal (summary) | Demoable increment |
|---|---|---|---|
| **S0 — Kickoff** | 5–6 Sep | **Register.** Tools installed. `FND-01` started | Repo exists, CI badge live |
| **S1 — Runway** | 7–13 Sep | Green CI + canonical models + FHIR parses its first fixture; `DAT-01` assembly; `UI-01` scaffold. **Temporal spike runs here (HoP), gate 12 Sep** | `uv run pytest` green with a CLM-0042 parse test |
| **S2 — Engine core** | 14–20 Sep | Full normalize + engine skeleton (`RUL-01..06`) + the 3 flagship rules firing + audit schema (`AUD-01/02`) | CLI: CLM-0042 → 3 findings + audit rows |
| **S3 — All rules + explanation + API** | 21–27 Sep | All rules, LLM narrative + verifiers, submit API, upload/detail UI, E2E. **Hard feature freeze 27 Sep** | POST CLM-0042 from the UI → 3 finding cards |
| **S4 — MVP freeze** | 28 Sep–1 Oct | **Stabilisation + submission only.** No new features | `demo-smoke` green twice; submit **1 Oct** |
| S5 — Confidence & HITL | 5–11 Oct | Calibration suite, HITL complete, security complete | Reliability diagram + override flow |
| S6 — Detection quality | 12–20 Oct | Macro F1 ≥ 0.90 push; submit **20 Oct** | Benchmark report with CIs |
| S7 — UI/UX + deliverables | 21 Oct–1 Nov | UI polish, docs, videos; submit **1 Nov** | Timed review ≤ 3 min |
| S8 — Pitch | 2–13 Nov | Deck + rehearsal ×3. **Finals 14–15 Nov** | 12-min pitch under 12:00 |

## The cut list — reordered to protect the senior dev

The v1 cut list was wrong: it cut beginner tasks when **the senior dev is the bottleneck**. v2 cuts
SD-owned work.

| Order | Cut | Why |
|---|---|---|
| 1 | All `BON-*` | +2 each after the first 100; zero Phase-1 points |
| 2 | Semantic entropy + self-consistency | **Calibration doesn't improve Macro F1** — which is what's scored. Keep Platt-on-logprobs + ECE with CIs |
| 3 | AUD-06/07 (replay + query API) | Phase-1 audit points come from writer + chain + nightly |
| 4 | UI-05/06/07 | "Usable" needs only intake + detail + review path |
| 5 | Full SEC corpus | Keep SEC-02 (delimiters) + SEC-04 (refusal) — they're the trust story |
| 6 | AUD-03 hash *chain* → single-hash-per-event | Recovers 6h of **SD** time; upgrade post-MVP |

**Never cut:** ING-01/02/04, RUL-01..12, LLM-01/03/05, AUD-01/02, API-01/02, EVL-09, DAT-01,
**and the P0 fixes**.

**De-risk the bottleneck:** pre-write detailed specs for RUL-07/08/09 so **you** can execute them
solo if SD stalls. They're self-contained and you own the rule content anyway.

---

# PART I — Scope changes from v1

| Change | Direction | Why |
|---|---|---|
| Payer policy packs | **ADD** | Our strongest differentiator; mostly schema discipline |
| FHIR Provenance emission | **ADD** | Cheap on top of evidence-first; matches the HIMSS26 blueprint |
| Baseline-diff suppression check | **ADD** | Closes the LLM-suppression hole (P1-5) |
| Semantic entropy + self-consistency | **CUT to Phase 2** | Doesn't improve Macro F1 |
| The 5 ADDED priority-1 rules | **PROMOTE** | Cheap, deterministic, de-risk the unknown 50-claim set |
| Cross-validate against the 13 Velodoc fixtures | **ADD** | The only truly independent test we have |
| Hand-crafted adversarial claims | **ADD** | Breaks the benchmark's circularity |
| Kubernetes, microservices | **DROP** | Wrong scale |

---

## Sources

All external claims in this document are anchored to primary sources fetched 2026-09-04/05:

Temporal: [workflows](https://docs.temporal.io/develop/python/workflows/basics) ·
[timers](https://docs.temporal.io/develop/python/workflows/timers) ·
[messages](https://docs.temporal.io/develop/python/workflows/message-passing) ·
[testing](https://docs.temporal.io/develop/python/best-practices/testing-suite) ·
[limits](https://docs.temporal.io/workflow-execution/limits) ·
[langgraph](https://docs.temporal.io/develop/python/integrations/langgraph) ·
[AI](https://docs.temporal.io/ai)

Stack: [FastAPI](https://fastapi.tiangolo.com/release-notes/) ·
[FastAPI vs Litestar](https://github.com/byte-ish/litestar-vs-fastapi) ·
[cel-python](https://github.com/cloud-custodian/cel-python/releases) ·
[Pydantic AI](https://github.com/pydantic/pydantic-ai) ·
[Instructor](https://github.com/567-labs/instructor) ·
[SQLAlchemy](https://docs.sqlalchemy.org/en/20/) ·
[Presidio](https://github.com/data-privacy-stack/presidio) ·
[Next.js 16](https://nextjs.org/docs/app/getting-started/installation) ·
[docker-otel-lgtm](https://grafana.com/docs/opentelemetry/docker-lgtm/)

AI reliability: [Miao et al. 2306.13063](https://arxiv.org/abs/2306.13063) ·
[Valdenegro-Toro 2405.02917](https://arxiv.org/abs/2405.02917) ·
[SelfCheckGPT 2303.08896](https://arxiv.org/abs/2303.08896) ·
[Semantic entropy (Nature 2024)](https://www.nature.com/articles/s41586-024-07421-0) ·
[Conformal abstention 2405.01563](https://arxiv.org/abs/2405.01563) ·
[Self-preference bias 2410.21819](https://arxiv.org/abs/2410.21819) ·
[OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs) ·
[OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)

Market/regulation: [Optum/ClaimsXten](https://www.onhealthcare.tech/p/how-optums-claims-editing-system-569) ·
[UHC edits](https://www.uhcprovider.com/en/resource-library/edi/edi-claim-edits-hipaa-ace-smart-edits.html) ·
[HIMSS26 blueprint](https://www.mobihealthnews.com/news/creating-blueprint-agentic-ai-claims-and-prior-authorization) ·
[FHIR Provenance](https://hl7.org/fhir/provenance.html) ·
[EU AI Act deferral](https://sakaradigital.com/blog/eu-ai-act-high-risk-deferral-december-2027-pharma/) ·
[ADHICS v2](https://itsecnow.com/regulators/adhics-cybersecurity)
