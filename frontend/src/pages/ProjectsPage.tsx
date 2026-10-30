import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useApplyProject, useCreateProject, usePreviewProject, useProject, useProjects, useUpdateProject } from "../api/queries";
import { idempotencyKey } from "../api/client";
import type { Preview, ProjectConfig } from "../api/types";
import { Empty, ErrorNote, Loading, Pill } from "../components/ui";
import { ProjectEditor } from "../components/ProjectEditor";
import { emptyConfig, normalizeRoot } from "../lib/projectConfig";

export function ProjectsPage() {
  const { projectId } = useParams();
  if (projectId === "new") return <RegisterProject />;
  if (projectId) return <ProjectDetail id={projectId} />;
  return <ProjectList />;
}

function ProjectList() {
  const q = useProjects();
  return (
    <section>
      <div className="row row--between">
        <h1 className="h1">Projects</h1>
        <Link className="btn" to="/projects/new">Register project</Link>
      </div>
      <ErrorNote error={q.error} />
      {q.isLoading && <Loading />}
      {q.data && q.data.items.length === 0 && <Empty>No project registered yet. Register one to start; nothing is written to disk until you apply.</Empty>}
      {q.data && q.data.items.length > 0 && (
        <table className="table">
          <thead><tr><th>Name</th><th>Id</th><th>Root</th><th>Files</th><th>Agents</th><th>Running</th><th></th></tr></thead>
          <tbody>
            {q.data.items.map((p) => (
              <tr key={p.project_id}>
                <td><Link to={`/projects/${p.project_id}`}>{p.name}</Link></td>
                <td><code>{p.project_id}</code></td>
                <td><code>{p.root}</code></td>
                <td><ScaffoldPill state={p.scaffold_state} /></td>
                <td>{p.agent_count}</td>
                <td>{p.active_run_count}</td>
                <td className="row">
                  <Link to={`/agents/${p.project_id}`}>Agents</Link>
                  <Link to={`/threads/${p.project_id}`}>Threads</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function ScaffoldPill({ state }: { state: "draft" | "applied" | "conflict" | "apply_failed" }) {
  const tone = state === "applied" ? "ok" : state === "draft" ? "info" : "bad";
  return <Pill tone={tone}>{state}</Pill>;
}

function RegisterProject() {
  const nav = useNavigate();
  const create = useCreateProject();
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [root, setRoot] = useState("");
  const [tz, setTz] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [key] = useState(() => idempotencyKey());
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    create.mutate({ config: emptyConfig(id.trim(), name.trim(), normalizeRoot(root), tz.trim()), key }, { onSuccess: (r) => nav(`/projects/${r.config.project.id}`) });
  };
  return (
    <section className="narrow">
      <h1 className="h1">Register a project</h1>
      <p className="muted">Registration stores a draft in the service only. Agents, levels and policies are edited on the project page; files are written only when you preview and apply.</p>
      <form onSubmit={submit} className="form">
        <label className="field"><span>Id (slug)</span><input value={id} onChange={(e) => setId(e.target.value)} pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,63}" required placeholder="my-project" /></label>
        <label className="field"><span>Name</span><input value={name} onChange={(e) => setName(e.target.value)} required /></label>
        <label className="field"><span>Root folder</span><input value={root} onChange={(e) => setRoot(e.target.value)} required placeholder="D:\\projects\\x" /><span className="muted">Local drive only; backslashes are normalised.</span></label>
        <label className="field"><span>Timezone</span><input value={tz} onChange={(e) => setTz(e.target.value)} required /></label>
        <ErrorNote error={create.error} />
        <div className="row"><button className="btn btn--primary" disabled={create.isPending}>Register</button><Link className="btn" to="/projects">Cancel</Link></div>
      </form>
    </section>
  );
}

function ProjectDetail({ id }: { id: string }) {
  const q = useProject(id);
  const update = useUpdateProject(id);
  const preview = usePreviewProject(id);
  const apply = useApplyProject(id);
  const [editing, setEditing] = useState(false);
  const [pv, setPv] = useState<Preview | null>(null);

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorNote error={q.error} />;
  if (!q.data) return null;
  const rec = q.data;
  const cfg = rec.config;

  const startEdit = () => { update.reset(); setPv(null); setEditing(true); };
  const save = (next: ProjectConfig) => {
    update.mutate({ config: next, etag: rec.etag, key: idempotencyKey() }, { onSuccess: () => setEditing(false) });
  };
  const runPreview = () => preview.mutate({ etag: rec.etag, key: idempotencyKey() }, { onSuccess: setPv });
  const runApply = () => pv && apply.mutate({ previewId: pv.preview_id, etag: rec.etag, key: idempotencyKey() }, { onSuccess: () => setPv(null) });

  return (
    <section>
      <div className="row row--between">
        <h1 className="h1">{cfg.project.name} <span className="muted">({cfg.project.id})</span></h1>
        <div className="row">
          <ScaffoldPill state={rec.scaffold_state} />
          <Link className="btn" to={`/agents/${id}`}>Agents</Link>
          <Link className="btn" to={`/threads/${id}`}>Threads</Link>
        </div>
      </div>
      <dl className="facts">
        <dt>Root</dt><dd><code>{cfg.project.root}</code></dd>
        <dt>Timezone</dt><dd>{cfg.project.timezone}</dd>
        <dt>Mode</dt><dd>{cfg.call_policy.mode}, max {cfg.call_policy.max_parallel} parallel</dd>
        <dt>Revision</dt><dd><code>{rec.revision}</code>{rec.applied_revision ? <> applied <code>{rec.applied_revision}</code></> : <span className="muted"> never applied</span>}</dd>
      </dl>

      <h2 className="h2">Agents ({cfg.agents.length})</h2>
      {cfg.agents.length === 0 ? <Empty>No agents yet. Edit the configuration to add levels and agents.</Empty> : (
        <table className="table">
          <thead><tr><th>Name</th><th>Level</th><th>Harness</th><th>Model</th><th>Duty</th><th>Invocation</th><th>Owns</th></tr></thead>
          <tbody>
            {cfg.agents.map((a) => (
              <tr key={a.id}>
                <td>{a.name} <code className="muted">{a.id}</code></td>
                <td>{cfg.levels.find((l) => l.id === a.level_id)?.label ?? a.level_id}</td>
                <td>{a.harness}</td><td>{a.model}{a.effort ? ` (${a.effort})` : ""}</td><td>{a.log_duty}</td><td>{a.invocation}</td>
                <td>{a.owns.map((o) => `${o.folder_id}:${o.path}`).join(", ") || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2 className="h2">Configuration</h2>
      {!editing ? (
        <div className="row">
          <button className="btn" onClick={startEdit}>Edit project</button>
          <button className="btn" onClick={runPreview} disabled={preview.isPending}>Preview generated files</button>
        </div>
      ) : (
        <ProjectEditor key={rec.revision} initial={cfg} onSave={save} onCancel={() => setEditing(false)} saving={update.isPending} error={update.error} />
      )}
      <ErrorNote error={preview.error} />
      <ErrorNote error={apply.error} />
      {pv && <PreviewView pv={pv} onApply={runApply} applying={apply.isPending} onDiscard={() => setPv(null)} />}
    </section>
  );
}

function PreviewView({ pv, onApply, applying, onDiscard }: { pv: Preview; onApply: () => void; applying: boolean; onDiscard: () => void }) {
  return (
    <div className="panel">
      <div className="row row--between">
        <strong>Preview {pv.preview_id}</strong>
        <span className="muted">expires {new Date(pv.expires_at).toLocaleTimeString()}</span>
      </div>
      {pv.warnings.length > 0 && <ul className="note note--warn">{pv.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
      <table className="table">
        <thead><tr><th>File</th><th>Action</th><th>Conflict</th></tr></thead>
        <tbody>
          {pv.changes.map((c, i) => (
            <tr key={i}>
              <td><code>{c.path.folder_id}:{c.path.path}</code></td>
              <td><Pill tone={c.action === "conflict" ? "bad" : c.action === "unchanged" ? "off" : "info"}>{c.action}</Pill></td>
              <td>{c.conflict_reason ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {pv.changes.filter((c) => c.diff).map((c, i) => (
        <details key={i}><summary><code>{c.path.path}</code></summary><pre className="md__code"><code>{c.diff}</code></pre></details>
      ))}
      <div className="row">
        <button className="btn btn--primary" onClick={onApply} disabled={!pv.can_apply || applying}>Apply these changes</button>
        <button className="btn" onClick={onDiscard}>Discard preview</button>
      </div>
    </div>
  );
}
