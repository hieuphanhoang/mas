"""Reference-style session inventory. It holds queued work; never adopts/kills."""
import json
import os
import subprocess
import time

from .adapters import executable, clean_environment


class ExternalSessions:
    def __init__(self):
        self.until = 0
        self.processes = None
        self.claude_ids = set()

    def reason(self, harness, session_id):
        if not session_id:
            return None
        if time.monotonic() >= self.until:
            self.until = time.monotonic() + 2
            self.claude_ids = set()
            opts = dict(capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3,
                        env=clean_environment(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            claude = executable("claude")
            if claude:
                try:
                    result = subprocess.run([claude, "agents", "--json"], **opts)
                    for row in json.loads(result.stdout or "[]"):
                        if row.get("sessionId") and row.get("status") not in ("completed", "stopped", "exited", "failed"):
                            self.claude_ids.add(row["sessionId"])
                except (OSError, ValueError, subprocess.TimeoutExpired, AttributeError, TypeError):
                    pass
            try:
                if os.name == "nt":
                    script = 'Get-CimInstance Win32_Process -Filter "Name=\'claude.exe\' OR Name=\'codex.exe\' OR Name=\'opencode.exe\'" | Select-Object Name,CommandLine | ConvertTo-Json -Compress'
                    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], **opts)
                    rows = json.loads(result.stdout or "[]")
                    if isinstance(rows, dict):
                        rows = [rows]
                    self.processes = [(r["Name"].lower().removesuffix(".exe"), r.get("CommandLine") or "") for r in rows] if result.returncode == 0 else None
                else:
                    result = subprocess.run(["ps", "-eo", "args="], **opts)
                    self.processes = [(h, line) for line in result.stdout.splitlines() for h in ("claude", "codex", "opencode")
                                      if h in line.split(" ", 1)[0]] if result.returncode == 0 else None
            except (OSError, ValueError, subprocess.TimeoutExpired, TypeError, KeyError):
                self.processes = None
        if harness == "claude" and session_id in self.claude_ids:
            return "session open elsewhere"
        if self.processes is None:
            return "session liveness unavailable"
        return "session open elsewhere" if any(h == harness and session_id in line for h, line in self.processes) else None
