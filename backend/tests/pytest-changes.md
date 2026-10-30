# Pytest changes

Compared with the preceding G1 run: 105 passed instead of 104 passed / 1 failed
(70.50s; basetemp D:/temp/g1ok). History checks now wait for both calls when
creation timestamps tie, instead of assuming request order determines run order.
Compared with R2: one added case covers Owner-confirmed restart reconciliation,
live-writer rejection, validation/authentication, unchanged session identity,
unknown historical outcomes, idempotent replay and release of queued work.
The existing Starlette/httpx deprecation warning is unchanged.
No saved test reports were replaced or deleted; output is in the terminal.
