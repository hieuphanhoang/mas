// Test helpers: a routed fetch mock and a wrapper with a fresh QueryClient and a router.
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

export type Handler = (url: URL, init?: RequestInit) => unknown;

/** Routes "METHOD /path" (query ignored) to a handler returning a JSON body. Records every call. */
export function mockFetch(routes: Record<string, Handler>) {
  const calls: { method: string; url: URL; body: unknown }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://127.0.0.1");
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const h = routes[`${method} ${url.pathname}`];
    if (!h) return new Response(JSON.stringify({ code: "not_found", message: url.pathname, details: [], request_id: "x", retryable: false }), { status: 404 });
    return new Response(JSON.stringify(h(url, init)), { status: method === "POST" ? 202 : 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

/** EventSource is missing in jsdom; the control room only needs it to exist. */
export class FakeEventSource {
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  constructor(public url: string) {}
  addEventListener() {}
  close() {}
}

export function Wrap({ path, route, children }: { path: string; route: string; children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path={route} element={children} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

export const session = () => ({ csrf_token: "csrf-test", expires_at: "2026-10-30T00:00:00Z" });

export function agentView(id: string, name: string) {
  return {
    config: {
      id, name, level_id: "members", role: `${name} role`, harness: "claude", model: "m", cwd_folder_id: "root",
      owns: [], reads: [], log_ids: ["main"], skills: [], log_duty: "member", invocation: "callable",
      launch_mode: "managed", permission_profile: "member",
    },
    status: {
      agent_id: id, revision: "r", state: "idle", observed_at: "2026-10-29T00:00:00Z", source: "supervisor",
      reason: null, queue_length: 0, queue_paused: false, session_id: null, session_generation: null, active_run_id: null,
    },
    capabilities: {
      harness: "claude", availability: "available", version: "x", reason: null, modes: ["managed"], resume: true,
      live_delivery: false, attach: false, stop: true,
      guard_coverage: { tool_paths: "unknown", shell_commands: "unknown", sandbox: "unknown", limitations: [] },
    },
  };
}
