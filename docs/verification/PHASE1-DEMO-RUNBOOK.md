# Phase-1 demo runbook

**Goal:** show the whole product — intake, the 15 deterministic checks, evidence, the XAI assistant,
a human decision, a correction and recheck, the audit trail, and the four roles — in about
**12–15 minutes**, without a single claim that behaves differently from what you say it does.

The claims are in `examples/demo/claims/` and are **verified**: `scripts/make_demo_claims.py` runs
the engine over each one and fails if a claim does not produce exactly the findings it declares. The
per-claim sheet is [`CORRECTIONS.md`](CORRECTIONS.md).

---

## 0. Before you hit record (5 minutes)

| | |
|---|---|
| **Credentials** | `examples/demo/CREDENTIALS.local.md` — local file, never committed. Four accounts, one per role. |
| **Servers** | `uv run claimguard serve` (API) and `cd frontend && npm run dev` (UI). Both must be up; the UI is on **:3000**. |
| **Session key** | The API needs `CLAIMGUARD_SESSION_KEY` **before it starts**, or every route answers 503 and you cannot sign in. If you can log in, it is set. |
| **The assistant** | `CLAIMGUARD_AI_MODE=groq` + the key in `.env` shows model answers; with it off every answer is the deterministic one and still correct — both are honest, but the model path is the better demo. |
| **Have open** | `examples/demo/claims/` in a file picker, `CORRECTIONS.md` on a second screen, and the corrected files in `examples/demo/corrected/`. |
| **Hide** | `.env`, the terminal with the API key, and `HANDOFF.md`. **Never show the API key on camera.** |
| **Browser** | Zoom ~110 %, notifications off, close other tabs. Bookmark `/workspace/my-queue` and `/workspace/document-intake`. |

**Dry-run once**: upload two claims, start one, open it. If that works, the demo works.

---

## 1. The flow, segment by segment

### Segment 1 — What this is (1 min) · landing page `/`
Say: *"ClaimGuard checks a healthcare claim before it is submitted, and explains what a human should
look at. It never approves, denies or decides anything — a reviewer does."*

Point at the landing page's own honesty line: **a PASS is not payer approval.**

### Segment 2 — Intake, and the step that matters (2 min) · Document Intake
Upload **three** claims, one after another: `01-clean`, `03-arithmetic-and-total`,
`06-code-identity-currency`.

Say while they land: *"Uploading normalises and stores the package — and stops there. Nothing has been
checked yet. They are queued."* Point at the list.

> This is the beat to linger on: the claim is a **draft waiting for a human to start the check**, not
> an auto-run. Pressing is a decision.

### Segment 3 — A valid claim is not flagged (2 min)
Press **Start check** on `01-clean` → open it from the queue.

Say: *"Fourteen checks passed and three are not applicable to this claim — not 'approved'. The three
are `NOT_APPLICABLE` because the rules do not apply here; they are not passes, and I will show you the
difference in a moment."*

### Segment 4 — The AI assistant (3 min) · the `03-arithmetic-and-total` claim
Start that one, open it, find **R007 · Line arithmetic**, and show the **evidence chips** first:
*"every finding cites the exact values it compared, from the claim as submitted."*

Then press **XAI** in the right-hand column and ask **"Why is this flagged?"**

Expect an answer that does the arithmetic out loud (2 × 130 = 260 against a recorded 271). Then type a
follow-up: **"Which line is affected and what did the rule compare?"** — the conversation continues.

**Then the guardrail**, verbatim: **"Should we just pay this claim?"**
It refuses, and says the decision belongs to a reviewer and a payer. Say: *"That refusal is
deterministic — no model was asked. The assistant cannot answer questions that are not about this
claim."*

### Segment 5 — A human decides, then corrects (3 min)
Still on `03`: type a reviewer note, press **Confirm issue**. (Across the whole demo sheet all four
buttons appear — `Confirm issue`, `Request information`, `Dismiss with reason` and
`Mark corrected for recheck` — so you can show the full decision set without contriving anything. The
`04-duplicate-and-limit` claim is the one that shows a reviewer **overriding** the engine on R006,
with a reason.)
Then **Correct claim & recheck** → select all in the JSON editor → paste
`corrected/03-arithmetic-and-total-fixed.json` → **Create version & recheck**.

Say: *"The original version is untouched — version 2 supersedes it. Nothing was edited in place; the
history keeps both."* Show the findings cleared and, at the bottom, **Recent audit activity**.

### Segment 6 — The roles (2 min)
Sign out and back in as each of the four accounts in turn. One sentence each:

* **reviewer** — only their own queue (assigned claims).
* **lead** — team queue, assignments, escalations, review quality.
* **admin** — all claims, departments, team and access, analytics, audit.
* **technical manager** — operations only, and **no claim content at all**: show that the claim pages
  are simply not there. *"Authorisation is a permission matrix in the API, not a hidden button."*

### Segment 7 — Close (1 min)
The four numbers, then the honest limits:

* **15 rules** implemented; **9,000/9,000** public claim-rule labels agree with the mentor's own
  scorer; **macro F1 1.0000**; **0 false positives**; **0.65 ms** per claim.
* Limits, said plainly: the mentor's **200 held-out claims** are the real test and are not here; the
  audit log is **tamper-evident, not immutable**; FHIR needs a sidecar because the teaching Bundle
  omits 11 fields; and with a cloud model enabled, the values cited by a finding leave the machine —
  `CLAIMGUARD_AI_MODE=off` sends nothing.

---

## 2. The points you must not forget to say

1. **"A PASS is not payer approval."** Every status is about *this* check on *this* data.
2. **`UNABLE_TO_ASSESS` is not a pass** — it is the check saying it cannot tell. `NOT_APPLICABLE`
   means the rule does not apply. Only `PASS` is a pass.
3. **The AI never decides.** It drafts wording; a verifier accepts or refuses it, and the
   deterministic status never moves.
4. **The refusal of an out-of-scope question happens before any model call.**
5. **A correction creates a new version** — the reviewed version is never overwritten.
6. **Every finding cites evidence** that re-resolves against the claim as submitted.
7. **Human-in-the-loop is real**: nothing is submitted to a payer from this product.
8. **Synthetic data only.**
9. **The honest limits** (§7 above) — saying them is what makes the rest credible.

---

## 2b. If you have extra minutes (pick one, not all)

| To show | Where | Why it lands |
|---|---|---|
| **All three intake formats** | `examples/phase1/` — `envelope.json`, the five files in `csv/`, `fhir-bundle.json` + `fhir-sidecar.json` | "A clinic sends whatever it has: complete JSON, a relational CSV export, or FHIR." For the FHIR path, say why the sidecar exists: the teaching Bundle omits eleven envelope fields and ClaimGuard refuses to invent them |
| **Unknown input handling** | Paste anything into the intake box with *auto* detection | It refuses with a specific reason ("missing envelope key: coverage") instead of guessing a format |
| **The audit chain** | Admin → **Audit integrity** | The ledger verifies end to end; say the honest limit out loud: tamper-**evident**, not immutable |
| **Review quality** | Lead → **Review Quality** | Decisions, override rate and who reviewed what — the management view |
| **The engine's own numbers** | `docs/verification/DETECTION-METRICS.md` | Macro F1, false-positive rate and latency, re-measurable with one command |

---

## 3. Pitfalls, and what to do if one happens

| What you see | What it is | What to say / do |
|---|---|---|
| An answer labelled **"Deterministic explanations only"** instead of AI wording | The model is off, misconfigured, or rate-limited | *"This is the fail-closed path — the deterministic explanation stands and the turn says so."* Then continue; nothing is broken |
| A finding has **no XAI button** | Only `FAIL` and `UNABLE_TO_ASSESS` can be explained; a `PASS` is never sent to a model | Say exactly that — it is a design choice, not a gap |
| A claim shows **"REVIEW COMPLETE"** and no findings | Every check passed, so there is nothing to explain | Use it: *"a valid claim is not flagged"*. For the AI demo, pick a claim with unresolved findings |
| Intake says **"requires sidecar"** | A FHIR Bundle alone omits 11 envelope fields | *"We refuse to invent them — the sidecar supplies them."* Or demo with the JSON/CSV path |
| Every route answers **503** | The API started without `CLAIMGUARD_SESSION_KEY` | Restart it with the key set (see §0) |
| A paste into the correction editor is rejected | The whole envelope must be pasted, `claim_id` unchanged | Select all first, then paste; the id must stay the same |

---

## 4. The claims, and what each one proves

| Claim | Demonstrates |
|---|---|
| `01-clean` | A valid claim is not flagged (14 PASS, 3 NOT_APPLICABLE) |
| `02-coverage-and-window` | Coverage ended the day before the service, and a late submission |
| `03-arithmetic-and-total` | A line that does not multiply out, and a total that matches nothing |
| `04-duplicate-and-limit` | Repeated service lines, and a quantity over the fictional maximum |
| `05-authorization-and-document` | Missing authorization reference **and** missing required report |
| `06-code-identity-currency` | Unknown service code, another member's coverage, wrong currency — **and the four checks that can only abstain while the code is unknown** |
| `07-missing-value` | A required value absent: one FAIL, and the checks that need it abstain |

Claim `06` is the one to use if you want to show **one edit clearing seven findings** — correcting the
service code alone resolves the four abstentions and the R011 failure.
