# ClaimGuard AI — evaluation report (development split)

Report format version **1.0.0** · generated 2026-09-22T01:59:49+00:00 · generator `scripts/edu_report.py` · engine revision `77171e6d94cb2d942b4fc6cd48180a35315c2bbb`

Headline: 6000 claim-rule pairs, status accuracy 1.0000, issue precision 1.0000, issue recall 1.0000, false alarms 0, missed issues 0.

Every number below was produced by this single run; none is estimated. A metric with an
empty denominator is printed as `null`, never as 100%.

## Reproduction

The generator ran, in this order: the engine, the mentor's strict scorer, then the
independent conformance harness. Each block is the literal argv of this run; the
placeholder form below it is the equivalent operator entry point, where `<pack>` is the
absolute path visible in the literal command.

**Engine** (`python -m claimguard.edu.run`), literal argv:

```bash
C:\Users\oussa\oussema\CSTAM\.venv\Scripts\python.exe -m claimguard.edu.run --claims C:\Users\oussa\oussema\CSTAM\ClaimGuardAI_Student_Starter_Pack\ClaimGuardAI_Student_Starter_Pack\data\development\claims.jsonl --rules-dir C:\Users\oussa\oussema\CSTAM\ClaimGuardAI_Student_Starter_Pack\ClaimGuardAI_Student_Starter_Pack\rules --output artifacts\edu-report\development\predictions.jsonl
```

Exit code 0; stderr (verbatim):

```text
claimguard.edu: claims=400 records=6000
claimguard.edu: by_rule=R001=400 R002=400 R003=400 R004=400 R005=400 R006=400 R007=400 R008=400 R009=400 R010=400 R011=400 R012=400 R013=400 R014=400 R015=400
claimguard.edu: by_status=FAIL=319 NOT_APPLICABLE=487 PASS=5014 UNABLE_TO_ASSESS=180
claimguard.edu: output=artifacts\edu-report\development\predictions.jsonl
```

```bash
uv run python -m claimguard.edu.run --claims <pack>/data/development/claims.jsonl --rules-dir <pack>/rules --output <workdir>/development/predictions.jsonl
```

**Mentor's strict scorer** (`<pack>/src/evaluate.py`), literal argv:

```bash
C:\Users\oussa\oussema\CSTAM\.venv\Scripts\python.exe C:\Users\oussa\oussema\CSTAM\ClaimGuardAI_Student_Starter_Pack\ClaimGuardAI_Student_Starter_Pack\src\evaluate.py --gold C:\Users\oussa\oussema\CSTAM\ClaimGuardAI_Student_Starter_Pack\ClaimGuardAI_Student_Starter_Pack\data\development\expected_results.jsonl --pred artifacts\edu-report\development\predictions.jsonl --claims C:\Users\oussa\oussema\CSTAM\ClaimGuardAI_Student_Starter_Pack\ClaimGuardAI_Student_Starter_Pack\data\development\claims.jsonl --output artifacts\edu-report\development\metrics.json
```

Exit code **0** (0 = accepted). Metrics JSON: `artifacts\edu-report\development\metrics.json`.

**Independent conformance harness** (`scripts/edu_conformance.py`):

```bash
uv run python scripts/edu_conformance.py --pred artifacts/edu-report/development/predictions.jsonl --split development --workdir artifacts/edu-report --accuracy-scope implemented --min-accuracy 1.0
```

**This report:**

```bash
uv run python scripts/edu_report.py --split development --output docs/verification/EDU-EVALUATION-REPORT.md
```

Generator: `scripts/edu_report.py` (format version 1.0.0); generated 2026-09-22T01:59:49+00:00; interpreter `C:\Users\oussa\oussema\CSTAM\.venv\Scripts\python.exe`.

Machine-readable context written alongside the report (every number in this report is a field of it): `artifacts\edu-report\development\report_context.json`.

## Data discipline and dataset identity

All supplied data is synthetic. The pack's protocol is that development is the open
development set, the validation labels must be disclosed as development feedback once
they influence development, and the stress split tests robustness rather than a
representative prevalence sample (docs/07_Evaluation_and_Acceptance.md).

**Our disclosure:** we have scored all three public splits (see
`docs/verification/EDU-PACK-CONFORMANCE.md`), so the validation labels are development
feedback for us and are treated as such. No split in this repository is naive to us any
more; the mentor's 200 held-out claims are the only untouched evidence, and they are not
in this repository and were not used.

Manifest `data/dataset_manifest.json`: version `1.0.0`, generated 2026-09-17, synthetic=`True`.

| Split | Claims | Claim-rule pairs | Expected statuses |
|---|---:|---:|---|
| development | 400 | 6000 | FAIL 319, NOT_APPLICABLE 487, PASS 5014, UNABLE_TO_ASSESS 180 |
| validation | 150 | 2250 | FAIL 117, NOT_APPLICABLE 181, PASS 1879, UNABLE_TO_ASSESS 73 |
| stress | 50 | 750 | FAIL 26, NOT_APPLICABLE 63, PASS 599, UNABLE_TO_ASSESS 62 |

Inputs of the scored **development** split, with live SHA-256 digests and the pack manifest's own recorded digest for the same path:

| Input | Bytes | SHA-256 (this run) | SHA-256 (pack manifest) | Agreement |
|---|---:|---|---|---|
| `data/development/claims.jsonl` | 529892 | `629ab7db7a87e4af8bd529e89c42b3c85f3a62d9c6b087c2cc8fe7982ea58104` | `629ab7db7a87e4af8bd529e89c42b3c85f3a62d9c6b087c2cc8fe7982ea58104` | match |
| `data/development/expected_results.jsonl` | 4280984 | `c5ac748271649a03a9180faec0a021e56bbf66c4403d95b8377aa4d6d04a40e7` | `c5ac748271649a03a9180faec0a021e56bbf66c4403d95b8377aa4d6d04a40e7` | match |
| `data/development/fhir_bundles.jsonl` | 1453586 | `4971ad95aae7ad41f83c620864601711c86621a84982d7cd848cb5898f074880` | `4971ad95aae7ad41f83c620864601711c86621a84982d7cd848cb5898f074880` | match |
| `data/development/csv/attachments.csv` | 48511 | `6aaf8f85533734c8e8503b5449ba8313903acf7897a9ad2389b9ef94f8340193` | `6aaf8f85533734c8e8503b5449ba8313903acf7897a9ad2389b9ef94f8340193` | match |
| `data/development/csv/authorizations.csv` | 24863 | `83647877c212bee4c01da784f86baf8f99fe1bd99742af5814aca7a10a14934e` | `83647877c212bee4c01da784f86baf8f99fe1bd99742af5814aca7a10a14934e` | match |
| `data/development/csv/claims.csv` | 75525 | `8240d649d61c55fd60527de47cffdd962be022e25e7f1882b6ef33be10a8e1d0` | `8240d649d61c55fd60527de47cffdd962be022e25e7f1882b6ef33be10a8e1d0` | match |
| `data/development/csv/coverage.csv` | 38358 | `d5c090392b1c19c97749571a6effe2969c430441b53127ad2dd0e041d850a2eb` | `d5c090392b1c19c97749571a6effe2969c430441b53127ad2dd0e041d850a2eb` | match |
| `data/development/csv/lines.csv` | 46499 | `e534cd06d238ed54fe28ffdb0923381cb164544b7786ba823dc057f73f80591f` | `e534cd06d238ed54fe28ffdb0923381cb164544b7786ba823dc057f73f80591f` | match |

## Engine and catalogue identity

Engine revision: `77171e6d94cb2d942b4fc6cd48180a35315c2bbb`. The working tree may carry uncommitted work; the source digest below is the authoritative identity of the code that produced these numbers.

Engine source digest: `b516003c5592a1a47a7d75641c14b40b11ded9d3d99a212a8b246c343a215c08` over 10 file(s):

| Source | SHA-256 |
|---|---|
| `claimguard/edu/__init__.py` | `4b0aeef638fd9d14fc56c5b1fda001e93ad96b8a090922c7b6368d55be9f714d` |
| `claimguard/edu/emit.py` | `278469991e05f35b971fb8ddae792fb00aca587328cb494a1c48e69a668470dc` |
| `claimguard/edu/engine.py` | `8a5e1bea8b266598d6bb75989d1e217d1f534f9bfa69b62c0785e1272a5a0bfa` |
| `claimguard/edu/envelope.py` | `944b65f25b4bf5a63888e1565e821924927f7325689e82037123d37b09e05f49` |
| `claimguard/edu/evidence.py` | `5c0a466cb5e9528c8cad91708a7aa48d5fb1b145046e0c6f3c54086075a02370` |
| `claimguard/edu/policy.py` | `e202019597af551db6df5f0c1d46be7d444fa20f669253ac0882ba9f2655cfd7` |
| `claimguard/edu/run.py` | `0534493f326ed3b5c8c11d9759f1d2968cf40e6b77b9aecd6417edd011212b7c` |
| `claimguard/edu/rules/__init__.py` | `223051a4e2acb01cf1295d1c51000cb62e1eacf81037ea77215427cda06ab23f` |
| `claimguard/edu/rules/r001_r007.py` | `7b9432142c6628f139941c6d0c486a2df39c8c01a2e9afc883978055b8d52d6d` |
| `claimguard/edu/rules/r008_r015.py` | `05ae15c410038f6fef5ec275660fe1906b48bee689eb4f0d34508a51cb49d05c` |

Rule catalogue digest: `b74380119147f6d2b1794ef9e5cbbb6f49ed72870f70dae7639438c05d404612` over 5 file(s):

| Catalogue file | SHA-256 |
|---|---|
| `<pack>/rules/diagnoses.json` | `16fb729732e67c0e2914a293402c2d7d351d22fcf7d9769b493e72cb21b46868` |
| `<pack>/rules/policies.json` | `fec1b06113ea03fe48a3e3d07ec1c6aa2472b65d84c61babf55e6a73dcbe7648` |
| `<pack>/rules/providers.json` | `eca93936b05b28060b30ba5490eb30f87bfa58ca391a251d981b95775b887984` |
| `<pack>/rules/rules.json` | `9c7a1c2995be3b01bed429d82c9da68253bf5a24f4be1027109588bf057d60a8` |
| `<pack>/rules/services.json` | `12df8d75640fed7ecbdbb247120666bd00a567db4b9bd2435bf0a0468cc8ba53` |

The 15 fictional rules the engine implements, as the catalogue declares them:

| Rule | Title | Severity | Version | Source |
|---|---|---|---|---|
| R001 | Required claim information | high | 1.0.0 | `fictional-rulebook/R001@1.0.0` |
| R002 | Service and submission chronology | high | 1.0.0 | `fictional-rulebook/R002@1.0.0` |
| R003 | Coverage active on service date | high | 1.0.0 | `fictional-rulebook/R003@1.0.0` |
| R004 | Member and beneficiary consistency | high | 1.0.0 | `fictional-rulebook/R004@1.0.0` |
| R005 | Provider in the supplied network | high | 1.0.0 | `fictional-rulebook/R005@1.0.0` |
| R006 | Possible duplicate service lines | medium | 1.0.0 | `fictional-rulebook/R006@1.0.0` |
| R007 | Line arithmetic | high | 1.0.0 | `fictional-rulebook/R007@1.0.0` |
| R008 | Required authorization reference | high | 1.0.0 | `fictional-rulebook/R008@1.0.0` |
| R009 | Authorization record matches service | high | 1.0.0 | `fictional-rulebook/R009@1.0.0` |
| R010 | Required supporting document | medium | 1.0.0 | `fictional-rulebook/R010@1.0.0` |
| R011 | Service code in fictional catalogue | high | 1.0.0 | `fictional-rulebook/R011@1.0.0` |
| R012 | Claim total equals line amounts | high | 1.0.0 | `fictional-rulebook/R012@1.0.0` |
| R013 | Quantity and price limits | medium | 1.0.0 | `fictional-rulebook/R013@1.0.0` |
| R014 | Submission window | medium | 1.0.0 | `fictional-rulebook/R014@1.0.0` |
| R015 | Currency matches policy | high | 1.0.0 | `fictional-rulebook/R015@1.0.0` |

## Scorer verdict and gates

**Verdict: CONFORMANT** — the mentor's scorer exited 0 (0 = the predictions are admissible).

The scorer's own output, verbatim:

```text
{
  "count": 6000,
  "tp": 319,
  "fp": 0,
  "fn": 0,
  "tn": 5681,
  "issue_precision": 1.0,
  "issue_recall": 1.0,
  "issue_f1": 1.0,
  "false_alarm_rate": 0.0,
  "status_accuracy": 1.0,
  "not_implemented": 0,
  "false_abstentions": 0,
  "missed_abstentions": 0
}
Report: artifacts\edu-report\development\metrics.json
```

Predictions scored: `artifacts/edu-report/development/predictions.jsonl` (sha256 `025366105049abe7b221082333219a03321ca6dec3c7ecc2bb3da50c3da62350`, 4254430 bytes), produced by the engine CLI (`python -m claimguard.edu.run`).

| Check | Value | Source |
|---|---|---|
| Oracle claim-rule pairs | 6000 | oracle `overall.count` |
| Independent admissibility problems | 0 | harness `independent.problems` |
| Evidence pointers re-resolved against the original claims | 20300 | harness `independent` |
| Independent recomputation of `status_accuracy` | 1.0000 | harness arithmetic over gold+pred |
| Implemented accuracy (pairs the engine committed to) | 1.0000 over 6000 pair(s) | harness arithmetic |
| Accuracy gate | scope=implemented min=1.0 accuracy=1.0000 → PASS | harness `gate` |

The gate is applied to the scope named above; it does not replace the oracle's raw
`status_accuracy`, which is reported in the metric set below and covers every pair
including any `NOT_IMPLEMENTED`.

## Metrics

All metrics are at claim-rule level unless labelled otherwise, and every value below is
the mentor's scorer JSON for this run (`overall` inside the metrics file).

| Metric | Value | Definition / source |
|---|---|---|
| Claim-rule pairs scored | 6000 | `overall.count` |
| True positives (expected FAIL, predicted FAIL) | 319 | `overall.tp` |
| False positives | 0 | `overall.fp` |
| False negatives | 0 | `overall.fn` |
| True negatives (neither side FAIL) | 5681 | `overall.tn` |
| Issue precision | 1.0000 | TP / (TP+FP); null when no FAIL is predicted |
| Issue recall | 1.0000 | TP / (TP+FN); null when no FAIL is expected |
| Issue F1 | 1.0000 | harmonic balance of the two |
| False-alarm rate | 0.0000 | predicted FAIL among pairs whose expected status is not FAIL |
| Status accuracy | 1.0000 | exact agreement across all five statuses |
| False abstentions | 0 | predicted unable-to-assess, expected something else |
| Missed abstentions | 0 | expected unable-to-assess, predicted something else |
| NOT_IMPLEMENTED predictions | 0 | visible incomplete results; counted as incorrect by the scorer |
| Claim exact match | 400 / 400 = 1.0000 | all 15 rule statuses correct for a claim (`claims_with_all_statuses_correct`) |

### Issue detection

Issue precision 1.0000, recall 1.0000, F1 1.0000. False alarms: 0 pair(s) flagged FAIL where the expected status is not FAIL. Missed issues: 0 expected FAIL pair(s) not flagged FAIL. Both are enumerated in the error analysis below.

### Uncertainty handling

False abstentions: 0 pair(s) where the engine answered unable-to-assess although the expected status is known; missed abstentions: 0 pair(s) where the expected status is unable-to-assess and the engine answered something else. Abstention is a distinct
outcome here: neither number is folded into the precision/recall pair above.

### Claim exact match

400 of 400 claim(s) have every one of their 15 statuses correct (1.0000). NOT_IMPLEMENTED counts as incorrect, so an engine that abstains from rules cannot reach a high number here by abstaining.

### Per-rule results

| Rule | n | Expected FAIL | tp | fp | fn | tn | Precision | Recall | F1 | False-alarm rate | Status accuracy | NOT_IMPLEMENTED |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R001 | 400 | 36 | 36 | 0 | 0 | 364 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0 |
| R002 | 400 | 11 | 11 | 0 | 0 | 389 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0 |
| R003 | 400 | 28 | 28 | 0 | 0 | 372 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0 |
| R004 | 400 | 28 | 28 | 0 | 0 | 372 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0 |
| R005 | 400 | 26 | 26 | 0 | 0 | 374 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0 |
| R006 | 400 | 24 | 24 | 0 | 0 | 376 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0 |
| R007 | 400 | 23 | 23 | 0 | 0 | 377 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0 |
| R008 | 400 | 11 | 11 | 0 | 0 | 389 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0 |
| R009 | 400 | 15 | 15 | 0 | 0 | 385 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0 |
| R010 | 400 | 15 | 15 | 0 | 0 | 385 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0 |
| R011 | 400 | 10 | 10 | 0 | 0 | 390 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0 |
| R012 | 400 | 23 | 23 | 0 | 0 | 377 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0 |
| R013 | 400 | 30 | 30 | 0 | 0 | 370 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0 |
| R014 | 400 | 20 | 20 | 0 | 0 | 380 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0 |
| R015 | 400 | 19 | 19 | 0 | 0 | 381 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0 |

### Confusion matrix

| Expected \ Predicted | PASS | FAIL | UNABLE_TO_ASSESS | NOT_APPLICABLE | NOT_IMPLEMENTED |
|---|---|---|---|---|---|
| PASS | 5014 | 0 | 0 | 0 | 0 |
| FAIL | 0 | 319 | 0 | 0 | 0 |
| UNABLE_TO_ASSESS | 0 | 0 | 180 | 0 | 0 |
| NOT_APPLICABLE | 0 | 0 | 0 | 487 | 0 |
| NOT_IMPLEMENTED | 0 | 0 | 0 | 0 | 0 |


### Reference ablation: the pack's own baseline

The pack ships a 3-rule reference engine. It is scored here by the same oracle on
the same split, as a floor for comparison — it is the mentor's own code, not our
AI layer, and its implementation line is quoted verbatim:

```text
Processed 400 claims. Implemented: R001, R003, R006. Other rules: NOT_IMPLEMENTED. Output: artifacts\edu-report\development\baseline_predictions.jsonl
```

| Metric | Our engine | Pack baseline |
|---|---|---|
| Claim-rule pairs | 6000 | 6000 |
| Issue precision | 1.0000 | 1.0000 |
| Issue recall | 1.0000 | 0.2759 |
| Issue F1 | 1.0000 | 0.4324 |
| False-alarm rate | 0.0000 | 0.0000 |
| Status accuracy | 1.0000 | 0.2000 |
| False abstentions | 0 | 0 |
| Missed abstentions | 0 | 156 |
| NOT_IMPLEMENTED | 0 | 4800 |
| Claim exact match | 400 / 400 | 0 / 400 |

Baseline predictions: `artifacts/edu-report/development/baseline_predictions.jsonl` (`4fdba4014c88946eb9dfbd7c414ebdea820d7de5906bc08293bc5c0c34812bfa`), scored with the gate disabled (oracle exit 0). Its 231 missed issue(s) are examples of the error class our engine does not currently produce; the first ones are listed in the error analysis.

## Error analysis

Categories are the pack's own definitions, recomputed from the gold and prediction files
and cross-checked against the oracle's JSON; a pair can fall into two categories, which
is exactly how the oracle counts it (for example an expected FAIL answered
unable-to-assess is both a missed issue and a false abstention).

| Category | Pairs | Oracle's own count | Agrees |
|---|---:|---:|---|
| false_alarm | 0 | 0 | yes |
| missed_issue | 0 | 0 | yes |
| false_abstention | 0 | 0 | yes |
| missed_abstention | 0 | 0 | yes |
| other_status_disagreement | 0 | no column | — |

The categories are:

- `false_alarm` — Predicted FAIL among pairs whose expected status is not FAIL (`fp`).
- `missed_issue` — Expected FAIL but predicted a different status (`fn`).
- `false_abstention` — Predicted unable-to-assess when the expected status is something else.
- `missed_abstention` — Expected unable-to-assess but predicted a different status.
- `other_status_disagreement` — A status disagreement that is none of the four categories above (for example expected PASS predicted NOT_IMPLEMENTED).

Status disagreements on this split: 0 of 6000 pair(s).

There are **no false alarms and no missed issues** on this split, so the pack's
template request for at least five false or missed findings *with Claim ID, Rule
ID and evidence* cannot be satisfied from this run. We do not manufacture them.
The closest honest substitute is the support analysis below plus the reference
ablation: the pack baseline's own misses are enumerated after it.

**Reference ablation errors** — the pack baseline's 25 most consequential enumerated status disagreement(s), missed issues first; the oracle counts 0 false alarm(s) and 231 missed issue(s) for it on this split.
Where the baseline left a rule unimplemented it cited no evidence at all, so the
template's 'with evidence' column is honestly empty:

| Claim ID | Rule ID | Expected | Predicted | Categories | Evidence cited |
|---|---|---|---|---|---|
| CG-123165DC3473 | R002 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-25C4F2B0CB03 | R002 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-3FA63C83E8FE | R002 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-772FD4A3A796 | R002 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-95A360C6359C | R002 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-9803B1BCD577 | R002 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-9C23B2B4D81D | R002 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-A5FE8740EAE1 | R002 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-CC927BE6D1F4 | R002 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-D9B906A730EA | R002 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-E6C6554D9BC0 | R002 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-0411B7199331 | R004 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-114A5E4AAD0D | R004 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-159105B3EBC0 | R004 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-18C278A76320 | R004 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-196A2D411E60 | R004 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-1CD9256E5BC4 | R004 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-1FF147810A45 | R004 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-27FDFBBC8C78 | R004 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-336CFEC281DA | R004 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-3584F5825D47 | R004 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-36070BCD4555 | R004 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-4AB86523A338 | R004 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-4CCB9192B4D4 | R004 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |
| CG-4F08C4FAC547 | R004 | FAIL | NOT_IMPLEMENTED | missed_issue | none cited (`NOT_IMPLEMENTED` carries no evidence) |

### Support: which rules carry the thinnest evidence

A perfect score on a rule with three expected FAILs rests on three observations. The
table ranks every rule by positive support (expected FAIL pairs — the recall
denominator) so the weakest claims are visible instead of hidden by the overall average:

| Rule | Expected PASS | Expected FAIL | Expected unable | Expected N/A | Discriminating labels | One flip moves recall by |
|---|---:|---:|---:|---:|---:|---:|
| R011 | 390 | 10 | 0 | 0 | 10 | 10.00 pts |
| R002 | 381 | 11 | 8 | 0 | 19 | 9.09 pts |
| R008 | 212 | 11 | 18 | 159 | 188 | 9.09 pts |
| R009 | 194 | 15 | 32 | 159 | 206 | 6.67 pts |
| R010 | 199 | 15 | 28 | 158 | 201 | 6.67 pts |
| R015 | 373 | 19 | 8 | 0 | 27 | 5.26 pts |
| R014 | 353 | 20 | 16 | 11 | 47 | 5.00 pts |
| R007 | 369 | 23 | 8 | 0 | 31 | 4.35 pts |
| R012 | 377 | 23 | 0 | 0 | 23 | 4.35 pts |
| R006 | 368 | 24 | 8 | 0 | 32 | 4.17 pts |
| R005 | 366 | 26 | 8 | 0 | 34 | 3.85 pts |
| R003 | 356 | 28 | 16 | 0 | 44 | 3.57 pts |
| R004 | 368 | 28 | 4 | 0 | 32 | 3.57 pts |
| R013 | 344 | 30 | 26 | 0 | 56 | 3.33 pts |
| R001 | 364 | 36 | 0 | 0 | 36 | 2.78 pts |

Thinnest positive support (fewest expected FAILs): **R011** (10 expected FAIL of 400 pair(s)), **R002** (11 expected FAIL of 400 pair(s)), **R008** (11 expected FAIL of 400 pair(s)).

Thinnest discriminating support (fewest labels that are not PASS): **R011** (10 label(s)), **R002** (19 label(s)), **R012** (23 label(s)).

Every rule has at least one expected FAIL on this split, so no per-rule precision is undefined here; recall for the thinnest rules still rests on single digits of labels.

Read this table together with the labels' own limits. The public labels cannot discriminate cross-line authorization quantity aggregation; R007's 0.01 tolerance at a rounding boundary; whitespace-only strings against a non-empty check; claims whose lines carry several service dates; precedence between a proven violation and an unknown input on the same rule.

A rule that passes every public example of such an edge is therefore not evidence that the edge is implemented correctly — only that this dataset never asked, which is why the edge-case tests for those rules are written from the rulebook rather than from the gold labels.

## AI explanation evaluation

This generator scores the deterministic engine. It does **not** score explanation
quality, and no explanation number appears in this report. The pack requires manual 0/1
scoring of the supplied explanation cases (correct finding, correct evidence, correct
rule, appropriate action, honest uncertainty) plus a separate list of unsupported
statements; that scorecard is produced by hand elsewhere and is not reproducible by a
command, so this report does not report it.

What this report can state about that seam is structural, and it is the pack's adapter
contract (`<pack>/src/llm_adapter.py`): the explanation output carries exactly four keys;
its cited evidence paths must be a subset of the finding's supplied evidence paths; its
cited rule id must equal the finding's rule id; its review flag must equal the finding's
own; and any failure falls back to the deterministic explanation with the fallback
marked. Nothing in the numbers above depends on whether a model answered, and a model
failure can never change a rule status — the statuses scored here are the deterministic
ones.

## Human review and security

Synthetic data only; no real patient record, payer rule or adjudication outcome is
present. This report is a read-only artefact: the generator writes the report, its
machine-readable context and the scorer's metrics file, and never writes inside the
mentor pack.

| Property | Evidence in this run |
|---|---|
| Pack inputs unmodified | 8 of 8 file digests agree with the pack's own `SHA256SUMS.json`; the rest are not listed there |
| Original claim envelopes preserved | predictions are a separate file (`artifacts/edu-report/development/predictions.jsonl`); no input was rewritten |
| No approval, denial, pricing or payment | the result contract has no approval or denial field; every status is one of the five review outcomes |
| Untrusted text treated as data | attachment text and `notes` never carry instructions; the deterministic engine scores them as values |

Audit, review and access-boundary evidence is produced by those workstreams and is not
re-derived here.

## Honesty rules and limitations

These are the pack's honesty rules, restated for this run. They are part of the report,
not a footnote:

- **Instructional oracle, not ground truth.** The labels in this pack are an instructional oracle for a fictional rulebook: they are neither clinical ground truth nor reimbursement ground truth, and agreement with them is not evidence of production readiness.
- **Dataset split.** This report covers the development split (400 claims, 6000 claim-rule pairs) of the supplied synthetic teaching dataset; the mentor's 200 held-out claims were not used and are not reachable from this repository.
- **Labels cannot discriminate every edge.** The public labels cannot discriminate several rulebook edges, so exact agreement here does not prove the rulebook's intent is implemented: cross-line authorization quantity aggregation; R007's 0.01 tolerance at a rounding boundary; whitespace-only strings against a non-empty check; claims whose lines carry several service dates; precedence between a proven violation and an unknown input on the same rule.
- **Evidence values do not prove relevance.** Re-resolving every evidence pointer against the original claim proves that the cited value exists and is exact; it does not prove that the cited field is relevant to the conclusion, which is a human-judgement question this generator cannot answer.
- **Explanations are scored manually.** Explanation quality is not scored by this generator: the pack requires manual 0/1 scoring of its supplied explanation cases, reported separately from the numbers here.
- **NOT_IMPLEMENTED counts as incorrect.** NOT_IMPLEMENTED is a visible incomplete result and counts against status accuracy: the mentor's scorer treats it as wrong, so an engine that abstains from a rule cannot score well by abstaining.
- **Synthetic data only, review not adjudication.** Every record is synthetic and this system reviews rather than adjudicates: it never approves, denies, prices or pays a claim, and nothing here is clinical advice.
- **Undefined metrics are null.** A precision, recall or rate whose denominator is empty is reported as null, never as 100%.
