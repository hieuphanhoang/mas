# Project Notes

MAS: a multi-agent system (backend/ Python service, frontend/ React UI, docs/contract/ the
shared API contract). See README.md for what it does and how to run it.

- Python via uv (`uv sync --project backend`, `uv run --project backend ...`), never pip.
- Frontend via npm in `frontend/`; regenerate API types with `npm --prefix frontend run gen:api`
  after any change to docs/contract/.
- Never commit `.gitignore` or `.gitattributes`. Stage explicit paths only.

## Multi-agent protocol

When this checkout has a `.handoff/` folder, several agents are working it at once (the folder is
local to that setup and is never published). Before writing anything:

1. Read `.handoff/PROTOCOL.md` - how the shared log works and what you may edit.
2. Read `.handoff/ROSTER.md` - ownership and invocation mode. Never edit a
   directory you do not own; open a thread or propose a contract change instead.
3. Write to the log with `.handoff/handoff.py`, not by hand:
   `python .handoff/handoff.py reply AGENT-004 --frm <you> --body-file msg.md`
   It stamps from the system clock. Never write a timestamp yourself.
4. Run `python .handoff/handoff.py summary <you>` to see what is waiting on
   you. Without a name it lists every live thread rather than yours.
