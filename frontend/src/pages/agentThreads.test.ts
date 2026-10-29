import { agentThreads } from "./ControlRoomPage";
import type { ThreadSummary } from "../api/types";

const t = (id: string, from: string, to: string) => ({ thread_ref: { log_id: "main", thread_id: id }, from_name: from, to_name: to }) as unknown as ThreadSummary;

test("only AGENT threads the agent is part of can be continued; its ASK threads go through the Inbox", () => {
  const items = [t("AGENT-001", "Fable", "Codex"), t("ASK-001", "Fable", "Owner"), t("AGENT-002", "Codex", "Fable, Gemini"), t("AGENT-003", "Codex", "Qwen")];
  expect(agentThreads(items, "Fable").map((x) => x.thread_ref.thread_id)).toEqual(["AGENT-001", "AGENT-002"]);
});
