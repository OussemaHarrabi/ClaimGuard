# Bounded interactive assistant

`claimguard.ai` answers questions about a finding that the caller is already authorized to read. It is an explanation and correction-guidance layer, not a decision-maker.

[Back to the project README](../../README.md)

## Authority graph

```text
authorize caller
      │
      ▼
gather read-only deterministic context
      │
      ▼
optional model draft ── unavailable ──► deterministic fallback
      │
      ▼
schema + grounding + authority verifier
      │ safe                 │ unsafe
      ▼                      ▼
finalize answer       repair once or fallback
      │
      ▼
append turn and provenance receipt
```

The context contains the selected finding, its evidence, rule description, deterministic corrective action, and minimal run metadata. It does not grant the model a general database query or mutation tool.

## Non-negotiable constraints

The assistant cannot:

- change a status, severity, rule, evidence pointer, confidence field, or reviewer decision;
- edit a claim or trigger a recheck;
- approve, deny, submit, diagnose, or recommend treatment;
- read another tenant's data;
- treat source-document text as instructions;
- invent facts not present in the read-only context.

If a draft violates the schema, contradicts source facts, or claims prohibited authority, the verifier refuses it and uses a deterministic answer.

## Configure a provider

The safe default is:

```dotenv
CLAIMGUARD_AI_MODE=off
```

Supported modes are `off`, `groq`, and `openai_compatible`. When enabling one, set the corresponding values documented in the root `.env.example`:

```dotenv
CLAIMGUARD_AI_MODE=openai_compatible
CLAIMGUARD_AI_BASE_URL=https://provider.example/v1
CLAIMGUARD_AI_MODEL=your-deployed-model
CLAIMGUARD_AI_API_KEY=replace-locally
CLAIMGUARD_AI_TIMEOUT=30
CLAIMGUARD_AI_MAX_TOKENS=700
```

Never commit a key. Never make core claim processing depend on provider availability.

## SLM policy

The Colab benchmark is an evaluation track, not evidence that the latest or largest model should be deployed. Selection should use a frozen task-specific dataset and measure factual grounding, forbidden-claim rate, correction usefulness, abstention, latency, memory, and quantization regression.

Fine-tuning is justified only if retrieval, prompt structure, and constrained decoding still miss a predeclared acceptance gate. Any future fine-tuned model remains inside the same verifier and authority boundary.

Read [the benchmark methodology](../../docs/18-SLM-Benchmark-Methodology.md), [the assistance security envelope](../../docs/19-Assistance-Security-Envelope.md), and [the full assistant design](../../docs/22-AI-Assistant-Design.md).

## Code map and tests

| File | Responsibility |
|---|---|
| `graph.py` | State transitions and safe fallback path |
| `tools.py` | Narrow read-only context tools |
| `schemas.py` | Typed model inputs, outputs, and receipts |
| `prompts.py` | System task and authority constraints |
| `config.py` | Provider modes and limits |
| `store.py` | Append-only thread and turn persistence |
| `errors.py` | Explicit safe failure types |

```powershell
uv run pytest tests/ai tests/edu_explain -m "not llm and not e2e"
```

Provider-specific live tests must remain opt-in and must assert that provider failure changes no deterministic result.
