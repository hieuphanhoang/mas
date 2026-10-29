// SSE subscriber for GET /projects/{p}/events (events.schema.json).
// Bootstrap: caller fetches a snapshot, reads its event_cursor, then subscribes with ?after=.
// Reconnect: the browser resends Last-Event-ID automatically; we dedupe by event_id.
// stream.reset_required: close, tell the caller to refetch, and resubscribe from the new cursor.

export interface EventEnvelope<P = unknown> {
  schema_version: 1;
  event_id: string;
  project_id: string;
  type: string;
  occurred_at: string;
  entity_id: string;
  revision: string;
  correlation_id: string;
  payload: P;
}

export interface Subscription {
  close(): void;
}

export interface SubscribeOptions {
  projectId: string;
  after: string;
  onEvent: (e: EventEnvelope) => void;
  /** Called when the server says the cursor is unusable; the caller refetches and resubscribes. */
  onReset: (reason: string) => void;
  onStateChange?: (state: "connecting" | "open" | "closed") => void;
}

/** Cursors are decimal strings; compare as BigInt, never lexically (contract note). */
export function cursorGreater(a: string, b: string): boolean {
  return BigInt(a) > BigInt(b);
}

export function subscribe(opts: SubscribeOptions): Subscription {
  let last = opts.after;
  const url = `/api/v1/projects/${encodeURIComponent(opts.projectId)}/events?after=${encodeURIComponent(opts.after)}`;
  const es = new EventSource(url, { withCredentials: true });
  opts.onStateChange?.("connecting");
  es.onopen = () => opts.onStateChange?.("open");

  const handle = (raw: MessageEvent) => {
    let env: EventEnvelope;
    try {
      env = JSON.parse(raw.data as string) as EventEnvelope;
    } catch {
      return;
    }
    if (env.type === "stream.reset_required") {
      const reason = (env.payload as { reason?: string })?.reason ?? "unknown";
      es.close();
      opts.onStateChange?.("closed");
      opts.onReset(reason);
      return;
    }
    if (!cursorGreater(env.event_id, last)) return; // duplicate or replayed
    last = env.event_id;
    opts.onEvent(env);
  };

  // The server sets `event:` to the type, so each type needs a listener; `message` catches untyped frames.
  for (const t of EVENT_TYPES) es.addEventListener(t, handle as EventListener);
  es.onmessage = handle;
  es.onerror = () => opts.onStateChange?.("connecting");

  return {
    close() {
      es.close();
      opts.onStateChange?.("closed");
    },
  };
}

export const EVENT_TYPES = [
  "project.changed",
  "agent.status_changed",
  "delivery.queued",
  "delivery.state_changed",
  "run.started",
  "run.finished",
  "thread.changed",
  "inbox.changed",
  "stream.reset_required",
] as const;
