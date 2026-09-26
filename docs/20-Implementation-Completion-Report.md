# 20 — Product rebuild completion report

> **Release date:** 2026-09-26
> **Target branch:** `main`
> **Source branch:** `codex/product-rebuild`
> **Scope:** deterministic claim validation, reviewer workflow, Next.js evidence desk, secured SLM
> assistance, JEV advisory experiment, deployment packaging, benchmark methodology and handoff.
> **Posture:** review, do not adjudicate.

## 1. Executive summary

ClaimGuard is now an end-to-end pre-submission review system for the fictional CSTAM/Velodoc claim
contract. It normalizes a claim, runs all fifteen versioned deterministic rules, preserves exact
evidence pointers, creates an immutable review run, exposes findings in a responsive Next.js
cockpit, lets an administrator record bounded decisions or submit a corrected claim as a new
version, and records audit/provenance data separately from the frozen scoring record.

The explanation capability has been upgraded from a prose-only optional rewrite into a secured SLM
assistance contract. For every attention finding, the SLM may draft an explanation and a contextual
correction recommendation. It cannot set status, severity, routing, evidence or a review decision.
Every candidate is checked by a deterministic verifier and receives an `accept`, `fallback` or
`decline` decision plus a SHA-256 receipt. Unsafe, unavailable or malformed output is replaced by a
clearly labelled deterministic safe twin.

The previous Colab results remain preserved, but no model is called deployable. Qwen3 4B BF16 had
the highest raw aggregate score and Gemma 4 E4B Q4 was the strongest next experimental candidate;
both failed at least one hard gate. The benchmark notebook now implements secured contract v2 and
must be rerun before a checkpoint is selected. Fine-tuning is intentionally deferred until a larger,
adjudicated evaluation demonstrates a stable residual error that constrained generation and the
security envelope do not solve.

## 2. Delivered product capabilities

| Area | Delivered behaviour | Primary implementation |
|---|---|---|
| Contract | Exact 17-key claim envelope and frozen 15-key result record | `claimguard/edu/envelope.py` |
| Rules | R001–R015 with five statuses and rulebook precedence | `claimguard/edu/rules/` |
| Evidence | RFC 6901 paths re-resolved against the original envelope | `claimguard/edu/evidence.py` |
| Intake | Authoritative JSONL plus CSV reconstruction and bounded FHIR projection | `claimguard/edu/intake/` |
| Review runs | Immutable versioned runs, results, decisions and corrections | `claimguard/review/` |
| Queue | Counts, filters, unresolved state and claim/run selection | `GET /v1/queue` |
| Decisions | Request information, confirm issue, dismiss with reason, corrected-for-recheck | `POST /v1/runs/{id}/decisions` |
| Correction | Stored-envelope retrieval and new-version recheck | `GET /v1/runs/{id}/claim`, `POST /v1/claims/{id}/recheck` |
| Primary UI | Responsive Next.js evidence desk | `frontend/` |
| SLM assistance | Explanation plus correction recommendation under an exact five-field contract | `claimguard/edu/explain/` |
| Security envelope | Citation verification, invariant checks, injection guards, decisions and receipts | `provider.py`, `verifier.py` |
| JEV | Offline-safe typed advisory second opinion and sidecar | `claimguard/edu/judge/` |
| Audit | Append-only, hash-chained audit events with documented limitations | `claimguard/audit/`, migration `0001` |
| Packaging | Multi-stage API/frontend images and Compose stack | `Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` |
| Evaluation | Mentor scorer, independent conformance harness and generated reports | `scripts/edu_conformance.py`, `scripts/edu_report.py` |

## 3. Runtime architecture and authority boundaries

The operational flow is:

1. A normalized claim enters the API.
2. The deterministic engine evaluates all fifteen rules.
3. The frozen result records are stored as the authoritative run output.
4. Findings with `FAIL`, `UNABLE_TO_ASSESS` or `NOT_IMPLEMENTED` are eligible for bounded SLM
   assistance; `PASS` and `NOT_APPLICABLE` do not need model-generated help.
5. The SLM receives only the finding, selected rule context and supplied evidence. Evidence is data,
   never instruction authority.
6. The deterministic verifier either accepts the candidate or creates the deterministic safe twin.
7. Provenance is stored in `run_explanations`; it never adds keys to the graded result record.
8. The administrator reviews the finding, evidence, assistance and verifier state together.
9. Human actions create decision events. Corrections create a new claim version and a new run.

Authority is deliberately asymmetric:

- the rule catalogue and engine own status, severity, evidence, routing and human-review flags;
- the SLM owns no state and may only draft reviewer-facing language;
- the assistance verifier owns whether model language is displayable;
- JEV may produce a typed advisory sidecar but cannot override the engine or verifier;
- only a human can record a review decision or submit a corrected envelope;
- no explanation, judge output or UI interaction mutates an existing run.

This is the part inspired by the AegisGraph work: explicit authority edges, untrusted-data labels,
fail-closed decisions, evidence-bound outputs, tamper-evident receipts, and measurable security
outcomes instead of a prompt-only claim of safety.

## 4. Next.js frontend rebuild

The old HTML/CSS/JavaScript page remains as a fallback, but the primary product surface is a Next.js
16 reviewer cockpit. It is designed as an evidence desk rather than a chat interface.

### 4.1 Main interaction model

- left: claims queue, counts, search and unresolved state;
- centre: selected immutable run, deterministic findings, evidence and bounded review actions;
- right: explanation, correction recommendation, provenance, security decision, receipt and verifier
  warnings;
- responsive layouts preserve the same information hierarchy at narrower breakpoints;
- the correction drawer retrieves the stored claim, edits synthetic JSON, validates `claim_id`, and
  submits a new version for recheck;
- “Use as editable note” copies a verified recommendation into the administrator's note. It does
  not submit a decision or modify claim data.

### 4.2 Honesty and accessibility details

- model output is labelled “Model-assisted wording”;
- rejected output is labelled “Deterministic fallback”;
- explicitly deterministic output is never presented as SLM-generated;
- security state and receipt prefix remain visible beside provider/model/prompt provenance;
- human-review and non-adjudication boundaries are repeated at the point of use;
- keyboard-labelled controls, semantic headings, evidence regions, reduced-motion support and
  responsive breakpoints are present;
- demo mode is visibly read-only and cannot masquerade as a live API.

`PRODUCT.md` and `DESIGN.md` preserve the product and interface rationale. The rebuild follows the
familiar operational density and calm visual language requested for the Velodoc jury without copying
proprietary assets or creating a deceptive clone.

## 5. Secured SLM assistance contract

### 5.1 Exact model output

The deployed prompt version is `2.0.0`. The model must return exactly:

```json
{
  "explanation": "string",
  "correction_recommendation": "string",
  "cited_evidence_paths": ["/pointer"],
  "cited_rule_ids": ["R003"],
  "needs_human_review": true
}
```

Generation uses temperature `0.0`, JSON-object response mode and bounded tokens. The authority map in
the payload states that the engine owns every decision field and the model only drafts language.

### 5.2 Deterministic verification

The candidate is rejected when it:

- has missing or extra keys;
- returns empty explanation or recommendation text;
- cites a path that was not supplied;
- cites another rule;
- changes the engine's human-review flag;
- asserts approval, denial, payment or a clinical judgement;
- proposes automatic or unreviewed action;
- contains instruction-like content, including tested Base64-transformed forms;
- times out, returns invalid JSON, fails transport, or is not configured.

The fallback carries deterministic explanation and correction text, the rejection reasons, a
`fallback` decision and a new receipt. Missing model configuration in explicit model mode is visible;
it is not silently treated as a normal deterministic run.

### 5.3 Receipts and persistence

The receipt hashes claim/rule/status identity, explanation, correction recommendation, citations,
provider, security decision, rejection reasons and fallback state. Migration
`0004_assistance_security_envelope.sql` adds:

- `correction_recommendation`;
- `cited_evidence_paths`;
- `security_decision`;
- `receipt_sha256`;
- constraints for known decisions and 64-character lowercase hashes.

Legacy rows remain honest: their decision is `unrecorded` and no receipt is invented.

## 6. Model benchmark and deployment decision

### 6.1 Preserved historical run

The 2026-09-25 Tesla T4 run evaluated Gemma 4 E4B Q4, Phi-4 Mini BF16/Q4 and Qwen3 4B BF16/Q4.
Gemma 4 BF16 exceeded the notebook's declared fit threshold and was skipped.

| Candidate | Relevant observation | Decision |
|---|---|---|
| Qwen3 4B BF16 | Highest raw aggregate score (`0.7000`) | Rejected: schema and prompt-injection failures |
| Gemma 4 E4B Q4 | Best measured exact-contract rate (`75%`) | Next experimental candidate, not deployable |
| Phi-4 Mini variants | Ran within the recorded T4 environment | Failed at least one hard gate |
| Qwen3 4B Q4 | Lowest memory among the named Qwen variants | Failed hard gates |

All 22 manual semantic-support labels remain unadjudicated. Therefore the historical run has no
winner. Its raw CSV/JSON/environment artifacts remain under
`docs/verification/slm-benchmark/2026-09-25/`.

### 6.2 Updated v2 notebook

`notebooks/slm_explanation_benchmark_colab.ipynb` now measures the same five-field contract used by
the application. The next Colab run should compare at least:

- Gemma 4 E4B BF16 when the accelerator fits it;
- Gemma 4 E4B Q4;
- Phi-4 Mini BF16 and Q4;
- Qwen3 4B BF16 and Q4;
- raw, prompt-constrained, schema-constrained, verifier-only and complete-envelope conditions.

Hard gates include contract validity, citation validity, status invariance, prompt-injection success,
semantic support, false fallback, reviewer usefulness, latency and VRAM. Quantization is acceptable
only when the quantized candidate clears every hard gate and is not materially worse than its
unquantized counterpart.

### 6.3 Fine-tuning decision

Fine-tuning is not the next step. The current corpus is too small and incompletely adjudicated to
justify changing weights. First establish a v2 baseline with constrained decoding and the complete
security envelope. Fine-tune only when repeated errors form a stable category, the training and
held-out sets are independently reviewed, and the tuned model still passes every safety gate.

## 7. JEV advisory layer

The JEV integration is deliberately independent from the prose-generating SLM. `JevJudge` submits a
typed state and typed questions to TypeSafe AI System One and stores typed answers in a sidecar.
`NullJudge` is the default and performs no network I/O. All provider failures are typed, redacted and
made inert.

The current questions assess grounding, status agreement and attention. They are advisory signals,
not decisions. A JEV answer cannot change a result record, approve SLM language or reorder the queue
until a separately recorded evaluation authorizes that use. Live access has not been tested because
no credential/model access was supplied.

## 8. Configuration and deployment

The intended local stack is:

```bash
Copy-Item .env.example .env
docker compose up -d --build
```

Services:

- PostgreSQL 16 at `localhost:5432`;
- FastAPI at `http://localhost:8000` and OpenAPI at `/docs`;
- Next.js at `http://localhost:3001`;
- the legacy fallback at `http://localhost:8000/review`.

Model assistance is selected with:

```text
CLAIMGUARD_EXPLAIN_MODE=model
CLAIMGUARD_EXPLAIN_BASE_URL=<OpenAI-compatible endpoint>
CLAIMGUARD_EXPLAIN_MODEL=<winner from secured v2 benchmark>
CLAIMGUARD_EXPLAIN_API_KEY=<optional endpoint secret>
```

Leaving endpoint/model blank produces an explicit safe fallback. No repository secret is required or
committed. JEV stays disabled unless `CLAIMGUARD_TYPESAFE_API_KEY` is set and `claimguard judge probe`
confirms the offered model.

## 9. Verification evidence at release

Commands were run from the release worktree after the final formatting pass:

| Gate | Result |
|---|---|
| Clean-worktree backend | **610 passed, 39 skipped, 0 failed**; every skip explicitly names the absent mentor pack |
| Merged `main` backend | **649 passed, 0 skipped, 0 failed** with the local gitignored nested mentor pack present |
| `uv run --extra dev ruff check .` | Passed |
| `uv run --extra dev ruff format --check .` | 143 files already formatted |
| Focused strict Pyright | 0 errors, 1 existing private-test-helper warning |
| `npm test -- --run` | **11 passed in 3 files** |
| `npm run lint` | Passed |
| `npm run typecheck` | Passed |
| `npm run build` | Next.js production build passed; `/` and `/_not-found` prerendered |
| Notebook JSON parse | Passed |
| `git diff --check` | Passed; Windows line-ending notices only |
| Browser verification | Demo mode (`NEXT_PUBLIC_DEMO_MODE=true`) rendered; responsive three-column desktop grid confirmed; recommendation copied into the correct note. **Live mode was verified separately on 2026-09-26**: with the API origin set at build time, the cockpit loaded a real queue (13 claims / 29 findings), opened a claim, showed the evidence chips and the security panel, and recorded a decision (queue went 29 unresolved → 28 unresolved / 1 resolved, audit entry `reviewer-12 · Confirm Issue`) |

The public mentor data result remains 1.0000 status accuracy on all 9,000 public claim-rule labels,
but this is not evidence of real-claim accuracy or held-out performance.

## 10. Known limitations and explicit non-claims

1. No authentication, tenancy or role-based access control is implemented.
2. The displayed reviewer identity is configuration, not verified identity.
3. The audit ledger is tamper-evident, not deletion-proof or externally anchored.
4. No real PHI, payer integration, production denial rate or clinical outcome has been tested.
5. The mentor's private 200-claim held-out set has not been seen.
6. No v2 SLM checkpoint has passed the secured benchmark.
7. JEV has not made a live request and must remain advisory.
8. The model verifier checks structural and bounded semantic invariants; it is not a proof of factual
   relevance. Human review remains required.
9. The reviewer queue has no server-side pagination, saved views or full command palette.
10. Temporal remains a spike and is not part of the running request path.
11. No OCR capability is claimed or required by the current pack.
12. Docker Compose configuration was validated, but a complete production-like multi-container load
    and failure test remains future work.

## 11. Remaining work by priority and ownership

### P0 — project leads / senior implementation

1. Run the secured v2 notebook in Colab, complete two-reviewer semantic adjudication and select a
   deployable SLM only if every hard gate passes.
2. Configure the winning endpoint and run an end-to-end model-assisted staging evaluation.
3. Add authentication, tenant isolation, RBAC and server-derived actor identity before any real data.
4. Test migration `0004`, rollback/backup procedures and the complete Compose stack in a clean
   environment.
5. Run the mentor scorer and independent conformance gate immediately before submission.
6. Test against the private held-out set when mentors provide it; do not tune against it.
7. Record the demo video and produce the jury pitch deck from verified claims only.

### P1 — suitable beginner-team work with senior review

- B1: adjudicate SLM explanations/recommendations, label unsupported statements, expand adversarial
  cases and write reviewer-usability notes.
- B2: run the reproducible Colab matrix, capture latency/VRAM/quality artifacts and compare
  quantized versus unquantized candidates without choosing deployment policy.
- B3: build rulebook retrieval evaluation and evidence-relevance labels; keep it out of the status
  decision path.
- Frontend: pagination UX, saved filters, empty/error states, keyboard shortcuts and print styles.
- Documentation: screenshots, demo narration, operator FAQ and submission checklist.

### P2 — later production hardening

- external audit anchoring/WORM retention;
- observability dashboards and alert thresholds;
- load, soak, chaos and recovery testing;
- endpoint cost and capacity measurements;
- localization and accessibility review with real users;
- approved secret management and key rotation.

## 12. Operational handoff checklist

Before changing the engine, read `docs/10-ADR-Starter-Pack-Authority.md`. Before changing the UI or
assistance layer, read `PRODUCT.md`, `DESIGN.md`, `docs/16`, `docs/18` and `docs/19`.

For every release:

1. keep the frozen 15-key record unchanged;
2. keep model/judge provenance in sidecars;
3. apply migrations in order through `0004`;
4. run backend, lint, format, types, frontend tests and production build;
5. run mentor conformance locally when the nested pack is present;
6. archive benchmark inputs, outputs, environment and manual labels together;
7. state failures and missing evidence explicitly;
8. never call a model deployable merely because it has the highest average score.

The detailed repository map, traps, commands and mentor questions remain in `HANDOFF.md`.
