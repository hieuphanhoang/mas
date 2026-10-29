import { useMemo, useState } from "react";
import { useCapabilities } from "../api/queries";
import type { AgentConfig, ProjectConfig } from "../api/types";
import {
  hints as computeHints,
  newAgent,
  normalize,
  normalizeRoot,
  pathRefsToText,
  referenceLevels,
  slug,
  textToPathRefs,
  toggleEdge,
} from "../lib/projectConfig";
import { ErrorNote, Pill } from "./ui";

type Tab = "general" | "folders" | "levels" | "agents" | "calls" | "json";
const TABS: { id: Tab; label: string }[] = [
  { id: "general", label: "General" },
  { id: "folders", label: "Folders and logs" },
  { id: "levels", label: "Levels" },
  { id: "agents", label: "Agents" },
  { id: "calls", label: "Call policy" },
  { id: "json", label: "JSON" },
];

const HARNESSES: AgentConfig["harness"][] = ["claude", "codex", "opencode", "gemini", "relay"];

export function ProjectEditor({ initial, onSave, onCancel, saving, error }: {
  initial: ProjectConfig;
  onSave: (cfg: ProjectConfig) => void;
  onCancel: () => void;
  saving: boolean;
  error: unknown;
}) {
  const [cfg, setCfg] = useState<ProjectConfig>(initial);
  const [tab, setTab] = useState<Tab>("agents");
  const [json, setJson] = useState<string | null>(null);
  const [jsonError, setJsonError] = useState<string | null>(null);
  const hints = useMemo(() => computeHints(normalize(cfg)), [cfg]);
  const set = (patch: Partial<ProjectConfig>) => setCfg((c) => ({ ...c, ...patch }));

  const switchTab = (t: Tab) => {
    if (tab === "json" && json !== null) {
      try { setCfg(JSON.parse(json) as ProjectConfig); setJsonError(null); setJson(null); }
      catch (e) { setJsonError((e as Error).message); return; }
    }
    if (t === "json") setJson(JSON.stringify(normalize(cfg), null, 2));
    setTab(t);
  };

  const save = () => {
    let next = cfg;
    if (tab === "json" && json !== null) {
      try { next = JSON.parse(json) as ProjectConfig; } catch (e) { setJsonError((e as Error).message); return; }
    }
    onSave(normalize(next));
  };

  return (
    <div className="editor-shell panel">
      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.id} type="button" className={`tab ${tab === t.id ? "tab--on" : ""}`} onClick={() => switchTab(t.id)}>
            {t.label}{t.id === "agents" ? ` (${cfg.agents.length})` : ""}
          </button>
        ))}
      </div>

      {tab === "general" && <General cfg={cfg} set={set} />}
      {tab === "folders" && <Folders cfg={cfg} set={set} />}
      {tab === "levels" && <Levels cfg={cfg} set={set} />}
      {tab === "agents" && <Agents cfg={cfg} set={set} />}
      {tab === "calls" && <Calls cfg={cfg} set={set} />}
      {tab === "json" && (
        <div className="form">
          <p className="muted small">Advanced: the exact document sent to the service. Switching tabs applies your edits.</p>
          <textarea className="editor" rows={28} spellCheck={false} value={json ?? ""} onChange={(e) => setJson(e.target.value)} />
          {jsonError && <div className="note note--bad">JSON: {jsonError}</div>}
        </div>
      )}

      {hints.length > 0 && (
        <details className="note note--warn small" open={hints.length <= 4}>
          <summary>{hints.length} thing(s) the service will likely reject</summary>
          <ul>{hints.map((h, i) => <li key={i}><strong>{h.where}:</strong> {h.message}</li>)}</ul>
        </details>
      )}
      <ErrorNote error={error} />
      <div className="row">
        <button type="button" className="btn btn--primary" onClick={save} disabled={saving}>Save draft</button>
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        <span className="muted small">Saving stores a draft revision only. Files are written after preview and apply.</span>
      </div>
    </div>
  );
}

type Sec = { cfg: ProjectConfig; set: (p: Partial<ProjectConfig>) => void };

function General({ cfg, set }: Sec) {
  const p = cfg.project;
  return (
    <div className="grid2">
      <label className="field"><span>Id</span><input value={p.id} disabled /><span className="muted small">Fixed after registration.</span></label>
      <label className="field"><span>Root</span><input value={p.root} disabled /><span className="muted small">Fixed after registration.</span></label>
      <label className="field"><span>Name</span><input value={p.name} onChange={(e) => set({ project: { ...p, name: e.target.value } })} /></label>
      <label className="field"><span>Timezone (IANA)</span><input value={p.timezone} onChange={(e) => set({ project: { ...p, timezone: e.target.value } })} /></label>
      <label className="field"><span>Captured output kept (days)</span>
        <input type="number" min={1} max={365} value={cfg.retention.output_days} onChange={(e) => set({ retention: { ...cfg.retention, output_days: Number(e.target.value) } })} />
      </label>
      <label className="field"><span>Events kept (days)</span>
        <input type="number" min={1} max={365} value={cfg.retention.event_days} onChange={(e) => set({ retention: { ...cfg.retention, event_days: Number(e.target.value) } })} />
      </label>
      <label className="field field--inline"><input type="checkbox" checked={cfg.retention.capture_output} onChange={(e) => set({ retention: { ...cfg.retention, capture_output: e.target.checked } })} /><span>Capture run output</span></label>
      <label className="field"><span>Guard mode</span>
        <select value={cfg.guard_policy.mode} onChange={(e) => set({ guard_policy: { ...cfg.guard_policy, mode: e.target.value as "advisory" | "guarded" } })}>
          <option value="guarded">guarded - block what the harness can check</option>
          <option value="advisory">advisory - warn only</option>
        </select>
        <span className="muted small">Workflow checks, not isolation; coverage per harness is on the capabilities list.</span>
      </label>
    </div>
  );
}

function Folders({ cfg, set }: Sec) {
  const [newPath, setNewPath] = useState("");
  const addFolder = () => {
    const path = normalizeRoot(newPath);
    if (!path) return;
    let id = slug(path.split("/").filter(Boolean).pop() ?? "folder");
    while (cfg.folders.some((f) => f.id === id)) id += "2";
    set({ folders: [...cfg.folders, { id, path }] });
    setNewPath("");
  };
  const hasLog = (fid: string) => cfg.logs.some((l) => l.folder_id === fid);
  const toggleLog = (fid: string) => {
    if (hasLog(fid)) {
      const removed = new Set(cfg.logs.filter((l) => l.folder_id === fid).map((l) => l.id));
      set({ logs: cfg.logs.filter((l) => l.folder_id !== fid), agents: cfg.agents.map((a) => ({ ...a, log_ids: a.log_ids.filter((x) => !removed.has(x)) })) });
    } else {
      let id = fid;
      while (cfg.logs.some((l) => l.id === id)) id += "-log";
      set({ logs: [...cfg.logs, { id, folder_id: fid, relative_path: ".handoff", members: [] }] });
    }
  };
  return (
    <div>
      <p className="muted small">Each working folder can have its own <code>.handoff</code> log (the reference system had one per team plus one at the root).</p>
      <table className="table">
        <thead><tr><th>Id</th><th>Path</th><th>Log</th><th></th></tr></thead>
        <tbody>
          {cfg.folders.map((f, i) => (
            <tr key={f.id}>
              <td><code>{f.id}</code></td>
              <td><code>{f.path}</code></td>
              <td><label className="row"><input type="checkbox" checked={hasLog(f.id)} onChange={() => toggleLog(f.id)} /> {cfg.logs.find((l) => l.folder_id === f.id)?.id ?? <span className="muted">none</span>}</label></td>
              <td>{i > 0 && <button type="button" className="linklike" onClick={() => set({ folders: cfg.folders.filter((x) => x.id !== f.id), logs: cfg.logs.filter((l) => l.folder_id !== f.id) })}>remove</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row">
        <input className="grow" value={newPath} onChange={(e) => setNewPath(e.target.value)} placeholder="D:\\project\\Requirements" />
        <button type="button" className="btn" onClick={addFolder}>Add folder</button>
      </div>
    </div>
  );
}

function Levels({ cfg, set }: Sec) {
  const sorted = cfg.levels.slice().sort((a, b) => a.order - b.order);
  const update = (id: string, label: string) => set({ levels: cfg.levels.map((l) => (l.id === id ? { ...l, label } : l)) });
  const move = (id: string, d: -1 | 1) => {
    const idx = sorted.findIndex((l) => l.id === id);
    const j = idx + d;
    if (j < 0 || j >= sorted.length) return;
    const re = sorted.slice();
    [re[idx], re[j]] = [re[j], re[idx]];
    set({ levels: re.map((l, i) => ({ ...l, order: i })) });
  };
  const add = () => {
    let id = `level-${cfg.levels.length + 1}`;
    while (cfg.levels.some((l) => l.id === id)) id += "x";
    set({ levels: [...cfg.levels, { id, label: `Level ${cfg.levels.length + 1}`, order: cfg.levels.length }] });
  };
  const used = (id: string) => cfg.agents.some((a) => a.level_id === id);
  return (
    <div>
      <p className="muted small">Levels are labels for grouping lanes; who may call whom is set separately under Call policy.</p>
      <table className="table">
        <thead><tr><th>Order</th><th>Label</th><th>Id</th><th>Agents</th><th></th></tr></thead>
        <tbody>
          {sorted.map((l, i) => (
            <tr key={l.id}>
              <td className="row"><button type="button" className="linklike" onClick={() => move(l.id, -1)} disabled={i === 0}>up</button><button type="button" className="linklike" onClick={() => move(l.id, 1)} disabled={i === sorted.length - 1}>down</button></td>
              <td><input value={l.label} onChange={(e) => update(l.id, e.target.value)} /></td>
              <td><code>{l.id}</code></td>
              <td>{cfg.agents.filter((a) => a.level_id === l.id).length}</td>
              <td>{!used(l.id) && <button type="button" className="linklike" onClick={() => set({ levels: cfg.levels.filter((x) => x.id !== l.id) })}>remove</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row">
        <button type="button" className="btn" onClick={add}>Add level</button>
        {cfg.levels.length === 0 && <button type="button" className="btn" onClick={() => set({ levels: referenceLevels() })}>Use the reference arrangement (L1 program, L2 leads, L3 workers)</button>}
      </div>
    </div>
  );
}

function Agents({ cfg, set }: Sec) {
  const [open, setOpen] = useState<string | null>(cfg.agents[0]?.id ?? null);
  const caps = useCapabilities();
  const replace = (id: string, a: AgentConfig) => {
    const agents = cfg.agents.map((x) => (x.id === id ? a : x));
    // an id rename must follow into edges and sponsors
    const ren = (x: string) => (x === id ? a.id : x);
    set({
      agents: agents.map((x) => (x.sponsor_agent_id ? { ...x, sponsor_agent_id: ren(x.sponsor_agent_id) } : x)),
      call_policy: { ...cfg.call_policy, allowed_edges: cfg.call_policy.allowed_edges.map((e) => ({ from_agent_id: ren(e.from_agent_id), to_agent_id: ren(e.to_agent_id) })) },
    });
    if (open === id) setOpen(a.id);
  };
  const remove = (id: string) => {
    set({
      agents: cfg.agents.filter((a) => a.id !== id).map((a) => (a.sponsor_agent_id === id ? { ...a, sponsor_agent_id: undefined } : a)),
      call_policy: { ...cfg.call_policy, allowed_edges: cfg.call_policy.allowed_edges.filter((e) => e.from_agent_id !== id && e.to_agent_id !== id) },
    });
  };
  const add = () => {
    const a = newAgent(cfg);
    set({ agents: [...cfg.agents, a] });
    setOpen(a.id);
  };
  const availability = (h: string) => caps.data?.adapters.find((x) => x.harness === h)?.availability;
  return (
    <div>
      {cfg.levels.length === 0 && <div className="note note--warn small">Add at least one level first (Levels tab).</div>}
      <ul className="list">
        {cfg.agents.map((a) => (
          <li key={a.id} className="list__item">
            <div className="row row--between">
              <button type="button" className="linklike row" onClick={() => setOpen(open === a.id ? null : a.id)}>
                <strong>{a.name}</strong>
                <span className="muted small">{a.harness} - {a.model || "no model"} - {cfg.levels.find((l) => l.id === a.level_id)?.label ?? "no level"} - {a.log_duty}</span>
                {availability(a.harness) && availability(a.harness) !== "available" && <Pill tone="off">{availability(a.harness)}</Pill>}
              </button>
              <button type="button" className="linklike small" onClick={() => remove(a.id)}>remove</button>
            </div>
            {open === a.id && <AgentForm cfg={cfg} a={a} onChange={(n) => replace(a.id, n)} profiles={caps.data?.permission_profiles ?? []} />}
          </li>
        ))}
      </ul>
      <button type="button" className="btn" onClick={add} disabled={cfg.levels.length === 0}>Add agent</button>
    </div>
  );
}

function AgentForm({ cfg, a, onChange, profiles }: {
  cfg: ProjectConfig;
  a: AgentConfig;
  onChange: (a: AgentConfig) => void;
  profiles: { id: string; harness: string; label: string; description: string }[];
}) {
  const [owns, setOwns] = useState(() => pathRefsToText(a.owns));
  const [reads, setReads] = useState(() => pathRefsToText(a.reads));
  const [skills, setSkills] = useState(() => a.skills.join(", "));
  const up = (p: Partial<AgentConfig>) => onChange({ ...a, ...p });
  const myProfiles = profiles.filter((p) => p.harness === a.harness);
  const members = cfg.agents.filter((x) => x.log_duty === "member" && x.id !== a.id);
  return (
    <div className="grid2 agent-form">
      <label className="field"><span>Name</span><input value={a.name} onChange={(e) => up({ name: e.target.value })} /></label>
      <label className="field"><span>Id</span><input value={a.id} onChange={(e) => up({ id: e.target.value })} pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,63}" /></label>
      <label className="field"><span>Level</span>
        <select value={a.level_id} onChange={(e) => up({ level_id: e.target.value })}>
          {cfg.levels.slice().sort((x, y) => x.order - y.order).map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
        </select>
      </label>
      <label className="field"><span>Harness</span>
        <select value={a.harness} onChange={(e) => {
          const h = e.target.value as AgentConfig["harness"];
          up({ harness: h, invocation: h === "relay" ? "relay" : a.invocation === "relay" ? "callable" : a.invocation, launch_mode: h === "relay" ? "manual" : a.launch_mode });
        }}>
          {HARNESSES.map((h) => <option key={h} value={h}>{h}{h === "gemini" ? " (planned)" : h === "opencode" ? " (next)" : ""}</option>)}
        </select>
      </label>
      <label className="field"><span>Model</span><input value={a.model} onChange={(e) => up({ model: e.target.value })} placeholder={a.harness === "claude" ? "claude-opus-5-5" : a.harness === "codex" ? "gpt-6-astra" : ""} /></label>
      <label className="field"><span>Effort</span><input value={a.effort ?? ""} onChange={(e) => up({ effort: e.target.value || undefined })} placeholder="high" /></label>
      <label className="field span2"><span>Role (becomes the generated prompt if no prompt file exists)</span>
        <textarea rows={3} value={a.role} onChange={(e) => up({ role: e.target.value })} />
      </label>
      <label className="field"><span>Working folder</span>
        <select value={a.cwd_folder_id} onChange={(e) => up({ cwd_folder_id: e.target.value })}>
          {cfg.folders.map((f) => <option key={f.id} value={f.id}>{f.id} - {f.path}</option>)}
        </select>
      </label>
      <label className="field"><span>Permission profile</span>
        {myProfiles.length ? (
          <select value={a.permission_profile} onChange={(e) => up({ permission_profile: e.target.value })}>
            {myProfiles.map((p) => <option key={p.id} value={p.id} title={p.description}>{p.label}</option>)}
          </select>
        ) : <input value={a.permission_profile} onChange={(e) => up({ permission_profile: e.target.value })} />}
        {myProfiles.find((p) => p.id === a.permission_profile) && <span className="muted small">{myProfiles.find((p) => p.id === a.permission_profile)!.description}</span>}
      </label>
      <label className="field"><span>Owns (one per line, folder:path)</span>
        <textarea rows={3} value={owns} onChange={(e) => setOwns(e.target.value)} onBlur={() => up({ owns: textToPathRefs(owns, a.cwd_folder_id) })} />
      </label>
      <label className="field"><span>Reads (one per line, folder:path)</span>
        <textarea rows={3} value={reads} onChange={(e) => setReads(e.target.value)} onBlur={() => up({ reads: textToPathRefs(reads, a.cwd_folder_id) })} />
      </label>
      <label className="field"><span>Duty</span>
        <select value={a.log_duty} onChange={(e) => up({ log_duty: e.target.value as AgentConfig["log_duty"] })}>
          <option value="member">member - writes its own log entries</option>
          <option value="helper">helper - one brief per call, a sponsor logs for it</option>
        </select>
      </label>
      {a.log_duty === "helper" ? (
        <label className="field"><span>Sponsor</span>
          <select value={a.sponsor_agent_id ?? ""} onChange={(e) => up({ sponsor_agent_id: e.target.value || undefined })}>
            <option value="">choose a member</option>
            {members.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </label>
      ) : (
        <fieldset className="field"><span>Logs</span>
          <div className="row">
            {cfg.logs.map((l) => (
              <label key={l.id} className="row"><input type="checkbox" checked={a.log_ids.includes(l.id)} onChange={(e) => up({ log_ids: e.target.checked ? [...a.log_ids, l.id] : a.log_ids.filter((x) => x !== l.id) })} /> {l.id}</label>
            ))}
          </div>
        </fieldset>
      )}
      <label className="field"><span>Who starts it</span>
        <select value={a.invocation} disabled={a.harness === "relay"} onChange={(e) => up({ invocation: e.target.value as AgentConfig["invocation"] })}>
          {a.harness === "relay" ? <option value="relay">relay (Owner pastes briefs)</option> : <>
            <option value="callable">callable by other agents</option>
            <option value="owner">Owner only</option>
          </>}
        </select>
      </label>
      <label className="field"><span>Launch</span>
        <select value={a.launch_mode} disabled={a.harness === "relay"} onChange={(e) => up({ launch_mode: e.target.value as AgentConfig["launch_mode"] })}>
          <option value="managed">managed by the service</option>
          <option value="manual">manual (the Owner runs it)</option>
        </select>
      </label>
      <label className="field span2"><span>Skills (comma separated)</span>
        <input value={skills} onChange={(e) => setSkills(e.target.value)} onBlur={() => up({ skills: skills.split(",").map((s) => s.trim()).filter(Boolean) })} />
      </label>
    </div>
  );
}

function Calls({ cfg, set }: Sec) {
  const cp = cfg.call_policy;
  const callable = cfg.agents.filter((a) => a.invocation === "callable");
  const has = (f: string, t: string) => cp.allowed_edges.some((e) => e.from_agent_id === f && e.to_agent_id === t);
  const num = (k: "max_parallel" | "max_chain_depth" | "max_calls_per_chain" | "run_timeout_seconds", v: string) => set({ call_policy: { ...cp, [k]: Number(v) } });
  return (
    <div className="form">
      <label className="field"><span>Mode</span>
        <select value={cp.mode} onChange={(e) => set({ call_policy: { ...cp, mode: e.target.value as typeof cp.mode } })}>
          <option value="independent">independent - only you start agents</option>
          <option value="orchestrated">orchestrated - agents may call the edges below</option>
          <option value="mixed">mixed - per agent, see "Who starts it"</option>
        </select>
      </label>
      {cp.mode !== "independent" && (
        <div>
          <div className="muted small">Row calls column. Only agents marked "callable by other agents" can be targets. Your own calls need no edge.</div>
          {cfg.agents.length === 0 ? <div className="muted">No agents yet.</div> : (
            <div className="matrix-wrap">
              <table className="table matrix">
                <thead><tr><th>caller \ target</th>{callable.map((t) => <th key={t.id}>{t.name}</th>)}</tr></thead>
                <tbody>
                  {cfg.agents.filter((a) => a.harness !== "relay").map((f) => (
                    <tr key={f.id}>
                      <th>{f.name}</th>
                      {callable.map((t) => (
                        <td key={t.id}>{f.id === t.id ? <span className="muted">-</span> : (
                          <input type="checkbox" aria-label={`${f.name} may call ${t.name}`} checked={has(f.id, t.id)} onChange={() => set({ call_policy: { ...cp, allowed_edges: toggleEdge(cp.allowed_edges, f.id, t.id) } })} />
                        )}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
      <div className="grid2">
        <label className="field"><span>Agents running at once in this project</span><input type="number" min={1} max={64} value={cp.max_parallel} onChange={(e) => num("max_parallel", e.target.value)} /></label>
        <label className="field"><span>Max call chain depth</span><input type="number" min={1} max={32} value={cp.max_chain_depth} onChange={(e) => num("max_chain_depth", e.target.value)} /></label>
        <label className="field"><span>Max calls per chain</span><input type="number" min={1} max={1000} value={cp.max_calls_per_chain} onChange={(e) => num("max_calls_per_chain", e.target.value)} /></label>
        <label className="field"><span>Run timeout (seconds)</span><input type="number" min={30} max={86400} value={cp.run_timeout_seconds} onChange={(e) => num("run_timeout_seconds", e.target.value)} /></label>
      </div>
      <div className="muted small">Fixed by your decisions: subagents disabled, no fallback to another paid model, merge and push stay yours.</div>
    </div>
  );
}
