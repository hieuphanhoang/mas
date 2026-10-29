# Pytest changes

Compared with the previous uncommitted 0.3 run: still 102 passed, no regressions
(30.14s; basetemp D:/temp/mas03-final). The OpenCode terminal case now checks that
effort uses the agent config variant instead of the unsupported TUI --variant flag.
Compared with committed H1: six added cases cover history projections, terminal
commands/profiles, reservation/replay/queue holds, errors and restart reconciliation.
The existing Starlette/httpx deprecation warning is unchanged.
No saved test reports were replaced or deleted; output is in the terminal.
