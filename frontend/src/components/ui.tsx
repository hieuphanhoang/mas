import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import type { Freshness, ThreadStatus } from "../api/types";

export function Pill({ tone, children }: { tone: "ok" | "warn" | "bad" | "off" | "info"; children: ReactNode }) {
  return <span className={`pill pill--${tone}`}>{children}</span>;
}

export function StatusPill({ status }: { status: ThreadStatus | null }) {
  const tone = status === "open" ? "warn" : status === "answered" ? "info" : status === "blocked" ? "bad" : status === "closed" ? "ok" : "off";
  return <Pill tone={tone}>{status ?? "?"}</Pill>;
}

export function FreshnessNote({ f }: { f: Freshness }) {
  if (f.state === "current") return null;
  const tone = f.state === "stale" ? "warn" : "bad";
  return <Pill tone={tone}>{f.state}{f.reason ? `: ${f.reason}` : ""}</Pill>;
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  if (error instanceof ApiError) {
    return (
      <div className="note note--bad" role="alert">
        <strong>{error.code}</strong> {error.body?.message}
        {error.body?.details?.length ? (
          <ul>{error.body.details.map((d, i) => <li key={i}><code>{d.location}</code> {d.message}</li>)}</ul>
        ) : null}
        {error.body?.request_id ? <span className="muted"> request {error.body.request_id}</span> : null}
      </div>
    );
  }
  return <div className="note note--bad" role="alert">{String((error as Error)?.message ?? error)}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty muted">{children}</div>;
}

export function Loading() {
  return <div className="muted">Loading...</div>;
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { hour12: false });
}
