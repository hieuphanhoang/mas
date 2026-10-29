// Thin HTTP client over the slice-1 contract (docs/contract/openapi.yaml).
// Rules implemented here, so pages never repeat them:
//  - same-origin cookie session; CSRF token sent on every mutation (X-MAS-CSRF);
//  - every mutation carries an Idempotency-Key (stable per logical action, see idempotencyKey);
//  - PUT/preview/apply carry If-Match from the last ETag seen for that resource;
//  - all errors are the contract's Error shape, surfaced as ApiError.

export interface ApiErrorBody {
  code: string;
  message: string;
  details: { location: string; code: string; message: string }[];
  request_id: string;
  retryable: boolean;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: ApiErrorBody | null,
  ) {
    super(body?.message ?? `HTTP ${status}`);
  }
  get code() {
    return this.body?.code ?? `http_${this.status}`;
  }
}

export const API_BASE = "/api/v1";

let csrfToken: string | null = null;
let pending: Promise<string> | null = null;

/** R1 of the contract review: GET /session returns {csrf_token, expires_at} and sets the cookie.
 *  Concurrent first requests share one bootstrap instead of each fetching a session. */
export async function ensureSession(): Promise<string> {
  if (csrfToken) return csrfToken;
  if (!pending) {
    pending = (async () => {
      const res = await fetch(`${API_BASE}/session`, { credentials: "same-origin" });
      if (!res.ok) throw new ApiError(res.status, await safeJson(res));
      const data = (await res.json()) as { csrf_token: string };
      csrfToken = data.csrf_token;
      return csrfToken;
    })().finally(() => { pending = null; });
  }
  return pending;
}

export function resetSession() {
  csrfToken = null;
}

async function safeJson(res: Response): Promise<ApiErrorBody | null> {
  try {
    return (await res.json()) as ApiErrorBody;
  } catch {
    return null;
  }
}

/** A stable key per logical action: the caller passes something unique to the action (form submit id). */
export function idempotencyKey(seed?: string): string {
  if (seed) return seed.replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 128);
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT";
  body?: unknown;
  ifMatch?: string;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

export interface Envelope<T> {
  data: T;
  etag: string | null;
  status: number;
}

export async function request<T>(path: string, opts: RequestOptions = {}, retried = false): Promise<Envelope<T>> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  // Every protected route needs the local session cookie, reads included: bootstrap it once.
  const token = await ensureSession();
  if (method !== "GET") {
    headers["X-MAS-CSRF"] = token;
    headers["Idempotency-Key"] = opts.idempotencyKey ?? idempotencyKey();
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  }
  if (opts.ifMatch) headers["If-Match"] = opts.ifMatch;
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    credentials: "same-origin",
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    signal: opts.signal,
  });
  if (res.status === 401) {
    resetSession();
    // An expired session is re-bootstrapped once; a mutation keeps its idempotency key so a retry is safe.
    if (!retried) return request<T>(path, { ...opts, idempotencyKey: headers["Idempotency-Key"] ?? opts.idempotencyKey }, true);
  }
  if (!res.ok) throw new ApiError(res.status, await safeJson(res));
  const etag = res.headers.get("ETag");
  const data = res.status === 204 ? (undefined as T) : ((await res.json()) as T);
  return { data, etag, status: res.status };
}

export const get = <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal });
export const post = <T>(path: string, body?: unknown, o: Omit<RequestOptions, "method" | "body"> = {}) =>
  request<T>(path, { ...o, method: "POST", body });
export const put = <T>(path: string, body: unknown, o: Omit<RequestOptions, "method" | "body"> = {}) =>
  request<T>(path, { ...o, method: "PUT", body });
