# ClaimGuard Assistance Security Envelope

## Decision

ClaimGuard uses an SLM to draft both the reviewer explanation and a contextual correction
recommendation for every attention finding (`FAIL`, `UNABLE_TO_ASSESS`, or `NOT_IMPLEMENTED`). The
SLM is not an adjudicator and cannot mutate or submit a claim. Its response is an inert candidate
that must pass a deterministic envelope before it reaches the administrator.

If the SLM is absent, times out, violates the exact schema, fabricates a citation, emits an
instruction-like payload, or crosses the decision boundary, ClaimGuard displays the deterministic
safe twin. This is degraded assistance, not silent success, and the UI labels it as a fallback.

## Authority graph

1. The versioned rule catalogue and deterministic engine own status, severity, routing and the
   human-review boundary.
2. Evidence pointers resolve against the immutable submitted envelope. Evidence values are data;
   they have no instruction authority.
3. The SLM may draft language and a recommended human step. It has no execution authority.
4. JEV may later provide an independent semantic-support opinion. It cannot approve rejected SLM
   output or override a deterministic finding.
5. The administrator remains the only actor who can record a review decision or submit a corrected
   envelope as a new version.

## Exact SLM contract

The model returns exactly five fields:

- `explanation`
- `correction_recommendation`
- `cited_evidence_paths`
- `cited_rule_ids`
- `needs_human_review`

Generation uses temperature zero and requests JSON-object mode. The verifier requires the exact
key set, real citations, the exact rule identifier, the unchanged human-review flag, non-empty
language, and the absence of adjudication, clinical conclusions, automatic action, or direct and
Base64-transformed instruction language.

## Decisions and receipts

The envelope records `accept`, `fallback`, or `decline`. Each displayed result carries a SHA-256
receipt over the claim/rule/status identity, explanation, correction recommendation, citations,
provider, decision, rejection reasons and fallback state. Migration `0004` persists these values in
the immutable `run_explanations` sidecar; the frozen 15-key scoring record remains unchanged.

Legacy rows are labelled `unrecorded` and have no invented receipt.

## Administrator experience

The explanation panel displays:

- the SLM explanation and correction recommendation;
- the accepted/fallback security decision;
- provider, model, prompt version and receipt prefix;
- verifier reasons when a draft was rejected;
- a “Use as editable note” action that copies the recommendation into the reviewer note without
  changing the claim or submitting a decision.

## Benchmark methodology

The Colab notebook now benchmarks the same five-field secured contract. The preserved 2026-09-25
results remain valid evidence about the older prompt, but they cannot select a model for the new
contract. The next run must compare raw model, prompt-only, schema-constrained, verifier, and full
envelope configurations and measure prompt-injection success, contract validity, citation and
semantic support, false fallback, reviewer utility, latency and VRAM.

No fine-tuning is authorized until the expanded, adjudicated corpus shows a residual error that
constrained generation and the deterministic envelope do not solve.
