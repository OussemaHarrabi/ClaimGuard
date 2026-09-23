# 17 — The JEV judge layer (advisory second opinion)

> **Status:** built and configured, **not yet enabled** — there is no API key yet, so the layer runs
> in its null mode and makes no request. Written 2026-09-23 on branch `feat/jev-judge-layer`.
> **Read with:** `docs/10-ADR-Starter-Pack-Authority.md` (why the 15-key contract is frozen),
> `docs/11-Architecture-and-Dataflow.md` (where this layer sits in the pipeline),
> `docs/16-User-Flow-and-Explainability.md` (the explanation layer this one deliberately does *not*
> extend).
> **Scope:** synthetic educational data only. This layer is a second opinion on a check result. It
> does not decide anything, and nothing it produces reaches the graded record.

---

## 1. What Jev is

TypeSafe's Jev ("System One") is not a chat model. Its API takes **unstructured state in** and
returns **typed probabilistic decisions out**:

| | |
|---|---|
| **In** | `POST /v1/systemone` with `model`, `state` (a string, object or array — the content the questions refer to) and `questions` (a map of *your* names to question definitions). |
| **Out** | `{"model": ..., "answers": {...}, "usage": {...}}` — one answer per question name, schema-matched. |
| **Answer kinds** | `noul` → a probability in `[0, 1]` that the answer is *true*; `choice` → the selected name, a confidence, and the full probability distribution over the choices; `score` → a position on an ordered criteria list, a confidence, a legend and a distribution. |
| **Never** | generated text. There is no completion to sanitise, no prose to fact-check against a source, and no prompt injection surface in the output. |
| **Also** | probabilities are calibrated by the vendor, output tokens are free, latency is 70–500 ms, and the service is in **early access** — model names must be verified against `GET /v1/models` rather than assumed. |

The whole HTTP contract is mirrored as Pydantic models in
`claimguard/edu/judge/models.py` (request envelope, the three question variants discriminated by
`type`, the three answer variants, the response envelope with usage, and `GET /v1/models`). Every
model is `extra="forbid"`, so an undocumented field is a contract violation and never a silent
pass-through.

## 2. Why it fits this problem

Three properties of this system make a typed adjudicator the right shape of model, and one makes it
the wrong shape of authority.

1. **The engine cannot see its own prose.** R001..R015 prove that evidence pointers resolve and
   values match (`claimguard/edu/evidence.py`). They cannot prove that the *sentence* built from
   those pointers says no more than the pointers show. Asking for the probability that every
   statement in the explanation is supported by the cited evidence is a question the deterministic
   layer structurally cannot answer about itself.
2. **A second opinion is cheap and typed.** The engine's status is fixed by a rule and a rule
   version. Asking a *different* model whether it would report the same status, and with what
   confidence, produces a signal about the rule — without producing a competing status.
3. **Severity is not triage.** `severity` comes from the rule manifest, so every R008 finding is
   `high` whether or not it matters today. An ordered attention scale ("can wait" → "needs attention
   this week" → "needs attention today") is the one ranking the contract does not already carry.
4. **And the wrong shape of authority**, because Jev is probabilistic. A calibrated probability is
   not evidence, and a probability that a status is wrong is not a status. So the judge sits beside
   the engine, never in it.

## 3. The three questions

Built by `claimguard/edu/judge/questions.py` from **one validated result record**, reading that
record's own keys (a record that is not exactly the frozen 15 is refused before anything is built):

| Name | Kind | The question | Why it exists |
|---|---|---|---|
| `grounded` | `noul` | Is every statement in the finding's explanation supported by the cited evidence, and by nothing else? | The one thing the deterministic engine cannot check about itself. |
| `status_agreement` | `choice` (`agree` / `agree_but_low_confidence` / `disagree`) | Is the status the rule reported the status you would report for this evidence? | A second opinion on the rule's own status — recorded separately, never merged into it. |
| `attention` | `score` (`can wait` / `needs attention this week` / `needs attention today`) | How much human attention does this finding deserve? | Triage order, which the manifest-fixed severity cannot express. |

## 4. The exact request we send

This is the real payload for one record of the vendored catalogue (an R008 `FAIL`, an imaging line
with no authorization reference), printed by `build_body` — the same function the runner uses. The
`state` carries **only** the validated record, its evidence pointers (path + value) and a bounded
rule excerpt; no claim envelope, no notes, no attachment text, no credential.

```json
{
  "model": "jev-latest",
  "state": {
    "finding": {
      "claim_id": "CG-TEST-0002",
      "rule_id": "R008",
      "rule_version": "1.0.0",
      "status": "FAIL",
      "severity": "high",
      "affected_line_ids": [
        "L1"
      ],
      "evidence": [
        {
          "path": "/lines/0/service_code",
          "value": "SVC-IMAGE"
        },
        {
          "path": "/lines/0/authorization_id",
          "value": null
        }
      ],
      "rule_source": "fictional-rulebook/R008@1.0.0",
      "explanation": "Required authorization ID missing",
      "corrective_action": "Request the authorization reference or escalate its absence.",
      "confidence": null,
      "confidence_kind": "not_probabilistic",
      "requires_human_review": true,
      "method": "deterministic",
      "review_status": "unreviewed"
    },
    "evidence": [
      {
        "path": "/lines/0/service_code",
        "value": "SVC-IMAGE"
      },
      {
        "path": "/lines/0/authorization_id",
        "value": null
      }
    ],
    "rule_excerpt": {
      "rule_id": "R008",
      "title": "Required authorization reference",
      "severity": "high",
      "logic": "For each service in policy.auth_required_services, its line authorization_id must be nonempty. A known empty reference fails. No required service means NOT_APPLICABLE. Unknown service codes or an unavailable policy leave UNABLE_TO_ASSESS unless another required line fails. This checks reference presence only; R009 checks the record.",
      "corrective_action": "Request the authorization reference or escalate its absence.",
      "version": "1.0.0",
      "source": "fictional-rulebook/R008@1.0.0"
    }
  },
  "questions": {
    "grounded": {
      "type": "noul",
      "instructions": "Claim CG-TEST-0002, rule R008, reported status FAIL. Is every statement in the finding's explanation supported by the evidence cited in its evidence list, and by nothing else? Answer with the probability that it is fully supported.",
      "criteria": {
        "true": "every statement in the explanation is supported by the cited evidence",
        "false": "at least one statement is unsupported by, contradicted by, or goes beyond the cited evidence"
      }
    },
    "status_agreement": {
      "type": "choice",
      "criteria": {
        "agree": "the reported status is the correct status for the cited evidence",
        "agree_but_low_confidence": "the reported status is probably correct, but the cited evidence is thin, ambiguous or incomplete",
        "disagree": "the reported status is wrong for the cited evidence"
      },
      "instructions": "Claim CG-TEST-0002, rule R008, reported status FAIL. That status was produced by a deterministic rule, not by you. Reading the finding and its evidence, is that the status you would report? Choose the single closest option."
    },
    "attention": {
      "type": "score",
      "criteria": [
        "can wait: the finding is informational for this claim; the normal review queue is enough",
        "needs attention this week: a reviewer should look at this claim during the current week",
        "needs attention today: a reviewer should look at this claim today, before it is processed further"
      ],
      "instructions": "Claim CG-TEST-0002, rule R008, reported status FAIL. How much human attention does this finding deserve? Answer with the position of one level in the criteria list, counting from 0."
    }
  }
}
```

The answer comes back keyed by those same three names, and is stored raw in the sidecar:

```json
{
  "model": "jev-latest",
  "answers": {
    "grounded": {"type": "noul", "noul": 0.93},
    "status_agreement": {
      "type": "choice",
      "choice": "agree_but_low_confidence",
      "confidence": 0.71,
      "probabilities": {"agree": 0.145, "agree_but_low_confidence": 0.71, "disagree": 0.145}
    },
    "attention": {
      "type": "score",
      "score": 2.0,
      "confidence": 0.71,
      "legend": {"0": "can wait", "1": "needs attention this week", "2": "needs attention today"},
      "probabilities": {"0": 0.29, "1": 0.71, "2": 0.0}
    }
  },
  "usage": {"input_tokens": 512, "output_tokens": 24}
}
```

which is derived, in `claimguard/edu/judge/run.py`, into the part a human reads:

```json
"advisory": {
  "grounded_probability": 0.93,
  "agreement": "agree_but_low_confidence",
  "agreement_confidence": 0.71,
  "attention_score": 2.0,
  "attention_level": "needs attention today"
}
```

## 5. The safety boundary: why the judge sits *outside* the graded contract

The graded record has exactly **15 keys** and the mentor's scorer rejects any extra or missing one
(`RESULT_KEYS`, `claimguard/edu/envelope.py`; `docs/10-ADR-Starter-Pack-Authority.md`). So the judge
does not write into it. It writes a **sidecar**, one JSON object per `(claim_id, rule_id)`:

```json
{
  "claim_id": "CG-TEST-0002",
  "rule_id": "R008",
  "status": "assessed",
  "reason": "the model answered every question",
  "provider": "jev",
  "model": "jev-test-1",
  "questions": { "...": "the three questions, as sent" },
  "answers": { "...": "the three answers, as received" },
  "advisory": { "...": "the derived summary above" },
  "usage": {"input_tokens": 512, "output_tokens": 24},
  "latency_ms": 0.18
}
```

Four mechanisms, not four promises, keep the two apart:

1. **A separate record type.** `JudgeAssessment.status` is `assessed | skipped | failed` — the
   judge's own vocabulary. It shares no value domain with the contract's `Status`.
2. **A merge guard that is two checks deep.** `sidecar.assert_graded_records` refuses any record
   whose key set is not exactly the frozen 15 *and* any record that no longer validates against the
   contract. A record with an `advisory` block added, a key removed, or a `status` overwritten with
   `"assessed"` cannot pass through `separate()` or `pair_records()` at all.
3. **Identity, asserted.** `separate(records, assessments)` returns the records as the *same
   objects*, in the same order, with the same keys — tested by object identity and by byte
   comparison (`tests/judge/test_sidecar.py`, `tests/judge/test_run.py`).
4. **A null provider by default.** `build_provider` returns `NullJudge` unless a key is configured,
   and `NullJudge` performs no I/O whatsoever. With no key, the whole path is a loop that records
   `skipped`.

**Any judge failure is inert.** A timeout, a refused connection, a 422, a 500, a non-JSON body, an
unknown answer `type`, a choice we never offered, an off-scale score — each becomes a `failed`
assessment carrying its reason, and nothing else changes. The tests exercise each of those paths and
assert the record is byte-identical afterwards.

**What is sent.** Only synthetic, already-validated finding data: the record, its evidence and a
bounded rule excerpt. Before anything is sent, the runner re-resolves the record's evidence against
the claim envelope it came from (`verify_evidence`); a finding whose evidence does not verify is
**skipped, never sent**. The API key travels only in the `Authorization` header, is never written to
a file, and is redacted from every message this layer can raise
(`JudgeSettings.redact`).

## 6. Enabling it, in three steps

Nothing below has been done yet — the layer is built, tested and off.

```bash
# 1. Put the key in the environment (never in a tracked file).
#    .env.example documents it; .env is for the operator.
CLAIMGUARD_TYPESAFE_API_KEY=<the key>

# 2. Verify access and learn which model names this credential can actually use.
uv run claimguard judge probe

# 3. Set the model name the probe listed, then judge a run.
CLAIMGUARD_JEV_MODEL=<a name the probe printed>
uv run claimguard judge assess \
    --results artifacts/edu/development.jsonl \
    --claims  <pack>/data/development/claims.jsonl \
    --output  artifacts/edu/judge.jsonl
```

`probe` calls `GET /v1/models` and prints every offered model with its release date, marking the one
`CLAIMGUARD_JEV_MODEL` names — and warning when that name is *not* offered. That warning exists
because Jev is in early access: `jev-latest` is a default we hope is right, not a name we verified.

Exit codes: `0` the judge ran; `1` the judge was configured and something failed; `2` a prerequisite
is missing (no key, no rule catalogue, a bad input file). With no key, `assess` still writes the
sidecar — every row `skipped`, so the shape of a run is reviewable offline — and exits `2`.

## 7. What this layer will NOT be allowed to do

- **Change a status, severity, evidence pointer, corrective action or review flag.** It has no code
  path that writes to a record, and `separate()` refuses a record that has been written to.
- **Change any routing.** It does not assign, prioritise, escalate or notify. `attention` is a
  number a human reads; no queue consumes it.
- **Merge into the graded record.** The 15 keys are the contract; the scorer never sees this layer.
- **Approve, deny, price or pay anything.** Nothing here expresses such a decision.
- **Run without a key, or call out without one.** `NullJudge` is the default and performs no I/O.
- **Send anything but the record, its evidence and the rule excerpt.** No claim envelope, no notes,
  no attachment text, no patient identifiers beyond what the record already carries, no secrets.
- **Turn a fault into a failure of the run.** Every fault is recorded on one assessment and stops
  there.

## 8. Honest limitations

- **Early access.** The vendor states it plainly. Endpoints, model names and field sets may change;
  the schema is mirrored strictly, so a vendor-side change shows up as `failed` assessments rather
  than as mis-read data — safe, but visible only in the sidecar counts.
- **A second opinion is not evidence.** `grounded = 0.93` is a probability from a model, not a
  proof. It does not verify a pointer, and it does not establish that the explanation is true.
- **The probabilities are the vendor's, not ours.** They are calibrated on the vendor's data. Before
  anyone writes the word "calibrated" next to a ClaimGuard number, the probabilities must be measured
  on our own synthetic corpus — and until then the sidecar carries raw numbers and no claim about
  them.
- **Nothing here is validated against ground truth yet.** There is no accuracy figure for
  `status_agreement`, no threshold for `attention`, and no measurement of whether either correlates
  with the pack's gold labels. Those measurements are the next piece of work, and they need the key.
- **The mentor's scorer does not see this layer at all.** No score, no metric and no acceptance
  criterion in `scripts/edu_conformance.py` depends on it. That is deliberate: the graded contract is
  deterministic, and a probabilistic second opinion must not be able to move it.
- **It costs input tokens.** Output tokens are free; input tokens are not. The sidecar records usage
  per finding, and `claimguard judge assess` prints the run total.
- **The judge is only as good as what it is shown.** It sees the record, the evidence and a 600
  character rule excerpt. It does not see the rest of the claim, so a `disagree` may mean "the rule is
  wrong" or "I was not given enough context" — which is exactly why it is a routing hint for a human
  and not a status.

## 9. Where the code is

| Path | What it is |
|---|---|
| `claimguard/edu/judge/models.py` | The typed mirror of the Jev HTTP contract, and `JudgeAssessment`. |
| `claimguard/edu/judge/config.py` | The four environment variables; `configured()`, `describe()`, `redact()`. |
| `claimguard/edu/judge/provider.py` | `JudgeProvider`, `NullJudge` (default), `JevJudge`, `probe()`, typed errors, the injectable transport. |
| `claimguard/edu/judge/questions.py` | The three questions and the state they see; `build_body` for the exact payload. |
| `claimguard/edu/judge/run.py` | One record in, one inert assessment out; the advisory derivation. |
| `claimguard/edu/judge/sidecar.py` | The JSONL store, the pairing view and the merge guard. |
| `claimguard/cli/judge.py` | `claimguard judge probe` / `claimguard judge assess`. |
| `tests/judge/` | 97 tests, a fake transport throughout, no network, no mentor pack. |
