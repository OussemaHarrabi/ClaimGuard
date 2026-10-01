# Demo corrections — what to change, and what to press

Every claim under `claims/` has its corrected twin under `corrected/`. To demonstrate the
correction and recheck step: open the claim in **My Queue**, press **Correct claim &
recheck**, select everything in the JSON editor, paste the matching `corrected/` file,
and press **Create version & recheck**. The original version stays; version 2 supersedes
it and the findings should clear.

| Claim file | Demonstrates | Findings it produces |
|---|---|---|
| `claims/01-clean.json` | A valid claim: nothing is flagged (14 pass, 3 not applicable) | none — 14 PASS, 3 NOT_APPLICABLE |
| `claims/02-coverage-and-window.json` | Coverage ended the day before the service, and the claim was submitted late | `R003` FAIL, `R014` FAIL |
| `claims/03-arithmetic-and-total.json` | A line that does not add up, and a claim total matching neither line nor itself | `R007` FAIL, `R012` FAIL |
| `claims/04-duplicate-and-limit.json` | Two identical service lines, and a quantity above the fictional maximum | `R006` FAIL, `R013` FAIL |
| `claims/05-authorization-and-document.json` | An imaging service with no authorization reference and no accompanying report | `R008` FAIL, `R009` UNABLE_TO_ASSESS, `R010` FAIL |
| `claims/06-code-identity-currency.json` | A service code outside the catalogue, a coverage naming another member, and the wrong currency - and the four checks that can only ABSTAIN while the code is unknown | `R004` FAIL, `R008` UNABLE_TO_ASSESS, `R009` UNABLE_TO_ASSESS, `R010` UNABLE_TO_ASSESS, `R011` FAIL, `R013` UNABLE_TO_ASSESS, `R015` FAIL |
| `claims/07-missing-value.json` | A required value missing: the check fails, and the ones that need it abstain | `R001` FAIL, `R007` UNABLE_TO_ASSESS, `R013` UNABLE_TO_ASSESS |

---

## `01-clean.json` — A valid claim: nothing is flagged (14 pass, 3 not applicable)

**Nothing to fix.** This is the control: a complete, consistent claim that
the engine does not flag. Use it to show that a valid claim passes, and that the
remaining statuses are `NOT_APPLICABLE` rather than `PASS`.

## `02-coverage-and-window.json` — Coverage ended the day before the service, and the claim was submitted late

**What the engine reports**

- `R003` → **FAIL**
- `R014` → **FAIL**

**What to change** (field → new value)

```text
coverage.end_date  2026-04-29 -> 2026-12-31  (the service date must fall inside it)
submission_date    2026-09-14 -> 2026-05-05   (within 60 days of the service date)
```

**Paste-ready:** `corrected/02-coverage-and-window-fixed.json`

**Suggested reviewer interaction** - across the set this uses all four buttons a
reviewer has:

- `R003` → **Confirm issue** — "Coverage dates verified against eligibility; the service is outside it."
- `R014` → **Confirm issue** — "Submission lag confirmed from the dispatch record."

For the **XAI** assistant, these questions stay in scope:
- "Why is this flagged?"
- "What should I check first?"
- "Which line is affected and what did the rule compare?"

Guardrail: ask *"Should we just pay this claim?"* - it refuses, and says the
decision is a reviewer's and a payer's.

## `03-arithmetic-and-total.json` — A line that does not add up, and a claim total matching neither line nor itself

**What the engine reports**

- `R007` → **FAIL**
- `R012` → **FAIL**

**What to change** (field → new value)

```text
lines[0].net_amount  271 -> 260   (quantity 2 x unit price 130)
total_amount         999 -> 260   (the sum of the line amounts)
```

**Paste-ready:** `corrected/03-arithmetic-and-total-fixed.json`

**Suggested reviewer interaction** - across the set this uses all four buttons a
reviewer has:

- `R007` → **Confirm issue** — "Line amount recomputed: quantity x unit price does not reach it."
- `R012` → **Mark corrected for recheck** — "Total corrected on the new version; rechecking it."

For the **XAI** assistant, these questions stay in scope:
- "Why is this flagged?"
- "What should I check first?"
- "Which line is affected and what did the rule compare?"

Guardrail: ask *"Should we just pay this claim?"* - it refuses, and says the
decision is a reviewer's and a payer's.

## `04-duplicate-and-limit.json` — Two identical service lines, and a quantity above the fictional maximum

**What the engine reports**

- `R006` → **FAIL**
- `R013` → **FAIL**

**What to change** (field → new value)

```text
lines[1].service_date  2026-05-25 -> 2026-05-26  (two services need two dates)
lines[1].quantity      4 -> 3                     (the policy maximum for SVC-LAB)
lines[1].net_amount    480 -> 360                 (3 x 120)
total_amount           720 -> 600                 (240 + 360)
```

**Paste-ready:** `corrected/04-duplicate-and-limit-fixed.json`

**Suggested reviewer interaction** - across the set this uses all four buttons a
reviewer has:

- `R006` → **Dismiss with reason** — "Clinic confirmed two separate services on the same day; not a duplicate."
- `R013` → **Confirm issue** — "Quantity is above the fictional maximum for this service."

For the **XAI** assistant, these questions stay in scope:
- "Why is this flagged?"
- "What should I check first?"
- "Which line is affected and what did the rule compare?"

Guardrail: ask *"Should we just pay this claim?"* - it refuses, and says the
decision is a reviewer's and a payer's.

## `05-authorization-and-document.json` — An imaging service with no authorization reference and no accompanying report

**What the engine reports**

- `R008` → **FAIL**
- `R009` → **UNABLE_TO_ASSESS**
- `R010` → **FAIL**

**What to change** (field → new value)

```text
lines[0].authorization_id null -> AUTH-DEMO-05   (the reference the policy demands)
authorizations            [] -> one approved record matching patient and service
attachments               [] -> one final imaging-report for this service and date
```

**Paste-ready:** `corrected/05-authorization-and-document-fixed.json`

**Suggested reviewer interaction** - across the set this uses all four buttons a
reviewer has:

- `R008` → **Request information** — "Authorization reference absent; requested from the provider."
- `R010` → **Request information** — "Imaging report absent; requested from the provider."

For the **XAI** assistant, these questions stay in scope:
- "Why is this flagged?"
- "What should I check first?"
- "Which line is affected and what did the rule compare?"

Guardrail: ask *"Should we just pay this claim?"* - it refuses, and says the
decision is a reviewer's and a payer's.

## `06-code-identity-currency.json` — A service code outside the catalogue, a coverage naming another member, and the wrong currency - and the four checks that can only ABSTAIN while the code is unknown

**What the engine reports**

- `R004` → **FAIL**
- `R008` → **UNABLE_TO_ASSESS**
- `R009` → **UNABLE_TO_ASSESS**
- `R010` → **UNABLE_TO_ASSESS**
- `R011` → **FAIL**
- `R013` → **UNABLE_TO_ASSESS**
- `R015` → **FAIL**

**What to change** (field → new value)

```text
lines[0].service_code  SVC-XRAY -> SVC-LAB   (a code the catalogue contains;
                                              this one change clears R008, R009, R010
                                              and R013, which could only abstain)
                                                    code resolved to nothing)
coverage.member_id     MEM-SOMEONE-ELSE -> the member_id above (must be equal)
currency                 USD -> SAR                   (the policy currency)
```

**Paste-ready:** `corrected/06-code-identity-currency-fixed.json`

**Suggested reviewer interaction** - across the set this uses all four buttons a
reviewer has:

- `R011` → **Confirm issue** — "Not in the payer catalogue; confirmed against the coding sheet."
- `R015` → **Confirm issue** — "The policy is priced in SAR; a USD total cannot be processed as submitted."

For the **XAI** assistant, these questions stay in scope:
- "Why is this flagged?"
- "What should I check first?"
- "Which line is affected and what did the rule compare?"

Guardrail: ask *"Should we just pay this claim?"* - it refuses, and says the
decision is a reviewer's and a payer's.

## `07-missing-value.json` — A required value missing: the check fails, and the ones that need it abstain

**What the engine reports**

- `R001` → **FAIL**
- `R007` → **UNABLE_TO_ASSESS**
- `R013` → **UNABLE_TO_ASSESS**

**What to change** (field → new value)

```text
lines[0].unit_price  null -> 120   (then 2 x 120 = 240, as the line and total say)
```

**Paste-ready:** `corrected/07-missing-value-fixed.json`

**Suggested reviewer interaction** - across the set this uses all four buttons a
reviewer has:

- `R001` → **Request information** — "Unit price missing from the source; requested from the provider."
- `R007` → **Request information** — "The line cannot be computed until the unit price is supplied."

For the **XAI** assistant, these questions stay in scope:
- "Why is this flagged?"
- "What should I check first?"
- "Which line is affected and what did the rule compare?"

Guardrail: ask *"Should we just pay this claim?"* - it refuses, and says the
decision is a reviewer's and a payer's.
