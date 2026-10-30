# Pytest changes

Compared with the preceding R2 run: 104 passed instead of 103 passed / 1 failed
(43.80s; basetemp D:/temp/r2pass). Process-tree cancellation now waits for the
fake child's record instead of a fixed delay that could cancel before startup.
Compared with R1: one added fake-subprocess case checks Claude owned Python/pytest
permissions and negative commands; the earlier oversized rule set was compacted
and the five guard tests now pass (initial draft: three passed, two spawn failures).
The existing Starlette/httpx deprecation warning is unchanged.
No saved test reports were replaced or deleted; output is in the terminal.
