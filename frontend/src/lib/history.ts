// Labels for an agent's call history (contract 0.3.0: caller, run_started_at, run_finished_at on the
// calls list).

export interface Caller { kind: "owner" | "agent" | "unknown"; agent_id: string | null }

/** "You" for the Owner, the calling agent's name, or "unknown" for history older than 0.3.0. */
export function callerLabel(caller: Caller | null | undefined, names: Map<string, string>): string {
  if (!caller) return "-";
  if (caller.kind === "owner") return "You";
  if (caller.kind === "agent" && caller.agent_id) return names.get(caller.agent_id) ?? caller.agent_id;
  return "unknown";
}

/** Run length as "42s" or "3m 05s"; "running" while the run has no finish time; "-" if it never started. */
export function runDuration(started: string | null | undefined, finished: string | null | undefined): string {
  if (!started) return "-";
  if (!finished) return "running";
  const s = Math.max(0, Math.round((Date.parse(finished) - Date.parse(started)) / 1000));
  if (Number.isNaN(s)) return "-";
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}
