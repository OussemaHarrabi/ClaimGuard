# Detection metrics

**What this is.** The detection figures the challenge names - metrics, F1, false positive rate and latency - measured against the mentor pack's own published labels on all three splits. It complements `EDU-EVALUATION-REPORT.md` (issue-level precision, recall and F1, plus the per-rule confusion matrix) and `ENGINE-PERFORMANCE-ANALYSIS.md` (where the labels stop discriminating); it duplicates neither.

**How to reproduce it.**

```bash
uv run python scripts/detection_metrics.py
```

**What the numbers mean.** A rule's **F1** treats `FAIL` as the positive class: it is the harmonic mean of precision (of the checks we failed, the share the labels also fail) and recall (of the checks the labels fail, the share we failed). **Macro F1** is the unweighted mean of the fifteen rules' F1 scores, so a rare rule counts as much as a common one - the figure the challenge asks for, and why it is reported beside the pooled (micro) figure rather than instead of it.

**What it does not claim.** These are the pack's PUBLIC labels for a fictional payer, on synthetic claims, and the engine was developed against this data. Perfect agreement here is conformance, not generalisation: the mentor's 200 held-out claims are not in this repository and remain the only honest test of that. Nothing below is a calibrated probability of anything.

---

## 1. Headline

| Split | Claims | Pairs | **Macro F1 (15 rules)** | Macro F1 (exercised) | Micro F1 | False positive rate | Mean latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| development | 400 | 6000 | **1.0000** | 1.0000 | 1.0000 | 0.0000% | 0.64 ms |
| validation | 150 | 2250 | **1.0000** | 1.0000 | 1.0000 | 0.0000% | 0.60 ms |
| stress | 50 | 750 | **0.4000** | 1.0000 | 1.0000 | 0.0000% | 0.48 ms |

Mean latency is per claim for all fifteen rules **plus** the emitted-record contract check - the same pair of calls the API runs per submission. 5 claims are run untimed first so first-call import cost is not charged to a measured claim.

### Why the two macro columns differ from the micro column

A strict macro average over fifteen rules scores a rule with **no positive examples in that split** as 0.0. That is arithmetic about the dataset, not about the engine, and it is the whole reason the stricter figure is printed beside the fairer one. Support per split:

| Split | Rules with at least one failing label | Rules the split cannot exercise |
|---|---:|---|
| development | 15 of 15 | none - every rule is exercised |
| validation | 15 of 15 | none - every rule is exercised |
| stress | 6 of 15 | R002, R004, R005, R006, R007, R008, R011, R014, R015 |

So on `stress` the strict fifteen-rule figure is not a measurement of the engine: nine rules have no failing example anywhere in those fifty claims, no engine could score above 0.4 by that definition, and on every pair the split *can* test the engine is exact (micro F1 1.0000, zero false alarms, zero missed issues). `validation`, where all fifteen rules are exercised, is the split that measures the challenge's macro F1 without that caveat.

## 2. Latency

| Split | Mean | Median | p95 | Max | Throughput |
|---|---:|---:|---:|---:|---:|
| development | 0.64 ms | 0.52 ms | 1.37 ms | 7.24 ms | 1566 claims/s |
| validation | 0.60 ms | 0.48 ms | 1.28 ms | 2.25 ms | 1678 claims/s |
| stress | 0.48 ms | 0.40 ms | 0.70 ms | 0.94 ms | 2103 claims/s |

A single claim's fifteen checks are pure functions over one JSON object: no network, no database, no model. The API adds persistence and the audit append; the engine itself is sub-millisecond.

The timings are a snapshot of the machine that generated this file, which is why `--check` re-measures them and then ignores them when comparing. The accuracy figures above are not machine-dependent.

## 3. Errors that must be zero

| Split | False alarms | Missed issues | Wrong abstentions | Missed abstentions | Other disagreements | Valid claims wrongly flagged |
|---|---:|---:|---:|---:|---:|---:|
| development | 0 | 0 | 0 | 0 | 0 | 0 of 160 |
| validation | 0 | 0 | 0 | 0 | 0 | 0 of 62 |
| stress | 0 | 0 | 0 | 0 | 0 | 0 of 24 |

`Valid claims wrongly flagged` is the false-positive rate that matters commercially: claims with no real issue at all that the engine still sent to a human. It is reported separately from the pair-level rate because one clean claim with fifteen passing checks is fifteen chances to raise a false alarm.

## 4. Macro F1 and per-rule support

Every rule scored individually, so a rule that is never exercised cannot hide inside an average. A split with no positive examples for a rule cannot measure it - that is a property of the dataset, and it is stated rather than averaged away.

| Rule | Development F1 | Validation F1 | Stress F1 | Validation support |
|---|---:|---:|---:|---:|
| R001 | 1.0000 | 1.0000 | 1.0000 | 17 |
| R002 | 1.0000 | 1.0000 | 0.0000 | 4 |
| R003 | 1.0000 | 1.0000 | 1.0000 | 7 |
| R004 | 1.0000 | 1.0000 | 0.0000 | 7 |
| R005 | 1.0000 | 1.0000 | 0.0000 | 6 |
| R006 | 1.0000 | 1.0000 | 0.0000 | 10 |
| R007 | 1.0000 | 1.0000 | 0.0000 | 7 |
| R008 | 1.0000 | 1.0000 | 0.0000 | 4 |
| R009 | 1.0000 | 1.0000 | 1.0000 | 5 |
| R010 | 1.0000 | 1.0000 | 1.0000 | 5 |
| R011 | 1.0000 | 1.0000 | 0.0000 | 4 |
| R012 | 1.0000 | 1.0000 | 1.0000 | 13 |
| R013 | 1.0000 | 1.0000 | 1.0000 | 11 |
| R014 | 1.0000 | 1.0000 | 0.0000 | 7 |
| R015 | 1.0000 | 1.0000 | 0.0000 | 10 |

## 5. Limitations

1. **Public labels only.** The engine was developed against these splits. Perfect agreement measures conformance to the labelling programme, not accuracy on unseen data.
2. **A fictional payer.** The rules are the mentor's; the catalogues are invented. These figures say nothing about a real payer's adjudication behaviour.
3. **Synthetic claims.** No real claim, patient or member data is involved, so nothing here measures behaviour on the messiness of real submissions.
4. **Macro F1 is unweighted by frequency.** A rule with three examples contributes as much as a rule with three hundred. That is the intent of a macro average and also its limitation; the per-rule table above shows which rules are thinly supported.
5. **Latency is single-process and in-memory.** It excludes database writes, the audit append, HTTP overhead and any model call. It is the engine's cost, not a request's.
6. **No calibration.** Deterministic checks report `confidence: null` by contract; no figure here is a probability, and none should be quoted as one.

---

Generated by `scripts/detection_metrics.py` against the catalogue at `ClaimGuardAI_Student_Starter_Pack\ClaimGuardAI_Student_Starter_Pack\rules`.
