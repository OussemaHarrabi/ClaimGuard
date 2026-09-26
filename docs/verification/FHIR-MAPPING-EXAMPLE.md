# FHIR mapping example — one real Bundle, projected

> **What this is.** The pack's Required MVP behaviour 1 asks for the normalized JSONL teaching
> data to be ingested *and* for **one FHIR mapping example** to be demonstrated
> (`<pack>/docs/01_Challenge_Brief.md`). This page is that demonstration: one real collection
> Bundle from the development split, projected onto the claim envelope, showing the fields the
> bundle yields, the fields it cannot, and what those gaps mean for the 15 checks.
>
> **Everything below was captured from an actual run.** No number here is estimated, and every
> number comes from the command printed next to it.

The projection itself is committed code —
`claimguard/edu/intake/fhir_source.py` — and its own tests run in CI without the mentor pack.
This page adds what a code path cannot: a run a reviewer can read.

---

## The command

```bash
uv run python scripts/fhir_example.py
```

| Flag | Effect |
|---|---|
| *(none)* | uses the **first bundle whose Claim carries an attachment** — an attachment is where a bundle runs out of information, so it is the honest default |
| `--claim-id CG-…` | demonstrates the bundle whose `Claim.id` matches, or refuses with exit code `2` |
| `--split stress\|validation` | reads that split's `fhir_bundles.jsonl` (default `development`) |
| `--pack-root <dir>` | names the mentor pack explicitly instead of auto-discovering it |

Exit codes: `0` transcript printed; `2` refused (pack, split or bundle unusable). The run builds
no HTTP client and opens no database session.

### Prerequisites

| Need | Why | Check |
|---|---|---|
| The mentor pack on disk | It supplies the bundles and the rule titles | `ls ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack/data/development/fhir_bundles.jsonl` |
| Nothing else | No database, no network, no model | the transcript prints `network : none used` and `database : none used` |

The pack is gitignored delivered reference material. On a machine without it the script refuses
with exit code `2`, and the tests for it skip.

---

## Captured transcript

```
ClaimGuard AI — one FHIR mapping example (pack Required MVP behaviour 1)
======================================================================
Synthetic teaching data. Nothing here is submitted to a payer, and no claim is
approved, denied or judged: the system reviews, it does not adjudicate.

pack root      : ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack
split          : development
source         : ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack/data/development/fhir_bundles.jsonl
source sha256  : 4971ad95aae7ad41f83c620864601711c86621a84982d7cd848cb5898f074880
bundles        : 400 bundle(s), one JSON object per line
demonstrating  : object 3 of 400, Claim.id CG-F5F2411AC3AD
selection      : first bundle whose Claim carries an attachment; --claim-id names another
rules.json     : ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack/rules/rules.json sha256 9c7a1c2995be3b01bed429d82c9da68253bf5a24f4be1027109588bf057d60a8
network        : none used — the JSONL is read from disk; no socket, no request is made
database       : none used — no connection or session is opened; no ORM is imported

the pack's own words (docs/11_FHIR_Orientation.md, "Deliberate limitations"):
      “Full authorization details, policy limits, notes and some source metadata remain in the
      normalized sidecar; FHIR files alone are insufficient to reproduce all 15 checks. No reverse
      adapter is included.”

[1/6] bundle resource inventory (entry order)
    0  Patient             PAT-9EC6FD5402
    1  Organization        EDU-PROV-02
    2  Organization        EDU-PAYER
    3  Coverage            COV-CG-F5F2411AC3AD
    4  Claim               CG-F5F2411AC3AD
    5  DocumentReference   DOC-CG-F5F2411AC3AD-1
  6 resource(s): Claim 1, Coverage 1, DocumentReference 1, Organization 2, Patient 1

[2/6] envelope fields the projection recovers from this bundle
      the projection can supply 30 of the 41 contract leaf paths; this bundle carries 30 of them
  /claim_id                          = "CG-F5F2411AC3AD"
  /invoice_number                    = "INV-CG-F5F2411AC3AD"
  /patient_id                        = "PAT-9EC6FD5402"
  /member_id                         = "MEM-9EC6FD5402"
  /provider_id                       = "EDU-PROV-02"
  /payer_id                          = "EDU-PAYER"
  /policy_id                         = "EDU-PLUS"
  /diagnosis_code                    = "DX-EDU-02"
  /submission_date                   = "2026-03-15"
  /currency                          = "SAR"
  /total_amount                      = 1500
  /coverage/coverage_id              = "COV-CG-F5F2411AC3AD"
  /coverage/status                   = "active"
  /coverage/beneficiary_patient_id   = "PAT-9EC6FD5402"
  /coverage/member_id                = "MEM-9EC6FD5402"
  /coverage/start_date               = "2026-01-01"
  /coverage/end_date                 = "2026-12-31"
  /lines/0/service_code              = "SVC-IMAGE"
  /lines/0/service_date              = "2026-03-06"
  /lines/0/modifier                  = null
  /lines/0/quantity                  = 1
  /lines/0/unit_price                = 1500
  /lines/0/net_amount                = 1500
  /lines/0/authorization_id          = "AUTH-CG-F5F2411AC3AD-1"
  /authorizations/0/authorization_id = "AUTH-CG-F5F2411AC3AD-1"
  /attachments/0/attachment_id       = "DOC-CG-F5F2411AC3AD-1"
  /attachments/0/type                = "imaging-report"
  /attachments/0/patient_id          = "PAT-9EC6FD5402"
  /attachments/0/service_date        = "2026-03-06"
  /attachments/0/text                = "SYNTHETIC: SVC-IMAGE completed on 2026-03-06; record for training only."
  /coverage                          = object
  /lines                             = 1 element(s)
  /authorizations                    = 1 element(s)
  /attachments                       = 1 element(s)
  mapping table: claimguard/edu/intake/fhir_source.py (module docstring), verified
  bundle by bundle in tests/edu_intake/test_fhir_source.py

[3/6] envelope fields the projection CANNOT supply (11 of 41 contract leaf paths)
      every path the module declares, with its own reason; a reason shared by
      consecutive paths is stated once
  /schema_version
      The bundle carries no teaching-contract version marker (no Bundle.meta.versionId, no
      Claim.meta); the contract version exists only in the normalized sidecar.
  /notes
      Claim.note is absent from every public bundle; notes are free text and stay in the
      normalized sidecar. docs/11_FHIR_Orientation.md, 'Deliberate limitations': full
      authorization details, policy limits, notes and some source metadata remain in the
      normalized sidecar; FHIR files alone are insufficient to reproduce all 15 checks.
  /lines/*/line_id
      Claim.item carries only the ordinal Claim.item.sequence; the stable L1/L2 identifier is not
      projected anywhere. Deriving 'L<sequence>' would invent a value the bundle does not carry
      (docs/03_Data_Dictionary.md: affected_line_ids use the stable identifiers, not array
      offsets).
  /attachments/*/service_code
      No coded field exists: the service code appears only inside the free text of
      DocumentReference.description ('Synthetic <code>') and of the document itself. Attachment
      text is untrusted data and is never parsed into field values.
  /attachments/*/document_status
      DocumentReference.docStatus is written in the HL7 code space
      (preliminary|final|amended|entered-in-error) while the envelope uses its own vocabulary; the
      pack documents no inverse mapping, so carrying docStatus verbatim would silently change the
      value (observed in the public splits: draft<->preliminary 15x, final<->final 357x). Shipping
      'preliminary' as document_status would be a translation this module is not authorised to
      make.
  /authorizations/*/patient_id
      Only the authorization *reference* is projected (Claim.insurance.preAuthRef and the teaching
      line extension); the record itself is sidecar-only. docs/11_FHIR_Orientation.md, 'Deliberate
      limitations': full authorization details, policy limits, notes and some source metadata
      remain in the normalized sidecar; FHIR files alone are insufficient to reproduce all 15
      checks.
  /authorizations/*/service_code  (same reason as above)
  /authorizations/*/status  (same reason as above)
  /authorizations/*/valid_from  (same reason as above)
  /authorizations/*/valid_to  (same reason as above)
  /authorizations/*/max_quantity  (same reason as above)

[4/6] what the gaps mean for the 15 checks
      a check counts as answerable here only if every envelope leaf path it reads is
      one the bundle supplies. The rule-directory catalogues are separate rule inputs,
      unchanged by the projection, so /policy_id is enough for a policy-dependent check.
  R001  yes  Required claim information                   reads 8 envelope path(s)
  R002  yes  Service and submission chronology            reads 2 envelope path(s)
  R003  yes  Coverage active on service date              reads 4 envelope path(s)
  R004  yes  Member and beneficiary consistency           reads 4 envelope path(s)
  R005  yes  Provider in the supplied network             reads 2 envelope path(s)
  R006  yes  Possible duplicate service lines             reads 3 envelope path(s)
  R007  yes  Line arithmetic                              reads 3 envelope path(s)
  R008  yes  Required authorization reference             reads 3 envelope path(s)
  R011  yes  Service code in fictional catalogue          reads 1 envelope path(s)
  R012  yes  Claim total equals line amounts              reads 2 envelope path(s)
  R013  yes  Quantity and price limits                    reads 4 envelope path(s)
  R014  yes  Submission window                            reads 3 envelope path(s)
  R015  yes  Currency matches policy                      reads 2 envelope path(s)
  R009  NO   Authorization record matches service         blocked by 6 path(s)
           /authorizations/*/patient_id
           /authorizations/*/service_code
           /authorizations/*/status
           /authorizations/*/valid_from
           /authorizations/*/valid_to
           /authorizations/*/max_quantity
         and the projection does not carry them because:
           Only the authorization *reference* is projected (Claim.insurance.preAuthRef and the
           teaching line extension); the record itself is sidecar-only.
           docs/11_FHIR_Orientation.md, 'Deliberate limitations': full authorization details,
           policy limits, notes and some source metadata remain in the normalized sidecar; FHIR
           files alone are insufficient to reproduce all 15 checks.
  R010  NO   Required supporting document                 blocked by 2 path(s)
           /attachments/*/service_code
           /attachments/*/document_status
         and the projection does not carry them because:
           No coded field exists: the service code appears only inside the free text of
           DocumentReference.description ('Synthetic <code>') and of the document itself.
           Attachment text is untrusted data and is never parsed into field values.
           DocumentReference.docStatus is written in the HL7 code space
           (preliminary|final|amended|entered-in-error) while the envelope uses its own
           vocabulary; the pack documents no inverse mapping, so carrying docStatus verbatim would
           silently change the value (observed in the public splits: draft<->preliminary 15x,
           final<->final 357x). Shipping 'preliminary' as document_status would be a translation
           this module is not authorised to make.
  answerable 13 of 15; not answerable 2 (R009, R010)

[5/6] why this projection is not engine input
      the transport contract requires exactly the 17 envelope keys and, inside them,
      every child key. This projection omits 2 key(s) and 9 nested field(s):
        keys   : schema_version, notes
        nested : /lines/*/line_id
                 /attachments/*/service_code
                 /attachments/*/document_status
                 /authorizations/*/patient_id
                 /authorizations/*/service_code
                 /authorizations/*/status
                 /authorizations/*/valid_from
                 /authorizations/*/valid_to
                 /authorizations/*/max_quantity
      the contract's own validator says: TransportError: Unexpected or missing envelope keys
      so it is an integration artifact: read and reviewed, never scored. The
      engine's input stays the normalized JSONL envelope.

[6/6] what this example does not claim
  - FHIR alone cannot reproduce all 15 checks. That is the pack's statement, not our
    finding: docs/11_FHIR_Orientation.md, "Deliberate limitations" (quoted above).
  - No reverse adapter was written, and none is needed: the normalized JSONL envelope
    is the benchmark input, and FHIR is an integration exercise beside it.
  - "answerable" means every field the check reads is supplied by the bundle. It does
    not promise the check will not abstain for another reason (an unknown service code,
    a policy the catalogue does not list).
  - R009 and R010 cannot be completed from the bundle: an authorization record's
    status, dates, service, patient and quantity, and an attachment's service code and
    document status, live in the sidecar. Nothing here guesses them.
  - The recovered fields mirror the bundle verbatim. A reference is read as written, a
    code stays in the code space it was written in, and attachment text is untrusted
    data that is never parsed into a field value.
  - The run is a file read, a projection and a print: no socket is opened, no database
    connection is opened, and no model is called.
  - The data is synthetic. No claim is submitted to a payer, and no status printed by
    this script is a payment approval — no status is printed at all.

  reproduce: uv run python scripts/fhir_example.py
             uv run pytest tests/edu_intake -q
```

*(Everything verbatim; the script prints no timestamps, so the transcript is byte-reproducible
from the same pack revision.)*

---

## Why the normalized envelope, and not FHIR, is the benchmark input

The pack decides this itself, in three places, and the projection respects all three rather than
working around them.

**1. The manifest names the authoritative format.** From
`<pack>/data/dataset_manifest.json`:

```bash
$ jq -r '.authoritative_format' \
    ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack/data/dataset_manifest.json
normalized JSONL
```

FHIR is shipped *beside* the benchmark input, as an integration exercise
(`<pack>/docs/11_FHIR_Orientation.md`), not as a second way to score a claim.

**2. FHIR genuinely cannot carry the benchmark.** The bundles supply only part of the envelope
contract, and section `[3/6]` of the transcript prints every leaf path they cannot supply. The gap
is not sloppiness in the bundle, it is the pack's design: authorization records, policy limits,
notes and the document status live in the normalized sidecar, and "no reverse adapter is included"
(docs/11, quoted in the transcript). Filling those paths from free text, from an ordinal, or from a
different code space would be invention, and the engine would then be scoring values the bundle
never contained. So the projection reports them instead, with the module's exact reason for each;
the count of supplied and unsupplied paths is the module's, printed in sections `[2/6]` and `[3/6]`.

**3. The scoring contract is defined on the envelope, not on resources.** A result record cites
evidence as RFC 6901 pointers **into the original envelope**, and the mentor's scorer re-resolves
every pointer against the claim it was given. A projection missing leaf paths cannot satisfy that
contract — which is why the script runs the transport contract's own validator and prints the
refusal it gets (section `[5/6]`: `TransportError: Unexpected or missing envelope keys`). The
partial projection is an integration artifact; it is read and reviewed, never scored, and it can
never silently become the benchmark input.

The consequence for behaviour 1 is stated plainly in section `[4/6]`: most of the checks read only
envelope fields a bundle supplies, and the two that cannot be completed from FHIR alone — R009 and
R010, since an authorization record's status, dates, service, patient and quantity and an
attachment's service code and document status are sidecar-only — are named with the paths that
block them. The script guesses neither.

### How the section `[4/6]` table is derived

The rule-input table is declared once, in `scripts/fhir_example.py` (`RULE_INPUTS`), each list read
off the rule implementations (`claimguard/edu/rules/r001_r007.py`, `r008_r015.py`). At run time
every declared path is checked against `fhir_source.ALL_FIELD_PATHS`, so a typo fails loudly
instead of passing as "supported"; a check counts as answerable only if none of the paths it reads
is one the bundles cannot supply. The rule-directory catalogues (policies, services) are separate
rule inputs and are unchanged by the projection, which is why `/policy_id` is enough for
policy-dependent checks.

`tests/edu_intake/test_fhir_example_script.py` pins this page to the code: it runs the script,
then requires this document to contain every section header, every path in
`fhir_source.UNSUPPORTED_FIELDS` and the answerability summary the script prints. Change the module
without regenerating the transcript and the test fails.

---

## What this example proves, and what it does not

**Proves.** One real pack bundle projects with no invention: every value in section `[2/6]` comes
from the bundle, attachment text included, and is carried verbatim. The leaf paths the projection
can supply and the ones it cannot are both reported — the counts are the module's, not prose, and
the unsupported ones carry the module's reason rather than a filled-in value. The checks that read
only fields a bundle supplies, and the two that cannot be completed from FHIR at all, are separated
with the paths that decide each. The pack's own transport contract refuses the projection, which is
printed rather than hidden. And the whole run is offline and database-free.

**Does not prove.** That FHIR could be made a substitute for the envelope — it cannot, by the
pack's design, and writing a reverse adapter was deliberately not done. That every check will
reach a verdict when it is answerable: a check may still abstain for a reason the bundle cannot
speak to (an unknown service code, a policy the catalogue does not list). That the projection is
sufficient for R009 or R010: those inputs must come from the normalized sidecar.

**And it produces no verdict at all.** Nothing in this example approves, denies, prices or judges a
claim; the projection carries fields, and the engine's statuses are pre-validation findings for a
human reviewer. A `PASS` elsewhere in this system is never payment approval, and this script prints
no status of any kind.
