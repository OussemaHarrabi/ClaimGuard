# Phase 1: hands-on verification, not a feature checklist

This guide uses only synthetic teaching data. It is intended for a teammate or jury
member to test ingestion, rules, explanations, correction and audit in the running
app. The input files are under [`examples/phase1/`](../../examples/phase1/).
Use a local reviewer account from the **private local handoff**; no credentials
belong in this document or the demo recording.

## Actual verdict against the four scored requirements

| CSTAM item | What can be proved now | Boundary to disclose |
|---|---|---|
| Data ingestion and normalization (15) | Full ClaimGuard JSON; the five-file relational CSV export; and a FHIR R4 Bundle **paired with a verified full normalized sidecar** all reach the same 17-key engine envelope through Document Intake. Invalid packages are quarantined. | The teaching FHIR source alone omits 11 of 41 envelope leaf paths; it cannot truthfully run all 15 rules by itself. The example Bundle includes an Encounter, but the frozen scoring envelope has no encounter field, so encounter details are not persisted in that internal claim. This is **partial**, not general FHIR ingestion. The app is one-claim-per-package and 64 KiB. |
| Deterministic and AI rule engine (15) | Every accepted envelope runs R001–R015; the API returns 15 records. A coverage lapse in every example fires R003. Public-pack conformance was previously 9,000/9,000 labels, not an unseen-data accuracy estimate. | The live service defaults to deterministic explanations. No benchmark candidate has passed the model safety gate, so do **not** claim an approved SLM is running or that all AI credit is secured. |
| Explainability and structured output (10) | `GET /v1/runs/{run_id}/results` contains claim ID, rule ID, original-value JSON-pointer evidence, severity, corrective action and confidence fields for each of 15 results, plus separately persisted recommendation/provenance records. | For deterministic rules `confidence` is deliberately `null` with `confidence_kind=not_probabilistic`; it is not an omitted or invented probability. The reviewer UI shows only checks needing attention by default, with a disclosure for all 15 outcomes. |
| Audit log engine (10) | The accepted run and its 15 write-once result/provenance rows are persisted together with one append-only, SHA-256-chained `validated` ledger event; reviewer decisions add ledger events; correction creates a new version. The chain can be verified and a run replayed. | This is a **run-level** ledger, not 15 separately chained check events. Intake rejections, page views and every admin action are not individually ledgered. A database owner can rewrite chain roots. Describe it as tamper-evident within the stated trust boundary, not absolutely immutable. |

The architecture and data-flow artifact is
[`docs/11-Architecture-and-Dataflow.md`](../11-Architecture-and-Dataflow.md).
The short MVP **video still must be recorded**; a script or browser rehearsal is
not the submission artifact.

## Start the local stack

From the repository root, use the README installation steps, start PostgreSQL,
apply migrations, then run `uv run claimguard serve`. In a second terminal run
`cd frontend` and `npm run dev`. Set `CLAIMGUARD_SESSION_KEY` to a private,
random value before starting the API; provision demo accounts using the private
handoff. The frontend proxies `/v1` to `http://127.0.0.1:8000` by default.
Open `/workspace/document-intake` as an RCM reviewer or lead.

## Test A — full normalized JSON

1. Choose **Complete ClaimGuard JSON** and select
   [`envelope.json`](../../examples/phase1/envelope.json).
2. Click **Normalize and review draft**. Check the normalized patient, provider,
   coverage end date, two lines and 330 SAR total against the uploaded file.
   The drawer shows the stored intake-payload SHA-256. It fingerprints the
   server's assembled source representation (not necessarily the original file
   bytes) and does not prove that the source facts are clinically correct.
3. Click **Run 15 checks and create claim**, then **Open checked claim and findings**.
   The claim is `PHASE1-JSON-001`; R003 should report a service on 25 May 2026
   outside coverage that ended 1 May 2026. The finding and next step appear in
   the same review row. Expand **View all 15 rule outcomes** to see the full
   engine coverage, including passes and not-applicable results.
4. Click **Correct claim & recheck**. Compare the claim with the separate
   synthetic [`coverage-verification.json`](../../examples/phase1/coverage-verification.json).
   For this exercise, change **Coverage · end date** to `2026-12-31`; do not
   change a value without independent source evidence in a real review. Click
   **Create version & recheck**. Version 2 should have zero findings needing
   review. Version 1 remains in run history and audit; this is not payer approval.

Use a fresh claim ID if repeating the first submission after correcting it:
reusing an earlier ID with different content creates another version of that
claim and makes the demonstration history harder to interpret.
The sample IDs were used during local rehearsal; to create a wholly new demo
claim, copy the sample and consistently replace its claim ID (in both files for
FHIR, or the related CSV rows for CSV) before uploading.

## Test B — relational CSV

1. Choose **Five-file CSV package** and select *all five* files in
   [`examples/phase1/csv/`](../../examples/phase1/csv/) at once: `claims.csv`,
   `coverage.csv`, `lines.csv`, `authorizations.csv`, `attachments.csv`. The last
   two contain only headers and must still be selected.
2. Review the normalized `PHASE1-CSV-001` draft, submit, and open its findings.
   It reaches the same 15-rule engine; R003 should fail. Missing or unknown
   columns, duplicate/unknown claim IDs, and malformed numeric cells are
   rejected, never silently repaired.
3. Independent command-line check: run
   `python -m claimguard.edu.intake.csv_source --folder examples/phase1/csv --output <temporary-output.jsonl>`
   and then
   `python -m claimguard.edu.run --claims <temporary-output.jsonl> --rules-dir tests/edu/fixtures/pack_reference --output <temporary-results.jsonl>`.
   The result file must contain 15 JSON records for this one claim.

## Test C — FHIR R4 with an explicit completeness boundary

1. Choose **FHIR R4 Bundle + normalized sidecar**. Select
   [`fhir-bundle.json`](../../examples/phase1/fhir-bundle.json) as the Bundle and
   [`fhir-sidecar.json`](../../examples/phase1/fhir-sidecar.json) as the sidecar.
   The Bundle contains Patient, Encounter, Coverage, two Organizations (provider
   and payer), Claim diagnosis and two line items. The adapter projects the
   fields the Bundle actually carries and checks every projected value against
   the full sidecar. It never treats sidecar data as if it came from FHIR.
2. Review `PHASE1-FHIR-001`, submit and open the 15 outcomes. R003 should fail.
3. Negative test: omit the sidecar, or change its coverage end date so it
   contradicts the Bundle. The package must be quarantined with a clear reason
   and **must not** create a claim run. FHIR-only projection and its 11 unsupported
   paths are documented in [`FHIR-MAPPING-EXAMPLE.md`](FHIR-MAPPING-EXAMPLE.md).

## Inspect exact machine-readable evidence and the audit

After opening a checked claim, copy its `RUN-...` ID from the claim header.

- In the signed-in browser open `/v1/runs/RUN-ID/results`. Inspect the 15 `results`
  and 15 `explanations`. For R003 verify `claim_id`, `rule_id`, `severity`,
  `status`, `evidence` such as `/coverage/end_date`, `corrective_action`,
  `confidence: null`, `confidence_kind: not_probabilistic`, the correction
  recommendation and its deterministic/model provenance.
- Open `/v1/runs/RUN-ID` for its input hash, versions and `audit` stamp.
- As clinic admin, open **Audit** to see clinic run/decision events and chain
  hashes. As technical manager, open **Audit Integrity** to check the shared
  chain without reading claim content. The reviewer sees recent *decisions* in
  the claim workspace, not the whole audit ledger.
- From the repository run
  `python scripts/audit_replay.py --run-id RUN-ID --rules-dir tests/edu/fixtures/pack_reference`.
  It recomputes the deterministic checks from the stored envelope, compares the
  stored result fields and verifies the ledger chain. An unsuccessful replay
  exits non-zero. Do not substitute a historical transcript for a fresh run.

## What to say in the video

“The deterministic engine owns pass/fail. The recommendation is advisory and
source-linked. We can normalize JSON or CSV directly, and can check a FHIR
teaching Bundle with its verified sidecar; FHIR alone is incomplete. The result
is a structured 15-rule record, the reviewer can correct a documented error in
a new version, and the run/decision ledger can be replayed. Our SLM integration
is guarded but the current benchmark has not approved a deployment model.”
