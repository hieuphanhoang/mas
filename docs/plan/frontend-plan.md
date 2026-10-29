# Frontend plan - draft 2 (Fable, 2026-10-23)

Note for this repository: the threads named below (ASK-001, AGENT-001 to AGENT-005) are in the
private build log kept outside this repository; the decisions they record are written out here.

Status: agreed between Fable and Codex in `.handoff/threads/AGENT-001` (draft 2 carries the six
adjustments from `docs/plan/backend-plan.md` section 1). Waiting on the Owner's answers to
ASK-001 before any implementation.

Decided by the Owner on 2026-10-24 (ASK-001, all recommendations accepted; quote in the thread):

- Scope S0 confirmed. Harnesses: Claude Code + Codex in v1, opencode next, **Gemini CLI joins
  in a later release** (adapter slot reserved); relay members in the data model from day one.
- **Exactly one PC (this one)** in v1: UI on localhost with Host/Origin/CSRF, no login, no
  remote execution, no lab PC.
- New projects first; read-only import preview of existing MAS projects later.
- Wizard creates and edits projects, ending in preview + apply; files stay hand-editable.
- No extra members or temporary subagents by default (per-project switch later). Explicit call
  edges per project; review before merge; merge and push stay the Owner's; weekly schedule
  opt-in, kickoff and review manual.
- Guards are workflow checks plus the harness's verified sandbox; coverage shown per adapter.
- Two active turns globally at first, finite chain depth / calls / runtime, no automatic paid
  fallback. No transcript copies; run output kept 7 days; `.handoff/` until archived.
- Stack: backend Python 3.12 + FastAPI + Uvicorn + Pydantic + SQLite via uv, pytest; frontend
  React 18 + TypeScript + Vite, API types generated from the contract, own small design system.
  UI delivered as a localhost page served by the backend. English only. Working name: MAS.
- Git initialised locally on `main`; no remote until the Owner names the account.
- ASK answers are given in the UI and transcribed verbatim; output pane read-only, attach
  capability-gated.

Decided by the Owner on 2026-10-29 (AGENT-003):

- Permissions are chosen once, at project setup, per agent in the project editor (the
  reference's `mas init` model). Agents never ask at run time.
- An agent wakes another only through the backend (`mas call`), which keeps one running session
  per agent and also holds the call when the session is open elsewhere, as the reference did.

Decisions promoted from AGENT-001:

- Levels are configurable labels with explicit call edges (`call_policy.allowed_edges`); the
  reference topology (L1/L2/L3) is a template, not the model.
- Member identity, harness session (with generations) and process run are three objects and
  the UI shows them as such.
- Calls to a busy member queue; queue length is shown separately from status. Native messaging
  and terminal attachment are adapter capabilities (`GET /capabilities`); the UI hides what an
  adapter does not advertise.
- Hooks are workflow checks (tool paths, git commands), not filesystem isolation. The doctor
  screen shows guard coverage per adapter honestly.
- Localhost still gets Host/Origin validation, a local browser session cookie and a CSRF token
  on every mutating call.
- Saving a project config and applying generated files are separate steps: the wizard ends
  with preview (paths, diffs, conflicts) then an explicit Apply of that reviewed revision.
- Thread references are qualified: {project_id, log_id, thread_id}. API prefix `/api/v1`,
  ETag/If-Match on config, 202 + delivery_id on async actions, SSE envelope with replay.
- Contract work happens in AGENT-002 after ASK-001, split into `slice-1` and `later`.

## 1. What the app is (shared understanding, to be confirmed by Codex and the Owner)

A reusable "control room + launcher" for teams of independent AI coding agents. It generalises the
earlier single-project multi-agent system (the "reference system") so that any project can be run
the same way:

- a **project** = a root folder, a set of working folders, and a roster of agents on levels
  (L1 program, L2 team leads, L3 workers), each agent one long-lived resumable session;
- agents run on **different harnesses** (Claude Code, Codex CLI, opencode, maybe relay-only chat
  models) and **call each other directly** through the launcher, with the `.handoff/` file
  protocol (`agents-collaboration-protocol` skill) as the record of what was asked and decided;
- the **Owner** starts the first agent, runs rituals (kickoff, weekly review), answers `ASK-`
  threads, and can talk to any agent at any time;
- **guards** (hooks per harness, where the harness supports them) check tool paths and git
  commands against ownership; coverage differs per adapter and is reported, not assumed.

What the reference does today and the app must keep: `mas init / kickoff / call / resume /
sprint-review / status / doctor / lease / inbox / web`, session registry (`sessions.json`),
per-agent prompts and settings, hooks (guard, session_start re-orientation, stop check, commit
audit), runbooks (`mas-ops` skill), the control-room page (lanes, lamps, drawer, chat, wake/stop).

What is new: many projects in one app; agents and harnesses defined by data, not by code; a UI
to create and edit a project (roster, folders, ownership, prompts) instead of hand-written JSON;
a backend API so that the UI, the CLI and the agents' hooks all talk to the same state.

## 2. Proposed split

| Area | Owner | Path |
|---|---|---|
| Web UI (control room, project wizard, thread browser, ASK inbox) | Fable | `frontend/` |
| Backend service (project/agent registry, session adapters per harness, launcher, log reader, scheduler, API, CLI, hooks generation) | Codex | `backend/` |
| API contract (OpenAPI + event schema) | joint | `docs/contract/` |
| Plans | each its own | `docs/plan/frontend-plan.md` (Fable), `docs/plan/backend-plan.md` (Codex) |

The frontend never reads the filesystem or starts processes; it talks only to the backend API.
The backend owns everything that touches the machine. This keeps the Codex territory bounded
(terminal, processes, files, infra) and the Claude territory bounded (UI), per
`references/task-fit.md`.

## 3. Frontend proposal

### 3.1 Screens

1. **Projects** - list of registered projects (name, root, agents count, live agents, waiting
   ASKs). Create project (wizard), open project, archive.
2. **Project wizard / settings** - steps: root folder and working folders; levels (labels,
   order) and agents (name, harness, model, effort, folder, owns, reads, skills, role prompt,
   invocation, log duty member/helper, sponsor for helpers); call policy (allowed call edges
   drawn as a graph, limits); rituals (kickoff, review cadence, who runs them); guard policy;
   then **preview** (exact generated paths, diffs, conflicts with existing AGENTS.md / settings
   / hooks) and **apply** of that reviewed revision. Save and apply are distinct API calls.
   A "reference topology" template pre-fills the L1/L2/L3 arrangement of the reference system.
3. **Control room** (the `mas web` page, generalised) - one lane per agent grouped by level
   label: lamp (offline / starting / busy / needs input / idle / stopping / error / unknown),
   queue length, current session generation, current activity, activity strip, threads owed,
   last call. Level tabs. Click a lane: drawer with runs, threads, output pane (read-only), chat
   box (message becomes the agent's next turn; queued if busy), Wake up / Stop (pauses the
   queue) / Resume queue / Attach-in-window when the adapter advertises it.
4. **Threads** - browser of every log (L1 and each folder): INDEX sections (awaiting owner, open,
   history, all), thread view rendered from the markdown, filters by member/status/type. Read only
   except the Owner's answers (next item).
5. **Owner inbox** - every open `ASK-` across all projects with its recommendation; answer form
   that writes the Owner's words verbatim as `[Owner, ...]` through the backend (which runs
   `handoff.py reply`), then triggers the asking agent.
6. **Calls and timeline** - who called whom and when (calls.log), commits per repo (commits.log),
   helper runs; a simple timeline per day.
7. **Doctor** - the `mas doctor` result as a checklist with fix hints.

### 3.2 Stack (my recommendation; Owner to confirm)

- React 18 + TypeScript + Vite, single-page app served by the backend on localhost (same as
  `mas web` today, so no CORS, no auth, no second server). TanStack Query for API state, an
  SSE/WebSocket client for live lamps. No heavy UI kit: a small own design system (tokens, light
  and dark), so the app does not look like a template.
- Markdown rendering of threads client-side; code blocks and tables preserved.
- API types generated from `docs/contract/openapi.yaml` (openapi-typescript), so drift is a
  build error, not a runtime surprise (protocol section 2).
- Live output: a read-only terminal pane (xterm.js) fed by the backend's log stream; the real
  interactive window stays a terminal the Owner opens (`resume --mode window`).

### 3.3 What the frontend needs from the backend (contract draft, to be written jointly)

- `GET /projects`, `POST /projects`, `GET /projects/{id}`, `PUT /projects/{id}` (config as JSON
  schema the wizard renders from);
- `GET /projects/{id}/agents` with live status; `POST .../agents/{name}/call` (thread, note,
  mode), `.../wake`, `.../stop`, `.../message` (chat to a running agent), `.../resume-window`;
- `GET /projects/{id}/logs` (every `.handoff` log), `GET .../logs/{key}/index`,
  `GET .../logs/{key}/threads/{id}`, `POST .../logs/{key}/threads/{id}/reply` (Owner answers
  only; `frm` forced to Owner);
- `GET /inbox` (all ASK- across projects);
- `GET /projects/{id}/events` (SSE: agent status, new comment, new call, commit);
- `GET /projects/{id}/doctor`, `GET .../calls`, `GET .../commits`, `GET .../runs/{id}/output`
  (streaming).
- A JSON schema for the project config (agents, harness adapters, rituals, guards) so the wizard
  can render forms from it rather than hard-code them.

## 4. Questions I need the Owner to answer (frontend side)

Merged with Codex's B1..B10 into `.handoff/threads/ASK-001` (F5 merged with B2, F6 with B10).
Kept here for reference; the ASK thread is the version the Owner answers.

F1. Delivery form: a localhost web page served by the backend (like `mas web`, my recommendation),
    a desktop app (Tauri or Electron), or a VS Code extension panel?
F2. Stack: React + TypeScript + Vite as above, or a preference (Svelte, Vue, plain HTML)?
F3. Must the UI create and edit projects (wizard, prompts, roster) or is it enough to edit the
    config files by hand and have the UI read-only for configuration?
F4. Does the Owner answer ASK- threads in the UI (verbatim transcription by the backend) or only
    in the agents' windows as today?
F5. Single user on localhost only, or reachable from another PC (the lab PC case) with a login?
F6. Live agent output inside the browser (read-only terminal pane) wanted, or links to windows
    are enough?
F7. Language of the UI: English only?
F8. A name for the app (the reference calls it "MAS").
