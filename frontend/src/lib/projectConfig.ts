// Pure helpers for editing a ProjectConfig in the UI. The backend is the authority on validity
// (schema + semantic rules); these helpers only keep the obvious invariants while the Owner edits
// and give early hints, so a 422 is the exception rather than the way to learn the rules.
import type { AgentConfig, ProjectConfig } from "../api/types";

export type PathRef = AgentConfig["owns"][number];
export type Level = ProjectConfig["levels"][number];
export type Folder = ProjectConfig["folders"][number];
export type CallEdge = ProjectConfig["call_policy"]["allowed_edges"][number];

export const ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;

/** Minimal valid config for a new project; the Owner fills it in with the editor. */
export function emptyConfig(id: string, name: string, root: string, timezone: string): ProjectConfig {
  return {
    schema_version: 1,
    project: { id, name, root, timezone, archived: false },
    folders: [{ id: "root", path: root }],
    logs: [{ id: "root", folder_id: "root", relative_path: ".handoff", members: [] }],
    levels: [],
    agents: [],
    call_policy: { mode: "independent", allowed_edges: [], subagents: "disabled", max_parallel: 2, max_chain_depth: 8, max_calls_per_chain: 32, run_timeout_seconds: 3600, paid_model_fallback: false },
    guard_policy: { mode: "guarded", protected_paths: [], merge_by: "owner", pushes: "owner", review_before_merge: true, leases_enabled: false },
    rituals: [],
    retention: { output_days: 7, event_days: 7, capture_output: true, copy_provider_transcripts: false },
    adapter_options: { claude: {}, codex: {}, opencode: {}, gemini: {} },
  };
}

/** "D:\x\" -> "D:/x"; the schema wants absolute local paths with forward slashes. */
export function normalizeRoot(input: string): string {
  const s = input.trim().replace(/\\/g, "/").replace(/\/+$/, "");
  return s.length === 2 && s[1] === ":" ? s + "/" : s;
}

export function slug(s: string): string {
  const out = s.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
  return out || "x";
}

/** "folder:path" per line <-> PathRef[]; a bare path uses the default folder. */
export function pathRefsToText(refs: PathRef[]): string {
  return refs.map((r) => `${r.folder_id}:${r.path}`).join("\n");
}

export function textToPathRefs(text: string, defaultFolder: string): PathRef[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const i = l.indexOf(":");
      // "D:/x" is a drive path, not folder:path; only treat the prefix as a folder when it is an id.
      if (i > 0 && ID_RE.test(l.slice(0, i)) && i !== 1) return { folder_id: l.slice(0, i), path: l.slice(i + 1).replace(/\\/g, "/") || "." };
      return { folder_id: defaultFolder, path: l.replace(/\\/g, "/") };
    });
}

export function newAgent(cfg: ProjectConfig, harness: AgentConfig["harness"] = "claude"): AgentConfig {
  const n = cfg.agents.length + 1;
  let id = `agent-${n}`;
  while (cfg.agents.some((a) => a.id === id)) id = `${id}x`;
  const relay = harness === "relay";
  return {
    id,
    name: `Agent ${n}`,
    level_id: cfg.levels[0]?.id ?? "",
    role: "",
    harness,
    model: harness === "claude" ? "claude-opus-5-5" : harness === "codex" ? "gpt-6-astra" : "",
    cwd_folder_id: cfg.folders[0]?.id ?? "root",
    owns: [],
    reads: [{ folder_id: cfg.folders[0]?.id ?? "root", path: "." }],
    log_ids: cfg.logs[0] ? [cfg.logs[0].id] : [],
    skills: ["agents-collaboration-protocol"],
    log_duty: "member",
    invocation: relay ? "relay" : "callable",
    launch_mode: relay ? "manual" : "managed",
    permission_profile: "default",
  };
}

/**
 * Invariants the schema enforces that are easy to keep automatically:
 *  - relay agents are invocation relay + manual launch;
 *  - helpers carry a sponsor and are not log members; members carry no sponsor;
 *  - log.members is derived from the members' log_ids (the schema requires them to agree);
 *  - call edges only reference existing agents and never a self-call.
 */
export function normalize(cfg: ProjectConfig): ProjectConfig {
  const agents = cfg.agents.map((a) => {
    const b: AgentConfig = { ...a };
    if (b.harness === "relay") { b.invocation = "relay"; b.launch_mode = "manual"; }
    else if (b.invocation === "relay") b.invocation = "callable";
    if (b.log_duty === "member") delete b.sponsor_agent_id;
    if (b.log_duty === "helper") b.log_ids = [];
    if (!b.effort) delete b.effort;
    if (b.prompt_file && !b.prompt_file.path) delete b.prompt_file;
    return b;
  });
  const ids = new Set(agents.map((a) => a.id));
  const logs = cfg.logs.map((l) => ({
    ...l,
    members: agents.filter((a) => a.log_duty === "member" && a.log_ids.includes(l.id)).map((a) => a.id),
  }));
  const seen = new Set<string>();
  const edges = cfg.call_policy.allowed_edges.filter((e) => {
    const k = `${e.from_agent_id}>${e.to_agent_id}`;
    if (seen.has(k) || e.from_agent_id === e.to_agent_id || !ids.has(e.from_agent_id) || !ids.has(e.to_agent_id)) return false;
    seen.add(k);
    return true;
  });
  return { ...cfg, agents, logs, call_policy: { ...cfg.call_policy, allowed_edges: edges } };
}

export interface Hint { where: string; message: string }

/** Early hints only; the backend's 422 details remain the authoritative list. */
export function hints(cfg: ProjectConfig): Hint[] {
  const out: Hint[] = [];
  const dup = (xs: string[]) => xs.filter((x, i) => xs.indexOf(x) !== i);
  for (const d of dup(cfg.folders.map((f) => f.id))) out.push({ where: "folders", message: `duplicate folder id ${d}` });
  for (const d of dup(cfg.levels.map((l) => l.id))) out.push({ where: "levels", message: `duplicate level id ${d}` });
  for (const d of dup(cfg.agents.map((a) => a.id))) out.push({ where: "agents", message: `duplicate agent id ${d}` });
  for (const d of dup(cfg.agents.map((a) => a.name))) out.push({ where: "agents", message: `duplicate agent name ${d}` });
  const folders = new Set(cfg.folders.map((f) => f.id));
  const levels = new Set(cfg.levels.map((l) => l.id));
  const logs = new Set(cfg.logs.map((l) => l.id));
  const members = new Set(cfg.agents.filter((a) => a.log_duty === "member").map((a) => a.id));
  for (const a of cfg.agents) {
    const w = `agent ${a.name}`;
    if (!ID_RE.test(a.id)) out.push({ where: w, message: `id "${a.id}" must be a slug` });
    if (!levels.has(a.level_id)) out.push({ where: w, message: "level is missing" });
    if (!folders.has(a.cwd_folder_id)) out.push({ where: w, message: "working folder is missing" });
    if (!a.role.trim()) out.push({ where: w, message: "role is empty (it becomes the generated prompt)" });
    if (!a.model.trim() && a.harness !== "relay") out.push({ where: w, message: "model is empty" });
    for (const r of [...a.owns, ...a.reads]) if (!folders.has(r.folder_id)) out.push({ where: w, message: `unknown folder ${r.folder_id} in ${r.path}` });
    for (const l of a.log_ids) if (!logs.has(l)) out.push({ where: w, message: `unknown log ${l}` });
    if (a.log_duty === "helper" && (!a.sponsor_agent_id || !members.has(a.sponsor_agent_id))) out.push({ where: w, message: "a helper needs a member as sponsor" });
    if (a.log_duty === "member" && a.log_ids.length === 0) out.push({ where: w, message: "a member should belong to at least one log" });
  }
  const owns = cfg.agents.flatMap((a) => a.owns.map((o) => ({ a: a.name, k: `${o.folder_id}:${o.path.replace(/\/+$/, "")}` })));
  for (let i = 0; i < owns.length; i++)
    for (let j = i + 1; j < owns.length; j++) {
      const x = owns[i], y = owns[j];
      if (x.a !== y.a && (x.k === y.k || x.k.startsWith(y.k + "/") || y.k.startsWith(x.k + "/") || x.k.endsWith(":.") || y.k.endsWith(":.")))
        out.push({ where: "ownership", message: `${x.a} and ${y.a} overlap at ${x.k} / ${y.k}` });
    }
  if (cfg.call_policy.mode === "independent" && cfg.call_policy.allowed_edges.length)
    out.push({ where: "call policy", message: "independent mode ignores call edges" });
  return out;
}

/** Levels of the reference arrangement: program lead, team leads, workers. */
export function referenceLevels(): Level[] {
  return [
    { id: "l1", label: "L1 - program", order: 0 },
    { id: "l2", label: "L2 - team leads", order: 1 },
    { id: "l3", label: "L3 - workers", order: 2 },
  ];
}

export function toggleEdge(edges: CallEdge[], from: string, to: string): CallEdge[] {
  const has = edges.some((e) => e.from_agent_id === from && e.to_agent_id === to);
  return has ? edges.filter((e) => !(e.from_agent_id === from && e.to_agent_id === to)) : [...edges, { from_agent_id: from, to_agent_id: to }];
}
