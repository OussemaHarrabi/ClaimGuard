# Adversarial and boundary cases: pushing the engine to its edges

**What this is.** 87 hand-built claims, each one aimed at a single boundary the
rulebook words precisely, run against the deterministic engine. All 87 behave as
the rulebook says. The cases are executable: `scripts/adversarial_cases.py` (with
`tests/edu/test_adversarial_cases.py` pinning them in CI), so this is a standing
check rather than a one-off report.

**Why it was needed.** The pack's three splits are *representative*: 600 claims
generated from one distribution. Passing them - which we do, 9000/9000 labels,
`status_accuracy 1.0000` - proves the engine agrees with the labelling programme.
It does not prove the engine survives the edges, because a generator rarely
produces "coverage ends exactly on the service date" or "the total is off by
exactly one halala". Those are where the rulebook's wording does the work, and
where a false positive (rejecting a valid claim) or a false negative (letting a
violation through) would cost points.

## What each case asserts

Each case states the status its rule MUST return, taken from the rulebook's own
sentence:

| Rule | The sentence being tested |
|---|---|
| R002 | *service_date must be on or before submission_date. Equality passes.* |
| R003 | *within coverage.start_date and end_date, **both inclusive*** |
| R006 | *Normalize null modifier to an empty string* |
| R007 | *at most 0.01 SAR passes* / *ROUND_HALF_UP* |
| R009 | *inclusive valid_from/valid_to* / *aggregate quantity <= max_quantity* |
| R010 | *if matching attachments exist but all are draft/unknown, UNABLE_TO_ASSESS* |
| R013 | *equality at the maximum passes* / *quantity must be positive* |
| R014 | *submission_date minus the latest service_date must be <= window; equality passes* |

Plus transport cases (malformed envelopes that must be refused before any rule
runs), robustness cases (hostile payloads that must not crash the engine), and a
coverage assertion that every one of the fifteen rules has at least one boundary
case - a rule whose edges nobody probes is a rule whose edges are unknown.

## Result

```
claimguard adversarial cases
  catalogue : C:/Users/oussa/oussema/CSTAM/ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack/rules
  rules     : 15  services: 6  policies: 2

case                                            expected           observed           verdict
----------------------------------------------------------------------------------------------------------
R002 service == submission (equality passes)    PASS               PASS               OK
R002 service one day after submission           FAIL               FAIL               OK
R002 service_date null                          UNABLE_TO_ASSESS   UNABLE_TO_ASSESS   OK
R001 service_date null is a known absence       FAIL               FAIL               OK
R003 service == coverage.start (inclusive)      PASS               PASS               OK
R003 service == coverage.end (inclusive)        PASS               PASS               OK
R003 service one day before coverage start      FAIL               FAIL               OK
R003 service one day after coverage end         FAIL               FAIL               OK
R003 coverage.status terminated                 FAIL               FAIL               OK
R003 coverage.status null                       UNABLE_TO_ASSESS   UNABLE_TO_ASSESS   OK
R003 coverage.end_date null                     UNABLE_TO_ASSESS   UNABLE_TO_ASSESS   OK
R003 coverage.start_date null                   UNABLE_TO_ASSESS   UNABLE_TO_ASSESS   OK
R004 member_id mismatch                         FAIL               FAIL               OK
R004 beneficiary mismatch                       FAIL               FAIL               OK
R004 absent comparison input                    UNABLE_TO_ASSESS   UNABLE_TO_ASSESS   OK
R005 provider outside the network               FAIL               FAIL               OK
R006 identical code/date/modifier               FAIL               FAIL               OK
R006 same code and date, different modifier     PASS               PASS               OK
R006 null modifier vs empty modifier            FAIL               FAIL               OK
R006 same code, different date                  PASS               PASS               OK
R006 three identical lines                      FAIL               FAIL               OK
R007 net off by exactly 0.01                    PASS               PASS               OK
R007 net off by exactly 0.02                    FAIL               FAIL               OK
R007 half-up rounding 3 x 0.335 = 1.01          PASS               PASS               OK
R007 float noise 3 x 0.1 = 0.3                  PASS               PASS               OK
R007 net_amount null                            UNABLE_TO_ASSESS   UNABLE_TO_ASSESS   OK
R007 quantity null                              UNABLE_TO_ASSESS   UNABLE_TO_ASSESS   OK
R008 required authorization reference empty     FAIL               FAIL               OK
R008 required authorization reference null      FAIL               FAIL               OK
R008 non-required service is not applicable     NOT_APPLICABLE     NOT_APPLICABLE     OK
R009 referenced authorization is absent         FAIL               FAIL               OK
R009 authorization status pending               FAIL               FAIL               OK
R009 valid_to == service_date (inclusive)       PASS               PASS               OK
R009 valid_to one day before service            FAIL               FAIL               OK
R009 valid_from == service_date (inclusive)     PASS               PASS               OK
R009 valid_from one day after service           FAIL               FAIL               OK
R009 authorization service_code mismatch        FAIL               FAIL               OK
R009 authorization patient mismatch             FAIL               FAIL               OK
R009 aggregate quantity == max_quantity         PASS               PASS               OK
R009 aggregate quantity exceeds max by one      FAIL               FAIL               OK
R009 line reference null while R008 fails       UNABLE_TO_ASSESS   UNABLE_TO_ASSESS   OK
R010 required document present and final        PASS               PASS               OK
R010 matching attachment all draft              UNABLE_TO_ASSESS   UNABLE_TO_ASSESS   OK
R010 attachments empty                          FAIL               FAIL               OK
R010 attachment for another patient             FAIL               FAIL               OK
R010 attachment wrong service_code              FAIL               FAIL               OK
R010 attachment wrong service_date              FAIL               FAIL               OK
R010 attachment wrong type                      FAIL               FAIL               OK
R010 no required document is not applicable     NOT_APPLICABLE     NOT_APPLICABLE     OK
R011 unknown service code                       FAIL               FAIL               OK
R011 service_code null                          UNABLE_TO_ASSESS   UNABLE_TO_ASSESS   OK
R012 total matches exactly                      PASS               PASS               OK
R012 total off by exactly 0.01                  PASS               PASS               OK
R012 total off by exactly 0.02                  FAIL               FAIL               OK
R012 total_amount null                          UNABLE_TO_ASSESS   UNABLE_TO_ASSESS   OK
R012 two lines, total ignores one               FAIL               FAIL               OK
R013 unit_price == max (260)                    PASS               PASS               OK
R013 unit_price one over max (261)              FAIL               FAIL               OK
R013 unit_price zero                            FAIL               FAIL               OK
R013 quantity == max (3)                        PASS               PASS               OK
R013 quantity == max + 1 (4)                    FAIL               FAIL               OK
R013 quantity zero                              FAIL               FAIL               OK
R013 quantity negative                          FAIL               FAIL               OK
R014 lag == window (30 days)                    PASS               PASS               OK
R014 lag == window + 1 (31 days)                FAIL               FAIL               OK
R015 currency SAR                               PASS               PASS               OK
R015 currency USD                               FAIL               FAIL               OK
transport: missing top-level key (currency)     REFUSED            REFUSED            OK
transport: extra top-level key                  REFUSED            REFUSED            OK
transport: duplicate line_id                    REFUSED            REFUSED            OK
transport: line missing net_amount key          REFUSED            REFUSED            OK
transport: empty lines array                    REFUSED            REFUSED            OK
transport: __proto__ key                        REFUSED            REFUSED            OK
transport: structural null provider_id          REFUSED            REFUSED            OK
transport: structural null submission_date      REFUSED            REFUSED            OK
transport: structural null currency             REFUSED            REFUSED            OK
transport: line service_date not a date         REFUSED            REFUSED            OK
transport: authorization record with a null id  REFUSED            REFUSED            OK
robust: 100k-character notes                    (no crash, contract valid) 15 records, contract valid OK
robust: markup and control characters in notes  (no crash, contract valid) 15 records, contract valid OK
robust: 200 service lines                       (no crash, contract valid) 15 records, contract valid OK
robust: amounts at 1e12                         (no crash, contract valid) 15 records, contract valid OK
robust: date 1900-01-01                         (no crash, contract valid) 15 records, contract valid OK
robust: date 9999-12-31                         (no crash, contract valid) 15 records, contract valid OK
robust: unicode identifiers                     (no crash, contract valid) 15 records, contract valid OK
robust: 10k-character service_code              (no crash, contract valid) 15 records, contract valid OK
robust: deeply nested attachment text           (no crash, contract valid) 15 records, contract valid OK

87/87 cases behaved as the rulebook says  (0.10s)
```

## What it found

**No crash, no contract violation, no wrong status.** Every case returned either
the status the rulebook requires or - for the malformed envelopes - a clean
transport refusal. The robustness group is the interesting one: 100,000
characters of notes, markup and control characters (`<script>`, `\x00`, a
right-to-left override), 200 service lines, amounts of 1e12, year 1900 and year
9999, emoji identifiers, a 10,000-character service code, and 500-deep nested
JSON inside an attachment. All produced exactly fifteen records that satisfy the
emitted-record contract against the original object.

**The one thing worth knowing: there are two gates, and they disagree about
`null` on purpose.** Five of my first-draft cases were wrong, not the engine. I
had asserted that `provider_id: null` should reach R005 and abstain
(`UNABLE_TO_ASSESS`), because that is what the rulebook's *missing comparison
input* language suggests. It never gets there: `validate_transport` refuses the
envelope first. The split is deliberate and documented in
`claimguard/edu/envelope.py`:

*   **Structural keys** - `schema_version`, `claim_id`, `patient_id`,
    `provider_id`, `payer_id`, `policy_id`, `submission_date`, `currency`, `notes`
    - must be nonempty strings. A null is a transport defect, refused with a 422
    before any rule runs.
*   **Business values** - `invoice_number`, `member_id`, `diagnosis_code`, a
    line's `service_date`, `unit_price`, and a line's `authorization_id`
    reference - stay nullable, "deliberately permitted even when a payer rule
    demands them", so the rules can abstain on them.

The pack's own data agrees with that split exactly: across all 600 claims, the
only nulls are in `lines.unit_price`, `lines.service_date`, `member_id`,
`diagnosis_code` and `invoice_number` - all nullable by contract - and never in
`submission_date`, `currency`, `provider_id` or an authorization record's id. So
the refusal path is real but unreachable from the pack, which is why the split
never showed up in the benchmark. Worth knowing before anyone submits a
hand-written claim: a null in a structural key is rejected outright rather than
scored as an abstention.

A related detail, now pinned by a case: a **line's** `authorization_id` may be
null (R008 fails, and R009 abstains because R008 already caught it), but an
**authorization record's** id may not - the record has no identity to resolve
without it.

## What it does not prove

1.  **That the rules are right.** These cases check the engine against the
    rulebook. If a rule's wording is wrong about healthcare, every case still
    passes. The rulebook is the mentor's; its correctness is not ours to certify.
2.  **Anything about real claims.** Every case is synthetic and inside the
    fictional payer's vocabulary. Nothing here is evidence about a real payer's
    behaviour, and `docs/12` §"what this does not prove" still stands.
3.  **The held-out set.** 87 adversarial cases are not the mentor's 200 unseen
    claims. The engine's behaviour there remains the one thing we cannot measure.
4.  **Performance at scale.** 200 lines costs milliseconds, but the case is a
    correctness probe, not a load test.
