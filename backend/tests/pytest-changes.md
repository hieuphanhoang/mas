# Pytest changes

Compared with this branch's main baseline: still 91 passed, no regressions.
Existing fake runtime tests now check first-start Claude/OpenCode labels, the
prompt's project/agent first line, and no rename or new session on resume.
The earlier test/levels run passed 96 tests; its five guard/packaging tests are
not on this separate feature/session-labels branch created from main.
The existing Starlette/httpx deprecation warning is unchanged.
No saved test reports were replaced or deleted; output is in the terminal.
