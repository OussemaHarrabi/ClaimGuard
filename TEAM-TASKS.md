# Team task sheets — Sprint 1 (mentor data has arrived)

> **Who this is for:** B1, B2 and B3. You asked for real work in your own field now
> that the mentor's data is here — this is it.
> **Read this with:** `TEAM-ROADMAP.md` (how we work: branches, commits, PRs) and
> `docs/01-Domain-Gulf-Claims-101.md` (the domain, if you have not read it yet).

---

## How this document works

Each of you gets **one lab**: a small, self-contained piece of work in your own
field that produces something real we can show the mentor and the jury.

Rules of the game, so nobody feels lost:

1. **You work in your own folder.** B1 → `team/b1-explanations/`, B2 →
   `team/b2-evaluation/`, B3 → `team/b3-documents/`. You will not touch shared
   code and shared code will not touch you. Nothing you do can break the product.
2. **You may READ everything, you may only WRITE in your folder.** Reading the
   engine is encouraged — that is how you learn what a real codebase looks like.
3. **One branch per lab:** `stream/<your-id>/<topic>`, e.g.
   `stream/b1/explanation-scorecard`. Open a PR when your lab is done.
4. **Progress is measured by artifacts, not by hours.** Every lab below ends with
   files that a stranger could open and understand.
5. **Stuck for more than 2 hours on the same thing? Ask.** Write down: what you
   wanted, what you tried, the exact error, and what you think is wrong. Ask in the
   team channel, not by DM — everyone learns from the answer.
6. **Never invent a number.** If you did not measure it, do not write it. This is
   the single most important rule in this project, because our whole pitch is
   honesty about what the system can and cannot do.

### The environment (do this once)

```bash
uv sync --all-extras                 # install everything
uv run pytest tests/ -q              # should pass; if some tests skip, that is fine
```

The mentor's data ("the pack") lives at
`ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack`.
It is **not stored in git** (it is delivered reference material), so:

> **CI rule.** Any test you write that needs the pack must skip cleanly when the
> pack is absent, or our pipeline goes red. Copy the pattern already used in
> `tests/edu_conformance/test_harness_selfcheck.py`:
> `pytest.mark.skipif(not PACK_PATH.is_file(), reason="mentor starter pack absent ...")`.

### What already exists (so you know what to build on, not rebuild)

| Piece | Path | What it does |
|---|---|---|
| Rules engine | `claimguard/edu/` | Runs the 15 rules, one verdict per rule per claim |
| Bounded explanations | `claimguard/edu/explain/` | Deterministic explanation text + optional model rewrite, with citation guards |
| Reviewer API | `claimguard/review/` | Submit a claim, read results, record a decision |
| Verified numbers | `docs/verification/EDU-EVALUATION-REPORT.md` | The measured results (accuracy, F1, false alarms) |

Run one claim through the engine to see the shape of everything:

```bash
uv run python -m claimguard.edu.run \
  --claims ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack/data/development/claims.jsonl \
  --rules-dir ClaimGuardAI_Student_Starter_Pack/ClaimGuardAI_Student_Starter_Pack/rules \
  --output C:/tmp/dev_results.jsonl
```

---

# B1 — The explanation quality lab (your field: AI / language)

**Your mission.** We generate an explanation for every problem we find. Right now
nobody has measured whether those explanations are actually *good*. You are going
to build the measurement and report what you find.

**Why this matters.** The mentor's assessment gives 20 of 100 points to "grounded
AI explanations" and says plainly that explanation quality is scored by a human,
not by a script. So a human scorecard is the only honest instrument. That is your
tool to build.

**Read first (30 minutes):**
- `ClaimGuardAI_Student_Starter_Pack/.../docs/05_Architecture_and_AI.md` — the
  "AI exercise" section defines the contract.
- `ClaimGuardAI_Student_Starter_Pack/.../prompts/explain_findings.md` — the prompt.
- `ClaimGuardAI_Student_Starter_Pack/.../exercises/llm_explanation_cases.jsonl` —
  the 25 cases you will score.
- `claimguard/edu/explain/` — how explanations are produced today.

**Build (in this order):**

| Step | Deliverable in `team/b1-explanations/` |
|---|---|
| 1 | `scorecard.py` — for each of the 25 cases, print: the rule, the evidence (`path = value`), the explanation, and five 0/1 boxes: *correct finding / correct evidence / correct rule / appropriate action / honest uncertainty*, plus a free-text "unsupported statements" column. Output both a readable page and a CSV to fill in. |
| 2 | `filled_scorecard.csv` — you actually score all 25 by hand. This is the point of the exercise. |
| 3 | `score.py` — read the filled CSV and compute per-criterion totals, the rate of unsupported statements, and which explanation style scored best/worst. |
| 4 | `FINDINGS.md` — half a page: what we do well, what we do badly, and **three concrete prompt improvements** you would try, each with the case that convinced you. |

**How you know you are done:**
- [ ] All 25 cases appear in the scorecard, none skipped.
- [ ] `uv run python team/b1-explanations/score.py` prints the totals.
- [ ] Every number in `FINDINGS.md` comes from your own CSV.
- [ ] `uv run pytest team/b1-explanations -q` passes (test your parser on a tiny
      hand-written scorecard — do not test that the engine works, that is not yours).
- [ ] The word "probably" appears nowhere as a substitute for a measurement.

**If you get stuck:** the most likely snag is case number 14, where the
deterministic path and the model path disagree about whether to escalate. That is
real and interesting — record it as a finding rather than a bug.

---

# B2 — The uncertainty and calibration lab (your field: deep learning / statistics)

**Your mission.** Two questions nobody has answered yet: *how much can we trust our
own accuracy number*, and *when the system says "I can't tell", is it right to
abstain there?*

**Why this matters.** We report accuracy on 400 claims. A single number on a sample
is not a measurement — it is a measurement **with an interval**. The mentor asks for
false alarms, missed issues and uncertainty handling reported *separately*, and
Phase 2 is entirely about detection quality. You are building the instrument that
will carry Phase 2.

**Read first (30 minutes):**
- `ClaimGuardAI_Student_Starter_Pack/.../docs/07_Evaluation_and_Acceptance.md` —
  the metric definitions are all here; do not invent your own.
- `ClaimGuardAI_Student_Starter_Pack/.../data/dataset_manifest.json` — the declared
  counts, so you can check your own arithmetic against theirs.
- `docs/verification/EDU-EVALUATION-REPORT.md` — the numbers you are going to put
  intervals around.

**Build (in this order):**

| Step | Deliverable in `team/b2-evaluation/` |
|---|---|
| 1 | `load_results.py` — load a predictions file and the matching gold file, and build the claim × rule table. Sanity-check it against `dataset_manifest.json`. |
| 2 | `bootstrap.py` — resample **claims with replacement** 2000 times and report, for issue precision, issue recall, issue F1, false-alarm rate and status accuracy: the point estimate, the 2.5th and 97.5th percentiles. Also per rule. |
| 3 | `abstention_analysis.py` — take apart every `UNABLE_TO_ASSESS` and `NOT_APPLICABLE`: which rules, which claims, what evidence was missing, and cross-tabulate against the confusion matrix. Answer in one sentence where the system abstains and whether that is the right place. |
| 4 | `FINDINGS.md` — the intervals as a table, the three most uncertain rules, and an explicit statement of what an interval does *not* prove. |

**How you know you are done:**
- [ ] The point estimates your bootstrap produces match
      `docs/verification/EDU-EVALUATION-REPORT.md` exactly. If they do not, you
      have a bug — find it before writing anything else.
- [ ] `uv run pytest team/b2-evaluation -q` passes, including a test where the
      bootstrap is run on a hand-built tiny table where you know the answer.
- [ ] No interval is reported from fewer than 100 resamples, and you say how many
      you used.
- [ ] `FINDINGS.md` states that a narrow interval on a synthetic set does not mean
      the system is correct on real claims.

**If you get stuck:** be careful with the difference between "per claim" and "per
claim-rule pair". The mentor's metrics are per **pair** (6000 of them on
development), while resampling should happen per **claim** (400) because rules
within one claim are not independent. That distinction is the analytical heart of
this lab — get it right and explain it in your report.

---

# B3 — The documents and data-integrity lab (your field: computer vision / data)

**Your mission.** Own the "documents" side. Claims arrive with attachments and,
separately, as FHIR bundles — and we have publicly claimed that FHIR **cannot**
carry 11 of the fields our rules need. You are going to independently check that
claim, and then characterise the attachment population nobody has looked at.

**Why this matters.** Two reasons. First, independent verification: we asserted
something in our own code; a colleague re-deriving it is exactly how a real team
catches its own mistakes. Second, attachments are where the bonus OCR points live,
and before promising OCR you must know what the documents actually look like.

**Read first (30 minutes):**
- `ClaimGuardAI_Student_Starter_Pack/.../docs/11_FHIR_Orientation.md` — especially
  "Deliberate limitations".
- `claimguard/edu/intake/fhir_source.py` — our claim, in code.
- `ClaimGuardAI_Student_Starter_Pack/.../docs/03_Data_Dictionary.md` — the
  attachment record definition.

**Build (in this order):**

| Step | Deliverable in `team/b3-documents/` |
|---|---|
| 1 | `attachment_census.py` — across all **three** splits: how many attachments, the distribution of `type` and of `document_status`, how many exist whose `patient_id` differs from the claim's patient, how long the `text` field is, and what the text actually looks like (quote two short examples). |
| 2 | `fhir_gap_check.py` — re-derive, from the raw bundles alone, exactly which envelope fields a FHIR bundle cannot provide. Then print your list next to the list in `claimguard/edu/intake/fhir_source.py` and say **agree** or **disagree per field**, with the reason. |
| 3 | `CENSUS.md` — the measured tables, the agree/disagree result, and what surprised you. |
| 4 | `OCR_FEASIBILITY.md` — if attachments were scanned PDFs instead of inline text: which two libraries you would compare and why, what could go wrong, and why any text coming out of OCR must be treated as untrusted data that can never change a rule result. |

**How you know you are done:**
- [ ] The census covers all three splits and every number is printed by your script.
- [ ] The gap check gives a per-field verdict, not a general opinion.
- [ ] `uv run pytest team/b3-documents -q` passes.
- [ ] `OCR_FEASIBILITY.md` contains no claim about OCR accuracy — you have not
      measured any, and the pack states there is no OCR task in this challenge.

**If you get stuck:** do not try to "fix" the eight attachments whose patient does
not match the claim. They are deliberate — the pack's own notes say some records
intentionally reference a different document patient, and our R010 rule exists
precisely to catch that. Finding them is the success, not changing them.

---

# The week

| When | B1 | B2 | B3 |
|---|---|---|---|
| Day 1 | Read the three sources, run the engine once, open your branch | Read the metric definitions, build `load_results.py` | Read the FHIR notes, run `fhir_gap_check.py` skeleton |
| Day 2 | Build the scorecard generator | Get the bootstrap point estimates matching the report | Finish the census script |
| Day 3 | Score all 25 cases **by hand** | Finish intervals + start abstention analysis | Finish the gap check per field |
| Day 4 | `score.py` + `FINDINGS.md` | `FINDINGS.md` | `CENSUS.md` + `OCR_FEASIBILITY.md` |
| Day 5 | PR + 5-minute demo to the team | PR + 5-minute demo | PR + 5-minute demo |

**Definition of done for any lab:** it runs from a clean checkout, it has at least
one test that would fail if the logic broke, every number is traceable to a command,
and you can explain what you built in five minutes without reading it aloud.

---

# One thing to keep straight

Everything in this challenge is **synthetic and educational**. Our system
pre-validates administrative data; it never approves, denies, or judges a claim,
and it never gives medical advice. If a finding in your lab output could be read as
"this claim should be paid" or "this patient needs X", that is a defect — tell the
team lead rather than writing around it.
