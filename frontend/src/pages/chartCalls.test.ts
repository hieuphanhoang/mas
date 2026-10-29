import { toChartCalls } from "./ControlRoomPage";

const d = (delivery_id: string, agent_id: string, parent_delivery_id: string | null, state: string) =>
  ({ delivery_id, agent_id, parent_delivery_id, state }) as Parameters<typeof toChartCalls>[0][number];

test("an Owner call starts at the Owner, an agent call at its caller", () => {
  const calls = toChartCalls([d("1", "lead", null, "running"), d("2", "worker", "1", "queued"), d("3", "x", null, "completed")]);
  expect(calls).toEqual([
    { from: null, to: "lead", live: true },
    { from: "lead", to: "worker", live: false },
  ]);
});

test("a call whose parent is not on the loaded page gets no arc, never an Owner arc", () => {
  expect(toChartCalls([d("9", "worker", "old-parent", "running")])).toEqual([]);
});
