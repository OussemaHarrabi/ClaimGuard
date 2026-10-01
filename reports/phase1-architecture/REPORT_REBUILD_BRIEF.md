# ClaimGuard professional report rebuild brief

## Identity

- Product: **ClaimGuard**
- Team: **Claimix**
- Authors: **Oussema Harrabi, Wassim Hajji, Eya Ayedi, Ghassen Benkaji, Maram Kouki**
- Scope: synthetic healthcare claims and fictional payer rules
- Product posture: pre-submission review, never adjudication

## Format

The replacement report will be a portrait A4 technical report, not a landscape slide deck. It will use a formal cover, abstract, table of contents, list of figures, numbered chapters, numbered figures and tables, cross-references, page headers, page numbers, a conclusion, and a short appendix. Wide architecture plates may use isolated landscape pages inside the portrait document.

## Planned narrative

1. **General introduction** - the context, the submission goal, and how to read the report.
2. **Problem and domain context** - why pre-submission claim review is difficult, where preventable administrative defects arise, and why a black-box AI is unsuitable.
3. **ClaimGuard solution** - users, value proposition, product boundary, end-to-end reviewer story, and the review-not-adjudication principle.
4. **Requirements and design decisions** - the four Phase 1 rubric areas, deterministic authority, strict data contracts, evidence-first output, model authority limits, versioning, tenancy, and auditability.
5. **Global source architecture** - the supplied master architecture image followed by a component-by-component explanation and trust-boundary analysis.
6. **Data ingestion and normalization** - JSON, relational CSV, FHIR R4 plus verified sidecar, the 17-key envelope, quarantine, current limitations, and a detailed data-flow diagram.
7. **Validation and explainability** - the R001-R015 catalogue, five-status semantics, evidence resolution, the structured result contract, bounded explanation, correction recommendation, verifier, provenance, and fallback.
8. **Human review workflow** - queue, evidence desk, four reviewer actions, assignment, requests, escalation, correction, recheck, and version history. Includes a sequence diagram.
9. **Data and audit architecture** - entity groups, tenant relationships, run-version relationships, assistant-thread separation, immutable-table triggers, hash-chain construction, and replay. Includes an ER-style database diagram.
10. **Implementation and verification** - the concrete stack, repository modules, reproducible checks, current measured evidence, and what those results do and do not prove.
11. **Limitations and next work** - held-out evaluation, explanation-quality review, fuller document intake, SLM selection or fine-tuning only if justified, bounded JEV evaluation, row-level isolation, deployment identity, monitoring, and usability testing.
12. **General conclusion** - the system contribution and the next validation gate.

## Figure set

1. ClaimGuard problem-positioning diagram.
2. Global system architecture plate supplied from the master prompt.
3. Claim package data-flow diagram.
4. Claim submission and validation sequence diagram.
5. Reviewer correction and versioned recheck sequence diagram.
6. Guarded AI assistant state graph.
7. PostgreSQL logical data architecture and tenant relations.
8. Audit-event hash-chain and replay diagram.

## Writing constraints

- Use full paragraphs and connected reasoning, not slide fragments.
- Explain every figure before or immediately after it appears.
- Separate implementation facts, measured evidence, design rationale, current limits, and future work.
- Use no em dashes.
- Do not expose local credentials, private handoff content, API keys, or internal team notes.
- Do not claim real-world clinical accuracy, payer approval, production readiness, or direct payer submission.
- Do not present a model benchmark winner as deployable without grounded qualitative review.
- Use the exact author names supplied by the user.
