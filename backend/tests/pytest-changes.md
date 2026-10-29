# Pytest changes

Compared with the previous full run: still 91 passed, no regressions.
OpenCode's probe now accepts help on stderr; the fake CLI reproduces this
installed 1.18.34 behavior. The existing probe test covers that correction.
The existing Starlette/httpx deprecation warning is unchanged.
No saved test reports were replaced or deleted; output is in the terminal.
