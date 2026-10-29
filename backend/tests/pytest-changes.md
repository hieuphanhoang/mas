# Pytest changes

Compared with the previous full run: still 94 passed, no regressions.
Owned external folders now pass OpenCode's separate directory gate while the edit
rules retain their owned-path restriction; the fake launch regression covers it.
The existing Starlette/httpx deprecation warning is unchanged.
No saved test reports were replaced or deleted; output is in the terminal.
