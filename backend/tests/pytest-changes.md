# Pytest changes

Compared with the preceding R1 run: 103 passed instead of 102 passed / 1 failed
(38.09s; basetemp D:/temp/mas-r1-ok). The history fixture now accesses its live
database on the app event-loop thread, fixing the intermittent missing-input read.
Compared with 0.3's 102 tests, one new fake-subprocess test proves the agent finds
this service's mas executable when the parent PATH has no Scripts directory,
and that the inherited PATH tail is preserved.
The existing Starlette/httpx deprecation warning is unchanged.
No saved test reports were replaced or deleted; output is in the terminal.
