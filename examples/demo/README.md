# Demonstration kit

[Back to the project README](../../README.md) · [Phase 1 input samples](../phase1/README.md) · [Demo runbook](../../docs/verification/PHASE1-DEMO-RUNBOOK.md)

Eight synthetic claims: one clean, seven with one to three deliberate defects each.
`00-coverage-and-total` carries three at once - the coverage lapse and the late
submission of `02`, plus a total that does not match the line - so one upload can be
the whole demonstration. Every claim here was generated and then **checked by the
engine** (`scripts/make_demo_claims.py`); if a claim stopped producing the findings it
declares, that script fails rather than shipping a demo that narrates something else.

```text
claims/     upload these (one claim per file, complete ClaimGuard JSON)
corrected/  the same claims with the defects repaired — paste into the correction editor
```

**The flow these are built for:** Document Intake -> upload a file -> it waits in
the list (nothing runs yet) -> press **Start check** on that row -> it is checked
and appears in **My Queue** -> read the findings and evidence, ask **XAI**, decide,
correct and recheck.

The presenter's sheet - every claim, what it demonstrates, the fields to change, the
reviewer note and the button to press — is [`CORRECTIONS.md`](CORRECTIONS.md).

| Claim | Demonstrates |
|---|---|
| `claims/00-coverage-and-total.json` | Coverage ended before the service, the submission is late, and the total does not match the line |
| `claims/01-clean.json` | A valid claim: nothing is flagged (12 pass, 3 not applicable) |
| `claims/02-coverage-and-window.json` | Coverage ended the day before the service, and the claim was submitted late |
| `claims/03-arithmetic-and-total.json` | A line that does not add up, and a claim total matching neither line nor itself |
| `claims/04-duplicate-and-limit.json` | Two identical service lines, and a quantity above the fictional maximum |
| `claims/05-authorization-and-document.json` | An imaging service with no authorization reference and no accompanying report |
| `claims/06-code-identity-currency.json` | A service code outside the catalogue, a coverage naming another member, and the wrong currency - and the four checks that can only ABSTAIN while the code is unknown |
| `claims/07-missing-value.json` | A required value missing: the check fails, and the ones that need it abstain |

All content is synthetic and refers to a fictional payer; no real patient or payer data
involved. The service codes, policies and limits come from the teaching pack's catalogue.
