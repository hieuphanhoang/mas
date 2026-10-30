# Pytest changes

Compared with the passing G1 run: 106 passed instead of 105 (38.66s;
basetemp D:/temp/h3full). One added mocked-window case checks the visible hold
reason with an empty queue, clearing after exit, unchanged identity/pause state,
and one status event per reason change rather than events on every polling tick.
The existing Starlette/httpx deprecation warning is unchanged.
No saved test reports were replaced or deleted; output is in the terminal.
