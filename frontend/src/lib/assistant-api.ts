/**
 * The interactive assistant's browser client.
 *
 * Deliberately separate from `review-api.ts`: that module reads the frozen run record, while
 * every call here reads or writes only the assistant's own conversation tables. Nothing in this
 * module can change a finding's status, severity, evidence or routing — the shapes below mirror
 * `claimguard/ai/schemas.py`, and a turn's five-key answer is exactly the pack's explanation
 * contract, judged by the same verifier the graded explanation layer uses.
 *
 * The wire format is snake_case, as in `review-api.ts`: the caller reads the server's field
 * names directly rather than through a lossy mapping layer that could quietly rename a
 * provenance field.
 */

/** The longest question the server accepts (mirrors `MAX_QUESTION_CHARS`). */
export const MAX_QUESTION_CHARS = 500;

/** How an answer was produced. Shown to the reviewer on every turn. */
export type AssistantVerification = "accepted" | "repaired" | "fallback" | "refused";

/** Who is speaking in a turn. */
export type AssistantRole = "reviewer" | "assistant";

/** The validated five-key answer, or whatever the fallback/refusal path recorded. */
export type AssistantAnswerPayload = {
  explanation: string;
  correction_recommendation: string;
  cited_evidence_paths: string[];
  cited_rule_ids: string[];
  needs_human_review: boolean;
};

export type AssistantTurnPayload = {
  turn_id: string;
  thread_id: string;
  sequence: number;
  role: AssistantRole;
  question: string | null;
  answer: AssistantAnswerPayload | null;
  verification: AssistantVerification;
  reasons: string[];
  model_version: string;
  prompt_version: string;
  receipt: string | null;
  latency_ms: number | null;
  created_at: string;
};

export type AssistantThreadPayload = {
  thread_id: string;
  tenant_id: string;
  run_id: string;
  claim_id: string;
  rule_id: string;
  created_by: string;
  created_at: string;
  closed_at: string | null;
};

export type AssistantConversation = {
  thread: AssistantThreadPayload;
  turns: AssistantTurnPayload[];
};

export type AssistantStatus = {
  enabled: boolean;
  mode: string;
  model: string;
  prompt_version: string;
  detail: string;
};

async function responseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: string; message?: string };
      detail = payload.detail ?? payload.message ?? detail;
    } catch {
      // The status alone still gives the reviewer an actionable failure boundary.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

/** Whether the assistant can answer, and with what. Called before the first request so the
 *  panel can label a deterministic answer honestly instead of implying a model wrote it. */
export async function getAssistantStatus(signal?: AbortSignal): Promise<AssistantStatus> {
  return responseJson<AssistantStatus>(
    await fetch("/v1/ai/status", { signal, cache: "no-store" }),
  );
}

/** Open the conversation for one finding, optionally with the reviewer's first question. */
export async function explainFinding(
  runId: string,
  ruleId: string,
  question?: string,
  signal?: AbortSignal,
): Promise<AssistantConversation> {
  const body = question?.trim() ? { question: question.trim() } : {};
  return responseJson<AssistantConversation>(
    await fetch(
      `/v1/runs/${encodeURIComponent(runId)}/findings/${encodeURIComponent(ruleId)}/explain`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
        signal,
      },
    ),
  );
}

/** Continue an existing conversation. */
export async function sendAssistantMessage(
  threadId: string,
  question: string,
  signal?: AbortSignal,
): Promise<AssistantConversation> {
  return responseJson<AssistantConversation>(
    await fetch(`/v1/threads/${encodeURIComponent(threadId)}/messages`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question }),
      signal,
    }),
  );
}

/** Re-read a conversation without asking anything new. */
export async function getAssistantThread(
  threadId: string,
  signal?: AbortSignal,
): Promise<AssistantConversation> {
  return responseJson<AssistantConversation>(
    await fetch(`/v1/threads/${encodeURIComponent(threadId)}`, { signal, cache: "no-store" }),
  );
}
