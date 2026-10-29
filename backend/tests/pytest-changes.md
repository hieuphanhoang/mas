# Pytest changes

Compared with the previous full run: 96 passed, zero failed (was 95 passed and
one CRLF assertion failure in the new test). Owner replies use the packaged CLI
both without a target CLI and with a deliberately failing target CLI present.
Normal-wheel inspection also confirms the licensed CLI is shipped without any
private .handoff files. No package was installed.
The existing Starlette/httpx deprecation warning is unchanged.
No saved test reports were replaced or deleted; output is in the terminal.
