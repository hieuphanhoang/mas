# Pytest changes

Compared with the previous successful full run: 95 passed (was 94), no regressions.
Fake launches now cover normalized Claude Windows edit paths, cwd-relative owned
paths, and exact absolute service mas call rules for Claude and OpenCode.
The first attempt could not create D:/temp in the sandbox (90 setup errors and
one environment-dependent failure); the approved rerun passes all 95 tests.
The existing Starlette/httpx deprecation warning is unchanged.
No saved test reports were replaced or deleted; output is in the terminal.
