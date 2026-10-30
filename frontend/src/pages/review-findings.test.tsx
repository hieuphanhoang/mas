// Regression tests for Codex's frontend review findings in AGENT-005.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { InboxPage } from "./InboxPage";
import { AgentsPage, OutputPane } from "./AgentsPage";
import { FakeEventSource, Wrap, agentView, mockFetch, session } from "../test/mockApi";
import { resetSession } from "../api/client";

beforeEach(() => resetSession());
afterEach(() => vi.unstubAllGlobals());

const summary = (id: string, title: string) => ({
  thread_ref: { project_id: "p", log_id: "main", thread_id: id }, title, type: "QUESTION", status: "open",
  from_name: "Alpha", to_name: "Owner", owes_reply: "Owner", updated_at: "2026-10-29T00:00:00Z", revision: `rev-${id}`, parse_errors: [],
});
const doc = (id: string, title: string) => ({
  metadata: summary(id, title), markdown: `# ${title}`, event_cursor: "0",
  freshness: { state: "current", observed_at: "2026-10-29T00:00:00Z", reason: null },
});

test("#1 an answer draft and wake choice never carry over to another ASK", async () => {
  mockFetch({
    "GET /api/v1/session": session,
    "GET /api/v1/inbox": () => ({ items: [summary("ASK-001", "Question one"), summary("ASK-002", "Question two")], next_cursor: null, sources: [] }),
    "GET /api/v1/projects/p/logs/main/threads/ASK-001": () => doc("ASK-001", "Question one"),
    "GET /api/v1/projects/p/logs/main/threads/ASK-002": () => doc("ASK-002", "Question two"),
    "GET /api/v1/projects/p/agents": () => ({ items: [agentView("alpha", "Alpha")], event_cursor: "0" }),
  });
  render(<Wrap path="/inbox" route="/inbox"><InboxPage /></Wrap>);
  fireEvent.click(await screen.findByRole("button", { name: /Question one/ }));
  const box1 = await screen.findByPlaceholderText(/Short answers are fine/);
  fireEvent.change(box1, { target: { value: "Approve ONLY ASK-001" } });
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "alpha" } });
  fireEvent.click(screen.getByRole("button", { name: /Question two/ }));
  const box2 = await screen.findByPlaceholderText(/Short answers are fine/);
  expect((box2 as HTMLTextAreaElement).value).toBe("");
  expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("");
});

test("#2 switching lanes never carries one agent's chat draft to another", async () => {
  vi.stubGlobal("EventSource", FakeEventSource);
  const project = {
    config: {
      schema_version: 1, project: { id: "p", name: "P", root: "D:/p", timezone: "UTC", archived: false },
      folders: [{ id: "root", path: "D:/p" }], logs: [{ id: "main", folder_id: "root", relative_path: ".handoff", members: ["alpha", "beta"] }],
      levels: [{ id: "members", label: "Members", order: 0 }], agents: [], rituals: [],
      call_policy: { mode: "orchestrated", allowed_edges: [], subagents: "disabled", max_parallel: 2, max_chain_depth: 8, max_calls_per_chain: 32, run_timeout_seconds: 3600, paid_model_fallback: false },
      guard_policy: { mode: "guarded", protected_paths: [], merge_by: "owner", pushes: "owner", review_before_merge: true, leases_enabled: false },
      retention: { output_days: 7, event_days: 7, capture_output: true, copy_provider_transcripts: false },
      adapter_options: { claude: {}, codex: {}, opencode: {}, gemini: {} },
    },
    revision: "r1", applied_revision: "r1", scaffold_state: "applied", event_cursor: "0",
  };
  mockFetch({
    "GET /api/v1/session": session,
    "GET /api/v1/projects": () => ({ items: [], next_cursor: null }),
    "GET /api/v1/projects/p": () => project,
    "GET /api/v1/projects/p/agents": () => ({ items: [agentView("alpha", "Alpha"), agentView("beta", "Beta")], event_cursor: "0" }),
    "GET /api/v1/projects/p/calls": () => ({ items: [], next_cursor: null, event_cursor: "0" }),
    "GET /api/v1/projects/p/logs": () => ({ items: [{ project_id: "p", log_id: "main", folder_id: "root", members: ["alpha", "beta"], freshness: { state: "current", observed_at: null, reason: null } }], event_cursor: "0" }),
  });
  render(<Wrap path="/agents/p" route="/agents/:projectId"><AgentsPage /></Wrap>);
  fireEvent.click((await screen.findByText("Alpha")).closest("button")!);
  fireEvent.click(await screen.findByRole("button", { name: "chat" }));
  fireEvent.change(await screen.findByPlaceholderText(/written verbatim/), { target: { value: "Followup intended for A" } });
  fireEvent.click(screen.getAllByText("Beta")[0].closest("button")!);
  fireEvent.click(await screen.findByRole("button", { name: "chat" }));
  const box = await screen.findByPlaceholderText(/written verbatim/);
  expect((box as HTMLTextAreaElement).value).toBe("");
});

test("#3 output keeps polling while the run is active, also when caught up", async () => {
  let polls = 0;
  mockFetch({
    "GET /api/v1/session": session,
    "GET /api/v1/projects/p/runs/r1/output": (url) => {
      const offset = url.searchParams.get("offset");
      if (offset === "0") {
        polls += 1;
        return polls === 1
          ? { run_id: "r1", chunks: [], next_offset: "0", eof: false, expires_at: "2026-11-05T00:00:00Z" }
          : { run_id: "r1", chunks: [{ offset: "0", stream: "stdout", text: "hello from the run" }], next_offset: "1", eof: false, expires_at: "2026-11-05T00:00:00Z" };
      }
      return { run_id: "r1", chunks: [], next_offset: "1", eof: true, expires_at: "2026-11-05T00:00:00Z" };
    },
  });
  render(<Wrap path="/" route="/"><OutputPane projectId="p" runId="r1" /></Wrap>);
  await waitFor(() => expect(screen.getByTestId("run-output").textContent).toBe("hello from the run"), { timeout: 5000 });
  await waitFor(() => expect(screen.getByText("finished")).toBeInTheDocument(), { timeout: 5000 });
});
