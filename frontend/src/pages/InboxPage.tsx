import { useState } from "react";
import { Link } from "react-router-dom";
import { idempotencyKey } from "../api/client";
import { useAgents, useInbox, useReplyAsOwner, useThread } from "../api/queries";
import { threadKey, type ThreadRef, type ThreadSummary } from "../api/types";
import { Markdown } from "../lib/markdown";
import { Empty, ErrorNote, FreshnessNote, Loading, StatusPill, fmtTime, Pill } from "../components/ui";

export function InboxPage() {
  const q = useInbox();
  const [selected, setSelected] = useState<ThreadRef | null>(null);
  return (
    <section className="split">
      <aside className="split__side">
        <h1 className="h1">Awaiting you</h1>
        <ErrorNote error={q.error} />
        {q.isLoading && <Loading />}
        {q.data && q.data.items.length === 0 && <Empty>Nothing is waiting on you.</Empty>}
        {q.data && (
          <ul className="list">
            {q.data.items.map((t) => (
              <li key={`${t.thread_ref.project_id}/${t.thread_ref.log_id}/${t.thread_ref.thread_id}`} className={`list__item ${selected && sameRef(selected, t.thread_ref) ? "list__item--on" : ""}`}>
                <button className="linklike" onClick={() => setSelected(t.thread_ref)}>
                  <div className="row row--between"><code>{t.thread_ref.project_id}/{t.thread_ref.log_id}/{t.thread_ref.thread_id}</code><StatusPill status={t.status} /></div>
                  <div>{t.title}</div>
                  <div className="muted small">from {t.from_name} - since {fmtTime(t.updated_at)}</div>
                </button>
              </li>
            ))}
          </ul>
        )}
        {q.data && q.data.sources.some((s) => s.freshness.state !== "current") && (
          <div className="note note--warn small">
            Some logs could not be read; an empty list does not mean nothing is waiting:
            <ul>{q.data.sources.filter((s) => s.freshness.state !== "current").map((s) => <li key={`${s.project_id}/${s.log_id}`}><code>{s.project_id}/{s.log_id}</code> <FreshnessNote f={s.freshness} /></li>)}</ul>
          </div>
        )}
      </aside>
      <div className="split__main">
        {/* key = full thread identity: a draft or wake choice must never carry over to another ASK (AGENT-005 #1) */}
        {selected ? <AnswerPane key={threadKey(selected)} r={selected} summary={q.data?.items.find((t) => sameRef(t.thread_ref, selected))} /> : <Empty>Select a question to answer it. Your words are written verbatim into the thread as the Owner.</Empty>}
      </div>
    </section>
  );
}

const sameRef = (a: ThreadRef, b: ThreadRef) => a.project_id === b.project_id && a.log_id === b.log_id && a.thread_id === b.thread_id;

function AnswerPane({ r, summary }: { r: ThreadRef; summary?: ThreadSummary }) {
  const thread = useThread(r);
  const agents = useAgents(r.project_id);
  const reply = useReplyAsOwner();
  const [body, setBody] = useState("");
  const [wake, setWake] = useState<string>("");
  const [key, setKey] = useState(() => idempotencyKey());

  const send = (e: React.FormEvent) => {
    e.preventDefault();
    if (!thread.data) return;
    reply.mutate(
      { ref: r, key, body: { body, expected_revision: thread.data.metadata.revision, ...(wake ? { wake_agent_id: wake } : {}) } },
      { onSuccess: () => { setBody(""); setKey(idempotencyKey()); } },
    );
  };

  const asker = summary?.from_name ?? thread.data?.metadata.from_name;
  const askerAgent = agents.data?.items.find((a) => a.config.name === asker);

  return (
    <article>
      <div className="row row--between">
        <h1 className="h1"><code>{r.thread_id}</code> {thread.data?.metadata.title}</h1>
        <Link className="btn" to={`/threads/${r.project_id}/${r.log_id}/${r.thread_id}`}>Open in Threads</Link>
      </div>
      {thread.isLoading && <Loading />}
      <ErrorNote error={thread.error} />
      {thread.data && <div className="scroll"><Markdown source={thread.data.markdown} /></div>}
      <form className="form panel" onSubmit={send}>
        <label className="field">
          <span>Your answer (written verbatim as <code>[Owner, ...]</code>)</span>
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={6} required placeholder='Short answers are fine. "ok" is a decision.' />
        </label>
        <label className="field field--inline">
          <span>Then wake</span>
          <select value={wake} onChange={(e) => setWake(e.target.value)}>
            <option value="">nobody</option>
            {agents.data?.items.filter((a) => a.config.log_duty === "member").map((a) => <option key={a.config.id} value={a.config.id}>{a.config.name}{askerAgent?.config.id === a.config.id ? " (asked)" : ""}</option>)}
          </select>
        </label>
        <ErrorNote error={reply.error} />
        {reply.data && (
          <div className="note note--ok">
            Recorded at {fmtTime(reply.data.stamped_at)}. Sync <Pill tone={reply.data.sync_state === "synced" ? "ok" : "warn"}>{reply.data.sync_state}</Pill>
            {" "}wake <Pill tone={reply.data.wake_state === "failed" ? "bad" : "info"}>{reply.data.wake_state}</Pill>
            {reply.data.reason ? <span className="muted"> {reply.data.reason}</span> : null}
          </div>
        )}
        <div className="row"><button className="btn btn--primary" disabled={!thread.data || reply.isPending}>Send answer</button></div>
      </form>
    </article>
  );
}
