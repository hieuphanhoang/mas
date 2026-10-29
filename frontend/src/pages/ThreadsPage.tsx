import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useLogIndex, useLogs, useThread } from "../api/queries";
import type { HistoryRow, IndexSection, ThreadRef, ThreadSummary } from "../api/types";
import { Markdown } from "../lib/markdown";
import { ProjectPicker } from "../components/ProjectPicker";
import { Empty, ErrorNote, FreshnessNote, Loading, StatusPill, fmtTime } from "../components/ui";

const SECTIONS: { id: IndexSection; label: string }[] = [
  { id: "awaiting_owner", label: "Awaiting owner" },
  { id: "open", label: "Open" },
  { id: "history", label: "Conversation history" },
  { id: "all", label: "All" },
];

export function ThreadsPage() {
  const params = useParams();
  const nav = useNavigate();
  const projectId = params.projectId;
  const [logId, setLogId] = useState<string | undefined>(params.logId);
  const [section, setSection] = useState<IndexSection>("open");
  const logs = useLogs(projectId);
  const effectiveLog = logId ?? logs.data?.items[0]?.log_id;
  const index = useLogIndex(projectId, effectiveLog, section);
  const ref: ThreadRef | undefined = projectId && params.logId && params.threadId ? { project_id: projectId, log_id: params.logId, thread_id: params.threadId } : undefined;

  return (
    <section className="split">
      <aside className="split__side">
        <ProjectPicker value={projectId} onChange={(id) => nav(`/threads/${id}`)} />
        {logs.data && (
          <label className="field field--inline">
            <span className="muted">Log</span>
            <select value={effectiveLog ?? ""} onChange={(e) => setLogId(e.target.value)}>
              {logs.data.items.map((l) => <option key={l.log_id} value={l.log_id}>{l.log_id} ({l.folder_id})</option>)}
            </select>
          </label>
        )}
        <div className="tabs">
          {SECTIONS.map((s) => <button key={s.id} className={`tab ${section === s.id ? "tab--on" : ""}`} onClick={() => setSection(s.id)}>{s.label}</button>)}
        </div>
        <ErrorNote error={logs.error ?? index.error} />
        {index.isLoading && <Loading />}
        {index.data && <FreshnessNote f={index.data.log.freshness} />}
        {index.data && section === "history" && <History rows={index.data.items as HistoryRow[]} />}
        {index.data && section !== "history" && <ThreadList items={index.data.items as ThreadSummary[]} selected={ref} />}
      </aside>
      <div className="split__main">
        {ref ? <ThreadView r={ref} /> : <Empty>Select a thread.</Empty>}
      </div>
    </section>
  );
}

function ThreadList({ items, selected }: { items: ThreadSummary[]; selected?: ThreadRef }) {
  if (!items.length) return <Empty>Nothing here.</Empty>;
  return (
    <ul className="list">
      {items.map((t) => {
        const on = selected && selected.thread_id === t.thread_ref.thread_id && selected.log_id === t.thread_ref.log_id;
        return (
          <li key={`${t.thread_ref.log_id}/${t.thread_ref.thread_id}`} className={`list__item ${on ? "list__item--on" : ""}`}>
            <Link to={`/threads/${t.thread_ref.project_id}/${t.thread_ref.log_id}/${t.thread_ref.thread_id}`}>
              <div className="row row--between"><code>{t.thread_ref.thread_id}</code><StatusPill status={t.status} /></div>
              <div>{t.title ?? <span className="muted">(untitled)</span>}</div>
              <div className="muted small">{t.from_name} -&gt; {t.to_name}{t.owes_reply ? ` - owes: ${t.owes_reply}` : ""} - {fmtTime(t.updated_at)}</div>
              {t.parse_errors.length > 0 && <div className="small note--bad">{t.parse_errors.length} parse error(s)</div>}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function History({ rows }: { rows: HistoryRow[] }) {
  if (!rows.length) return <Empty>No history rows.</Empty>;
  return (
    <ol className="history">
      {rows.map((r, i) => (
        <li key={i}>
          <div className="row row--between"><strong>{r.speaker}</strong><span className="muted small">{r.time_text}</span></div>
          <div className="small">{r.threads.map((t) => <code key={t}>{t} </code>)}</div>
          <div>{r.summary}</div>
        </li>
      ))}
    </ol>
  );
}

export function ThreadView({ r }: { r: ThreadRef }) {
  const q = useThread(r);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorNote error={q.error} />;
  if (!q.data) return null;
  const m = q.data.metadata;
  return (
    <article>
      <div className="row row--between">
        <h1 className="h1"><code>{r.thread_id}</code> {m.title}</h1>
        <div className="row"><StatusPill status={m.status} /><FreshnessNote f={q.data.freshness} /></div>
      </div>
      <div className="muted small">{m.type} - {m.from_name} -&gt; {m.to_name} - updated {fmtTime(m.updated_at)} - revision <code>{m.revision}</code></div>
      {m.parse_errors.length > 0 && <ul className="note note--warn">{m.parse_errors.map((e, i) => <li key={i}>{e}</li>)}</ul>}
      <Markdown source={q.data.markdown} />
    </article>
  );
}
