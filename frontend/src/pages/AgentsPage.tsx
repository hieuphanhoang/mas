import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { idempotencyKey, post } from "../api/client";
import { useAgentAction, useAgents, useCalls, useLogIndex, useLogs, useProject, useRunOutput, useThread } from "../api/queries";
import { useMutation } from "@tanstack/react-query";
import { textToPathRefs } from "../lib/projectConfig";
import { resumeCommand } from "../lib/resume";
import { callerLabel, runDuration } from "../lib/history";
import { Markdown } from "../lib/markdown";
import type { AgentStatus, AgentView, Delivery, ResumeWindowReceipt, ThreadRef, ThreadSummary } from "../api/types";
import { useProjectEvents } from "../api/useProjectEvents";
import { ProjectPicker } from "../components/ProjectPicker";
import { Empty, ErrorNote, Loading, Pill, fmtTime } from "../components/ui";
import { Glyph, Icon, type Harness } from "../components/icons";

// Agent panel width: dragged by the Owner, remembered in this browser only.
const DRAWER_KEY = "mas.drawerWidth";
const DRAWER_DEFAULT = 460;
const DRAWER_MIN = 340;
export const clampDrawer = (w: number, viewport: number) => Math.round(Math.max(DRAWER_MIN, Math.min(w, viewport - 420)));

function useDrawerWidth() {
  const [w, setW] = useState(() => {
    try { return Number(localStorage.getItem(DRAWER_KEY)) || DRAWER_DEFAULT; } catch { return DRAWER_DEFAULT; }
  });
  useEffect(() => { try { localStorage.setItem(DRAWER_KEY, String(w)); } catch { /* storage blocked */ } }, [w]);
  return [w, (next: number) => setW(clampDrawer(next, window.innerWidth))] as const;
}

export function AgentsPage() {
  const { projectId } = useParams();
  const nav = useNavigate();
  const project = useProject(projectId);
  const agents = useAgents(projectId);
  const stream = useProjectEvents(projectId, agents.data?.event_cursor, agents.dataUpdatedAt);
  const [selected, setSelected] = useState<string | null>(null);
  const [level, setLevel] = useState<string>("all");
  const [drawerW, setDrawerW] = useDrawerWidth();

  const levels = useMemo(() => (project.data?.config.levels ?? []).slice().sort((a, b) => a.order - b.order), [project.data]);
  const lanes = useMemo(() => {
    const items = agents.data?.items ?? [];
    return level === "all" ? items : items.filter((a) => a.config.level_id === level);
  }, [agents.data, level]);
  const selectedAgent = agents.data?.items.find((a) => a.config.id === selected) ?? null;

  return (
    <section className="agents">
      <div className="row row--between">
        <div className="row">
          <ProjectPicker value={projectId} onChange={(id) => nav(`/agents/${id}`)} />
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
      <div className={`agents__grid ${selectedAgent ? "agents__grid--drawer" : ""}`} style={{ "--drawer-w": `${drawerW}px` } as React.CSSProperties}>
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
        {selectedAgent && projectId && (
          <div className="drawer-wrap">
            <ResizeGrip width={drawerW} onResize={setDrawerW} />
            <Drawer key={`${projectId}/${selectedAgent.config.id}`} projectId={projectId} a={selectedAgent} onClose={() => setSelected(null)}
              workingFolder={project.data?.config.folders.find((f) => f.id === selectedAgent.config.cwd_folder_id)?.path ?? null} />
          </div>
        )}
      </div>
    </section>
  );
}

/** Drag (or arrow keys) on the panel's left edge to make it wider or narrower; double-click resets. */
function ResizeGrip({ width, onResize }: { width: number; onResize: (w: number) => void }) {
  const start = (e: React.PointerEvent) => {
    e.preventDefault();
    const x0 = e.clientX;
    const move = (ev: PointerEvent) => onResize(width + x0 - ev.clientX);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.classList.remove("resizing");
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    document.body.classList.add("resizing");
  };
  const key = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowLeft") { e.preventDefault(); onResize(width + 40); }
    if (e.key === "ArrowRight") { e.preventDefault(); onResize(width - 40); }
  };
  return (
    <div className="drawer__grip" role="separator" aria-orientation="vertical" aria-label="Resize agent panel"
      aria-valuenow={width} aria-valuemin={DRAWER_MIN} tabIndex={0} title="Drag to resize - double-click to reset"
      onPointerDown={start} onKeyDown={key} onDoubleClick={() => onResize(DRAWER_DEFAULT)} />
  );
}

function StreamPill({ state, reason }: { state: string; reason: string | null }) {
  const tone = state === "open" ? "ok" : state === "connecting" ? "warn" : state === "reset" ? "bad" : "off";
  return <Pill tone={tone}>live: {state}{reason ? ` (${reason})` : ""}</Pill>;
}

const TONE_VAR = { ok: "var(--ok)", warn: "var(--amber)", bad: "var(--alert)", off: "var(--offline)", info: "var(--chart)" } as const;

/** Threads the Owner may continue with this agent: AGENT threads it is part of. An ASK is answered
 *  through the Owner reply flow in the Inbox; the message endpoint rejects an ASK thread_ref
 *  (AGENT-004, Codex P2). */
export function agentThreads(items: ThreadSummary[], name: string): ThreadSummary[] {
  return items
    .filter((t) => t.thread_ref.thread_id.startsWith("AGENT-"))
    .filter((t) => t.from_name === name || (t.to_name ?? "").split(",").map((x) => x.trim()).includes(name))
    .slice(0, 30);
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
      <Glyph harness={a.config.harness as Harness} size={16} color={TONE_VAR[lampTone(s.state)]} title={`${a.config.harness}, ${s.state}`} />
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

/** The agent's own session: id, generation, the command to open it yourself, and (when the service
 *  supports it) a button that opens it in a terminal window on this PC. */
function SessionPanel({ projectId, a, workingFolder }: { projectId: string; a: AgentView; workingFolder: string | null }) {
  const s = a.status;
  const resume = resumeCommand({ harness: a.config.harness, sessionId: s.session_id, model: a.config.model, workingFolder });
  const cmd = resume && "command" in resume ? resume.command : null;
  const [copied, setCopied] = useState(false);
  const open = useMutation({
    mutationFn: async () => (await post<ResumeWindowReceipt>(`/projects/${encodeURIComponent(projectId)}/agents/${encodeURIComponent(a.config.id)}/resume-window`, undefined, { idempotencyKey: idempotencyKey() })).data,
  });
  const busy = s.state === "busy" || s.state === "starting" || s.state === "stopping";
  const copy = async () => {
    if (!cmd) return;
    try { await navigator.clipboard.writeText(cmd); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { setCopied(false); }
  };
  return (
    <div className="session">
      <div className="row row--between">
        <span className="session__label">Session</span>
        <span className="muted small mono">{s.session_id ? `${s.session_id.slice(0, 18)}${s.session_id.length > 18 ? "..." : ""} - gen ${s.session_generation ?? "-"}` : "none yet - it starts on the first call"}</span>
      </div>
      {resume && "reason" in resume && <div className="muted small">{resume.reason}</div>}
      {resume && (
        <>
          {cmd && <code className="session__cmd">{cmd}</code>}
          <div className="row">
            {cmd && <button className="btn" onClick={copy}><Icon name={copied ? "check" : "output"} size={15} />{copied ? "Copied" : "Copy resume command"}</button>}
            {a.capabilities.attach && (
              <button className="btn btn--primary" disabled={busy || open.isPending} onClick={() => open.mutate()} title={busy ? "Wait until the agent finishes its turn" : "Opens this agent's session in a new terminal window"}>
                <Icon name="call" size={15} />Open in terminal
              </button>
            )}
          </div>
          <div className="muted small">
            {busy ? "The agent is working now. Open its session when it is idle: two writers on one session break it." : "While its window is open, MAS holds new calls to this agent. Close the window to let them run."}
          </div>
          <ErrorNote error={open.error} />
          {open.data && <div className="note note--ok small">Opened in a new PowerShell window in {open.data.working_folder}. Calls to {a.config.name} wait until you close it.</div>}
        </>
      )}
    </div>
  );
}

/** The chat conversation: the thread rendered with the agent's replies, kept live by the SSE stream. */
function Conversation({ r }: { r: ThreadRef }) {
  const q = useThread(r);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { box.current?.scrollTo({ top: box.current.scrollHeight }); }, [q.data?.metadata.revision]);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorNote error={q.error} />;
  if (!q.data) return null;
  const body = q.data.markdown.split(/\n---\n/).slice(1).join("\n---\n") || q.data.markdown;
  return (
    <div className="conversation" ref={box}>
      <Markdown source={body} />
      {q.data.metadata.owes_reply && <div className="muted small">waiting for {q.data.metadata.owes_reply}</div>}
    </div>
  );
}

function Drawer({ projectId, a, onClose, workingFolder }: { projectId: string; a: AgentView; onClose: () => void; workingFolder: string | null }) {
  const act = useAgentAction(projectId);
  const calls = useCalls(projectId, a.config.id);
  const team = useAgents(projectId);
  const names = useMemo(() => new Map((team.data?.items ?? []).map((x) => [x.config.id, x.config.name])), [team.data]);
  const logs = useLogs(projectId);
  const [tab, setTab] = useState<"history" | "call" | "chat" | "output">("history");
  const [text, setText] = useState("");
  const [threadRef, setThreadRef] = useState<ThreadRef | null>(null);
  const [logId, setLogId] = useState<string>("");
  const [runId, setRunId] = useState<string | null>(null);
  const s = a.status;
  const member = a.config.log_duty === "member";
  const effectiveLog = logId || a.config.log_ids[0] || logs.data?.items[0]?.log_id || "";
  const allThreads = useLogIndex(projectId, member ? effectiveLog : undefined, "all");
  const theirThreads = agentThreads((allThreads.data?.items ?? []) as ThreadSummary[], a.config.name);

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
      <SessionPanel projectId={projectId} a={a} workingFolder={workingFolder} />
      <div className="row">
        <button className="btn" disabled={!member || act.wake.isPending} onClick={() => act.wake.mutate({ agent: a.config.id, key: idempotencyKey() })}>Wake up</button>
        <button className="btn" disabled={act.stop.isPending} onClick={() => act.stop.mutate({ agent: a.config.id, key: idempotencyKey() })}>Stop</button>
        {s.queue_paused && s.state !== "unknown" && <button className="btn" disabled={act.resumeQueue.isPending} onClick={() => act.resumeQueue.mutate({ agent: a.config.id, key: idempotencyKey() })}>Resume queue</button>}
      </div>
      {s.state === "unknown" && (
        <div className="note small">
          MAS cannot tell whether {a.config.name}'s last run or terminal window is still going (for example after a restart).
          If you are sure it has stopped, free the agent. Its session is kept.
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn" disabled={act.resumeQueue.isPending} onClick={() => act.resumeQueue.mutate({ agent: a.config.id, key: idempotencyKey(), confirmStopped: true })}>It has stopped - free {a.config.name}</button>
          </div>
        </div>
      )}
      <ErrorNote error={act.wake.error ?? act.stop.error ?? act.resumeQueue.error} />
      <div className="tabs">
        {(["history", "call", "chat", "output"] as const).map((t) => <button key={t} className={`tab ${tab === t ? "tab--on" : ""}`} onClick={() => setTab(t)}>{t}</button>)}
      </div>

      {tab === "call" && <CallForm projectId={projectId} a={a} onSent={() => setTab("history")} />}

      {tab === "history" && (
        <div>
          <ErrorNote error={calls.error} />
          {calls.data && calls.data.items.length === 0 && <Empty>No work yet. Every call and message to {a.config.name} shows up here.</Empty>}
          {calls.data && calls.data.items.length > 0 && (
            <table className="table small">
              <thead><tr><th>When</th><th>From</th><th>Thread</th><th>State</th><th>Took</th><th></th></tr></thead>
              <tbody>
                {calls.data.items.map((d: Delivery) => (
                  <tr key={d.delivery_id}>
                    <td>{fmtTime(d.run_started_at ?? d.created_at)}</td>
                    <td>{callerLabel(d.caller, names)}{d.purpose === "notification" ? <div className="muted">notify</div> : null}</td>
                    <td>{d.thread_ref ? <Link to={`/threads/${d.thread_ref.project_id}/${d.thread_ref.log_id}/${d.thread_ref.thread_id}`}>{d.thread_ref.thread_id}</Link> : "-"}</td>
                    <td><DeliveryState d={d} />{d.reason ? <div className="muted">{d.reason}</div> : null}</td>
                    <td className="mono">{runDuration(d.run_started_at, d.run_finished_at)}</td>
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
                  <div className="row">
                    <label className="field field--inline"><span>New thread in log</span>
                      <select value={effectiveLog} onChange={(e) => setLogId(e.target.value)}>
                        {(logs.data?.items ?? []).map((l) => <option key={l.log_id} value={l.log_id}>{l.log_id}</option>)}
                      </select>
                    </label>
                    {theirThreads.length > 0 && (
                      <label className="field field--inline"><span>or continue</span>
                        <select value="" onChange={(e) => { const t = theirThreads.find((x) => x.thread_ref.thread_id === e.target.value); if (t) setThreadRef(t.thread_ref); }}>
                          <option value="">a thread with {a.config.name}</option>
                          {theirThreads.map((t) => <option key={t.thread_ref.thread_id} value={t.thread_ref.thread_id}>{t.thread_ref.thread_id} {t.title}</option>)}
                        </select>
                      </label>
                    )}
                  </div>
                )}
              </div>
              {threadRef && <Conversation r={threadRef} />}
              <textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} required placeholder="Your words are written verbatim into the thread and become the agent's next turn (queued if busy)." />
              <ErrorNote error={act.message.error} />
              <div className="row"><button className="btn btn--primary" disabled={act.message.isPending || !effectiveLog}>Send</button></div>
            </>
          )}
        </form>
      )}

      {tab === "output" && (runId ? <OutputPane key={runId} projectId={projectId} runId={runId} /> : <Empty>Pick a run in the history tab.</Empty>)}
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
