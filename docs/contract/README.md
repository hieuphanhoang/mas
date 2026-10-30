# MAS contract v1 - slice 1

Revision 0.3.1 adds optional `{confirm_stopped: true}` to Owner-only `resume-queue`.
After verifying the old process/window has stopped, the Owner can clear unknown
liveness after restart. A known live writer still blocks this operation. Session
identity stays unchanged; uncertain deliveries become failed with unknown process
outcome, and their Run stays unknown. The confirmation is recorded; stale windows
close and queued work resumes. No old delivery is retried. No-body behavior and
all response shapes are unchanged; regenerate request types. This is an Owner
assertion, not proof from process scanning or process adoption.

Contract revision 0.3.0 (AGENT-005) adds Owner-only `resume-window` and history
metadata to the existing calls list. Regenerate clients together for the new
optional Delivery properties: `caller` (`kind`, `agent_id`), `run_started_at`,
and `run_finished_at`. The list always populates them; other delivery shapes and
SSE payloads may omit them. Existing receipts/events stay byte-for-byte unchanged,
so no data migration or replay is needed. Pre-0.3 call-list cursors are invalid;
start a fresh list. Missing historical parent/input data is `caller.kind=unknown`,
never guessed to be the Owner. Times describe supervisor run records, not provider
transcripts or proof that an uncertain process exited.

The resume endpoint returns a launch receipt for one visible Windows terminal,
not a managed turn. A reservation blocks dispatch before spawn and until the
window exits. Failure to spawn releases it. On service restart an outstanding
reservation is held unknown/paused until manually reconciled, without adopting
or killing the Owner's process. The window inherits the selected profile and
OpenCode provider settings but receives no managed agent token. It is not a new
registered session. No transcript reading or live-turn streaming was added.

Contract revision 0.2.0 (AGENT-004) is a coordinated pre-release local upgrade.
Regenerate both clients and deploy them together. The required Delivery.purpose
field is a breaking shape change under additionalProperties=false; older clients
and older stored shapes are not compatible. Event schema_version stays 1 because
this is a coordinated upgrade of the local application, not mixed-version support.

Only replyAsOwner creates purpose=notification for its optional wake, bound to
the ASK answered even if no work remains pending. Successful execution completes
the notification with reason=null; it makes no claim that the answer was acted
upon. Every other delivery is purpose=task. Requests cannot set purpose. Manual,
failed, cancelled and uncertain notifications keep their actual states. No
follow_ups field is added: handwritten stamps cannot identify the authoring run.

On first 0.2 startup, a transactional shape migration adds purpose=task to old
deliveries, delivery payloads in the outbox, pagination snapshots and nested
HTTP receipts. It preserves IDs, event ordering, revisions, outcomes and old
missing_reply failures, and never dispatches or reruns anything. Original changed
HTTP receipts are retained as receipt_original audit rows. Replays return the
upgraded 0.2 shape; this is an explicit shape-only exception to identical historical
response bytes across the upgrade. New receipts replay normally. Back up the local
registry before upgrading; both members agreed this rollout in AGENT-004.

Baseline approved in **AGENT-002**; revision 0.2.0 agreed in **AGENT-004**.
Codex authors the backend/contract implementation; Fable reviews and regenerates
frontend types. The Owner accepted scope in ASK-001, including exactly this PC
and Gemini CLI later.

| Source | Authority |
|---|---|
| [openapi.yaml](openapi.yaml) | OpenAPI 3.1 HTTP paths, request/response shapes, security, ETags, retry semantics |
| [project.schema.json](project.schema.json) | JSON Schema 2020-12 project intent and reserved adapter configuration |
| [events.schema.json](events.schema.json) | JSON Schema 2020-12 SSE envelope, payload union and shared runtime shapes |

All references resolve locally; no remote schema fetching is needed. Schemas
describe structural validation; `x-semantic-validation` and operation prose are
also binding (ownership, call edges, caller identity, liveness, path resolution).
Defaults suggest wizard values; validators do not silently fill them in.
opencode is next; `gemini: {}` is reserved, planned and not executable in v1.
Rituals/leases are disabled definitions in slice 1. Later routes/events appear
only in the final OpenAPI comment block, not in `paths` or the event union.

After joint approval and the separate dependency-install ASK, run from the repo
root with pinned local dependencies. Fable generates frontend types into its
owned tree using `openapi-typescript`; Codex uses `datamodel-code-generator`
0.86.0 to generate Pydantic v2 component models.

```powershell
npm exec --prefix frontend --no -- openapi-typescript docs/contract/openapi.yaml -o frontend/src/generated/api.ts
uv run --project backend --frozen --no-sync datamodel-codegen --input docs/contract/openapi.yaml --input-file-type openapi --openapi-scopes schemas --output-model-type pydantic_v2.BaseModel --target-python-version 3.12 --disable-timestamp --formatters black isort --output backend/src/mas_backend/generated
uv run --project backend --frozen --no-sync openapi-spec-validator docs/contract/openapi.yaml
```

Create the owned output directories during implementation. The OpenAPI components
expose ProjectConfig and ProjectEvent, so generators see both external schemas.
Generator output is a type layer, not proof of full constraint support: runtime
JSON Schema validation must enforce conditional rules, and backend checks enforce
semantic constraints. Keep generators deterministic, never hand-edit generated
files, and check regeneration diffs plus positive/negative payload fixtures and
runtime OpenAPI equivalence. Frontend TypeScript alone is not runtime validation.
The approved backend install commands and outcome are recorded in ASK-002.
Generator CLI reference:
[datamodel-code-generator](https://datamodel-code-generator.koxudaxi.dev/).

Browser bootstrap calls `GET /api/v1/session` to obtain `{csrf_token, expires_at}`
and a local HttpOnly SameSite=Strict cookie, without a login screen. Local backend
`dev_allowed_origins` defaults to `[]`; for Vite set it to
`["http://127.0.0.1:5173"]` and proxy `/api` with upstream Host rewriting and
Set-Cookie forwarding. This is an Origin allowlist, not remote access or CORS.
Mutations send X-MAS-CSRF and a stable
Idempotency-Key. A 202 is a queued delivery receipt; poll its status_url or consume
events. Stop returns persisted pause/cancel intent, not proof the process exited.
Reply returns the committed Owner comment separately from sync/wake outcome.
Chat retains Delivery.thread_ref and sends it on follow-ups to reuse one thread.
The wizard selects permission profiles by `(harness, id)` from capabilities,
including `default` for each available harness. Omitted agent prompt_file means
`.agents/mas/prompts/<agent_id>.md` under its cwd folder: preview lists creation
from role plus preamble, apply creates only missing files and preserves existing
prompts. Explicit prompt paths must already exist.

Each registered agent has one persisted harness session, created on its first
managed turn and resumed by explicit session ID on subsequent turns. The service
never substitutes a fresh session for an existing ID after a failure or restart.
New Claude/OpenCode sessions are labeled `<project name> / <agent name>` through
`--name` / `run --title`; the same label is the launch prompt's first line for
Codex. Resumes do not rename existing sessions or replace their conversation.
This history-label clarification (AGENT-005 H1) does not change HTTP schemas.

For SSE, first read the project event_cursor, fetch the visible resources, then
subscribe with `?after=<cursor>`. Apply domain events by event ID, ignore duplicate
IDs, and refetch invalidated resources; consumers must not replace a newer fetched
snapshot with an older event payload. Last-Event-ID wins on reconnect. On
stream.reset_required, close and repeat bootstrap. Each tab may maintain its own
cursor. Read-only run output polls the bounded output endpoint independently.

Known limit: handoff.py is not fully locked across independent writers. The
service serializes its writes and reports detected 409 conflicts, but cannot
promise no lost updates with concurrent direct CLI writes. The skill author owns
the locking improvement; do not fork that CLI here. Hooks remain workflow checks,
with verified harness sandbox coverage reported explicitly, not hard isolation.

Review changes as one set: all three machine-readable files, this guide, backend
plan and their examples. Breaking shapes need a version/review decision. Fable's
approval/findings belong in AGENT-002 before merge; no push is authorized.
