# Backend plan - slice 1 (Codex)

Status: baseline contract approved in AGENT-002; notification revision 0.2.0
agreed in AGENT-004 and implemented in 491aa86. Backend I1/I2 are committed.
I3 adapters pass the fake-subprocess matrix; live smoke awaits an Owner ASK.

## Implementation checkpoint - 2026-10-29

N1 follow-up: npm vendor/bin lookup fixed; the approved Codex-only start/resume
smoke passed twice on one captured session (gpt-6-astra, installed CLI 0.164.0).
Claude's earlier approved start/resume passed separately. No further live turns
are authorized by those completed checks.

N2: before managed resume, inspect Claude's agents JSON and Claude/Codex process
command lines for the session ID, as in the reference system. Hold queued with a reason
while open elsewhere or inventory is unavailable. This is a cached observation,
not a cross-process lock/adoption mechanism. `mas call` uses the run's scoped
environment, backend queue and a stable idempotency key; launch context supplies
the call and handoff reply commands. Owner selects the member profile at setup.
Claude member preallows the handoff/mas-call Bash and PowerShell prefixes plus
Edit/Write. Codex member has network on, explicitly accepted by the Owner in
ASK-004 at 0752: sandbox_workspace_write.network_access=true, while retaining
workspace-write and approval_policy=never. This permits any network destination,
not only localhost; capabilities states that tradeoff. Default stays unchanged.
Local installed Codex config rendering accepted this setting without a model
call. The earlier unverified proxy/profile alternatives were not retained.
Launch context names agents-collaboration-protocol, configured skills and the
mas call roster command. The fresh bidirectional live rerun awaits Owner OK.

- `mas serve --fake-adapter` enables only simulated turns. `--real-adapters`
  enables managed Claude/Codex turns; the default service does not dispatch.
- Probe runs version/help only. Claude uses print/stream-json with an explicit
  UUID on creation and explicit resume afterward. Codex uses exec JSONL,
  captures thread.started.thread_id and resumes that exact ID. Both reject a
  mismatched reported ID, pause uncertain sessions and never fall back to last.
- Each launch replays role/policy/task context through UTF-8 stdin with a
  service-minted scoped credential in its environment. Sessions, deliveries,
  runs and output stay in the local registry. Model IDs are passed unchanged.
- Claude default permissions are manual with permission-prompts=none. Codex
  uses workspace-write with approval_policy=never. Approval-requiring actions
  are denied; no bypass flags are used. Subagent tools/features are disabled.
  Existing harness configuration may still impose tighter policy. Ownership
  context is not filesystem isolation; guard/sandbox coverage remains unverified.
- Output streams drain concurrently, use chunks up to 4096 characters, and
  stop on bounded protocol/output limits. Known launch secrets are redacted.
  Timeout and cancellation stop only the owned process tree: Windows job
  objects or POSIX process groups. A Windows job is attached immediately after
  spawn; children created before assignment are a known OS scheduling gap, not
  a hostile-process security guarantee. Failure to attach refuses execution.
- Restart marks interrupted runs uncertain/unknown and pauses their queues.
  It does not adopt external processes or kill stale PIDs. Sessions cannot be
  replaced or recovered by guessing; that remains an explicit future workflow.
- Fake-subprocess tests cover probes, both first-start/resume protocols, busy
  FIFO queues, stop/child cleanup, crash before/after identity, changed resume
  IDs, malformed/missing terminal output, provider errors, restart, Unicode,
  quoted multiline input, secret redaction and finite smoke failure handling.
- `mas smoke-adapters --plan --workspace <empty scratch dir>` prints the live
  test proposal without writes or model calls. Without --plan it makes at most
  four CLI turns (start/resume for each provider), with tools disabled for
  Claude and read-only sandbox for Codex, and writes a scratch receipt. It
  stops on failure without retry/fallback. Running it requires Owner approval.
  Provider-internal request count/currency cost cannot be inferred from four
  CLI turns; subscription/API quota is consumed. Existing login is used and
  provider-owned session persistence is not copied into the project.

Command evidence: installed Claude 2.1.296 and local Codex exec/resume --help;
[Claude CLI reference](https://code.claude.com/docs/en/cli-reference) and
[official Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode).
Local flags, lifecycle protocol and process cleanup passed offline tests; live
provider behavior is deliberately not claimed verified before the ASK smoke.

## Decided 2026-10-24

The Owner accepted the recommendations in ASK-001 and added Gemini for a later
release and exactly this one PC. The verbatim answer remains in that thread.

- MAS is a localhost web app on this Windows PC, with no login screen, lab PC or
  remote execution. Local browser session, Host/Origin checks and CSRF protection
  remain required. Projects may have relay/manual members, never remote control.
- Claude Code + Codex first; opencode next; Gemini CLI planned, not in v1.
  Relay membership is represented from the start. Only Owner-approved members;
  temporary subagents disabled by default and switchable only in a later slice.
- Explicit allowed call edges, review before merge, Owner merge/push defaults;
  kickoff/reviews manual, weekly scheduling opt-in in a later slice. The global
  service concurrency default is two, distinct from each project's lower cap.
  Chain/call/runtime limits are finite; no automatic paid-model fallback.
- Workflow checks plus verified harness sandbox coverage are the accepted
  boundary. Hard OS isolation is a separate milestone. No provider transcript
  copying; captured run output retained seven days; handoff records retained
  until explicit project archive/delete handling.
- New projects first, schema-driven wizard with preview/apply; import preview
  later. Owner answers in the UI; read-only run output is the common baseline,
  interactive attachment capability-gated and outside slice 1.
- Python 3.12, FastAPI, Uvicorn, Pydantic, stdlib SQLite, pytest and uv accepted;
  React 18/TypeScript/Vite frontend, English, working name MAS. Exact dependency
  installation still needs the later install ASK. Use an explicit uv cache path.
- Slice 1 is the surface in docs/contract/openapi.yaml. Leases, rituals, commits,
  archive, import and interactive attachment are later, not implemented paths.
  The project schema reserves their configuration without activating them.
- As agreed with Fable in AGENT-001/CONTRIBUTING.md, service writes serialize and
  return 409 on detected handoff conflicts. Direct CLI writers remain a known
  concurrency limit; do not fork the installed handoff CLI. Propose locking to
  its skill author with a failing test before claiming multi-writer safety.
- AGENT-002 R1-R4: GET /session bootstraps SPA cookie/CSRF; local-only
  dev_allowed_origins defaults to [] (Vite origin opt-in). Capabilities list
  permission profiles, including default for each available harness. Omitted
  agent prompt_file resolves to its cwd/.agents/mas/prompts/<id>.md; preview/apply
  creates a missing prompt from role plus preamble and preserves existing files.
  Chat follow-ups reuse the Delivery.thread_ref rather than making new threads.

## 1. Agreement and changes to the frontend draft

I agree with the control room plus launcher, independent resumable members,
multiple projects, file-based handoff record, and frontend/backend split in
frontend-plan.md sections 1 and 2. The frontend talks only to the service;
backend code, adapters, tests, CLI and generation templates live in backend/.
Shared contracts need both members' review before either implements them.

The following adjustments were accepted by Fable and the Owner:

1. Levels are configurable labels with explicit call permissions, not exactly
   three levels or fifteen agents. Provide the reference topology as a template.
2. One durable member identity has one current harness session, potentially many
   process runs. Session replacement is an explicit recovery action with history.
   Persisted conversation does not guarantee unlimited model memory.
3. A call to a busy member is durably queued. Native messaging is an optional
   adapter capability; it is not a portable promise. Never open a second writer
   on a session to deliver a message. Unknown liveness blocks dispatch.
4. Hooks are workflow checks, not universal filesystem isolation. Report guard
   coverage honestly; arbitrary shell subprocess writes need harness/OS sandbox
   enforcement to establish a stronger boundary. Do not claim every harness has
   equivalent hooks or that a write lease can expand its sandbox live.
5. Localhost still needs protection against another web page issuing commands.
   Serve UI and API together, bind loopback, validate Host/Origin, use a local
   browser session and CSRF protection. No cloud login is required for this scope.

The original v1 request forbids extra agents. The reference system's later design
permits throw-away subagents and lead merges. Those
are not blanket approvals for this app. ASK-001 settled B3/B4 as described above.
This repository's current instructions still control work here.

## 2. Evidence and reuse

Read: the reference system's design notes, README.md, mas.py, all hooks/*.py,
skills/SKILL.md, and calling, cross-folder and Qwen runbooks.
The reference system is partial: agents.json and config.json are empty;
the web implementation, runtime sessions and settings are absent. A working
import or live queue cannot be demonstrated from this snapshot.

| Reference | Reuse | Change |
|---|---|---|
| .handoff protocol and CLI | Thread lifecycle, authorship, clock stamping, summary, sync, doctor | Wrap a pinned CLI; preserve offline use; add a jointly reviewed concurrency strategy before concurrent writes |
| mas.py call_message / resolve_log | Thread-first calls and scoped log references | Use explicit project/log/thread IDs; no fixed dev/test/req/rel routing |
| mas.py clean_env / env_for | Strip inherited harness session identity | Per-adapter environment allowlist; preserve necessary auth without exposing credentials |
| mas.py session registry | Durable session identity and previous IDs | SQLite transactions, session generations, launch receipts, unique live ownership |
| mas.py cmd_call | Resume independent members | It currently returns instructions for opencode; implement a real adapter |
| mas.py cmd_call / running_map | Detect running sessions before resume | Check-and-start has a race; add one dispatcher, locks, fencing and unknown state |
| mas.py launch_window | Explicit interactive windows | Avoid shell interpolation and lossy sanitize_for_cmd; deliver text through stdin/files |
| hooks/session_start.py | Reorientation from project files and waiting threads | Generic dates/rituals, bounded context, no milestones from the reference system embedded in code |
| hooks/guard.py and _common.py | Policy cases and failure examples | Regex checks and exception fall-through are not security isolation; canonical path handling and explicit degraded coverage |
| hooks/post_git.py | Commit audit concept | Supplement hooks with repository scans; unknown author stays unknown |
| skills/references | Kickoff, review, proposal-and-apply, bug loop, helper briefs | Parameterized templates, editable by project owners; no fixed roles or weekday |

Members' results remain their own thread replies. Console output is diagnostic
and optional Owner visibility; it is not a substitute for a member's answer.
Helpers are a separately declared role with a sponsoring member responsible for
logging their evidence. Do not silently turn full members into helpers.

## 3. Service architecture and persistence

Use one Python 3.12 service: FastAPI for HTTP/validation, asyncio for supervision,
SQLite via stdlib sqlite3 for durable runtime state, and an argparse CLI. Keep
domain operations separate from HTTP handlers. FastAPI supports OpenAPI and JSON
Schema; that fits the shared contract requirement
([official features](https://fastapi.tiangolo.com/features/)). Dependencies and
versions are pinned only during implementation after approval; nothing installed
for this plan. No Redis, Celery, model API orchestration framework, or mandatory
external database is needed for the proposed local scope.

Components under backend/: registry, policy, adapters, supervisor, queue,
handoff gateway/indexer, scaffold generator, rituals, event store, API, CLI,
tests/fixtures, and packaging metadata. One service owns dispatch per machine
profile. No multi-worker HTTP deployment until dispatch leadership is designed.

Three distinct authorities:

- Project intent: <project>/.agents/mas/project.json plus prompts/runbooks.
  Versioned and readable by all harnesses; no credentials or transient PIDs.
  Registered external working folders require explicit configuration.
- Collaboration evidence: each registered .handoff directory. Threads are
  canonical; INDEX sections and service indexes are rebuildable projections.
- Runtime: local app-data SQLite database plus bounded run-output files. Tables
  cover projects/config revisions, agents, session generations, runs, deliveries,
  ritual occurrences, leases, event outbox, operation journals and idempotency
  receipts. Keep this database on local disk, not an SMB share.

Do not import credentials from provider auth files or commit session databases.
Harnesses use their existing login. Store only references to credential sources.
Reserve transcript capture for the configured retention policy; store task IDs,
status and redacted diagnostics by default. Back up the DB consistently with its
journal; project exports omit secrets and transient handles. Missing runtime
state must lead to reconciliation, never automatic replay of every old call.

Configuration saves validate schema and cross-references, require If-Match on
revision, and persist a desired draft in the registry. Preview/apply promotes it
to project.json with atomic replace and generated files through a journal.
Malformed external edits preserve the last
valid projection and block launches until reconciled. Generated roster/config
drift is reported; do not overwrite human ownership decisions silently.

Project creation has a preview/apply journal: show exact generated paths and
conflicts, then apply only the reviewed revision and hashes. Updating config is
not permission to replace existing AGENTS.md, CLAUDE.md, hooks or settings.
Merge only clearly marked generated sections; record backups and conflicts.
Reference import is read-only preview first, preserves original files and IDs,
and validates missing configuration. Importing an ID does not launch it.

## 4. Adapter contract and session lifecycle

Each adapter implements probe, validate_config, prepare_launch, start, resume,
observe, stop, and normalize_event. Optional attach, deliver_live and export
capabilities are advertised separately. probe reports executable/version,
supported modes, permission profile, guard coverage and limitations. Executable
paths are local configuration; untrusted requests cannot submit shell commands.

| Harness | Creation / resume | Liveness / stop | Busy delivery |
|---|---|---|---|
| Claude Code | Baseline print-mode turn with structured output; capture/verify session ID and resume that ID | Owned process handle; native supervisor listing/stop only after version probe | Queue until managed turn ends; optional native messaging/attachment after verification |
| Codex CLI | exec JSONL; capture thread.started.thread_id; exec resume with explicit ID | Owned process handle plus normalized turn events; stop managed process tree | Queue next exec resume; no assumed CLI mid-turn input |
| opencode | run JSON events; capture returned session ID; later run with explicit --session | Owned process; session list is inventory, not proof a turn is running; stop managed tree | Queue until turn exits; optional server adapter later |
| Gemini CLI (planned, not in v1) | Reserved probe/validate/start/resume adapter slot; commands and ID format unverified | Reserved observe/stop contract; no executable or process support in v1 | Unavailable in v1; no dispatch |
| Relay/manual | Export a brief with log links; no process creation | Report manually managed, never fabricate running status | Pending/manual delivery; verbatim attributed reply on return |

Documented foundations: [Claude CLI](https://code.claude.com/docs/en/cli-reference)
documents print, explicit session IDs, resume and background mode;
[Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
documents JSONL events and explicit-ID resume;
[opencode CLI](https://opencode.ai/docs/cli/) documents run JSON output,
--session and session inventory. These support the baseline design, not a claim
that every installed version behaves identically. Check actual command help and
perform approved adapter smoke tests before supporting a version. Do not use
--last, infer IDs from names, or assume a preallocated UUID was accepted.

Baseline uses short supervised headless turns against persistent conversations.
Claude background supervision is an enhancement, not the common abstraction.
On Windows, use an owned process tree/job where available, keep launch children
hidden, drain stdout and stderr concurrently, and bound buffers/timeouts. Stop
requests attempt graceful termination then terminate only the verified owned
tree. Preserve session history. Never kill by broad process name or stale PID.

Agent status: offline, starting, busy, needs_input, idle, stopping, error,
unknown. Include observed_at, source and reason. Queue length is separate from
status. Missing permission events mean unknown/attention-required, not a guessed
needs_input signal. A process ending successfully does not prove a thread was
answered; record reply observation separately from process exit.

Persist Session(project_id, agent_id, generation, harness_session_id,
created_at, previous_generation, mode) separately from Run(run_id, session_ref,
delivery_id, process_identity, state, exit_code). Session replacement increments
generation and keeps the old ID; queued work is paused for explicit reconciliation.
Replay identity, ownership pointers and required sandbox/settings at each launch
using the adapter's verified mechanism. Do not assume changed role prompts are
automatically adopted by an existing conversation.

On restart: recover dispatch journals; identify owned processes by PID plus
creation time and adapter session identity; reconcile before releasing locks.
A failed observation returns unknown and holds work. Externally opened sessions
need explicit adoption/close guidance. Where no reliable external liveness probe
exists, promise single-writer only for MAS-managed sessions and make this limit
visible. resume-window must attach to an existing writer if supported, or reserve
the stopped session for an interactive process; never race background dispatch.

## 5. Calls, messages and queue semantics

1. Authenticate caller and validate project, membership, invocation mode, target
   call edge, budget, log reference and thread existence. Agent identity comes
   from a scoped launch credential, not a caller-supplied frm field.
2. Require a thread for member-to-member work. A helper requires a bounded brief
   and sponsor. Owner chat preserves exact text and records durable task context
   before launching work; short operational chat can reference an existing thread.
3. Persist Delivery plus an event in one transaction before returning 202.
   Idempotency-Key identifies retries; same key with different content conflicts.
4. A per-session dispatcher serializes FIFO delivery, takes an exclusive lease
   with generation/fencing token, and rechecks policy/config/session immediately
   before starting. A live writer keeps the item queued unless acknowledged live
   delivery is a verified adapter feature. Never inject text by terminal keystrokes.
5. Persist a launch receipt and session identity. Update state from actual events.
   Member completion is the thread reply; helper completion needs sponsor review.

Delivery states: queued, dispatching, running, awaiting_manual, completed,
failed, cancelled, uncertain. Track process outcome and thread_reply_observed
separately; successful process exit without a required reply is missing_reply.
Lost acknowledgement after launch becomes uncertain, not an automatic duplicate.
Exactly-once effects across filesystem and external harnesses are not promised.
Retry only failures known to occur before launch; reconcile uncertain launches.

Limit concurrent runs globally and per project/harness, plus call-chain depth,
call count and elapsed time. Include correlation_id, parent_delivery_id and
hop_count; calls return immediately so A waiting on B does not block the service.
Do not hold a session transaction while a member waits for another member.
No automatic ping-pong on every file change, unbounded retries, or silent model
fallback after throttling. Runtime/call limits are enforceable; monetary limits
are estimates unless the harness supplies reliable usage data.

Owner Stop pauses the agent's queue and stops the current run; otherwise its next
queued message would immediately wake it. Resume requires an explicit action.
Cancel targets one delivery. Archive disables schedules/new calls and requires
active runs to be resolved, without deleting the project or its evidence.

## 6. Handoff gateway, hooks and policy

Use the installed stdlib handoff.py through uv run --no-project, explicit root,
structured argv and body files. Set an allowed cache directory and offline mode
where needed; never resolve project dependencies during a log command. Pin/check
the CLI revision; treat a repository-provided executable as trusted only after
registration review. Read-only indexing parses data and does not execute it.

All API/CLI log mutations share a per-log writer queue. The existing CLI checks
for changed contents before atomic replacement but this is not a full lock
across writers. Offline/direct member writes would need the same cross-process
lock to guarantee no lost replies. Slice 1 detects conflicts and returns 409;
it does not claim multi-writer safety or fork the installed CLI. Propose locking
to the skill author with a failing concurrency test. Never replace another
member's history row.

Use operation journals around reply + sync + wake: record exact body and thread
revision, append once, then queue wake. If a crash makes append outcome ambiguous,
inspect/reconcile before retry; a repeated browser submission must not produce
two Owner comments. UI reply forces Owner identity; agent credentials cannot
access that route. Reply text stays verbatim, with CLI clock attribution.

Indexer watches configured logs, debounces events and periodically rescans by
content hash. Network shares/unavailable folders yield stale state with reason,
not empty logs. Malformed threads remain visible with parse errors. Reads include
revision and freshness. Sanitize markdown at rendering; do not serve arbitrary
absolute file paths through a download endpoint.

Generate policy per adapter: reorientation, pre-action checks if supported,
commit/stop notifications if supported, and instruction fallback. Codex hook
parity is unverified; use its configured sandbox/approval mechanisms and report
unsupported hooks instead of emitting Claude settings. opencode plugin hooks
likewise need a versioned test. Deny unregistered launches and policy changes at
the service boundary. Do not turn hooks off silently on failure in guarded mode.

Path validation resolves dot segments and existing symlink/junction ancestors,
handles Windows case/drive/UNC aliases and compares path components. Validate
again on use. Overlapping write ownership needs an explicit shared-file rule.
Log append permissions do not grant arbitrary changes to protocol/roster files.
Keep service credentials/runtime DB outside agent-owned project paths. These
controls protect service operations; agents under the same OS user are not a
hostile-tenant isolation boundary.

Cross-folder default: propose a change in a thread; the owner applies it.
Optional leases name exact resources, grantor, recipient, UTC expiry and approval
thread. Only the owning authority grants/revokes; validate at dispatch and action
time. If a harness cannot enforce expiry during a live run, do not offer live
leases for that adapter. Restart/re-sandbox is explicit where required. Foreign
commits remain the owning team's responsibility.

## 7. First contract proposal

Prefix /api/v1. IDs are stable opaque IDs, not mutable display names. A thread
reference is {project_id, log_id, thread_id}; AGENT-001 alone is ambiguous.
Draft contracts are in docs/contract/openapi.yaml, events.schema.json and
project.schema.json, pending AGENT-002 review. Generate frontend types and
Pydantic v2 DTOs only after both members approve; JSON Schema remains authoritative
for constraints generators cannot express. The table below is the full roadmap;
only paths present in openapi.yaml are slice 1. Apply/preview and control-state
writes are synchronous receipts; queued calls/message/wake return 202 with a
delivery ID. Owner reply returns 201 plus an optional queued wake receipt.

| Endpoint | Meaning |
|---|---|
| GET /health, GET /capabilities | Service health and detected adapter capabilities |
| GET, POST /projects | List / register draft project; registration never starts agents |
| GET, PUT /projects/{p} | Read / revise config with ETag and If-Match |
| POST /projects/{p}/preview, POST /projects/{p}/apply | Proposed generated changes / apply exact reviewed revision and hashes |
| POST /projects/{p}/archive | Disable dispatch and schedules; preserve files |
| GET /projects/{p}/agents | Config plus observed state, capabilities and queue count |
| POST /projects/{p}/agents/{a}/call | {thread_ref, note, mode}; accept one durable delivery |
| POST .../agents/{a}/message | {text, thread_ref?}; exact Owner text, next-turn queue |
| POST .../agents/{a}/wake | Queue bounded reorientation with waiting-thread snapshot |
| POST .../agents/{a}/stop | Pause queue and request managed run stop |
| POST .../agents/{a}/resume-window | Capability-gated attach or exclusive interactive reservation |
| POST .../agents/{a}/resume-queue | Explicitly resume queued work |
| GET /projects/{p}/calls, GET .../calls/{c} | Cursor-paginated deliveries and individual state |
| POST .../calls/{c}/cancel | Cancel pending delivery or request current run cancellation |
| GET /projects/{p}/logs, GET .../logs/{l}/index | Registered logs and derived index/freshness |
| GET .../logs/{l}/threads/{t} | Raw markdown, parsed metadata and revision |
| POST .../logs/{l}/threads/{t}/reply | Owner {body, expected_revision, wake_agent_id?}; forced attribution |
| GET /inbox | ASK aggregation with globally qualified references and freshness |
| GET /projects/{p}/events | Replayable SSE events |
| GET /projects/{p}/runs/{r}/output | Offset-based bounded diagnostic output, optional follow SSE |
| GET /projects/{p}/commits | Repository audit with provenance and unknown authors preserved |
| GET /projects/{p}/doctor | Last diagnostic report; no hidden repair |
| POST /projects/{p}/doctor-runs | Request fresh diagnostics, return operation receipt |
| POST /projects/{p}/rituals/{r}/run | Manual kickoff/review occurrence |
| GET, POST /projects/{p}/leases; POST .../leases/{l}/revoke | Policy-gated exact-file leases |

PUT returns a new revision; async actions return 202 with delivery_id or
operation_id, state, reason and status_url. Errors are
{code, message, details, request_id, retryable}: 401/403 authority, 404 missing,
409 revision/state/idempotency conflict, 422 invalid config/capability,
429 queue limit, 503 unavailable adapter. Lists have items and next_cursor.
Required actions accept Idempotency-Key. Agent CLI uses a separate scoped API
surface with the same domain operations; it cannot impersonate Owner replies.

SSE envelope: {schema_version:1, event_id, project_id, type, occurred_at,
entity_id, revision, correlation_id, payload}. Persist monotonic event IDs in
the outbox; Last-Event-ID resumes after the last applied event. Consumers dedupe.
After retention expiry send stream.reset_required and fetch a snapshot with its
cursor. Heartbeats do not imply agent activity. Separate output chunks from
durable domain events to avoid an output-heavy agent starving the UI.

Events: project.changed, agent.status_changed, delivery.queued,
delivery.state_changed, session.replaced, run.started, run.finished,
thread.changed, inbox.changed, commit.recorded, lease.changed,
ritual.state_changed, doctor.completed, stream.reset_required. thread.changed
carries a reference/revision, not a second authoritative thread body.

Project JSON shape (proposal, not the final schema):

```text
schema_version: 1
project: {id, name, root, timezone, archived}
folders[]: {id, path, repository_id?}
logs[]: {id, folder_id, relative_path: ".handoff", members[]}
levels[]: {id, label, order}
agents[]: {id, name, level_id, role, harness, model, effort?, cwd_folder_id,
  owns[], reads[], log_ids[], skills[], prompt_file,
  log_duty: member|helper, sponsor_agent_id?,
  invocation: callable|owner|relay, launch_mode, permission_profile}
call_policy: {mode: independent|orchestrated|mixed, allowed_edges[],
  subagents: disabled|ephemeral, max_parallel, max_chain_depth,
  max_calls_per_chain, run_timeout_seconds}
guard_policy: {mode: advisory|guarded, protected_paths[], merge_by,
  pushes: owner, leases_enabled}
rituals[]: {id, kind: kickoff|review|custom, target_agent_id, prompt_file,
  trigger: manual|weekly, timezone, weekday?, local_time?, enabled,
  missed_run_policy: skip|offer_one}
retention: {output_days, event_days, capture_output}
adapter_options: {claude: {...}, codex: {...}, opencode: {...}, gemini: {}}
```

Schema rejects unknown core fields, validates enums, bounds and unique IDs.
Semantic validation checks call graph targets, folder containment, ownership
overlaps, log membership, helper sponsor, invocation restrictions and capability
requirements. Agent model names remain data; never silently substitute one.
Backend-owned local settings hold binary paths and credentials, outside portable
project JSON. Missing invocation mode defaults to independent.

## 8. Rituals, CLI and distribution

Rituals are durable occurrences that enqueue ordinary calls; the scheduler does
not write plans or make agent decisions. Kickoff is once per project occurrence,
weekly reviews have explicit timezone, and manual reruns require a new occurrence
ID. Default manual triggers. Optional weekly scheduling runs only while the
service is active; persist last occurrence and avoid replay storms after downtime.
Specify DST behavior (skip nonexistent local time; first repeated occurrence)
and missed-run policy. No OS task/service registration without a later request.

CLI compatibility: mas init/preview/apply, call, resume, status, doctor, inbox,
web, kickoff, sprint-review, lease and explicit start --fresh. CLI and UI use
the same service, queue and policy; CLI must not become a second launcher when
the service is offline. Offline handoff CLI remains available. --dry-run must
be read-only: no session IDs marked created, temporary launch files, or calls.

Package the backend as a Python project managed by uv with pinned dependencies,
a mas entry point and bundled static frontend output. Windows-first local use;
defer Electron/Tauri, auto-updates and remote workers. Configure input roots,
state directory, port and executable paths rather than hardcoding D: paths.
Any session-support scripts needed later must first reuse/check D:/tools and be
saved/registered there; product source and tests belong in backend/ as assigned.

## 9. Build sequence and acceptance

1. Scope is accepted in ASK-001. Fable reviews the AGENT-002 contract draft;
   both members sign off before generation. Define adapter feature matrix and
   golden contract fixtures.
2. Registry, file preview/apply, handoff indexing and read-only UI. Fake adapter
   proves queue/event behavior without model calls or costs.
3. Supervisor and durable queue; adapter spikes for create, ID capture, resume,
   busy, stop, permission wait, crash and recovery. Ship an adapter only after
   its matrix passes on Windows. Start with Claude + Codex; opencode next,
   Gemini CLI in a later release.
4. Owner replies, cross-agent calls, guards and diagnostic output. Test one
   member-to-member request with actual replies preserved in .handoff.
5. Rituals, import/export, capability-gated leases, recovery and packaging.

Tests live under backend/tests. Use fake subprocesses first; paid live tests
need a bounded, approved run. Required cases: simultaneous calls to one session,
crash between launch and receipt, PID reuse, unavailable probe, busy manual
session, Unicode/quotes in messages, restart with queued work, cancelled wake,
queue paused on Stop, throttling and call-loop limits, SSE replay/reset, stale
config writes, duplicate Owner reply retries, offline handoff writer collision,
malformed log, missing network folder, junction/UNC escape, expired leases,
Host/Origin/CSRF rejection, oversized output, stale scaffold preview, and fake
adapter end-to-end UI contract. Compare repeated test reports and retain only
the newest run plus the required short changes summary, per AGENTS.md.

Release acceptance: two projects with distinct logs/session namespaces; at least
two different harnesses exchanging a thread-first request; no second writer when
busy; exact Owner reply once despite retry; recover a service restart without
duplicate execution; stop keeps the queue paused; doctor exposes unavailable or
unsupported features. Live smoke results, supported versions and guard limits
must be recorded. No implementation/runtime tests were run in this planning turn.

## 10. Settled Owner questions

ASK-001 accepted B1-B10 (with B2/F5 and B10/F6 merged), adding Gemini in the
future and exactly this one PC. The decisions at the top supersede the original
questions; no scope answer remains pending. Fable will consolidate exact backend
and frontend install commands in a separate ASK. Contract details require joint
technical review in AGENT-002, not another Owner questionnaire.
