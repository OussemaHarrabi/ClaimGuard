import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssistantPanel, type AssistantEvidence } from "./assistant-panel";
import { ReviewCockpit, type ReviewWorkspace } from "./review-cockpit";

const EVIDENCE: readonly AssistantEvidence[] = [
  { path: "/coverage/end_date", value: "2026-08-31" },
  { path: "/service_date", value: "2026-09-12" },
];

const THREAD = {
  thread_id: "TH-1",
  tenant_id: "tenant-a",
  run_id: "RUN-031",
  claim_id: "CLM-240031",
  rule_id: "R004",
  created_by: "reviewer-12",
  created_at: "2026-10-01T09:00:00Z",
  closed_at: null,
};

const EXPLANATION = {
  explanation: "Coverage ended on 31 August, before the 12 September service date.",
  correction_recommendation: "Verify the service date against the eligibility source before recheck.",
  cited_evidence_paths: ["/coverage/end_date", "/not/in/this/finding"],
  cited_rule_ids: ["R004"],
  needs_human_review: true,
};

function assistantTurn(overrides: Record<string, unknown>) {
  return {
    turn_id: "T-1",
    thread_id: "TH-1",
    sequence: 1,
    role: "assistant",
    question: null,
    answer: EXPLANATION,
    verification: "accepted",
    reasons: [],
    model_version: "qwen3.8-27b",
    prompt_version: "assistant-v1",
    receipt: "c".repeat(64),
    latency_ms: 640,
    created_at: "2026-10-01T09:00:01Z",
    ...overrides,
  };
}

const STATUS = {
  enabled: true,
  mode: "groq",
  model: "qwen3.8-27b",
  prompt_version: "assistant-v1",
  detail: "Groq key configured.",
};

function respond(payload: unknown) {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => payload,
  } as Response;
}

function fail(status: number, detail: string) {
  return {
    ok: false,
    status,
    statusText: "Bad Gateway",
    json: async () => ({ detail }),
  } as Response;
}

type RecordedRequest = { url: string; method: string | undefined; body: string | undefined };

/** A fetch stub keyed by exact URL, so every assertion about a request is about the URL, method
 *  and body the panel actually used. */
function stubFetch(routes: Record<string, () => Promise<Response>>) {
  const requests: RecordedRequest[] = [];
  vi.stubGlobal("fetch", async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    requests.push({
      url,
      method: init?.method,
      body: typeof init?.body === "string" ? init.body : undefined,
    });
    const route = routes[url];
    if (!route) throw new Error(`unexpected request: ${url}`);
    return route();
  });
  return requests;
}

function renderPanel() {
  render(<AssistantPanel runId="RUN-031" ruleId="R004" evidence={EVIDENCE} />);
  return screen.getByRole("button", { name: /XAI: explain finding R004/ });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AssistantPanel", () => {
  it("opens a conversation from the finding and reads the answer as prose", async () => {
    const requests = stubFetch({
      "/v1/ai/status": async () => respond(STATUS),
      "/v1/runs/RUN-031/findings/R004/explain": async () =>
        respond({ thread: THREAD, turns: [assistantTurn({})] }),
    });

    const trigger = renderPanel();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);

    const region = screen.getByRole("region", { name: "XAI assistant for R004" });
    expect(region).toHaveFocus();
    expect(screen.getByLabelText("Conversation about R004")).toHaveAttribute("aria-live", "polite");

    expect(await screen.findByText(EXPLANATION.explanation)).toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveAttribute("aria-label", "XAI: hide the explanation for R004");
    expect(trigger).toHaveTextContent("XAI");
    expect(screen.getByText(EXPLANATION.correction_recommendation)).toBeInTheDocument();
    expect(screen.getByText("AI-assisted wording")).toBeInTheDocument();
    // The latency may stay in the turn header; the model and its provider must not be rendered.
    expect(screen.getByText("640 ms", { selector: "span" })).toBeInTheDocument();
    expect(
      screen.getByText("AI-assisted wording, checked by the verifier"),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/qwen|groq/i);

    const cited = screen.getByLabelText("Cited evidence for R004");
    expect(within(cited).getByText("Coverage · end date")).toBeInTheDocument();
    expect(within(cited).getByText("2026-08-31")).toBeInTheDocument();
    expect(within(cited).getByText("not in this finding")).toBeInTheDocument();

    const explain = requests.find((request) => request.url.endsWith("/explain"));
    expect(explain?.url).toBe("/v1/runs/RUN-031/findings/R004/explain");
    expect(explain?.method).toBe("POST");
    expect(explain?.body).toBe("{}");
  });

  it("shows a fallback as deterministic text instead of a model answer", async () => {
    stubFetch({
      "/v1/ai/status": async () =>
        respond({ ...STATUS, enabled: false, detail: "No model configured." }),
      "/v1/runs/RUN-031/findings/R004/explain": async () =>
        respond({
          thread: THREAD,
          turns: [
            assistantTurn({
              verification: "fallback",
              reasons: ["unsupported citation"],
              model_version: "deterministic",
              latency_ms: 11,
            }),
          ],
        }),
    });

    fireEvent.click(renderPanel());

    expect(await screen.findByText("AI wording not used — deterministic explanation shown")).toBeInTheDocument();
    expect(screen.queryByText("AI-assisted wording")).not.toBeInTheDocument();
    expect(screen.getByText(/Draft answer not used: unsupported citation\./)).toBeInTheDocument();
    expect(screen.getByText("Deterministic explanations only")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/qwen|groq/i);
  });

  it("renders a refusal and its reason, not an error", async () => {
    stubFetch({
      "/v1/ai/status": async () => respond(STATUS),
      "/v1/runs/RUN-031/findings/R004/explain": async () =>
        respond({
          thread: THREAD,
          turns: [
            assistantTurn({
              verification: "refused",
              answer: null,
              reasons: ["the question asks for a clinical diagnosis"],
            }),
          ],
        }),
    });

    fireEvent.click(renderPanel());

    expect(await screen.findByText("Declined by the assistant")).toBeInTheDocument();
    expect(screen.getByText("The assistant declined to answer this question.")).toBeInTheDocument();
    expect(
      screen.getByText(/Declined because: the question asks for a clinical diagnosis\./),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps a failed request actionable and retries on demand", async () => {
    let attempts = 0;
    stubFetch({
      "/v1/ai/status": async () => respond(STATUS),
      "/v1/runs/RUN-031/findings/R004/explain": async () => {
        attempts += 1;
        return attempts === 1
          ? fail(502, "the assistant service is unreachable")
          : respond({ thread: THREAD, turns: [assistantTurn({})] });
      },
    });

    fireEvent.click(renderPanel());

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("the assistant service is unreachable")).toBeInTheDocument();
    expect(screen.queryByText(EXPLANATION.explanation)).not.toBeInTheDocument();

    fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(await screen.findByText(EXPLANATION.explanation)).toBeInTheDocument();
    expect(attempts).toBe(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("posts a follow-up to the thread, locks send while waiting, and appends the answer", async () => {
    const followUp = {
      ...EXPLANATION,
      explanation: "The unit price is 940 against a policy limit of 320.",
      cited_evidence_paths: ["/service_date"],
    };
    const withFollowUp = {
      thread: THREAD,
      turns: [
        assistantTurn({}),
        {
          ...assistantTurn({}),
          turn_id: "T-2",
          sequence: 2,
          role: "reviewer",
          question: "Why is the price wrong?",
          answer: null,
          latency_ms: null,
        },
        assistantTurn({
          turn_id: "T-3",
          sequence: 3,
          question: "Why is the price wrong?",
          answer: followUp,
        }),
      ],
    };
    const deferred: { resolve: (response: Response) => void } = { resolve: () => undefined };
    const pending = new Promise<Response>((resolve) => {
      deferred.resolve = resolve;
    });
    const requests = stubFetch({
      "/v1/ai/status": async () => respond(STATUS),
      "/v1/runs/RUN-031/findings/R004/explain": async () =>
        respond({ thread: THREAD, turns: [assistantTurn({})] }),
      "/v1/threads/TH-1/messages": () => pending,
    });

    fireEvent.click(renderPanel());
    const composer = await screen.findByLabelText("Your question about R004");
    await screen.findByText(EXPLANATION.explanation);

    fireEvent.keyDown(composer, { key: "Enter", shiftKey: true });
    expect(requests.filter((request) => request.url.includes("/messages"))).toHaveLength(0);

    fireEvent.change(composer, { target: { value: "Why is the price wrong?" } });
    composer.focus();
    fireEvent.keyDown(composer, { key: "Enter" });

    expect(await screen.findByText("Why is the price wrong?")).toBeInTheDocument();
    const send = screen.getByRole("button", { name: "Send" });
    expect(send).toBeDisabled();
    expect(composer).toHaveFocus();

    const message = requests.find((request) => request.url.includes("/messages"));
    expect(message?.url).toBe("/v1/threads/TH-1/messages");
    expect(message?.method).toBe("POST");
    expect(JSON.parse(String(message?.body))).toEqual({ question: "Why is the price wrong?" });

    deferred.resolve(respond(withFollowUp));

    expect(await screen.findByText(followUp.explanation)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Sending…")).not.toBeInTheDocument());
    // The lock is on the request, not on the reviewer: a new question re-enables Send.
    fireEvent.change(composer, { target: { value: "What do I ask the provider for?" } });
    expect(send).toBeEnabled();
  });

  it("wires the assistant into the guidance column of every finding the reviewer can act on", async () => {
    const workspace = {
      counts: { findings: 1, unresolved: 1, resolved: 0 },
      claims: [
        {
          claimId: "CLM-240031",
          runId: "RUN-031",
          version: 2,
          findings: 1,
          unresolved: 1,
          latestDecisionAt: null,
        },
      ],
      selected: {
        run: {
          runId: "RUN-031",
          claimId: "CLM-240031",
          version: 2,
          ruleVersion: "1.0.0",
          modelVersion: "slm-benchmark-pending",
          promptVersion: "explain-v1",
          initiatedBy: "reviewer-12",
          createdAt: "2026-09-24T08:35:00Z",
          supersedesRunId: null,
        },
        findings: [
          {
            ruleId: "R004",
            status: "FAIL",
            severity: "high",
            explanation: "Coverage ended before the service date.",
            correctiveAction: "Verify eligibility.",
            correctionRecommendation: "Verify the service date.",
            evidence: EVIDENCE,
            reviewStatus: "unreviewed",
            provenance: {
              source: "model",
              provider: "benchmark-candidate",
              rewritten: true,
              fallbackUsed: false,
              rejectionReasons: [],
              declinedReason: null,
              securityDecision: "accept",
              receiptSha256: "a".repeat(64),
            },
          },
        ],
        decisions: [],
      },
    } as const satisfies ReviewWorkspace;

    const requests = stubFetch({
      "/v1/ai/status": async () => respond(STATUS),
      "/v1/runs/RUN-031/findings/R004/explain": async () =>
        respond({ thread: THREAD, turns: [assistantTurn({})] }),
    });

    render(
      <ReviewCockpit
        workspace={workspace}
        busy={false}
        error={null}
        reviewer="reviewer-12"
        onSelectClaim={vi.fn()}
        onRefresh={vi.fn()}
        onRecordDecision={vi.fn()}
        onRecheck={vi.fn()}
      />,
    );

    const finding = screen.getByTestId("finding-R004");
    const assistant = within(finding).getByTestId("assistant-R004");
    // The conversation belongs to the guidance panel: inside the right-hand column, and never in
    // the middle card where the evidence chips, reviewer note and decision buttons live.
    expect(within(finding).getByTestId("explanation-R004")).toContainElement(assistant);
    expect(finding.querySelector(".finding-content")).not.toContainElement(assistant);
    expect(finding.querySelector(".finding-actions")).not.toContainElement(assistant);

    const trigger = within(within(finding).getByTestId("explanation-R004")).getByRole("button", {
      name: /XAI: explain finding R004/,
    });
    fireEvent.click(trigger);

    expect(await within(finding).findByText(EXPLANATION.explanation)).toBeInTheDocument();
    expect(
      within(finding).getByText(/cannot change a status, severity, evidence/),
    ).toBeInTheDocument();

    // Closing and re-opening shows the turns the reviewer already read, without asking again.
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(
      within(finding).getByTestId("assistant-R004").querySelector(".assistant-collapse"),
    ).toHaveAttribute("data-open", "false");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(within(finding).getByText(EXPLANATION.explanation)).toBeInTheDocument();
    expect(requests.filter((request) => request.url.endsWith("/explain"))).toHaveLength(1);
  });
});
