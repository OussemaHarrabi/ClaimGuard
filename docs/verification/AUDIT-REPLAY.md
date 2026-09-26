# Audit replay — reconstructing a stored run from the ledger

> **What this is:** one command that takes a `run_id` already in the database,
> re-runs the deterministic engine over the run's *stored* input envelope, compares
> the result field-by-field against the *stored* records, walks the run's rows in
> the append-only audit ledger and verifies them, and prints a transcript.
> Everything below was captured from actual runs on 2026-09-26 — no number here is
> estimated, and each one is printed together with the command that produced it.

This closes **gap G3** of `docs/verification/PHASE-1-GAP-ANALYSIS.md`: official
scoring item 4 is *"An audit log engine: append-only, tamper-evident,
**replayable** history"* (`docs/03-Challenge-Decode-Requirements.md` §3.1), and the
challenge brief's own RECORD verb promises *"replayability of any decision"*
(`docs/03` §1.1). We could verify the hash chain, and we could re-run a claim
deterministically, but nothing demonstrated that a **past decision can be
reconstructed**. That is what the transcript below shows.

---

## Prerequisites

| Need | Why | Check |
|---|---|---|
| PostgreSQL with migrations applied | The run, its records and the ledger rows live there | `uv run alembic upgrade head` (schema revision `0004`) |
| At least one stored run | The replay reconstructs a run that already exists | `POST /v1/claims`, or any run left by `scripts/sample_run.py` |
| A rule catalogue | The replay re-runs the engine, so it needs the same rules | `--rules-dir tests/edu/fixtures/pack_reference` (committed), or the mentor pack |
| No model call | The replay re-runs the deterministic engine and the deterministic explanation provider, in process | the transcript prints `model_version : deterministic-engine/1.0.0`; `grep -nE "httpx\|requests\|urllib" scripts/audit_replay.py` → no matches |
| No write access needed | The replay only reads | its whole output is one transcript |

The mentor pack is gitignored reference material. The committed catalogue at
`tests/edu/fixtures/pack_reference/` holds the same five catalogue files as the pack's
`rules/`, vendored verbatim (`PROVENANCE.json` records the digests; `diff -r` against
the pack reports no difference in those five files). The replay prints a digest over
exactly those five files, and both directories produce the same value
(`sha256 925ee77bc9a4129984a2d8249895078afb14b9cff09aefd4e2f56c7743af7e4f`), so the
transcript below is reproducible without the pack.

---

## The command

```bash
uv run python scripts/audit_replay.py \
  --run-id RUN-3e9e8da548f2471f98a138f25df06c89 \
  --rules-dir tests/edu/fixtures/pack_reference
```

`--rules-dir` is optional: without it the script resolves the catalogue exactly as
the review API does (`CLAIMGUARD_RULES_DIR`, then `CLAIMGUARD_PACK_ROOT`, then the
vendored pack). The DSN is **not** an argument — it comes from
`CLAIMGUARD_DATABASE_URL` via `claimguard.config`, because a replay must run against
the database the run was written to.

Exit codes: `0` the replay reproduced the stored run and the ledger verifies; `1` it
did not (a disagreement, or a broken chain); `2` refused (bad usage, unreachable
database, unresolvable catalogue, unknown run).

### The run in this transcript

`RUN-3e9e8da548f2471f98a138f25df06c89` is a real run over the synthetic claim
`CG-REPLAY-3634477F2C`, created through the review API in process (no server, no
network) and then decided once:

```python
claim = base_claim()                            # tests/edu/__init__.py: clean pack-conformant claim
claim["claim_id"] = "CG-REPLAY-3634477F2C"
claim["coverage"]["end_date"] = "2026-03-09"    # R003 fails: service date is 2026-03-10
POST /v1/claims                                 # -> 201, run RUN-3e9e8da548f2471f98a138f25df06c89
POST /v1/runs/RUN-3e9e8da548f2471f98a138f25df06c89/decisions
     {"rule_id": "R003", "action": "confirm_issue", "actor": "demo-reviewer",
      "reason": "Coverage ended before the service date; checked the source record."}
```

Any stored run can be replayed. The ids and hashes belong to this run; a different
run produces a different transcript with the same shape.

---

## Captured transcript — 15/15 reproduced, chain VERIFIED

```console
$ uv run python scripts/audit_replay.py --run-id RUN-3e9e8da548f2471f98a138f25df06c89 --rules-dir tests/edu/fixtures/pack_reference
ClaimGuard audit replay — reconstructing one stored run from the ledger
====================================================================================
Synthetic teaching data. This shows a past decision being reproduced;
it is not evidence that the checks are correct.

run_id         : RUN-3e9e8da548f2471f98a138f25df06c89
claim_id       : CG-REPLAY-3634477F2C
version        : 1
created_at     : 2026-09-26T14:49:04.928560+00:00
initiated_by   : api-submit
trace_id       : 0feed948544d442f93c1ed95cc6a3055

database       : postgresql+psycopg://claimguard:***@localhost:5432/claimguard (schema revision 0004)
rules dir      : tests\edu\fixtures\pack_reference
catalogue      : sha256 925ee77bc9a4129984a2d8249895078afb14b9cff09aefd4e2f56c7743af7e4f (5 files, 15 rules)
rule_version   : 1.0.0
model_version  : deterministic-engine/1.0.0
prompt_version : none

[1/4] stored input — the immutable envelope this run was made from
      stored input_hash : 0d151c3b9547c8180b419eeae1c5f2b9e55c1f7706dabc1888cde6700e4a6792
      recomputed digest : 0d151c3b9547c8180b419eeae1c5f2b9e55c1f7706dabc1888cde6700e4a6792  [MATCH]
      envelope keys     : 17

[2/4] replay — deterministic engine over the stored envelope, no model
      rule  stored          engine fields  explanation
      R001  PASS            all 14         reproduced
      R002  PASS            all 14         reproduced
      R003  FAIL            all 14         reproduced
      R004  PASS            all 14         reproduced
      R005  PASS            all 14         reproduced
      R006  PASS            all 14         reproduced
      R007  PASS            all 14         reproduced
      R008  NOT_APPLICABLE  all 14         reproduced
      R009  NOT_APPLICABLE  all 14         reproduced
      R010  NOT_APPLICABLE  all 14         reproduced
      R011  PASS            all 14         reproduced
      R012  PASS            all 14         reproduced
      R013  PASS            all 14         reproduced
      R014  PASS            all 14         reproduced
      R015  PASS            all 14         reproduced
      agreement : 15/15 records reproduced on all 14 engine fields

[3/4] ledger rows for this run — append-only, hash-chained
      #1 validated      at=2026-09-26T14:49:05.027233+00:00 findings=R003
          rule=1.0.0 model=deterministic-engine/1.0.0
          event_id   b6b4a433-6c4a-4699-b4c7-d06e477afc84
          prev_hash  60883dabeec4b84e2658e39482a586dabda1545996245f5e50052741ad05a8cf
          chain_hash 54bebdbd4ed9b177dd9e91f1474e985e32ec3d48d10e67600c2cbe0a196ac89d
      #2 review_decided at=2026-09-26T14:49:33.885123+00:00 findings=R003 decision=confirm_issue
          rule=1.0.0 model=deterministic-engine/1.0.0
          event_id   9950240c-f2ae-4817-91ef-4e2b361f5836
          prev_hash  54bebdbd4ed9b177dd9e91f1474e985e32ec3d48d10e67600c2cbe0a196ac89d
          chain_hash c1bae4e88cbc900c59b224f5cbbf40ce415d145aa918a2439967951d76eb1363
      anchor  : row ba24aefd-a379-4cde-9997-910e55212b5b
      hash    : 60883dabeec4b84e2658e39482a586dabda1545996245f5e50052741ad05a8cf
      content : 2/2 row hashes recompute
      linkage : every row chains to its predecessor
      run event provenance: input_sha256=0d151c3b9547c8180b419eeae1c5f2b9e55c1f7706dabc1888cde6700e4a6792 prompt_version=none actor=api-submit  [agrees with the run row]
      chain   : VERIFIED

[4/4] verdict
      input  : reproduced (the stored envelope is the hashed one)
      replay : 15/15 records reproduced
      chain  : verified
      RESULT : PASS

WHAT THIS PROVES
  - The 15 stored records are reproduced from the stored envelope alone: the replay
    recomputes status, severity, affected line ids, evidence pointers and corrective
    actions with the same deterministic engine and the same catalogue, then compares. No
    stored result is used as an input.
  - The stored envelope is the one the ledger hashed: its canonical digest equals the
    run row's input_hash, and that hash also sits inside the hashed provenance code of
    the run's 'validated' event.
  - The ledger rows for this run are intact and linked: each row's chain_hash recomputes
    from its own fields, each prev_hash is its predecessor's chain_hash, and the run
    event's versions and finding set agree with the run they describe.

WHAT THIS DOES NOT PROVE
  - It is not evidence that the checks are correct. Replay shows the same engine reaches
    the same answer on the same input; it says nothing about whether the fictional
    rulebook matches a payer's. A reproduced FAIL is a reproduced objection, not a
    denial.
  - A reproduced PASS is not payment approval. PASS means 'this fictional rulebook
    raises no objection to this synthetic claim'.
  - It is not proof against deletion or replacement of the whole log. A hash chain is
    tamper-EVIDENT: a row cut from the middle leaves a gap the link check detects, but
    the tail can be cut, the table dropped, or every row and every later hash rewritten
    into a self-consistent chain that no local check can refute — nothing outside the
    database pins the chain head (docs/12 §4.1).
  - It does not prove the run was reviewed. Decisions live in
    claimguard.review_decisions; this replay shows them only as ledger events, and it
    neither replays nor endorses a reviewer's judgement.
  - The data is synthetic teaching data. No claim here is real and nothing was submitted
    to a payer.
$ echo "EXIT=$?"
EXIT=0
```

Read against the requirement: **`input_hash` matches the recomputed canonical digest
of the stored envelope** (the input is what the ledger hashed), **15/15 records are
reproduced on all 14 fields the deterministic engine owns**, and **both ledger rows
are intact and linked**, with the human decision (`review_decided`, `confirm_issue`)
chained to the run event (`validated`) that precedes it. The last line of `[3/4]` is
the reconstructability check itself: the run event's hashed provenance code carries
`input_sha256=0d151c3b…`, which is the run's `input_hash` and the digest of the
envelope the replay just re-ran; the actor and prompt version in the same code are
the run row's, and the event's `finding_ids` (`R003`) are exactly the stored records
that need attention.

`explanation` is the one field the engine does not own: it is produced by the bounded
explanation layer (`claimguard/review/explanations.py`), which may hand the wording to
a model. Here the run recorded `model_version = deterministic-engine/1.0.0` and every
explanation was reproduced byte-for-byte. A record whose stored provenance says the
text was model-drafted is printed as `model-drafted`, and is not counted as a
disagreement — the wording is explicitly non-deterministic by design, while the
decision is not.

---

## Captured failure case — a deliberately drifted catalogue fails the replay

A replay can only mean something if it can fail. The failure below is produced by
replaying the *same* run with a catalogue that is not the one the run was made with:
a copy of the committed catalogue in which **one value** was changed —
`rules.json` → `R003.severity`, `high` → `low`.

```bash
# a scratch copy of the committed catalogue, with one value changed
rm -rf C:/tmp/audit-replay-drift
cp -r tests/edu/fixtures/pack_reference C:/tmp/audit-replay-drift
uv run python -c "
import json, pathlib
path = pathlib.Path('C:/tmp/audit-replay-drift/rules.json')
rows = json.loads(path.read_text(encoding='utf-8'))
for row in rows:
    if row['rule_id'] == 'R003':
        row['severity'] = 'low'
path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
"

uv run python scripts/audit_replay.py \
  --run-id RUN-3e9e8da548f2471f98a138f25df06c89 \
  --rules-dir C:/tmp/audit-replay-drift
```

```console
[2/4] replay — deterministic engine over the stored envelope, no model
      rule  stored          engine fields  explanation
      R001  PASS            all 14         reproduced
      R002  PASS            all 14         reproduced
      R003  FAIL            severity       differs
      R004  PASS            all 14         reproduced
      ...
      R015  PASS            all 14         reproduced
      agreement : 14/15 records reproduced on all 14 engine fields
      DISAGREEMENT R003: severity

[3/4] ledger rows for this run — append-only, hash-chained
      ... (identical to the verified transcript above)
      content : 2/2 row hashes recompute
      linkage : every row chains to its predecessor
      chain   : VERIFIED

[4/4] verdict
      input  : reproduced (the stored envelope is the hashed one)
      replay : 14/15 records reproduced
      chain  : verified
      RESULT : FAIL
$ echo "EXIT=$?"
EXIT=1
```

Two things are visible at once, and they are the point of the whole script:

* the replay **fails loudly** (`DISAGREEMENT R003: severity`, `14/15`, `EXIT=1`) — a
  stored result that the engine no longer produces is a defect, not a warning;
* the ledger verdict stays `VERIFIED`: the divergence is in the replay's inputs, not
  in the history. The two judgements are independent.

The test suite pins the same behaviour against a real database
(`test_a_replay_with_a_drifted_catalogue_fails_and_names_the_check`).

---

## What replay proves — and what it does not

**Proves.**

1. **Determinism.** Re-running the same engine over the same stored envelope
   reproduces the stored records — statuses, severities, affected line ids, evidence
   pointers and values, corrective actions — with no stored result used as an input.
2. **A reconstructable history.** The run's `validated` event carries its trace id;
   inside its hashed `reason_code` it carries the input hash, the prompt version and
   the actor; its own columns carry the rule and model versions; its `finding_ids`
   name the checks that needed a human eye. Every one of those is *checked against
   the run row and the stored records* rather than trusted, so an auditor holding
   only the ledger can state which input was checked, with which versions, by whom,
   and what it escalated. The review decision is a second row chained to the first.
3. **Tamper-evidence, within the retained log.** Each row's `chain_hash` recomputes
   from its own fields (the Python replica of the trigger's serialisation,
   `claimguard/audit/chain.py`), and each `prev_hash` is the `chain_hash` of the row
   that immediately precedes it **in the whole ledger** — not the previous event of
   the same run. The ledger is one global chain, so a run's second event legitimately
   chains to some other run's event when unrelated activity happened in between,
   which is the normal case on a shared database. The predecessor of every row is
   read from the ledger in `(at, event_id)` order, the same order the trigger and
   `claimguard.verify_audit_chain()` use.

   > **Correction, 2026-09-26.** The first version of this script compared a run's
   > events against each other, which reported `linkage: BROKEN` on any real run
   > whose decision arrived after unrelated activity — a false alarm, found by
   > replaying an older run rather than the freshly created one the script was
   > developed against. The transcripts above are unaffected: in them the run's two
   > events happen to be adjacent. `test_other_runs_between_two_events_are_not_a_break`
   > now pins the corrected rule.

**Does not prove.**

1. **That the checks are correct.** Replay shows the same engine reaches the same
   answer; it says nothing about whether the fictional rulebook matches a payer's.
   Reproducing a FAIL is reproducing an *objection*, not a denial — and a reproduced
   `PASS` is not approval to pay.
2. **Immutability.** A hash chain is tamper-**evident**, not tamper-proof. A row cut
   from the middle leaves a gap the link check detects, but **the tail can be cut,
   the table dropped, or every row and every later hash rewritten into a
   self-consistent chain that no local check can refute** — nothing outside the
   database pins the chain head. `docs/12-Privacy-and-Security-Note.md` §4.1 states
   the whole limit list, including: no trusted timestamp, no WORM storage, no
   backups, no controlled export, and a different writer ignoring the advisory lock
   could still fork the chain. The tests below make the tail-cut limit *executable*
   (`test_a_row_removed_from_the_tail_leaves_no_trace`).
3. **That anyone reviewed anything well.** The decision's free text lives in
   `claimguard.review_decisions`, deliberately not in the ledger; the replay shows
   the decision *event*, not its quality, and it neither replays nor endorses a
   reviewer's judgement.
4. **Production readiness.** No authentication, no retention lock, no payer
   integration (see `docs/20-Implementation-Completion-Report.md` §10).

---

## Tests

`tests/review/test_audit_replay.py` — 18 tests, in two halves:

| Half | Tests | Needs PostgreSQL |
|---|---|---|
| Pure: the field-by-field comparison, the ledger-linkage walk, and the run-event/run-row coherence check, on hand-built inputs | 14 | **No** — always run, CI included |
| End to end: a real run submitted through the review API, replayed | 4 | **Yes** — skipped automatically when PostgreSQL is unreachable |

The four database-backed tests are exactly the ones decorated `@requires_db`:
`test_a_stored_run_replays_from_its_own_envelope_and_verifies_its_ledger`,
`test_the_walk_finds_the_decision_event_and_its_link`,
`test_a_replay_with_a_drifted_catalogue_fails_and_names_the_check`, and
`test_the_cli_refuses_an_unknown_run`.

```console
$ uv run pytest tests/review/test_audit_replay.py -q
..................                                                       [100%]
18 passed in 1.59s
```

Without a reachable database — the CI configuration for a plain unit run — the same
file skips cleanly instead of failing:

```console
$ CLAIMGUARD_DATABASE_URL="postgresql+psycopg://claimguard:claimguard@localhost:5999/claimguard" \
  DATABASE_URL="postgresql://claimguard:claimguard@localhost:5999/claimguard" \
  uv run pytest tests/review/test_audit_replay.py -q
..............ssss                                                       [100%]
SKIPPED [1] tests\review\test_audit_replay.py:311: PostgreSQL is not reachable at postgresql://claimguard:claimguard@localhost:5999/claimguard; start it with `docker compose up -d db` to run these tests
SKIPPED [1] tests\review\test_audit_replay.py:348: PostgreSQL is not reachable at postgresql://claimguard:claimguard@localhost:5999/claimguard; start it with `docker compose up -d db` to run these tests
SKIPPED [1] tests\review\test_audit_replay.py:381: PostgreSQL is not reachable at postgresql://claimguard:claimguard@localhost:5999/claimguard; start it with `docker compose up -d db` to run these tests
SKIPPED [1] tests\review\test_audit_replay.py:412: PostgreSQL is not reachable at postgresql://claimguard:claimguard@localhost:5999/claimguard; start it with `docker compose up -d db` to run these tests
14 passed, 4 skipped in 0.49s
```

Scoped gates on the two files this work added:

```console
$ uv run ruff check scripts/audit_replay.py tests/review/test_audit_replay.py
All checks passed!

$ uv run ruff format --check scripts/audit_replay.py tests/review/test_audit_replay.py
2 files already formatted

$ uv run pyright scripts/audit_replay.py tests/review/test_audit_replay.py
0 errors, 0 warnings, 0 informations
```

The database tests use the committed catalogue and the deterministic explanation
provider, so they need neither the mentor pack nor a model. Like the rest of
`tests/review`, they clean up every row they create (`sandbox`).

---

## Reproducing this document

The exact sequence was run on 2026-09-26, in this order. Both blocks are excerpts —
every elided line is marked `...`; the full transcript of the first command is in
`docs/verification/REPRODUCIBLE-SAMPLE-RUN.md`, and the full transcript of the second
is the captured transcript above.

```console
$ uv run python scripts/sample_run.py
      ...
      run_id       : RUN-22b1b55447dd4a5faf193e2a8e5662f1
      ...
      chain verified: 2 event(s) recomputed; 0 unlinked
$ echo "EXIT=$?"
EXIT=0

$ uv run python scripts/audit_replay.py \
    --run-id RUN-22b1b55447dd4a5faf193e2a8e5662f1 \
    --rules-dir tests/edu/fixtures/pack_reference
      ...
      agreement : 15/15 records reproduced on all 14 engine fields
      ...
      anchor  : row 9950240c-f2ae-4817-91ef-4e2b361f5836
      hash    : c1bae4e88cbc900c59b224f5cbbf40ce415d145aa918a2439967951d76eb1363
      content : 2/2 row hashes recompute
      linkage : every row chains to its predecessor
      chain   : VERIFIED
      ...
      replay : 15/15 records reproduced
      RESULT : PASS
$ echo "EXIT=$?"
EXIT=0
```

The second run is worth reading closely: its anchor is the *decision row of the
previous run* (`9950240c…`, hash `c1bae4e8…`), which is exactly what a ledger-wide
chain means — the run's own events are not a private chain, they are links in the one
chain, and the replay reads the anchor from the live table rather than assuming
`genesis`. The first run in this document anchors on row `ba24aefd…`, a run that
already existed before it.

New ids and hashes are produced for a new run, because a new run hashes a new
envelope; the *shape* and the verdicts (`15/15`, `VERIFIED`, exit `0`) are the
reproducible part.

Finally, the words this repository will not use: the replay never says a claim is
approved, denied, payable, or judged. It reconstructs what the deterministic checks
objected to, and what a human did about it.
