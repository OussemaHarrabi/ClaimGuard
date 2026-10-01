# ClaimGuard documentation map

This directory holds domain context, architecture decisions, implementation descriptions, security boundaries, demonstration instructions, and generated verification evidence.

[Back to the project README](../README.md)

## Recommended reading paths

### New contributor

1. [Domain primer](01-DOMAIN-Gulf-Claims-101.md)
2. [Challenge requirements](03-Challenge-Decode-Requirements.md)
3. [Architecture and data flow](11-Architecture-and-Dataflow.md)
4. [Clinic platform foundation](21-Clinic-Platform-Foundation.md)
5. The README nearest the code you will change
6. [Implementation inventory and handoff](20-Implementation-Completion-Report.md)

### Jury or evaluator

1. [Problem narrative](02B-PITCH-Problem-Narrative.md)
2. [Phase 1 readiness](verification/PHASE-1-SUBMISSION-READINESS.md)
3. [Technical report](../output/pdf/ClaimGuard_Technical_Report.pdf)
4. [Hands-on rehearsal](verification/PHASE1-HANDS-ON-REHEARSAL.md)
5. [Generated evaluation report](verification/EDU-EVALUATION-REPORT.md)

### Security or AI reviewer

1. [Privacy and security note](12-Privacy-and-Security-Note.md)
2. [Assistance security envelope](19-Assistance-Security-Envelope.md)
3. [Interactive assistant design](22-AI-Assistant-Design.md)
4. [SLM benchmark methodology](18-SLM-Benchmark-Methodology.md)
5. [JEV advisory boundary](17-JEV-Judge-Layer.md)

## Product and architecture

| Document | Purpose |
|---|---|
| [01: Domain primer](01-DOMAIN-Gulf-Claims-101.md) | Healthcare-claim vocabulary and process context |
| [02: Problem and impact](02-PROBLEMATIC-Impact.md) | Problem framing and sourced claims |
| [02B: Pitch narrative](02B-PITCH-Problem-Narrative.md) | Shorter presentation narrative |
| [03: Challenge decode](03-Challenge-Decode-Requirements.md) | Rubric, constraints, and traceability |
| [04: Architecture](04-Architecture.md) | Earlier architecture baseline and decisions |
| [05: System design and data model](05-System-Design-Data-Model.md) | Detailed design reference; some sections are historical proposals |
| [06: Cahier des charges](06-Cahier-Des-Charges.md) | Functional and non-functional requirements |
| [09: Architecture v2 decisions](09-ARCHITECTURE-V2-Decisions.md) | Revised decisions, cuts, and delivery plan |
| [10: Starter-pack authority ADR](10-ADR-Starter-Pack-Authority.md) | Which contract governs Phase 1 evaluation |
| [11: Architecture and data flow](11-Architecture-and-Dataflow.md) | Current implemented pipeline and trust boundaries |
| [13: Technical report source](13-Technical-Report.md) | Markdown implementation report |
| [16: User flow and explainability](16-User-Flow-and-Explainability.md) | Reviewer journey and explanation behavior |
| [20: Implementation completion report](20-Implementation-Completion-Report.md) | Shipped inventory, limitations, and handoff |
| [21: Clinic platform foundation](21-Clinic-Platform-Foundation.md) | Tenancy, sessions, roles, and workspaces |

## AI, safety, and governance

| Document | Purpose |
|---|---|
| [12: Privacy and security](12-Privacy-and-Security-Note.md) | Data boundary, threat posture, and non-claims |
| [17: JEV judge layer](17-JEV-Judge-Layer.md) | Optional typed advisory sidecar |
| [18: SLM benchmark methodology](18-SLM-Benchmark-Methodology.md) | Colab evaluation protocol and deployment gate |
| [19: Assistance security envelope](19-Assistance-Security-Envelope.md) | AegisGraph-inspired authority graph and receipts |
| [22: AI assistant design](22-AI-Assistant-Design.md) | Interactive assistant components and data flow |

## Demonstration and team records

| Document | Purpose |
|---|---|
| [14: Contribution log](14-Contribution-Log.md) | Team contributions and AI-tool disclosure |
| [15: Demo script](15-Demo-Script.md) | Presentation narrative and fallback |
| [Phase 1 demo runbook](verification/PHASE1-DEMO-RUNBOOK.md) | Timed operational demonstration |
| [Phase 1 hands-on rehearsal](verification/PHASE1-HANDS-ON-REHEARSAL.md) | Manual verification of all scored paths |

## Verification evidence

Files under `verification/` are evidence, not marketing copy. The most useful are:

- [Phase 1 submission readiness](verification/PHASE-1-SUBMISSION-READINESS.md)
- [Phase 1 gap analysis](verification/PHASE-1-GAP-ANALYSIS.md)
- [Engine evaluation](verification/EDU-EVALUATION-REPORT.md)
- [Independent conformance](verification/EDU-PACK-CONFORMANCE.md)
- [Detection metrics](verification/DETECTION-METRICS.md)
- [Adversarial cases](verification/ADVERSARIAL-CASES.md)
- [FHIR mapping limits](verification/FHIR-MAPPING-EXAMPLE.md)
- [Audit replay](verification/AUDIT-REPLAY.md)
- [AI ablation](verification/AI-ABLATION.md)
- [Frontend refresh record](verification/FRONTEND-PRODUCT-REFRESH.md)
- [Preserved SLM benchmark artifacts](verification/slm-benchmark/2026-09-25/README.md)

## Source-of-truth order

When documents disagree, use this order:

1. executable tests and generated evidence for measured behavior;
2. current code, migrations, `.env.example`, and live OpenAPI for implementation behavior;
3. accepted architecture decisions for intended boundaries;
4. current implementation/handoff reports;
5. older design and planning documents as historical context.

Never copy a metric from an old document without rerunning its generator. Never publish private handoff details, credentials, keys, or real patient data.
