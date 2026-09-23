# 15 — Demo script (7 minutes)

> **For:** whoever presents the live demo. **Speakers:** up to 2.
> **Length:** 7 minutes of content; leave 3 spare for questions. The official
> finals slot is 12 minutes (5 presentation + 2 live demo + 5 Q&A) — this script is
> the 2-minute demo expanded into a rehearsable 7, so trim from the beats below if
> the clock is shorter.
> **Rule that overrides everything:** a **PASS is not payer approval**, and this
> system never approves, denies or judges a claim. Never say otherwise, on stage or
> in the deck.

---

## Before you start (10 minutes before the slot)

```bash
# 1. Database up and migrated
docker compose up -d db                 # or your local Postgres
uv run alembic upgrade head

# 2. Everything is wired correctly — this prints one screen and exits
uv run claimguard status                # expect: RESULT: ready

# 3. Conformance is green — this is the number you will quote
uv run claimguard evaluate --split all

# 4. Pre-warm the demo (so the audience never waits on a first run)
CLAIMGUARD_DATABASE_URL="postgresql+psycopg://claimguard:claimguard@localhost:5432/claimguard" \
uv run python scripts/sample_run.py --claim-id CG-785C09BD9CC8
```

**Fallback plan.** If the live stack misbehaves: run
`uv run python scripts/sample_run.py` (in-process, no server, no network — it
prints the same evidence, decision and audit transcript), and show
`docs/verification/REPRODUCIBLE-SAMPLE-RUN.md`. The demo must never depend on the
venue's internet: nothing in it does.

**Two tabs, ready:**
- **Tab A** — the reviewer UI at `http://localhost:8000/review`
- **Tab B** — a terminal in the repository root

---

## Beat 1 — the problem, in one minute (0:00–1:00)

*No screen. Just say it.*

> "A clinic finishes treating a patient and submits a claim to the insurer to get
> paid. Weeks later it comes back rejected — not because the medicine was wrong,
> but because something administrative was wrong: the coverage had lapsed a week
> before the service, a required pre-approval was never attached, the same scan got
> billed twice.
>
> The clinic then reworks it by hand. Everyone loses time and money on a mistake
> that was visible **before** the claim was ever sent.
>
> ClaimGuard reads the claim in that gap — after the clinic builds it, before the
> payer sees it. It finds the administrative problems, shows the exact field that
> proves each one, and hands the uncertain cases to a human. It never decides
> whether a claim gets paid. Review, don't adjudicate."

---

## Beat 2 — a clean claim and a broken claim (1:00–3:00)

*Tab A — the reviewer interface.*

**2a. The clean claim (30s).** Load a clean claim from the queue and point at the
verdicts.

> "Fifteen checks, all satisfied or not applicable. Two things I want you to notice.
> First, the green here means *this fictional rulebook raises no objection* — it is
> **not** approval to pay, and the page says so. Second, a clean result is still a
> handoff: it tells the reviewer exactly what was checked and when."

**2b. A claim that fails (60s).** Load `CG-785C09BD9CC8`.

> "Same fifteen checks. Two of them fail, and both are marked high severity and
> flagged for human review.
>
> The first one: the service happened on the tenth of April, but the coverage
> period ended on the ninth. Here is the evidence — four fields, each one read back
> from the original claim, with the value it actually held. We are not asserting
> this from a model's opinion; the rule compared two dates and the claim itself
> proves the mismatch.
>
> The second one is an identity inconsistency: the member number on the claim says
> one thing, the coverage record says another."

**2c. Why this is not an AI guess (30s).**

> "Every one of these verdicts comes from a deterministic rule over the data —
> fifteen named, versioned rules. The AI in this system never decides anything. It
> only helps write the sentence a human reads."

---

## Beat 3 — uncertainty, and asking for information (3:00–4:00)

*Still Tab A — filter the queue by `UNABLE_TO_ASSESS`.*

> "Now the part I think matters most, and the part most systems get wrong.
>
> Here the system does **not** say the claim is fine, and it does not invent an
> answer. It says: *I cannot assess this*, and it tells you what is missing — a
> service date, an authorization reference, a document still in draft.
>
> Three verdicts that look similar but are completely different: **PASS** means the
> check passed; **NOT APPLICABLE** means the rule does not apply to this claim at
> all; **UNABLE TO ASSESS** means the evidence to decide is not there. Only the
> third one is an abstention, and abstentions stay visible — they are never turned
> into a pass. That distinction is deliberately enforced in code, and we test it."

*Open one abstention and show the missing field, then request information.*

> "So the reviewer's action here is not approve or deny. It is *request the
> information* — and I will record that decision with my name and a reason, because
> the system will not accept a decision without both."

*(Type a one-line reason, submit. Point at the 422 that appears if the reason box is
empty — that is the API refusing an unexplained decision, not a UI trick.)*

---

## Beat 4 — the bounded AI, and its failure mode (4:00–5:00)

*Tab B — terminal.*

```bash
uv run python -c "
from claimguard.edu.explain.verifier import prohibited_assertions
for text in ['This claim is approved for payment.',
             'The diagnosis confirms clinical necessity.',
             'The service date falls after the coverage end date, so the check fails.']:
    print(repr(text[:46]), '->', prohibited_assertions(text) or 'accepted')
"
```

*Expected output — the first two are flagged, the third is accepted:*

```
'This claim is approved for payment.'          -> ('adjudication_outcome', 'approved_for_payment')
'The diagnosis confirms clinical necessity.'   -> ('clinical_judgement',)
'The service date falls after the coverage ...' -> accepted
```

> "The AI here is allowed to do exactly one thing: turn a validated finding into a
> sentence. It is not allowed to change a verdict, a severity, or a routing
> decision — and it cannot, because the explanation is produced *after* the rules
> run and the record's other fourteen fields are copied through untouched.
>
> Watch what happens when the model tries to step outside that lane. Given a claim,
> a model can say something like *'this claim is approved for payment'*. Our layer
> rejects that sentence outright — it asserts a decision the system is not allowed
> to make — and shows the deterministic wording instead. Same for a citation that
> points at a field we never supplied, and for a citation that does not exist in
> the claim at all.
>
> And if the model is slow, unavailable, or returns nonsense? The deterministic
> explanation stands. We tested that across 2250 enrichments: **zero** verdicts
> changed. A model failure can never remove a finding."

---

## Beat 5 — evidence, review, and the record (5:00–6:00)

*Tab A — the claim's decision history, then Tab B for the ledger.*

> "Here is the decision I just recorded: who made it, when, why, and which finding
> it applies to. The original evidence is untouched — a correction does not edit
> history, it creates a **new version** and re-runs the checks, and the old run
> stays readable.
>
> Every run and every decision goes into an append-only ledger where each entry
> carries the hash of the one before it."

```bash
uv run python scripts/sample_run.py    # step 7/7 prints and re-verifies the chain
```

> "Two things recorded for this run: the validation, with the input hash and the
> rule, model and prompt versions; and the review decision. The ledger recomputes
> the chain and reports zero unlinked entries.
>
> I want to be precise about what that buys us: it is **tamper-evident** — if
> someone edits an entry, the chain breaks and we can see it. It is not yet
> *immutable*. A hash chain does not stop someone deleting the whole file or rolling
> it back. Doing that properly needs append-only storage, independent trusted
> timestamps and access control, and we say so in the security note rather than
> pretending otherwise."

---

## Beat 6 — the measured result, and the limits (6:00–7:00)

*Tab B.*

```bash
uv run claimguard evaluate --split all
```

> "Finally, the number that matters to a jury — measured by the mentor's own
> scorer, not by us.
>
> On the development split: six thousand claim-rule checks, **status accuracy
> 1.0000** — four hundred claims out of four hundred with all fifteen verdicts
> correct. Issue precision, recall and F1 all 1.0000. **Zero false alarms** and
> **zero missed issues**. Zero missed abstentions. Validation and stress splits,
> same result.
>
> For scale: the starter baseline the mentors shipped scores **0.43 F1** and gets
> 20% of verdicts right, because it only implements three of the fifteen rules.
>
> Now the honest part, and I want to be direct about it.
>
> That number is agreement with the supplied labels on **synthetic** data with a
> **fictional** rulebook. It is not accuracy on real claims, and we do not claim it
> is. Several of the trickiest rule edges — how an authorization's quantity
> aggregates across lines, sub-cent rounding — **cannot be discriminated by the
> public labels at all**, so a wrong implementation would still look perfect here.
> The mentor's two hundred held-out claims are the real test, and they are not in
> this repository.
>
> We know exactly where our certainty ends. That is the point of the whole system:
> fifteen deterministic checks, evidence you can click, abstention instead of
> guessing, and an AI that is only allowed to write the explanation."

---

## Q&A preparation — the five questions that always come

| Question | Answer |
|---|---|
| "So it can deny claims automatically?" | No, and it never will. It produces findings for a human; there is no payment path in the codebase at all. |
| "What if the AI hallucinates?" | It cannot change a verdict — verdicts come from deterministic rules that run first. Its text is rejected and replaced when it asserts a decision or cites something we did not supply. |
| "Is 1.0 realistic?" | On this synthetic set with this rulebook, yes, and we reproduced it with the mentors' scorer. It is not a claim about real claims, and we say so in every report. |
| "What is not built?" | Authentication and RBAC; OCR (there is no OCR task in this challenge); production-grade immutable storage; the calibration work scheduled for Phase 2. All listed in the security note. |
| "Why should we trust the evidence?" | Every pointer names a field in the original claim and carries the value that was there, and the scorer rejects the run if a value does not re-resolve. What that check does *not* prove is that the field is *relevant* — which is why a human reviews. |

---

## Rehearsal checklist

- [ ] `uv run claimguard status` says `RESULT: ready` on the demo machine.
- [ ] `uv run claimguard evaluate --split all` is green, run **offline** (Wi-Fi off).
- [ ] `scripts/sample_run.py` completes in under 15 seconds.
- [ ] The reviewer page loads and one decision round-trip works.
- [ ] Two dry runs, timed, at under 7:00 each.
- [ ] The fallback path (in-process sample run + the captured transcript) has been
      rehearsed, not just noted.
- [ ] Nobody says "approved", "denied", or "the AI decided" at any point.
