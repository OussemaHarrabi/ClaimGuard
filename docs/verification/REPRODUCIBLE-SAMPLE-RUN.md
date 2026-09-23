# Reproducible sample run

> **What this is:** one command that exercises the whole product on real
> mentor-pack data — intake, all 15 checks, evidence read back from the original
> claim, the reviewer's decision, the append-only ledger, and the mentor's own
> scorer — and prints a transcript. Everything below was captured from an actual
> run, not written by hand.

---

## Prerequisites

| Need | Why | Check |
|---|---|---|
| The mentor pack on disk | It supplies the claims, the rules and the scorer | `ls ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack/rules/rules.json` |
| PostgreSQL with migrations applied | The reviewer workflow persists runs, results and decisions | `uv run alembic upgrade head` |
| No network | The run is fully in-process | the transcript prints `network: none` |

The pack is **gitignored reference material** — it is deliberately not baked into
the image or the repository. A committed copy of the small rule catalogue lives at
`tests/edu/fixtures/pack_reference/` for the test suite and for container runs.

---

## The command

```bash
CLAIMGUARD_DATABASE_URL="postgresql+psycopg://claimguard:claimguard@localhost:5432/claimguard" \
uv run python scripts/sample_run.py
```

Options: `--claim-id <id>` picks a specific claim (`--split` chooses the split);
without arguments it selects a development claim **that genuinely fails at least
one check**, so the demo cannot accidentally show only happy paths. Artifacts land
in `artifacts/sample-run/` (gitignored).

---

## Captured transcript

```
ClaimGuard AI — reproducible sample run
=======================================
Synthetic teaching data. No claim is submitted to a payer.

split        : development
pack root    : <repo>/ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack
rules dir    : <repo>/.../rules
rules.json   : sha256 9c7a1c2995be3b01bed429d82c9da68253bf5a24f4be1027109588bf057d60a8
database     : postgresql+psycopg://claimguard:***@localhost:5432/claimguard (schema revision 0002)
network      : none (ASGI app in process; no server, no socket)

[1/7] claim under review — CG-785C09BD9CC8
      submitted 2026-04-24 | SAR 1520 | 1 line(s)
      line L1: SVC-IMAGE on 2026-04-10 | net 1520

[2/7] POST /v1/claims -> 201
      run_id       : RUN-90f3a58c431a441bbb8123874649a19c
      version      : 1 (supersedes None)
      input_hash   : 8653933474668e8ab107f3efc6b57649902e2aa403f4487f648e096ca1b8a686
      versions     : rule 1.0.0 | model deterministic-engine/1.0.0 | prompt none
      by_status    : PASS=13 FAIL=2 UNABLE_TO_ASSESS=0 NOT_APPLICABLE=0 NOT_IMPLEMENTED=0
      needs_attention: 2 | duplicate: True
      audit        : validated event 8b441626-... chain_hash 45bb5f3d093afd18…

[3/7] GET /v1/runs/{run_id}/results -> 15 records
      R001 PASS   R002 PASS   R003 FAIL  R004 FAIL  R005 PASS
      R006 PASS   R007 PASS   R008 PASS  R009 PASS  R010 PASS
      R011 PASS   R012 PASS   R013 PASS  R014 PASS  R015 PASS

[4/7] failing checks, with evidence read back from the ORIGINAL envelope
      R003 FAIL high — service outside coverage period
        gold label: FAIL | affected lines: ['L1'] | requires_human_review: True
        /coverage/status                 = 'active'        [resolves]
        /coverage/start_date             = '2026-01-01'    [resolves]
        /coverage/end_date               = '2026-04-09'    [resolves]
        /lines/0/service_date            = '2026-04-10'    [resolves]
        corrective action: Verify coverage applicable on the service date with the source records.
      R004 FAIL high — Patient or member identifier mismatch
        gold label: FAIL | affected lines: none | requires_human_review: True
        /patient_id                      = 'PAT-3BDC00C0D3' [resolves]
        /coverage/beneficiary_patient_id = 'PAT-3BDC00C0D3' [resolves]
        /member_id                       = 'MEM-3BDC00C0D3' [resolves]
        /coverage/member_id              = 'MEM-MISMATCH'   [resolves]
        corrective action: Resolve the patient/member mismatch using the authoritative records.

[5/7] GET /v1/queue?claim_id=CG-785C09BD9CC8 -> counts for this claim
      findings=2 unresolved=1 resolved=1 by_severity={'high': 2}
      by_review_status={'confirmed': 1, 'unreviewed': 1}

[6/7] POST /v1/runs/{run_id}/decisions
      R003 confirm_issue by demo-reviewer | original status FAIL
      reason       : Coverage ended before the service date; checked the source record and confirmed the issue.
      review state : confirmed (decisions on this finding: 1)
      decisions on this run: 1

[7/7] audit ledger for this run (append-only, hash-chained)
      validated       8b441626-18d2-4af5-bfb8-494093dbdff4  decision=None
        finding_ids=['R003', 'R004'] rule_version=1.0.0 model_version=deterministic-engine/1.0.0
        reason_code=input_sha256=8653933474668e8ab107f3efc6b57649902e2aa403f4487f648e096ca1b8a686
        prompt_version=none actor=api-submit
        prev_hash=45a8acc9dc4d393b… chain_hash=45bb5f3d093afd18…
      review_decided  95bbeabe-ff55-4a67-a1db-65f59a0d7436  decision=confirm_issue
        finding_ids=['R003'] rule_version=1.0.0 model_version=deterministic-engine/1.0.0
        prev_hash=45bb5f3d093afd18… chain_hash=314f3741fd352181…
      chain verified: 2 event(s) recomputed; 0 unlinked

split verdict — the mentor's own strict scorer, over all of development
      engine : <python> -m claimguard.edu.run --claims .../data/development/claims.jsonl \
                     --rules-dir .../rules --output artifacts/sample-run/predictions.jsonl
               claimguard.edu: claims=400 records=6000
               claimguard.edu: by_status=FAIL=319 NOT_APPLICABLE=487 PASS=5014 UNABLE_TO_ASSESS=180
      scorer : <python> .../src/evaluate.py --gold .../expected_results.jsonl --pred ... --claims ...
      scorer exit 0 (0 = predictions accepted)
      overall: 6000 claim-rule pairs | status_accuracy 1.0000 | issue_precision 1.0000
               issue_recall 1.0000 | false_alarm_rate 0.0000
      counts : tp=319 fp=0 fn=0 tn=5681 | not_implemented=0 | false_abstentions=0 | missed_abstentions=0
      claims with all 15 statuses correct: 400

what this sample run does NOT prove
  - The data is synthetic teaching data. Nothing was submitted to a payer, and this
    system has no payer-submission path at all.
  - The 15 checks are an instructional oracle, not clinical or reimbursement ground
    truth. PASS is never approval or a prediction that a payer will pay.
  - The accuracy number is agreement with the pack's gold labels on the supplied
    development split (400 claims). It is not accuracy on real claims, and the
    mentor's 200 held-out claims are not in this repository.
  - NOT_IMPLEMENTED counts as incorrect in the scorer, so the number cannot be
    inflated by abstaining from a rule.
  - A recorded decision is a reviewer's note about one check: it approves nothing,
    and it does not overwrite the evidence the check cited.
  - The audit ledger is a tamper-evident prototype over the demo rows. Production
    immutability, retention and access control are described, not built here.
```

*(Paths abbreviated with `<repo>` / `…` for readability; the script prints them in
full. Everything else is verbatim.)*

---

## What this run proves, and what it does not

**Proves.** The engine, the reviewer API, the evidence contract, the decision
contract and the append-only ledger work together on real pack data; every
evidence value re-resolves against the original claim; the mentor's scorer accepts
the engine's 6000 development predictions with status accuracy 1.0000; and the
whole run needs no network.

**Does not prove.** That the system would be accurate on real claims (the data is
synthetic and the rulebook is fictional); that the explanations are *good* (the
mentor's scorer checks only that an explanation is non-empty, and the pack states
plainly that explanation quality needs human review); that the cited evidence is
*relevant* (value equality is checked, relevance is not); that the ledger is
immutable in production (it is tamper-evident in-process only); or that a PASS
means anything about payment.

Those limits are not caveats bolted on afterwards — they are the reason the
product says **review, don't adjudicate**.
