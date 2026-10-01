# Phase 1 ingestion samples

These synthetic files let a contributor or evaluator manually exercise every required ingestion shape through **Document Intake**.

[Back to the project README](../../README.md)

## Files

| Scenario | Select these files together | Expected format |
|---|---|---|
| ClaimGuard JSON envelope | `envelope.json` | `envelope_json` |
| Relational CSV package | all five files in `csv/` | `csv_split` |
| FHIR R4 package | `fhir-bundle.json` and `fhir-sidecar.json` | `fhir_bundle` |
| Supporting verification artifact | `coverage-verification.json` | Reference evidence; include only where the rehearsal instructs it |

The CSV directory must contain exactly:

```text
claims.csv
coverage.csv
lines.csv
authorizations.csv
attachments.csv
```

## Manual ingestion

1. Run the product and sign in as an RCM reviewer, lead, or clinic admin.
2. Open **Document Intake**.
3. Choose the source format or leave detection on `auto`.
4. Select the complete file set for one scenario.
5. Create the intake job and inspect its detected format, validation message, and normalized draft.
6. If it is accepted, select **Start check**. Rules do not run before this explicit submission.
7. Open the created run from the appropriate queue and inspect all 15 results.

An invalid or incomplete package should be rejected or quarantined with a reason. It must not silently become a passing claim.

## What each format proves

- The JSON sample proves the preferred structured envelope can enter the deterministic path directly after transport validation.
- The CSV package proves relational rows can be assembled into the same internal representation.
- The FHIR sample proves standard clinical resources can contribute data while unsupported scoring fields remain explicit in a verified sidecar rather than being hallucinated.

FHIR alone does not contain every field required by the fictional Phase 1 rule contract. Do not remove the sidecar merely to call the pipeline “FHIR-native.” The current design favors complete, inspectable provenance.

For the full expected behavior, correction, recheck, and audit steps, follow [the hands-on rehearsal](../../docs/verification/PHASE1-HANDS-ON-REHEARSAL.md). For presentation-specific defective and corrected claims, use [the demonstration kit](../demo/README.md).

All names and data in this directory are synthetic.
