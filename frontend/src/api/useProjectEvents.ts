import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { subscribe, type EventEnvelope } from "./events";
import { keys } from "./queries";
import type { AgentStatus, Delivery, ThreadRef } from "./types";

export type StreamState = "idle" | "connecting" | "open" | "closed" | "reset";

/**
 * Keeps react-query caches of one project fresh from the SSE stream.
 *
 * Bootstrap (contract): fetch a snapshot, take its event_cursor, subscribe with ?after=cursor.
 * The cursor is taken ONCE per subscription. Later refetches of the snapshot also carry a cursor,
 * but following it would close and reopen the stream on every event (each event triggers a
 * refetch). The browser's own reconnect uses Last-Event-ID, so the stream needs no new cursor
 * except after stream.reset_required; then we wait for a snapshot fetched after the reset.
 *
 * @param cursor     event_cursor of the latest snapshot (agents list)
 * @param fetchedAt  when that snapshot was fetched (react-query dataUpdatedAt)
 */
export function useProjectEvents(projectId: string | undefined, cursor: string | undefined, fetchedAt = 0) {
  const qc = useQueryClient();
  const [state, setState] = useState<StreamState>("idle");
  const [resetReason, setResetReason] = useState<string | null>(null);
  const [boot, setBoot] = useState<{ project: string; cursor: string } | null>(null);
  const resetAt = useRef(0);

  // Pick the bootstrap cursor: first snapshot for this project, or the first one fetched after a reset.
  useEffect(() => {
    if (!projectId) { setBoot(null); return; }
    if (boot && boot.project === projectId) return;
    if (cursor === undefined || fetchedAt <= resetAt.current) return;
    setBoot({ project: projectId, cursor });
  }, [projectId, cursor, fetchedAt, boot]);

  useEffect(() => {
    if (!boot || boot.project !== projectId) return;
    const pid = boot.project;
    const onEvent = (e: EventEnvelope) => {
      switch (e.type) {
        case "agent.status_changed": {
          const s = e.payload as AgentStatus;
          qc.setQueryData(keys.agents(pid), (old: { items: { status: AgentStatus }[] } | undefined) =>
            old ? { ...old, items: old.items.map((a) => (a.status.agent_id === s.agent_id ? { ...a, status: s } : a)) } : old,
          );
          break;
        }
        case "delivery.queued":
        case "delivery.state_changed": {
          const d = e.payload as Delivery;
          void qc.invalidateQueries({ queryKey: ["calls", pid] });
          if (d.state === "completed" || d.state === "failed") void qc.invalidateQueries({ queryKey: keys.agents(pid) });
          break;
        }
        case "run.started":
        case "run.finished":
          void qc.invalidateQueries({ queryKey: ["calls", pid] });
          void qc.invalidateQueries({ queryKey: ["output", pid] });
          break;
        case "thread.changed": {
          const r = (e.payload as { thread_ref: ThreadRef }).thread_ref;
          void qc.invalidateQueries({ queryKey: keys.thread(r) });
          void qc.invalidateQueries({ queryKey: ["index", pid, r.log_id] });
          break;
        }
        case "inbox.changed":
          void qc.invalidateQueries({ queryKey: keys.inbox });
          break;
        case "project.changed":
          void qc.invalidateQueries({ queryKey: keys.project(pid) });
          void qc.invalidateQueries({ queryKey: keys.projects });
          break;
      }
    };
    setResetReason(null);
    const sub = subscribe({
      projectId: pid,
      after: boot.cursor,
      onEvent,
      onStateChange: setState,
      onReset: (reason) => {
        setResetReason(reason);
        setState("reset");
        resetAt.current = Date.now();
        void qc.invalidateQueries({ queryKey: keys.agents(pid) });
        void qc.invalidateQueries({ queryKey: ["calls", pid] });
        void qc.invalidateQueries({ queryKey: keys.project(pid) });
        setBoot(null); // the next snapshot fetched after resetAt provides the new cursor
      },
    });
    return () => sub.close();
  }, [boot, projectId, qc]);

  return { state, resetReason };
}
