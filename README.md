# MAS - multi-agent control room

MAS lets a team of independent AI coding agents work on one project together. The agents can come
from different tools (Claude Code and Codex CLI today). Each one keeps its own long-lived session,
owns its own part of the project, and can call the others. You, the owner, watch everything from
one local web page and make the decisions the agents bring to you.

All coordination goes through the file-based **agents-collaboration-protocol**: every request,
answer and decision is a thread in the project's `.handoff/` folder, written by the agent that
said it. Nothing important lives only in a chat window.

This guide covers installation, setting up a project, running the agents, and answering them.

---

## 1. Concepts in one minute

| Term | Meaning |
|---|---|
| **Project** | A folder (and optional extra working folders) that MAS manages. |
| **Agent** | One AI session with a name, a tool (Claude Code or Codex), a model, a role, and the folders it owns. |
| **Level** | A label for grouping agents in the control room, for example "L1 program", "L2 team leads", "L3 workers". |
| **Log** | A `.handoff/` folder: `ROSTER.md` (who owns what), `PROTOCOL.md` (the rules), `INDEX.md` (what is waiting on whom) and `threads/`. |
| **Thread** | One topic in a log. `AGENT-001` is between agents; `ASK-001` is a question to you, always with a recommendation. |
| **Call** | Waking an agent about a thread. You call from the web page; agents call each other with `mas call`. |
| **Call edges** | Which agent may call which. Nobody else can be called. |
| **Permission profile** | What an agent may do without asking, chosen by you once at setup. |

---

## 2. Requirements

- Windows 10 or 11
- Python 3.12 (tested with 3.12.12) and [uv](https://docs.astral.sh/uv/)
- Node.js 20.19+ or 22.12+ with npm (only to build the web page)
- Git
- For real agents: **Claude Code** and/or **Codex CLI**, installed and signed in
- The **agents-collaboration-protocol** skill installed where your agent tools load skills from
  (`%USERPROFILE%\.claude\skills\` for Claude Code, `%USERPROFILE%\.agents\skills\` for Codex).
  Its `scripts/handoff.py` creates and writes the logs.

---

## 3. Install

From the repository root:

```powershell
uv sync --project backend --python 3.12   # backend and its pinned dependencies into backend\.venv
npm ci --prefix frontend           # web page dependencies
npm --prefix frontend run build    # builds frontend\dist, which the backend serves
```

---

## 4. Start MAS

```powershell
uv run --project backend mas serve --real-adapters
```

Open **http://127.0.0.1:8790**. The service listens on this PC only.

| Flag | Effect |
|---|---|
| `--real-adapters` | Agents run as real Claude Code / Codex sessions. This uses your model quota. |
| `--fake-adapter` | A simulated agent that prints three lines and stops. No model calls; use it to try the page, **with its own `--state-dir`** (see below). |
| (neither) | The page works, but no agent is ever started. |
| `--port 8791` | Another port (the default is 8790). |
| `--state-dir <folder>` | Where MAS keeps its own database (default `backend\state`). |

Try the fake mode in a separate state folder and on a throwaway project, for example
`uv run --project backend mas serve --fake-adapter --state-dir backend\state-demo`. Simulated
sessions are recorded like real ones, and an agent that ran in fake mode cannot later be started
with `--real-adapters` in the same state folder: MAS marks it unknown and pauses its queue rather
than guess.

Always start it with `uv run --project backend ...` as above: that puts the `mas` command on the
agents' PATH, which they need to call each other. Stop the service with Ctrl+C; agents' sessions
are kept and resume next time.

---

## 5. Prepare the project folders

Each folder that should have its own log needs a `.handoff/` folder before MAS can use it. Create it
once with the skill's script, in each such folder:

```powershell
cd D:\projects\my-project
# use the folder where the skill is installed on your PC:
#   %USERPROFILE%\.claude\skills\agents-collaboration-protocol   (Claude Code)
#   %USERPROFILE%\.agents\skills\agents-collaboration-protocol   (Codex and other tools)
uv run --no-project "$env:USERPROFILE\.claude\skills\agents-collaboration-protocol\scripts\handoff.py" init --root .
```

This writes `.handoff/PROTOCOL.md`, `ROSTER.md`, `INDEX.md`, `CONTRIBUTING.md`, the `threads/`
folder and a copy of `handoff.py`, and adds a short pointer to the folder's `AGENTS.md` if it has
one. Fill in `ROSTER.md` (members, what each owns, `Invocation mode: orchestrated` if agents may
call each other); the agents read it at every turn.

---

## 6. Register a project

1. **Projects** -> **Register project**.
2. Enter an **Id** (a short slug such as `my-project`), a **Name**, the **Root folder** and your
   **Timezone**. Register.

Registering only stores a draft inside MAS. Nothing is written into your folder yet.

---

## 7. Set up the team

On the project page click **Edit project**. The editor has these tabs:

**General** - name, timezone, how long run output is kept, guard mode.

**Folders and logs** - add each working folder (for example `Requirements`, `Release`) and tick
**Log** for every folder that has a `.handoff/` log.

**Levels** - add, rename and order the levels. **Use the reference arrangement** fills in
"L1 program / L2 team leads / L3 workers".

**Agents** - one entry per agent:

| Field | What to put |
|---|---|
| Name, Id | How the agent is shown and called, for example `Opus-dev` / `opus-dev`. |
| Level | Its lane group. |
| Harness | `claude` or `codex` (`opencode` and `gemini` are planned; `relay` is a chat-only model you paste for). |
| Model, Effort | The exact model, for example `claude-opus-5-5`, `high`. MAS never substitutes another model. |
| Role | What this agent does. On the first apply it becomes the agent's role prompt file (see Apply). |
| Working folder | Where its session runs. |
| Owns / Reads | One `folder:path` per line. Owned paths must not overlap between agents. |
| Duty | **member** (writes its own log replies) or **helper** (does one job from a brief; a member sponsors it). |
| Logs | Which logs it is a member of. |
| Who starts it | **callable by other agents** or **Owner only**. |
| Permission profile | See below. |
| Skills | Usually `agents-collaboration-protocol`. |

**Permission profiles** - chosen here once; agents are never asked at run time:

| Profile | Claude Code | Codex CLI |
|---|---|---|
| `default` | No shell commands that need approval. The agent can read but cannot post replies or call others. | Commands inside its workspace, no network. Can reply, cannot call others. |
| `member` | May run exactly the log tool (`handoff.py`) and `mas call`, and edit files. | Commands inside its workspace **with network to any host**, so it can reach MAS to call others. |

Use `member` for agents that take part in the conversation. Choose the Codex `member` profile only
for agents you trust with network access.

**Call policy** - the mode (`independent`: only you start agents; `orchestrated`: agents may call
along the ticked edges; `mixed`: per agent), a grid of who may call whom (row calls column), and the
limits: agents running at once, call chain depth, calls per chain, and the timeout per run.

**JSON** - the exact document, for advanced edits.

The editor warns you about anything MAS would reject (overlapping ownership, a helper without a
sponsor, missing roles). **Save draft** stores it.

### Apply

Click **Preview generated files**. MAS lists exactly what it will create:
`.agents/mas/project.json` and one role prompt per agent under `.agents/mas/prompts/`. It never
overwrites your `AGENTS.md`, `CLAUDE.md`, settings or logs. Check the list, then **Apply these
changes**. Agents can only be started on an applied project.

Role prompts are created only when missing. If you change an agent's **Role** later, the existing
prompt file is kept (the preview warns that it differs) and the agent keeps using it: edit
`.agents/mas/prompts/<agent id>.md` yourself to change what the agent is told.

---

## 8. Give the agents work

There are two ways.

**Chat with an agent.** Open **Control room**, click the agent's lane, open the **chat** tab, pick
the log and write your request. MAS writes your words, unchanged, as a new thread and wakes the
agent with it. Further messages from the same chat box go into the same thread.

**Call an agent about an existing thread.** Create the thread with the log tool:

```powershell
uv run --no-project .handoff\handoff.py new "Implement the login page" --frm Owner --to Opus-dev --type REQUEST --body-file task.md
```

then, in the agent's drawer, open **call**, choose the thread (threads the agent owes a reply on
are listed first), add an optional one-line note, and press **Call**.

From there the agents work on their own:

- An agent reads the roster, the protocol and its thread, does the work in its own folders, and
  posts its reply in the thread with `handoff.py`.
- When it needs another agent, it opens a thread and runs `mas call <agent> --thread AGENT-007`.
  MAS checks that this call is allowed, queues it if the target is busy, and resumes the target's
  own session. **One session per agent:** a busy agent is never started twice, and if you have an
  agent's session open yourself in a terminal, MAS waits instead of starting a second copy.
- Limits stop runaway chains: calls beyond the chain depth or count are refused.

---

## 9. Watch the work

**Control room** - one lane per agent, grouped by level:

| Lamp | Meaning |
|---|---|
| green **idle** | Finished its turn, waiting for work. |
| amber **busy / starting / stopping** | Working. |
| red **needs_input / error** | Something needs you; the lane shows the reason. |
| grey **offline** | Not started yet in this run of MAS. |

The lane also shows the queue length, "paused" if you stopped it, and the session generation.
Click a lane for its drawer:

- **runs** - every call to this agent with its state. For a member called about a thread,
  `completed` means it posted its reply there and `failed: missing_reply` means it finished
  without one. A helper (called with a brief) completes when its run ends; its sponsor records the
  result. `notified` means the agent was woken after you answered a question; no reply is expected
  and it says nothing about what the agent did.
- **output** - what the agent printed, live, while it runs.
- **Wake up** - asks the agent to look at threads waiting on it. **Stop** - stops the current run
  and pauses its queue; **Resume queue** continues.

**Threads** - every log of the project: "Awaiting owner", "Open", "Conversation history" and
"All", and each thread rendered in full.

**Harnesses** - which tools are installed, their versions, the permission profiles, and how far the
guards reach for each tool, exactly as MAS can verify it.

---

## 10. Answer the agents

Agents never ask you in passing: a decision for you is an `ASK-` thread with a recommendation.
Open **Inbox**:

1. Click a question to read the whole thread.
2. Write your answer. Short answers are fine; "ok" is a decision. Your words are written into the
   thread exactly as typed, as `[Owner, ...]`.
3. Optionally choose an agent under **Then wake** (usually the one that asked) and **Send answer**.

If a log cannot be read (missing, unreadable or out of date), the inbox lists it under a warning.
An empty inbox means nothing is waiting only when there is no such warning; otherwise questions in
that log may be hidden.

---

## 11. Troubleshooting

| You see | What it means / what to do |
|---|---|
| A run ends `failed: missing_reply` | The agent finished without posting in its thread. Read its **output**; often its permission profile is `default`, which cannot run the log tool. Use `member`. |
| Output shows "Permission ... denied" | The command is outside the agent's profile. Change the profile in the project editor, save, preview and apply. |
| A call stays queued with "session open elsewhere" | That agent's session is open in a terminal. Close it; the call then runs. |
| Apply fails with `apply_failed` | The details name the file and the Windows error. Fix that cause (for example access denied, disk full, or a path over 260 characters, then a shorter project folder), and apply the same preview again: MAS finishes the partial apply. |
| An action fails with `unsupported_capability` | Read the message. Usual causes: the tool is not installed or failed its check (see **Harnesses**), MAS was started without `--real-adapters`/`--fake-adapter`, the permission profile is not available for that tool, or the tool is planned (opencode, Gemini). |
| The Codex `member` agent cannot call others | Check the Harnesses page: the profile must show "network on". |
| The page shows "Bootstrap a local session first" | Reload the page; it creates its local session automatically. |

---

## 12. Safety and limits

- MAS listens on 127.0.0.1 only and checks the browser's origin and a per-session token on every
  change. There is no login, so do not expose the port.
- Guards are workflow checks (allowed tools, owned paths, git commands), **not isolation**. Agents
  run as your Windows user.
- Pushing, merging into main and installing software are yours: the protocol and each agent's
  instructions require the agent to ask you in an `ASK-` thread first. MAS does not block these
  commands itself, and an agent with network access (Codex `member`) technically could run them,
  so give that profile only to agents you trust.
- Every model turn uses your provider quota. MAS never falls back to another model.
- One PC only in this version. opencode and Gemini CLI adapters, scheduled rituals (for example a
  weekly review), cross-folder write leases and importing existing projects are planned.

---

## For developers

| Path | What |
|---|---|
| `backend/` | Python service (FastAPI, SQLite): registry, queues, adapters, `mas` CLI |
| `frontend/` | React + TypeScript web page |
| `docs/contract/` | OpenAPI 3.1 contract and JSON schemas both sides generate from |
| `docs/plan/` | Backend and frontend design plans |

```powershell
uv run --project backend pytest                 # backend tests
npm --prefix frontend test                      # frontend tests
npm --prefix frontend run dev                   # page with hot reload on http://127.0.0.1:5173
npm --prefix frontend run gen:api               # regenerate API types after a contract change
```

This repository is developed by AI agents with the same protocol; see `AGENTS.md` and `.handoff/`.
