// Friendly aliases over the generated contract types. Only this file imports from generated/.
import type { components, operations } from "../generated/api";

type S = components["schemas"];

export type Id = S["Id"];
export type Revision = S["Revision"];
export type Cursor = S["Cursor"];
export type ThreadRef = S["ThreadRef"];
export type ThreadStatus = S["ThreadStatus"];
export type AgentStatus = S["AgentStatus"];
export type Delivery = S["Delivery"];
export type ApiErrorShape = S["Error"];
export type PermissionProfile = S["PermissionProfile"];
export type AdapterCapability = S["AdapterCapability"];
export type ProjectSummary = S["ProjectSummary"];
export type ProjectRecord = S["ProjectRecord"];
// openapi-typescript copies the schema file's `$defs` block into the type; it is not payload data.
export type ProjectConfig = Omit<S["project.schema"], "$defs">;
export type AgentConfig = S["Agent"];
export type Preview = S["Preview"];
export type AgentView = S["AgentView"];
export type CallRequest = S["CallRequest"];
export type MessageRequest = S["MessageRequest"];
export type Freshness = S["Freshness"];
export type LogView = S["LogView"];
export type ThreadSummary = S["ThreadSummary"];
export type HistoryRow = S["HistoryRow"];
export type LogIndex = S["LogIndex"];
export type ThreadDocument = S["ThreadDocument"];
export type ReplyRequest = S["ReplyRequest"];
export type ReplyReceipt = S["ReplyReceipt"];
export type RunOutput = S["RunOutput"];
export type ResumeWindowReceipt = S["ResumeWindowReceipt"];

export type IndexSection = NonNullable<operations["getLogIndex"]["parameters"]["query"]>["section"];

export type Capabilities = operations["getCapabilities"]["responses"][200]["content"]["application/json"];
export type ProjectList = operations["listProjects"]["responses"][200]["content"]["application/json"];
export type AgentList = operations["listAgents"]["responses"][200]["content"]["application/json"];
export type LogList = operations["listLogs"]["responses"][200]["content"]["application/json"];
export type Inbox = operations["getInbox"]["responses"][200]["content"]["application/json"];
export type CallList = operations["listCalls"]["responses"][200]["content"]["application/json"];
export type Session = operations["getSession"]["responses"][200]["content"]["application/json"];

export const threadKey = (r: ThreadRef) => `${r.project_id}/${r.log_id}/${r.thread_id}`;
