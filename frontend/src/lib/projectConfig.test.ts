import { emptyConfig, hints, newAgent, normalize, normalizeRoot, textToPathRefs, toggleEdge } from "./projectConfig";

test("roots are normalised to forward slashes", () => {
  expect(normalizeRoot("D:\\AIStudio\\x\\")).toBe("D:/AIStudio/x");
  expect(normalizeRoot("D:\\")).toBe("D:/");
});

const base = () => {
  const c = emptyConfig("demo", "Demo", "D:/p/demo", "UTC");
  c.levels = [{ id: "l1", label: "L1", order: 0 }];
  return c;
};

test("path refs parse folder:path, bare paths and drive letters", () => {
  expect(textToPathRefs("root:src\nfrontend\n", "root")).toEqual([
    { folder_id: "root", path: "src" },
    { folder_id: "root", path: "frontend" },
  ]);
  expect(textToPathRefs("D:/x/y", "root")).toEqual([{ folder_id: "root", path: "D:/x/y" }]);
});

test("normalize derives log members, drops helper logs and bad edges", () => {
  const c = base();
  const a = newAgent(c);
  c.agents.push(a);
  const h = { ...newAgent(c), id: "h", name: "Helper", log_duty: "helper" as const, sponsor_agent_id: a.id };
  c.agents.push(h);
  c.call_policy.allowed_edges = [
    { from_agent_id: a.id, to_agent_id: "h" },
    { from_agent_id: a.id, to_agent_id: a.id },
    { from_agent_id: a.id, to_agent_id: "ghost" },
    { from_agent_id: a.id, to_agent_id: "h" },
  ];
  const n = normalize(c);
  expect(n.logs[0].members).toEqual([a.id]);
  expect(n.agents[1].log_ids).toEqual([]);
  expect(n.call_policy.allowed_edges).toEqual([{ from_agent_id: a.id, to_agent_id: "h" }]);
});

test("relay agents are forced to relay + manual", () => {
  const c = base();
  c.agents.push({ ...newAgent(c, "relay"), invocation: "callable", launch_mode: "managed" });
  const a = normalize(c).agents[0];
  expect(a.invocation).toBe("relay");
  expect(a.launch_mode).toBe("manual");
});

test("hints catch missing role, overlapping ownership and helper without sponsor", () => {
  const c = base();
  const a = { ...newAgent(c), owns: [{ folder_id: "root", path: "src" }] };
  const b = { ...newAgent(c), id: "b", name: "B", role: "x", owns: [{ folder_id: "root", path: "src/ui" }] };
  const h = { ...newAgent(c), id: "h", name: "H", role: "x", log_duty: "helper" as const };
  c.agents.push(a, b, h);
  const msgs = hints(c).map((x) => x.message).join(" | ");
  expect(msgs).toMatch(/role is empty/);
  expect(msgs).toMatch(/overlap/);
  expect(msgs).toMatch(/helper needs a member as sponsor/);
});

test("toggleEdge adds then removes", () => {
  const e1 = toggleEdge([], "a", "b");
  expect(e1).toEqual([{ from_agent_id: "a", to_agent_id: "b" }]);
  expect(toggleEdge(e1, "a", "b")).toEqual([]);
});
