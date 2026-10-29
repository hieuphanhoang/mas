# Pytest changes

Compared with the previous full run in the private build folder: still 77 passed,
no regressions after the move. The protected-path case now uses .git/file.
The existing Starlette/httpx deprecation warning is unchanged.
No saved test reports were replaced or deleted; output is in the terminal.
