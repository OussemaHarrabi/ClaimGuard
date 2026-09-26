# AI assistance ablation — what the explanation layer contributes, and what it costs when the model fails

> **Why this document exists.** The pack's submission checklist asks for an "Evaluation report with
> dataset split, rule metrics, false positives/negatives and **AI ablations**". The evaluation report
> (`EDU-EVALUATION-REPORT.md`) scores the deterministic engine and states that it does not score
> explanation quality; the ablation inside it compares the engine with the pack's own baseline, which
> is a *system* comparison. The AI ablation — what the bounded explanation layer contributes, and what
> its failure costs — was missing. This document supplies it, for the contract the product actually
> ships.
>
> **How to read it.** Every number below was printed by the command shown directly above it and is
> pasted verbatim. Nothing is estimated, and **no model-quality number appears anywhere**: we have not
> measured one on the current contract, and §5.2 says so explicitly.
>
> **Posture.** The system reviews; it does not adjudicate. A `PASS` in these tables is a rule status,
> never a payment approval; a `FAIL` is a finding for a human reviewer, never a denial.

---

## 1. The ablation

Two provider paths are run over the *same* findings of the *same* split, through the same verifier,
the same guards and the same fallback:

| Path | Provider | What it represents |
|---|---|---|
| `template` | `TemplateExplanationProvider` | The product default: deterministic template text, no model, no network. |
| `model-unavailable` | `UnavailableModelProvider` | Model mode selected but unreachable: every call fails closed before any transport exists. |

The measurement is an ablation of the layer's contribution and of its failure mode, not of model
quality:

- **Contribution.** On the deterministic path, how many explanations the verifier *accepts* — i.e.
  whether the shipped contract is satisfiable with no model at all.
- **Cost of failure.** On the failing path, how many findings fall back to the deterministic text
  (the model-eligible ones) and how many are declined outright (never sent to a model).
- **The number that matters.** How many of the statuses moved between the two paths. The assistance
  layer may rewrite prose only, so this count must be **0**; a non-zero value makes the script exit
  non-zero.

---

## 2. The run — development split

```bash
uv run python scripts/ai_ablation.py --split development
```

Captured output (exit code 0). The pack is auto-discovered; paths and the interpreter are the ones
`uv` selected on the machine that ran it.

```text
ClaimGuard AI assistance ablation — split=development
synthetic teaching data; the system reviews, it never approves, denies or pays a claim

claims file  : C:\Users\oussa\oussema\CSTAM\ClaimGuardAI_Student_Starter_Pack\ClaimGuardAI_Student_Starter_Pack\data\development\claims.jsonl
claims       : 400
findings     : 6000 (15 per claim)
engine       : C:\Users\oussa\oussema\CSTAM\.venv\Scripts\python.exe -m claimguard.edu.run --claims C:\Users\oussa\oussema\CSTAM\ClaimGuardAI_Student_Starter_Pack\ClaimGuardAI_Student_Starter_Pack\data\development\claims.jsonl --rules-dir C:\Users\oussa\oussema\CSTAM\ClaimGuardAI_Student_Starter_Pack\ClaimGuardAI_Student_Starter_Pack\rules --output artifacts\ai-ablation\development\engine_results.jsonl (exit 0)
results      : artifacts\ai-ablation\development\engine_results.jsonl (sha256 025366105049abe7…)
offline      : 0 socket event(s) observed while armed; model endpoint configured: no

Paths:
- `template` — deterministic template text: always available, no model, no network
- `model-unavailable` — model selected but unreachable: every model-eligible finding falls back to the deterministic text, every other finding is declined

### What each path did with all findings

| path | provider | provenance | served | accepted | fell back | declined | rewritten |
|---|---|---|---|---|---|---|---|
| template | `template` | deterministic | 6000 | 6000 | 0 | 0 | 6000 |
| model-unavailable | `model-unavailable` | model | 6000 | 0 | 499 | 5501 | 6000 |

### Reasons attached to outcomes

| path | reason category | count |
|---|---|---|
| template | (none) | 0 |
| model-unavailable | declined: status not model-eligible | 5501 |
| model-unavailable | fallback: provider failure | 499 |

Exact reason texts (first 10 per path, by frequency):

- **template**
  - (no reason was recorded: every finding was accepted as written)
- **model-unavailable**
  - 5014 times: status PASS is not sent to a model; the deterministic text stands
  - 499 times: provider model-unavailable failed: ProviderError: model mode is not fully configured; set CLAIMGUARD_EXPLAIN_BASE_URL and CLAIMGUARD_EXPLAIN_MODEL
  - 487 times: status NOT_APPLICABLE is not sent to a model; the deterministic text stands

### By rule

| rule | served | template: accepted | template: fell back | template: declined | model-unavailable: accepted | model-unavailable: fell back | model-unavailable: declined | statuses moved |
|---|---|---|---|---|---|---|---|---|
| R001 | 800 | 400 | 0 | 0 | 0 | 36 | 364 | 0 |
| R002 | 800 | 400 | 0 | 0 | 0 | 19 | 381 | 0 |
| R003 | 800 | 400 | 0 | 0 | 0 | 44 | 356 | 0 |
| R004 | 800 | 400 | 0 | 0 | 0 | 32 | 368 | 0 |
| R005 | 800 | 400 | 0 | 0 | 0 | 34 | 366 | 0 |
| R006 | 800 | 400 | 0 | 0 | 0 | 32 | 368 | 0 |
| R007 | 800 | 400 | 0 | 0 | 0 | 31 | 369 | 0 |
| R008 | 800 | 400 | 0 | 0 | 0 | 29 | 371 | 0 |
| R009 | 800 | 400 | 0 | 0 | 0 | 47 | 353 | 0 |
| R010 | 800 | 400 | 0 | 0 | 0 | 43 | 357 | 0 |
| R011 | 800 | 400 | 0 | 0 | 0 | 10 | 390 | 0 |
| R012 | 800 | 400 | 0 | 0 | 0 | 23 | 377 | 0 |
| R013 | 800 | 400 | 0 | 0 | 0 | 56 | 344 | 0 |
| R014 | 800 | 400 | 0 | 0 | 0 | 36 | 364 | 0 |
| R015 | 800 | 400 | 0 | 0 | 0 | 27 | 373 | 0 |

### By status

| status | served | template: accepted | template: fell back | template: declined | model-unavailable: accepted | model-unavailable: fell back | model-unavailable: declined | statuses moved |
|---|---|---|---|---|---|---|---|---|
| PASS | 10028 | 5014 | 0 | 0 | 0 | 0 | 5014 | 0 |
| FAIL | 638 | 319 | 0 | 0 | 0 | 319 | 0 | 0 |
| UNABLE_TO_ASSESS | 360 | 180 | 0 | 0 | 0 | 180 | 0 | 0 |
| NOT_APPLICABLE | 974 | 487 | 0 | 0 | 0 | 0 | 487 | 0 |

### Status invariance

| comparison | rows compared | statuses changed |
|---|---|---|
| template vs model-unavailable | 6000 | 0 |
| template vs engine output | 6000 | 0 |
| model-unavailable vs engine output | 6000 | 0 |
| template: fields other than `explanation` changed | 6000 | 0 |
| model-unavailable: fields other than `explanation` changed | 6000 | 0 |

claims with at least one moved status: 0 of 400

RESULT: PASS — the assistance layer moved no status on either path

machine-readable summary: artifacts\ai-ablation\development\ai_ablation.json
```

### 2.1 The status-change count is zero, and here is what backs it

| Comparison (development split, 6000 findings) | Rows | Statuses changed |
|---|---:|---:|
| `template` path vs `model-unavailable` path | 6000 | **0** |
| `template` path vs the engine's own output | 6000 | **0** |
| `model-unavailable` path vs the engine's own output | 6000 | **0** |
| Fields other than `explanation` changed (`template`) | 6000 | **0** |
| Fields other than `explanation` changed (`model-unavailable`) | 6000 | **0** |
| Claims with at least one moved status | 400 | **0** |

The two paths are compared *by `(claim_id, rule_id)`*, not positionally; the script refuses to
compare result sets that cover different rows, and refuses a duplicate row, so "0" cannot come from
comparing nothing. `RESULT: PASS` on the last line of the transcript is that same number, and the
process exit code is 0 only when it holds.

### 2.2 What the tables say, read plainly

- **The deterministic path satisfies the contract with no model.** 6000 of 6000 template
  explanations were accepted by the verifier, against the original envelope, with the citation,
  rule-echo, untrusted-instruction and no-decisions guards all active. Zero rejections, zero
  fallbacks, zero declines.
- **The failure mode is bounded and visible.** When the model is unavailable, the 499 findings whose
  status makes them model-eligible (`FAIL` 319 + `UNABLE_TO_ASSESS` 180) each fall back to the
  deterministic text with the provider fault recorded; the other 5501 (`PASS` 5014 +
  `NOT_APPLICABLE` 487) are declined without a call, because a rule that did not flag anything is
  never sent to a model. No finding lost its finding.
- **The blast radius is per-rule visible.** Fallbacks range from 10 (R011) to 56 (R013) — the model
  path's exposure is proportional to how often a rule flags something, not uniform across the
  rulebook.
- **Nothing moved but the prose.** Every comparison in §2.1 is 0: not one status, and not one field
  other than `explanation`, differed on either path, at any rule, at any status.

---

## 3. The other two splits

```bash
uv run python scripts/ai_ablation.py --split validation
uv run python scripts/ai_ablation.py --split stress
```

Digest of all three machine-readable summaries (`artifacts/ai-ablation/<split>/ai_ablation.json`):

```bash
uv run python -c "
import json, pathlib
print('split        claims findings | template accepted | model-eligible (FAIL+UNABLE+NOT_IMPL) fell_back | declined (never sent) | statuses moved | sockets')
for split in ('development','validation','stress'):
    path = pathlib.Path('artifacts/ai-ablation')/split/'ai_ablation.json'
    d = json.loads(path.read_text(encoding='utf-8'))
    t, f = d['paths']
    eligible = sum(f['by_status'].get(s, {}).get('served', 0) for s in ('FAIL','UNABLE_TO_ASSESS','NOT_IMPLEMENTED'))
    print(f\"{split:12s} {d['claims']:6d} {d['findings']:8d} | {t['counts']['accepted']:17d} | {eligible:12d} {f['counts']['fell_back']:9d} | {f['counts']['declined']:18d} | {d['invariance']['statuses_changed_between_paths']:14d} | {d['offline']['socket_events_observed']}\")
    assert eligible == f['counts']['fell_back']
print('every model-eligible finding fell back; no other field moved on any split:', all(json.loads((pathlib.Path('artifacts/ai-ablation')/s/'ai_ablation.json').read_text(encoding='utf-8'))['invariance']['immutable_field_changes'] == {'template': 0, 'model-unavailable': 0} for s in ('development','validation','stress')))
print('model endpoint configured in any run:', any(json.loads((pathlib.Path('artifacts/ai-ablation')/s/'ai_ablation.json').read_text(encoding='utf-8'))['offline']['model_endpoint_configured'] for s in ('development','validation','stress')))
"
```

```text
split        claims findings | template accepted | model-eligible (FAIL+UNABLE+NOT_IMPL) fell_back | declined (never sent) | statuses moved | sockets
development     400     6000 |              6000 |          499       499 |               5501 |              0 | 0
validation      150     2250 |              2250 |          190       190 |               2060 |              0 | 0
stress           50      750 |               750 |           88        88 |                662 |              0 | 0
every model-eligible finding fell back; no other field moved on any split: True
model endpoint configured in any run: False
```

All three splits agree: the deterministic path accepts every explanation, the failing path falls back
on exactly the model-eligible findings and declines the rest, and **no status moves on any of them**.

---

## 4. How the failing model was simulated — and the proof that no network was used

### 4.1 The simulation

`model-unavailable` is not a stub written for this document: it is the shipped fail-closed provider
`claimguard.edu.explain.UnavailableModelProvider`, the provider the product selects when model mode is
switched on but no endpoint is configured. Its `explain()` raises `ProviderError` immediately:

- no HTTP transport is constructed, so there is nothing to reach a network with;
- the raise happens before any socket, DNS lookup or request is attempted;
- the orchestrator catches it and returns the deterministic text with the fault recorded on the
  outcome (`fallback: provider failure`), which is exactly the production behaviour the pack's
  Required MVP behaviour 6 asks for.

That is why the reasoning path is honest: the ablation does not claim a small model's output was bad.
It measures what the layer does *when the model is not there*, which is a failure mode we can produce
exactly and repeatably, rather than a quality score we cannot.

### 4.2 The offline proof

Two independent facts, both printed by the run itself:

1. **`model endpoint configured: no`** — `ModelSettings.from_env()` is `None`, so no endpoint existed
   for any path to call. This is asserted, not assumed: the end-to-end tests invoke the script with
   `CLAIMGUARD_EXPLAIN_BASE_URL`, `CLAIMGUARD_EXPLAIN_MODEL`, `CLAIMGUARD_EXPLAIN_API_KEY`,
   `CLAIMGUARD_EXPLAIN_TIMEOUT` and `CLAIMGUARD_EXPLAIN_MAX_TOKENS` removed from the environment.
2. **`0 socket event(s) observed while armed`** — the script arms a `sys.addaudithook` hook for the
   whole explanation phase (`NetworkGuard` in `scripts/ai_ablation.py`). CPython raises
   `socket.__new__` whenever a socket object is constructed and `socket.getaddrinfo` whenever a name is
   resolved, which is everything a transport must do before sending a byte. The hook *fails the run*
   on any such event: if a transport had been reached, this run would have ended with
   `REFUSED: this ablation is offline by contract, but <event> was attempted while it ran` and exit
   code 2, not with a table.

That count is a measurement only if the guard fires when it should, so the same guard is exercised as
a negative control:

```bash
uv run pytest tests/edu_explain/test_ablation_script.py -k "guard or refused" -v
```

```text
collecting ... collected 18 items / 16 deselected / 2 selected

tests/edu_explain/test_ablation_script.py::test_a_socket_attempt_inside_the_run_is_refused PASSED [ 50%]
tests/edu_explain/test_ablation_script.py::test_the_network_guard_fails_closed_and_then_disarms PASSED [100%]

====================== 2 passed, 16 deselected in 1.68s =======================
```

- `test_the_network_guard_fails_closed_and_then_disarms` asserts that `socket.getaddrinfo` inside the
  armed guard raises `NetworkAttemptedError`, that the attempt is recorded, and that once disarmed an
  ordinary socket is unaffected.
- `test_a_socket_attempt_inside_the_run_is_refused` asserts that the guard is armed *inside the run*
  and not merely defined: a poisoned enrichment step that touches a socket makes the whole run end in
  `REFUSED: this ablation is offline by contract …` with exit code 2 and no summary file written.

"0 events" therefore means *nothing tried*, not *nothing was checked*.

---

## 5. What this measures, what `docs/18` measured, and what is still unmeasured

### 5.1 What this ablation measures

Structural properties of the shipped contract, on real data, all of them reproducible by one command:

- the share of findings the deterministic path can explain without any model (6000 of 6000 on
  development);
- the exposure of the model path (499 of 6000 findings model-eligible on development) and its
  behaviour on failure (all of them fall back, none of them is silently dropped);
- the layer's authority boundary, measured rather than asserted: **0 statuses moved between the two
  paths, and 0 fields other than `explanation` moved**, on 9000 findings across the three public
  splits.

It does **not** measure whether any of that prose is *good*. Nothing here says a sentence is clear,
complete or useful to a reviewer.

### 5.2 What `docs/18` measured, and why its numbers are historical evidence only

`docs/18-SLM-Benchmark-Methodology.md` asked a different question — can a small, locally deployable
model turn one deterministic finding into acceptable wording — and answered it with a Colab run on a
Tesla T4 on 2026-09-25. Its artifacts are preserved verbatim under
`docs/verification/slm-benchmark/2026-09-25/`. Two facts from those artifacts, measured here:

```bash
uv run python -c "
import csv, json, pathlib
root = pathlib.Path('docs/verification/slm-benchmark/2026-09-25')
rows = list(csv.DictReader((root/'claimguard_semantic_review.csv').open(encoding='utf-8')))
print('semantic_review rows:', len(rows), '| columns:', list(rows[0]))
print('non-empty supported labels:', sum(1 for r in rows if (r.get('supported') or '').strip()))
d = json.loads((root/'claimguard_slm_benchmark.json').read_text(encoding='utf-8'))
print('configurations:', len(d['summary']))
for c in d['summary']:
    print(' ', c['model'], 'schema_valid', c['schema_valid'], 'cases?', c.get('cases'), 'gate', c['safety_gate_pass'])
"
```

```text
semantic_review rows: 22 | columns: ['label_key', 'model', 'case_id', 'claim_index', 'claim_text', 'evidence_ids', 'cited_evidence', 'supported']
non-empty supported labels: 0
configurations: 5
  gemma4-e4b-q4 schema_valid 0.75 cases? None gate False
  phi4-mini-bf16 schema_valid 0.5 cases? None gate False
  phi4-mini-q4 schema_valid 0.25 cases? None gate False
  qwen3-4b-bf16 schema_valid 0.5 cases? None gate False
  qwen3-4b-q4 schema_valid 0.25 cases? None gate False
```

Those numbers are **historical evidence only**, for three reasons, all recorded in `docs/18` itself:

1. **They measured a superseded contract.** The run scored the earlier prompt and output shape. `docs/18`
   §10 records that the product now asks one model call for `explanation` **and**
   `correction_recommendation` together with exact evidence paths, rule IDs and the unchanged
   human-review boundary — a five-key output behind an `accept` / `fallback` / `decline` envelope with
   an assistance receipt. The notebook was upgraded to that contract and **has not been rerun**, so
   `docs/18` §9's table is evidence about the previous prompt, not about the one that ships.
2. **No configuration passed its own gate.** All five configurations recorded `safety_gate_pass:
   false`, and the semantic-review export has 22 rows with **0** completed `supported` labels, so
   unsupported-claim rate stays saturated and the gate cannot pass by construction. The run's own
   selection rule (§8) therefore kept the deterministic template as the product — which is why the
   deterministic path is the baseline this ablation measures against.
3. **Its corpus is small and not this split.** The semantic review covers 22 generated claims from the
   notebook's synthetic case set, not the 400-claim development split, and `docs/18` §4 says the set
   must be expanded (at least five examples per explanation-bearing rule/status combination, plus
   adversarial cases) before a jury-facing result is reported.

Because the contract changed and the notebook was not rerun, **this document deliberately reports no
model-quality figure**: we have no measurement of the current contract, and quoting the old one would
present a superseded number as a current one. `docs/18` §10 says the same thing in its own words.

### 5.3 What is still unmeasured — human explanation-quality scoring of the pack's 25 cases

This is the gap no script can close, and it is the largest unearned item in the mentor's proposed
weighting (grounded AI explanations, 20 of 100 in `docs/verification/PHASE-1-GAP-ANALYSIS.md` §6):

- The pack requires **manual 0/1 scoring of its 25 supplied explanation cases** — correct finding,
  correct evidence, correct rule, appropriate corrective action, honest uncertainty — plus a separate
  list of unsupported statements; `docs/18` §5 adds a blind fluency rating as a secondary human
  measure.
- That scorecard is **not reproducible by a command**: it is a human judgement about wording, and no
  automated check in this repository can substitute for it. The evaluation report already states this
  and reports no explanation-quality number; so does this document.
- The layer ships **the machinery** to run that lab — the deterministic text path, the model path, the
  verifier with its rejection reasons, and the corpus contract tests over the pack's cases
  (`tests/edu_explain/test_explanation_cases.py`) — but the 0/1 labels themselves are still to be
  produced by hand.

Until those labels exist and are adjudicated, the honest statement is: **the assistance layer is
structurally sound and measurably non-interfering; its prose quality is unscored.**

---

## 6. Reproducing

```bash
# the ablation (pack auto-discovered; artifacts land in artifacts/ai-ablation/, gitignored)
uv run python scripts/ai_ablation.py --split development
uv run python scripts/ai_ablation.py --split validation
uv run python scripts/ai_ablation.py --split stress

# the script's own tests (the pack-guarded end-to-end test skips cleanly where the pack is absent,
# e.g. in CI; the aggregation, guard and pack-independent end-to-end tests always run)
uv run pytest tests/edu_explain/test_ablation_script.py -q
```

Result of the test command on this machine: `18 passed`.

Options: `--claims` / `--rules-dir` run it without the mentor pack (against the committed catalogue
`tests/edu/fixtures/pack_reference/`), `--pred` reuses an existing engine result file instead of
re-running the engine, and `--workdir` moves the artifacts. Exit codes: `0` no status moved; `1` a
status moved (the tables say where); `2` refused (usage, IO, rule-catalogue, engine or contract
failure).
