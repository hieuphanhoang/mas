import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post, put } from "./client";
import type {
  AgentList,
  AgentStatus,
  CallList,
  CallRequest,
  Capabilities,
  Delivery,
  IndexSection,
  Inbox,
  LogIndex,
  LogList,
  MessageRequest,
  Preview,
  ProjectConfig,
  ProjectList,
  ProjectRecord,
  ReplyReceipt,
  ReplyRequest,
  RunOutput,
  ThreadDocument,
  ThreadRef,
} from "./types";

const enc = encodeURIComponent;
const p = (id: string) => `/projects/${enc(id)}`;

export const keys = {
  capabilities: ["capabilities"] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["project", id] as const,
  agents: (id: string) => ["agents", id] as const,
  calls: (id: string, agent?: string) => ["calls", id, agent ?? ""] as const,
  logs: (id: string) => ["logs", id] as const,
  index: (id: string, log: string, section: IndexSection) => ["index", id, log, section] as const,
  thread: (r: ThreadRef) => ["thread", r.project_id, r.log_id, r.thread_id] as const,
  inbox: ["inbox"] as const,
  output: (id: string, run: string, offset: string) => ["output", id, run, offset] as const,
};

export const useCapabilities = () =>
  useQuery({ queryKey: keys.capabilities, queryFn: async () => (await get<Capabilities>("/capabilities")).data, staleTime: 60_000 });

export const useProjects = () =>
  useQuery({ queryKey: keys.projects, queryFn: async () => (await get<ProjectList>("/projects?limit=100")).data });

export const useProject = (id: string | undefined) =>
  useQuery({
    queryKey: keys.project(id ?? ""),
    enabled: !!id,
    queryFn: async () => {
      const r = await get<ProjectRecord>(p(id!));
      return { ...r.data, etag: r.etag ?? `"${r.data.revision}"` };
    },
  });

export const useAgents = (id: string | undefined) =>
  useQuery({ queryKey: keys.agents(id ?? ""), enabled: !!id, queryFn: async () => (await get<AgentList>(`${p(id!)}/agents`)).data });

export const useCalls = (id: string | undefined, agent?: string) =>
  useQuery({
    queryKey: keys.calls(id ?? "", agent),
    enabled: !!id,
    queryFn: async () => (await get<CallList>(`${p(id!)}/calls?limit=100${agent ? `&agent_id=${enc(agent)}` : ""}`)).data,
  });

export const useLogs = (id: string | undefined) =>
  useQuery({ queryKey: keys.logs(id ?? ""), enabled: !!id, queryFn: async () => (await get<LogList>(`${p(id!)}/logs`)).data });

export const useLogIndex = (id: string | undefined, log: string | undefined, section: IndexSection) =>
  useQuery({
    queryKey: keys.index(id ?? "", log ?? "", section),
    enabled: !!id && !!log,
    queryFn: async () => (await get<LogIndex>(`${p(id!)}/logs/${enc(log!)}/index?section=${section}&limit=100`)).data,
  });

export const useThread = (r: ThreadRef | undefined) =>
  useQuery({
    queryKey: r ? keys.thread(r) : ["thread", "none"],
    enabled: !!r,
    queryFn: async () => (await get<ThreadDocument>(`${p(r!.project_id)}/logs/${enc(r!.log_id)}/threads/${enc(r!.thread_id)}`)).data,
  });

export const useInbox = () =>
  useQuery({ queryKey: keys.inbox, queryFn: async () => (await get<Inbox>("/inbox?limit=100")).data, refetchInterval: 30_000 });

export const useRunOutput = (id: string, run: string | undefined, offset: string) =>
  useQuery({
    queryKey: keys.output(id, run ?? "", offset),
    enabled: !!run,
    queryFn: async () => (await get<RunOutput>(`${p(id)}/runs/${enc(run!)}/output?offset=${offset}&limit=100`)).data,
    // Output chunks are not in the SSE stream (contract): poll until eof, also when caught up.
    refetchInterval: (query) => (query.state.data?.eof ? false : 1500),
  });

// ---- mutations -------------------------------------------------------------------------

export function useReplyAsOwner() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (v: { ref: ThreadRef; body: ReplyRequest; key: string }) =>
      (await post<ReplyReceipt>(`${p(v.ref.project_id)}/logs/${enc(v.ref.log_id)}/threads/${enc(v.ref.thread_id)}/reply`, v.body, { idempotencyKey: v.key })).data,
    onSuccess: (_r, v) => {
      void qc.invalidateQueries({ queryKey: keys.inbox });
      void qc.invalidateQueries({ queryKey: keys.thread(v.ref) });
      void qc.invalidateQueries({ queryKey: ["index", v.ref.project_id, v.ref.log_id] });
    },
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (v: { config: ProjectConfig; key: string }) => (await post<ProjectRecord>("/projects", v.config, { idempotencyKey: v.key })).data,
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.projects }),
  });
}

export function useUpdateProject(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (v: { config: ProjectConfig; etag: string; key: string }) =>
      (await put<ProjectRecord>(p(id), v.config, { ifMatch: v.etag, idempotencyKey: v.key })).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.project(id) });
      void qc.invalidateQueries({ queryKey: keys.projects });
    },
  });
}

export function usePreviewProject(id: string) {
  return useMutation({
    mutationFn: async (v: { etag: string; key: string }) => (await post<Preview>(`${p(id)}/preview`, undefined, { ifMatch: v.etag, idempotencyKey: v.key })).data,
  });
}

export function useApplyProject(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (v: { previewId: string; etag: string; key: string }) =>
      (await post<ProjectRecord>(`${p(id)}/apply`, { preview_id: v.previewId }, { ifMatch: v.etag, idempotencyKey: v.key })).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.project(id) });
      void qc.invalidateQueries({ queryKey: keys.projects });
    },
  });
}

export function useAgentAction(id: string) {
  const qc = useQueryClient();
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: keys.agents(id) });
    void qc.invalidateQueries({ queryKey: ["calls", id] });
  };
  const a = (agent: string, action: string) => `${p(id)}/agents/${enc(agent)}/${action}`;
  return {
    call: useMutation({ mutationFn: async (v: { agent: string; body: CallRequest; key: string }) => (await post<Delivery>(a(v.agent, "call"), v.body, { idempotencyKey: v.key })).data, onSuccess: invalidate }),
    message: useMutation({ mutationFn: async (v: { agent: string; body: MessageRequest; key: string }) => (await post<Delivery>(a(v.agent, "message"), v.body, { idempotencyKey: v.key })).data, onSuccess: invalidate }),
    wake: useMutation({ mutationFn: async (v: { agent: string; key: string }) => (await post<Delivery>(a(v.agent, "wake"), undefined, { idempotencyKey: v.key })).data, onSuccess: invalidate }),
    stop: useMutation({ mutationFn: async (v: { agent: string; key: string }) => (await post<AgentStatus>(a(v.agent, "stop"), undefined, { idempotencyKey: v.key })).data, onSuccess: invalidate }),
    resumeQueue: useMutation({ mutationFn: async (v: { agent: string; key: string; confirmStopped?: boolean }) => (await post<AgentStatus>(a(v.agent, "resume-queue"), v.confirmStopped ? { confirm_stopped: true } : undefined, { idempotencyKey: v.key })).data, onSuccess: invalidate }),
    cancel: useMutation({ mutationFn: async (v: { call: string; key: string }) => (await post<Delivery>(`${p(id)}/calls/${enc(v.call)}/cancel`, undefined, { idempotencyKey: v.key })).data, onSuccess: invalidate }),
  };
}
