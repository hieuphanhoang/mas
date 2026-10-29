# Pytest changes

Compared with the previous test/levels run: still 96 passed, no regressions.
The merged suite now also checks first-start labels and unchanged session IDs
on resume, retaining all guard and packaged-CLI regression coverage.
The existing Starlette/httpx deprecation warning is unchanged.
No saved test reports were replaced or deleted; output is in the terminal.
