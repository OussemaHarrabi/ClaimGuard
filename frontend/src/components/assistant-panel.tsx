"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { AlertTriangle, CircleAlert, Send, ShieldCheck, WandSparkles } from "lucide-react";

import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";
import { fieldLabel } from "../lib/claim-editor";
import {
  MAX_QUESTION_CHARS,
  explainFinding,
  getAssistantStatus,
  sendAssistantMessage,
  type AssistantAnswerPayload,
  type AssistantConversation,
  type AssistantStatus,
  type AssistantTurnPayload,
  type AssistantVerification,
} from "../lib/assistant-api";

/** One path/value pair already shown beside the finding, reused here so a cited path resolves
 *  to the same chip the reviewer just read. Structurally the cockpit's `Evidence`. */
export type AssistantEvidence = {
  readonly path: string;
  readonly value: unknown;
};

type AssistantPanelProps = {
  readonly runId: string;
  readonly ruleId: string;
  readonly evidence: readonly AssistantEvidence[];
};

type PendingRequest = "explain" | "message" | null;

type Failure = {
  readonly scope: "explain" | "message";
  readonly message: string;
};

/** Plain-word labels. A fallback never borrows the assistant's wording: the reviewer has to see
 *  that the deterministic text stood in. Deliberately provider- and model-free — which model
 *  drafted an answer is an audit record (the API and the database keep it), not reviewer prose. */
const VERIFICATION_LABELS: Record<AssistantVerification, string> = {
  accepted: "AI-assisted wording",
  repaired: "AI-assisted wording, repaired by the verifier",
  fallback: "AI wording not used — deterministic explanation shown",
  refused: "Declined by the assistant",
};

const VERIFICATION_TONES: Record<AssistantVerification, string> = {
  accepted: "assisted",
  repaired: "repaired",
  fallback: "fallback",
  refused: "refused",
};

const REASON_LEADS: Record<AssistantVerification, string> = {
  accepted: "Verifier notes",
  repaired: "Verifier corrections",
  fallback: "Draft answer not used",
  refused: "Declined because",
};

function evidenceLabel(path: string) {
  try {
    return fieldLabel(path);
  } catch {
    return path.replace(/^\//, "").replaceAll("/", " ").replaceAll("_", " ") || "claim evidence";
  }
}

/** The stored answer, or null when the server recorded a refusal (or something off-contract). */
function readAnswer(answer: AssistantAnswerPayload | null): AssistantAnswerPayload | null {
  if (!answer || typeof answer.explanation !== "string") return null;
  return {
    explanation: answer.explanation,
    correction_recommendation:
      typeof answer.correction_recommendation === "string" ? answer.correction_recommendation : "",
    cited_evidence_paths: Array.isArray(answer.cited_evidence_paths) ? answer.cited_evidence_paths : [],
    cited_rule_ids: Array.isArray(answer.cited_rule_ids) ? answer.cited_rule_ids : [],
    needs_human_review: answer.needs_human_review === true,
  };
}

/** The secondary line beside a turn's label. Latency is the reviewer's own signal — how long the
 *  answer took — and it is all that belongs there: the provider and model that drafted the turn
 *  stay in the audit record the API and database keep, and are never rendered here. */
function turnMeta(turn: AssistantTurnPayload): string | null {
  return typeof turn.latency_ms === "number" ? `${turn.latency_ms} ms` : null;
}

function AssistantTurnView({
  turn,
  evidence,
  ruleId,
}: {
  turn: AssistantTurnPayload;
  evidence: readonly AssistantEvidence[];
  ruleId: string;
}) {
  const answer = readAnswer(turn.answer);
  const reasons = Array.isArray(turn.reasons) ? turn.reasons : [];
  const meta = turnMeta(turn);

  return (
    <li
      className="assistant-turn assistant"
      data-testid={`assistant-turn-${turn.turn_id}`}
      data-verification={turn.verification}
    >
      <div className="provenance-line">
        <span className={`provenance ${VERIFICATION_TONES[turn.verification]}`}>
          {VERIFICATION_LABELS[turn.verification]}
        </span>
        {meta ? <span>{meta}</span> : null}
      </div>

      {answer ? (
        <>
          <p className="assistant-explanation">{answer.explanation}</p>
          <section
            className="correction-recommendation"
            aria-label={`Recommended correction for ${ruleId}`}
          >
            <span>Recommended correction</span>
            <p>{answer.correction_recommendation}</p>
            <small>Verify against source documents. No claim field is changed automatically.</small>
          </section>
          {answer.cited_evidence_paths.length ? (
            <div className="evidence-list" aria-label={`Cited evidence for ${ruleId}`}>
              {answer.cited_evidence_paths.map((path) => {
                const cited = evidence.find((entry) => entry.path === path);
                return (
                  <span className="evidence-item" key={path} data-cited-path={path}>
                    <span>{evidenceLabel(path)}</span>
                    <strong>
                      {cited === undefined
                        ? "not in this finding"
                        : typeof cited.value === "string"
                          ? cited.value
                          : JSON.stringify(cited.value)}
                    </strong>
                  </span>
                );
              })}
            </div>
          ) : null}
          {answer.cited_rule_ids.length ? (
            <div className="citation-row" aria-label={`Cited rules for ${ruleId}`}>
              {answer.cited_rule_ids.map((citedRule) => (
                <span className="citation" key={citedRule}>
                  {citedRule}
                </span>
              ))}
            </div>
          ) : null}
        </>
      ) : null}

      {turn.verification === "refused" ? (
        <p className="assistant-refusal">
          {answer?.explanation ?? "The assistant declined to answer this question."}
        </p>
      ) : null}

      {reasons.length ? (
        <div className={`verifier-warning${turn.verification === "refused" ? " refusal" : ""}`}>
          <AlertTriangle size={16} aria-hidden="true" />
          <span>
            {REASON_LEADS[turn.verification]}: {reasons.join(", ")}.
          </span>
        </div>
      ) : null}

      <details className="technical-provenance">
        <summary>Turn provenance for {turn.turn_id}</summary>
        <dl className="provenance-details" aria-label={`Provenance for turn ${turn.turn_id}`}>
          <div>
            <dt>Verification</dt>
            <dd>{turn.verification}</dd>
          </div>
          <div>
            <dt>Prompt</dt>
            <dd>{turn.prompt_version || "not recorded"}</dd>
          </div>
          <div>
            <dt>Latency</dt>
            <dd>{typeof turn.latency_ms === "number" ? `${turn.latency_ms} ms` : "not recorded"}</dd>
          </div>
          <div>
            <dt>Receipt</dt>
            <dd title={turn.receipt ?? "Not recorded"}>
              {turn.receipt ? `Receipt ${turn.receipt.slice(0, 8)}` : "Not recorded"}
            </dd>
          </div>
          <div>
            <dt>Needs human review</dt>
            <dd>{answer?.needs_human_review ? "Yes" : "No"}</dd>
          </div>
        </dl>
      </details>
    </li>
  );
}

/**
 * The assistant surface inside one finding's guidance column, under the deterministic wording
 * and the rule-based next step, above the technical provenance.
 *
 * It reads a stored run and writes only its own conversation: the deterministic engine stays the
 * authority on status, severity, evidence and routing, which is why every answer carries its own
 * provenance line instead of being blended into the finding's own block.
 *
 * The first explanation and the status check are requested by the reviewer's click, not on
 * render: a cockpit with twelve findings must not fire twelve model requests just because the
 * claim was opened. Re-opening asks for the same thread again — ``POST …/explain`` opens or
 * resumes it — so the turns a reviewer already read come back instead of being lost with the
 * panel.
 */
export function AssistantPanel({ runId, ruleId, evidence }: AssistantPanelProps) {
  const panelId = useId();
  const regionRef = useRef<HTMLElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const requestRef = useRef<AbortController | null>(null);
  const startedRef = useRef(false);

  const [open, setOpen] = useState(false);
  const [started, setStarted] = useState(false);
  const [pending, setPending] = useState<PendingRequest>(null);
  const [conversation, setConversation] = useState<AssistantConversation | null>(null);
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [draft, setDraft] = useState("");
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);

  useEffect(() => () => requestRef.current?.abort(), []);

  useEffect(() => {
    if (open) regionRef.current?.focus();
  }, [open]);

  const requestExplanation = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setPending("explain");
    setFailure(null);
    // The status check never blocks the explanation: an unreachable status route must not cost
    // the reviewer the answer the assistant can still give.
    const [statusOutcome, conversationOutcome] = await Promise.allSettled([
      getAssistantStatus(controller.signal),
      explainFinding(runId, ruleId, undefined, controller.signal),
    ]);
    if (controller.signal.aborted) return;
    if (statusOutcome.status === "fulfilled") setStatus(statusOutcome.value);
    if (conversationOutcome.status === "fulfilled") {
      setConversation(conversationOutcome.value);
    } else {
      setFailure({
        scope: "explain",
        message:
          conversationOutcome.reason instanceof Error
            ? conversationOutcome.reason.message
            : "The assistant request failed.",
      });
    }
    setPending(null);
  }, [runId, ruleId]);

  const send = useCallback(async () => {
    const question = draft.trim();
    if (!conversation || !question || pending) return;
    const threadId = conversation.thread.thread_id;
    setPending("message");
    setFailure(null);
    setPendingQuestion(question);
    setDraft("");
    try {
      const next = await sendAssistantMessage(threadId, question, requestRef.current?.signal);
      setConversation(next);
      setPendingQuestion(null);
    } catch (error) {
      // Put the reviewer's words back so the retry does not ask them to type it again.
      setPendingQuestion(null);
      setDraft(question);
      setFailure({
        scope: "message",
        message: error instanceof Error ? error.message : "The assistant request failed.",
      });
    } finally {
      setPending(null);
      composerRef.current?.focus();
    }
  }, [conversation, draft, pending]);

  function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (startedRef.current) return;
    startedRef.current = true;
    setStarted(true);
    void requestExplanation();
  }

  const turns = conversation?.turns ?? [];
  const busy = pending !== null;
  // What the reviewer is about to read, in their own words. The provider, its mode and the model
  // name the status route reports stay out of the interface: a reviewer needs to know whether an
  // AI drafted the wording, not which vendor produced it.
  const scopeLabel = status
    ? status.enabled
      ? "AI-assisted wording, checked by the verifier"
      : "Deterministic explanations only"
    : null;

  return (
    <div className="assistant-block" data-testid={`assistant-${ruleId}`}>
      <Button
        className="text-button assistant-trigger"
        variant="outline"
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={
          open ? `XAI: hide the explanation for ${ruleId}` : `XAI: explain finding ${ruleId}`
        }
        onClick={toggle}
      >
        <WandSparkles size={16} aria-hidden="true" />
        XAI
      </Button>

      {started ? (
        <div className="assistant-collapse" data-open={open ? "true" : "false"} inert={!open} aria-hidden={!open}>
          <div className="assistant-collapse-inner">
            <section
              className="assistant-panel"
              id={panelId}
              role="region"
              aria-label={`XAI assistant for ${ruleId}`}
              tabIndex={-1}
              ref={regionRef}
            >
              <div className="assistant-panel-head">
                <span className="assistant-mark" aria-hidden="true">
                  <WandSparkles size={15} />
                </span>
                <div>
                  <p className="eyebrow">XAI</p>
                  <h4>Ask about {ruleId}</h4>
                </div>
                {scopeLabel ? (
                  <span className="assistant-scope" data-enabled={status?.enabled ? "true" : "false"}>
                    {scopeLabel}
                  </span>
                ) : null}
              </div>

              <p className="assistant-boundary">
                <ShieldCheck size={14} aria-hidden="true" />
                Answers here explain the stored run. They cannot change a status, severity, evidence
                pointer or routing — the deterministic engine remains authoritative.
              </p>

              {pending === "explain" ? (
                <p className="assistant-pending" role="status">
                  Asking the assistant…
                </p>
              ) : null}

              {failure ? (
                <div className="assistant-error" role="alert">
                  <CircleAlert size={16} aria-hidden="true" />
                  <span>{failure.message}</span>
                  <button
                    type="button"
                    onClick={() => {
                      if (failure.scope === "message") void send();
                      else void requestExplanation();
                    }}
                  >
                    Try again
                  </button>
                </div>
              ) : null}

              <ol
                className="assistant-thread"
                aria-live="polite"
                aria-busy={pending === "message"}
                aria-label={`Conversation about ${ruleId}`}
              >
                {turns.map((turn) =>
                  turn.role === "reviewer" ? (
                    <li
                      className="assistant-turn reviewer"
                      key={turn.turn_id}
                      data-testid={`assistant-question-${turn.turn_id}`}
                    >
                      <p className="assistant-question">{turn.question}</p>
                    </li>
                  ) : (
                    <AssistantTurnView key={turn.turn_id} turn={turn} evidence={evidence} ruleId={ruleId} />
                  ),
                )}
                {pendingQuestion ? (
                  <li className="assistant-turn reviewer" data-testid="assistant-question-pending">
                    <p className="assistant-question">{pendingQuestion}</p>
                    <span className="assistant-awaiting">Sending…</span>
                  </li>
                ) : null}
              </ol>

              <form
                className="assistant-composer"
                onSubmit={(event) => {
                  event.preventDefault();
                  void send();
                }}
              >
                <label className="assistant-composer-field">
                  <span>Your question about {ruleId}</span>
                  <Textarea
                    ref={composerRef}
                    rows={2}
                    value={draft}
                    maxLength={MAX_QUESTION_CHARS}
                    placeholder={
                      conversation
                        ? "Why is the price wrong? What exactly do I ask the provider for?"
                        : "The message box opens once the assistant has answered."
                    }
                    disabled={!conversation || pending === "explain"}
                    onChange={(event) => setDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
                      event.preventDefault();
                      void send();
                    }}
                  />
                </label>
                <Button
                  className="primary-button assistant-send"
                  type="submit"
                  disabled={busy || !conversation || !draft.trim()}
                >
                  <Send size={15} aria-hidden="true" />
                  Send
                </Button>
              </form>
              <p className="assistant-help">
                {draft.length ? `${draft.length}/${MAX_QUESTION_CHARS} characters · ` : ""}Enter sends · Shift+Enter starts a new line.
              </p>
            </section>
          </div>
        </div>
      ) : null}
    </div>
  );
}
