import { callerLabel, runDuration } from "./history";

const names = new Map([["haiku", "Haiku"]]);

test("caller shows You, the calling agent's name, or unknown", () => {
  expect(callerLabel({ kind: "owner", agent_id: null }, names)).toBe("You");
  expect(callerLabel({ kind: "agent", agent_id: "haiku" }, names)).toBe("Haiku");
  expect(callerLabel({ kind: "agent", agent_id: "gone" }, names)).toBe("gone");
  expect(callerLabel({ kind: "unknown", agent_id: null }, names)).toBe("unknown");
  expect(callerLabel(undefined, names)).toBe("-");
});

test("run duration", () => {
  expect(runDuration("2026-10-30T06:46:00Z", "2026-10-30T06:46:42Z")).toBe("42s");
  expect(runDuration("2026-10-30T06:46:00Z", "2026-10-30T06:49:05Z")).toBe("3m 05s");
  expect(runDuration("2026-10-30T06:46:00Z", null)).toBe("running");
  expect(runDuration(null, null)).toBe("-");
});
