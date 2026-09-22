"""The deterministic path cannot reject its own corpus.

The template provider must serve every gold result record of the three public
splits (400 + 150 + 50 claims = 9 000 records) under the full contract: schema,
citation subset, rule citation, review boundary, citation resolution in the
original envelope and the prohibited-language guard. A single rejection here
would mean the fallback path is unusable exactly when it is needed most.

This is also the honest answer to "how many of the exercise cases can the
template path serve": it serves all of them, because it only restates the
finding — the model path is what can be *better*, not what is *required*.
"""

from __future__ import annotations

from claimguard.edu.explain import (
    DETERMINISTIC_PREFIX,
    TemplateExplanationProvider,
    explain_finding,
)

from tests.edu_explain import (
    SPLITS,
    load_claims,
    load_records,
    load_rule_manifest,
    requires_pack,
)

pytestmark = requires_pack

EXPECTED_RECORDS = {"development": 6000, "validation": 2250, "stress": 750}


def test_the_template_path_serves_every_gold_record_of_all_three_splits() -> None:
    provider = TemplateExplanationProvider()
    claims = load_claims()
    manifest = load_rule_manifest()
    served: dict[str, int] = {}
    for split in SPLITS:
        count = 0
        for record in load_records(split):
            claim_id, rule_id = str(record["claim_id"]), str(record["rule_id"])
            outcome = explain_finding(
                record, manifest[rule_id], provider, envelope=claims[claim_id]
            )
            assert outcome.declined_reason is None, f"{claim_id}:{rule_id}"
            assert outcome.fallback_used is False, f"{claim_id}:{rule_id}"
            assert outcome.rejection_reasons == (), (
                f"{claim_id}:{rule_id} {outcome.rejection_reasons}"
            )
            assert outcome.explanation.startswith(DETERMINISTIC_PREFIX)
            assert outcome.status == record["status"]
            assert list(outcome.cited_evidence_paths) == [
                entry["path"] for entry in record["evidence"]
            ]
            assert outcome.needs_human_review is record["requires_human_review"]
            count += 1
        served[split] = count

    print("template path served:", served)
    assert served == EXPECTED_RECORDS
    assert sum(served.values()) == 9000
