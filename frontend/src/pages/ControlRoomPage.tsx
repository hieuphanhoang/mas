import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { idempotencyKey } from "../api/client";
import { useAgentAction, useAgents, useCalls, useLogIndex, useLogs, useProject, useRunOutput } from "../api/queries";
import { textToPathRefs } from "../lib/projectConfig";
import type { AgentStatus, AgentView, Delivery, ThreadRef } from "../api/types";
import { useProjectEvents } from "../api/useProjectEvents";
import { ProjectPicker } from "../components/ProjectPicker";
import { Empty, ErrorNote, Loading, Pill, fmtTime } from "../components/ui";

export function ControlRoomPage() {
  const { projectId } = useParams();
  const nav = useNavigate();
  const project = useProject(projectId);
  const agents = useAgents(projectId);
  const stream = useProjectEvents(projectId, agents.data?.event_cursor, agents.dataUpdatedAt);
  const [selected, setSelected] = useState<string | null>(null);
  const [level, setLevel] = useState<string>("all");

  const levels = useMemo(() => (project.data?.config.levels ?? []).slice().sort((a, b) => a.order - b.order), [project.data]);
  const lanes = useMemo(() => {
    const items = agents.data?.items ?? [];
    return level === "all" ? items : items.filter((a) => a.config.level_id === level);
  }, [agents.data, level]);
  const selectedAgent = agents.data?.items.find((a) => a.config.id === selected) ?? null;

  return (
    <section className="room">
      <div className="row row--between">
        <div className="row">
          <ProjectPicker value={projectId} onChange={(id) => nav(`/room/${id}`)} />
          <div className="tabs">
            <button className={`tab ${level === "all" ? "tab--on" : ""}`} onClick={() => setLevel("all")}>All</button>
            {levels.map((l) => <button key={l.id} className={`tab ${level === l.id ? "tab--on" : ""}`} onClick={() => setLevel(l.id)}>{l.label}</button>)}
          </div>
        </div>
        <StreamPill state={stream.state} reason={stream.resetReason} />
      </div>
      <ErrorNote error={project.error ?? agents.error} />
      {agents.isLoading && <Loading />}
      {agents.data && lanes.length === 0 && <Empty>No agents in this project yet. Add levels and agents on the <Link to={`/projects/${projectId}`}>project page</Link>.</Empty>}
      <div className={`room__grid ${selectedAgent ? "room__grid--drawer" : ""}`}>
        <div className="lanes">
          {levels.filter((l) => level === "all" || l.id === level).map((l) => (
            <div key={l.id} className="level">
              <div className="level__label muted">{l.label}</div>
              {lanes.filter((a) => a.config.level_id === l.id).map((a) => (
                <Lane key={a.config.id} a={a} on={selected === a.config.id} onSelect={() => setSelected(a.config.id)} />
              ))}
            </div>
          ))}
          {lanes.filter((a) => !levels.some((l) => l.id === a.config.level_id)).map((a) => (
            <Lane key={a.config.id} a={a} on={selected === a.config.id} onSelect={() => setSelected(a.config.id)} />
          ))}
        </div>
        {/* key = project + agent: drafts, conversation thread and call form never carry over to another agent (AGENT-005 #2) */}
        {selectedAgent && projectId && <Drawer key={`${projectId}/${selectedAgent.config.id}`} projectId={projectId} a={selectedAgent} onClose={() => setSelected(null)} />}
      </div>
    </section>
  );
}

function StreamPill({ state, reason }: { state: string; reason: string | null }) {
  const tone = state === "open" ? "ok" : state === "connecting" ? "warn" : state === "reset" ? "bad" : "off";
  return <Pill tone={tone}>live: {state}{reason ? ` (${reason})` : ""}</Pill>;
}

export function lampTone(s: AgentStatus["state"]): "ok" | "warn" | "bad" | "off" | "info" {
  switch (s) {
    case "idle": return "ok";
    case "busy": case "starting": case "stopping": return "warn";
    case "needs_input": case "error": return "bad";
    case "unknown": return "info";
    default: return "off";
  }
}

function Lane({ a, on, onSelect }: { a: AgentView; on: boolean; onSelect: () => void }) {
  const s = a.status;
  return (
    <button className={`lane ${on ? "lane--on" : ""}`} onClick={onSelect}>
      <span className={`lamp lamp--${lampTone(s.state)}`} title={s.state} />
      <span className="lane__name">{a.config.name}</span>
      <span className="lane__meta muted small">{a.config.harness} - {a.config.model}{a.config.effort ? ` (${a.config.effort})` : ""}</span>
      <span className="lane__state">
        <Pill tone={lampTone(s.state)}>{s.state}</Pill>
        {s.queue_length > 0 && <Pill tone="info">queue {s.queue_length}</Pill>}
        {s.queue_paused && <Pill tone="warn">paused</Pill>}
        {s.session_generation != null && <span className="muted small">gen {s.session_generation}</span>}
        {a.capabilities.availability !== "available" && <Pill tone="off">{a.capabilities.availability}</Pill>}
      </span>
      <span className="lane__reason small">{s.reason ?? ""}</span>
    </button>
  );
}

function Drawer({ projectId, a, onClose }: { projectId: string; a: AgentView; onClose: () => void }) {
  const act = useAgentAction(projectId);
  const calls = useCalls(projectId, a.config.id);
  const logs = useLogs(projectId);
  const [tab, setTab] = useState<"runs" | "call" | "chat" | "output">("runs");
  const [text, setText] = useState("");
  const [threadRef, setThreadRef] = useState<ThreadRef | null>(null);
  const [logId, setLogId] = useState<string>("");
  const [runId, setRunId] = useState<string | null>(null);
  const s = a.status;
  const member = a.config.log_duty === "member";
  const effectiveLog = logId || a.config.log_ids[0] || logs.data?.items[0]?.log_id || "";

  const sendChat = (e: React.FormEvent) => {
    e.preventDefault();
    const body = threadRef ? { text, thread_ref: threadRef } : { text, log_id: effectiveLog };
    act.message.mutate({ agent: a.config.id, body, key: idempotencyKey() }, {
      onSuccess: (d) => { setText(""); if (d.thread_ref && !threadRef) setThreadRef(d.thread_ref); },
    });
  };

  return (
    <aside className="drawer">
      <div className="row row--between">
        <h2 className="h1" style={{ margin: 0 }}>{a.config.name}</h2>
        <button className="btn btn--ghost" onClick={onClose} aria-label="Close">x</button>
      </div>
      <div className="muted small">{a.config.role}</div>
      <div className="row">
        <Pill tone={lampTone(s.state)}>{s.state}</Pill>
        <span className="muted small">observed {fmtTime(s.observed_at)} via {s.source}</span>
      </div>
      {s.reason && <div className="note small">{s.reason}</div>}
      <div className="row">
        <button className="btn" disabled={!member || act.wake.isPending} onClick={() => act.wake.mutate({ agent: a.config.id, key: idempotencyKey() })}>Wake up</button>
        <button className="btn" disabled={act.stop.isPending} onClick={() => act.stop.mutate({ agent: a.config.id, key: idempotencyKey() })}>Stop</button>
        {s.queue_paused && <button className="btn" disabled={act.resumeQueue.isPending} onClick={() => act.resumeQueue.mutate({ agent: a.config.id, key: idempotencyKey() })}>Resume queue</button>}
      </div>
      <ErrorNote error={act.wake.error ?? act.stop.error ?? act.resumeQueue.error} />
      <div className="tabs">
        {(["runs", "call", "chat", "output"] as const).map((t) => <button key={t} className={`tab ${tab === t ? "tab--on" : ""}`} onClick={() => setTab(t)}>{t}</button>)}
      </div>

      {tab === "call" && <CallForm projectId={projectId} a={a} onSent={() => setTab("runs")} />}

      {tab === "runs" && (
        <div>
          <ErrorNote error={calls.error} />
          {calls.data && calls.data.items.length === 0 && <Empty>No deliveries yet.</Empty>}
          {calls.data && calls.data.items.length > 0 && (
            <table className="table small">
              <thead><tr><th>When</th><th>Kind</th><th>State</th><th>Thread</th><th></th></tr></thead>
              <tbody>
                {calls.data.items.map((d: Delivery) => (
                  <tr key={d.delivery_id}>
                    <td>{fmtTime(d.created_at)}</td>
                    <td>{d.purpose === "notification" ? "notify" : d.kind}</td>
                    <td><DeliveryState d={d} />{d.reason ? <div className="muted">{d.reason}</div> : null}</td>
                    <td>{d.thread_ref ? <Link to={`/threads/${d.thread_ref.project_id}/${d.thread_ref.log_id}/${d.thread_ref.thread_id}`}>{d.thread_ref.thread_id}</Link> : "-"}</td>
                    <td className="row">
                      {d.run_id && <button className="linklike" onClick={() => { setRunId(d.run_id); setTab("output"); }}>output</button>}
                      {(d.state === "queued" || d.state === "running" || d.state === "dispatching") && <button className="linklike" onClick={() => act.cancel.mutate({ call: d.delivery_id, key: idempotencyKey() })}>cancel</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "chat" && (
        <form className="form" onSubmit={sendChat}>
          {!member ? <Empty>Helpers take a brief through a call, not chat.</Empty> : (
            <>
              <div className="muted small">
                {threadRef ? <>Conversation thread <code>{threadRef.log_id}/{threadRef.thread_id}</code> <button type="button" className="linklike" onClick={() => setThreadRef(null)}>(start a new one)</button></> : (
                  <label className="field field--inline"><span>New thread in log</span>
                    <select value={effectiveLog} onChange={(e) => setLogId(e.target.value)}>
                      {(logs.data?.items ?? []).map((l) => <option key={l.log_id} value={l.log_id}>{l.log_id}</option>)}
                    </select>
                  </label>
                )}
              </div>
              <textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} required placeholder="Your words are written verbatim into the thread and become the agent's next turn (queued if busy)." />
              <ErrorNote error={act.message.error} />
              <div className="row"><button className="btn btn--primary" disabled={act.message.isPending || !effectiveLog}>Send</button></div>
            </>
          )}
        </form>
      )}

      {tab === "output" && (runId ? <OutputPane key={runId} projectId={projectId} runId={runId} /> : <Empty>Pick a run in the runs tab.</Empty>)}
    </aside>
  );
}

/** Owner call: a member is called about an existing thread (thread first); a helper gets a brief file. */
function CallForm({ projectId, a, onSent }: { projectId: string; a: AgentView; onSent: () => void }) {
  const act = useAgentAction(projectId);
  const member = a.config.log_duty === "member";
  const [logId, setLogId] = useState(a.config.log_ids[0] ?? "");
  const index = useLogIndex(projectId, member ? logId : undefined, "open");
  const [threadId, setThreadId] = useState("");
  const [brief, setBrief] = useState("");
  const [note, setNote] = useState("");
  const threads = (index.data?.items ?? []) as { thread_ref: ThreadRef; title: string | null; owes_reply: string | null }[];
  const owed = threads.filter((t) => (t.owes_reply ?? "").split(",").map((s) => s.trim()).includes(a.config.name));
  const others = threads.filter((t) => !owed.includes(t));

  const send = (e: React.FormEvent) => {
    e.preventDefault();
    const body = member
      ? { thread_ref: { project_id: projectId, log_id: logId, thread_id: threadId }, note }
      : { brief: textToPathRefs(brief, a.config.cwd_folder_id)[0], note };
    act.call.mutate({ agent: a.config.id, body, key: idempotencyKey() }, { onSuccess: onSent });
  };

  return (
    <form className="form" onSubmit={send}>
      {member ? (
        <>
          <div className="muted small">Thread first: the agent is pointed at the thread and answers there. Open a new thread from the chat tab if none fits.</div>
          <label className="field field--inline"><span>Log</span>
            <select value={logId} onChange={(e) => { setLogId(e.target.value); setThreadId(""); }}>
              {a.config.log_ids.map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
          </label>
          <label className="field"><span>Thread</span>
            <select value={threadId} onChange={(e) => setThreadId(e.target.value)} required>
              <option value="">choose an open thread</option>
              {owed.length > 0 && <optgroup label={`${a.config.name} owes a reply`}>{owed.map((t) => <option key={t.thread_ref.thread_id} value={t.thread_ref.thread_id}>{t.thread_ref.thread_id} {t.title}</option>)}</optgroup>}
              {others.length > 0 && <optgroup label="other open threads">{others.map((t) => <option key={t.thread_ref.thread_id} value={t.thread_ref.thread_id}>{t.thread_ref.thread_id} {t.title}</option>)}</optgroup>}
            </select>
          </label>
          <ErrorNote error={index.error} />
        </>
      ) : (
        <label className="field"><span>Brief file (folder:path)</span><input value={brief} onChange={(e) => setBrief(e.target.value)} required placeholder={`${a.config.cwd_folder_id}:.agents/briefs/task.md`} /></label>
      )}
      <label className="field"><span>Note (one sentence, optional)</span><input value={note} onChange={(e) => setNote(e.target.value)} maxLength={4000} /></label>
      <ErrorNote error={act.call.error} />
      <div className="row"><button className="btn btn--primary" disabled={act.call.isPending}>Call {a.config.name}</button></div>
    </form>
  );
}

/** Contract 0.2.0: a completed notification only means the turn finished, so it is shown as a
 *  neutral "notified", never as a green success. Every other notification outcome keeps its real
 *  state and colour, exactly like a task. */
export function DeliveryState({ d }: { d: Pick<Delivery, "purpose" | "state"> }) {
  if (d.purpose === "notification" && d.state === "completed") {
    return <span title="The agent's turn finished. This does not claim the answer was acted on."><Pill tone="off">notified</Pill></span>;
  }
  return <Pill tone={deliveryTone(d.state)}>{d.state}</Pill>;
}

function deliveryTone(s: Delivery["state"]): "ok" | "warn" | "bad" | "off" | "info" {
  switch (s) {
    case "completed": return "ok";
    case "queued": case "dispatching": case "running": return "warn";
    case "failed": case "uncertain": return "bad";
    case "awaiting_manual": return "info";
    default: return "off";
  }
}

/** Read-only run output. Polls while the run is not at eof (the query refetches on an interval,
 *  also when caught up), appends each chunk once, and advances the offset by itself (AGENT-005 #3). */
export function OutputPane({ projectId, runId }: { projectId: string; runId: string }) {
  const [offset, setOffset] = useState("0");
  const [text, setText] = useState("");
  const appended = useRef<bigint>(-1n);
  const q = useRunOutput(projectId, runId, offset);
  useEffect(() => {
    const d = q.data;
    if (!d) return;
    const fresh = d.chunks.filter((c) => BigInt(c.offset) > appended.current);
    if (fresh.length) {
      appended.current = BigInt(fresh[fresh.length - 1].offset);
      setText((t) => t + fresh.map((c) => (c.stream === "stderr" ? `! ${c.text}` : c.text)).join(""));
    }
    if (d.next_offset !== offset) setOffset(d.next_offset);
  }, [q.data, offset]);
  const eof = q.data?.eof ?? false;
  return (
    <div>
      <div className="row row--between small muted"><span>run <code>{runId}</code></span>{q.data && <span>{eof ? "finished" : "running"}</span>}</div>
      <ErrorNote error={q.error} />
      <pre className="md__code output" data-testid="run-output">{text}</pre>
    </div>
  );
}
