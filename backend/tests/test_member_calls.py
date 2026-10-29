import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mas_backend.adapters import Adapter, AdapterError
from mas_backend.busy import ExternalSessions
from mas_backend.capabilities import probe_capabilities
import mas_backend.busy as busy_module

from conftest import mutate
from test_adapters import real_runtime
from test_runtime import live, poll, P, A, REF


def test_member_profile_rules_and_capabilities(monkeypatch):
    adapter = Adapter("claude", ["fake-claude"])
    argv = adapter.argv("model", candidate="uuid", permission_profile="member")
    assert "Bash(uv run --no-project .handoff/handoff.py:*)" in argv
    assert "Bash(mas call:*)" in argv
    assert "PowerShell(uv run --no-project .handoff/handoff.py:*)" in argv
    assert "PowerShell(mas call:*)" in argv
    assert "Edit" in argv and "Write" in argv
    assert argv[argv.index("--permission-prompts") + 1] == "none"
    assert "--allowedTools" not in adapter.argv("model", candidate="uuid")
    codex = Adapter("codex", ["fake-codex"])
    member = codex.argv("model", permission_profile="member")
    assert "sandbox_workspace_write.network_access=true" in member
    assert member[member.index("--sandbox") + 1] == "workspace-write"
    assert 'approval_policy="never"' in member
    assert "sandbox_workspace_write.network_access=true" not in codex.argv("model")
    assert "sandbox_workspace_write.network_access=true" not in codex.argv("model", smoke=True, permission_profile="member")
    monkeypatch.setattr(Adapter, "probe", lambda self: ("fake 1", None))
    caps = probe_capabilities()
    for harness in ("claude", "codex"):
        assert {p["id"] for p in caps["permission_profiles"] if p["harness"] == harness} == {"default", "member"}
    assert "Network on" in next(p["description"] for p in caps["permission_profiles"] if p["harness"] == "codex" and p["id"] == "member")


def test_reference_inventory_combines_claude_list_and_process_scan(monkeypatch):
    session = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setattr(busy_module, "executable", lambda harness: "fake-claude")
    def run(args, **kwargs):
        if "agents" in args:
            return subprocess.CompletedProcess(args, 0, json.dumps([dict(sessionId=session)]), "")
        if os.name == "nt":
            stdout = json.dumps([dict(Name="codex.exe", CommandLine="codex exec resume " + session)])
        else:
            stdout = "codex exec resume " + session
        return subprocess.CompletedProcess(args, 0, stdout, "")
    monkeypatch.setattr(busy_module.subprocess, "run", run)
    inventory = ExternalSessions()
    assert inventory.reason("claude", session) == "session open elsewhere"
    assert inventory.reason("codex", session) == "session open elsewhere"
    assert inventory.reason("codex", "different-session") is None


def test_external_writer_holds_delivery_until_session_closes(real_runtime):
    client, app, _, _ = real_runtime
    first = mutate(client, "POST", A + "/call", dict(thread_ref=REF)).json()
    poll(client, P + "/calls/" + first["delivery_id"], lambda d: d["state"] == "failed")
    app.state.runtime.external_reason = lambda harness, session_id: "session open elsewhere"
    second = mutate(client, "POST", A + "/call", dict(thread_ref=REF)).json()
    held = poll(client, P + "/calls/" + second["delivery_id"], lambda d: d["reason"] == "session open elsewhere").json()
    assert held["state"] == "queued" and held["run_id"] is None
    app.state.runtime.external_reason = lambda harness, session_id: None
    done = poll(client, P + "/calls/" + second["delivery_id"], lambda d: d["state"] == "failed").json()
    assert done["reason"] == "missing_reply"


def test_agent_side_mas_call_creates_scoped_child_delivery(live):
    client, app, _ = live
    app.state.runtime.delay = 0.8
    mutate(client, "POST", P + "/agents/fable/stop")
    parent = mutate(client, "POST", A + "/call", dict(thread_ref=REF)).json()
    active = poll(client, P + "/calls/" + parent["delivery_id"], lambda d: d["state"] == "running").json()
    secret = app.state.runtime.issue_credential("mas-self", "codex", active["run_id"])
    app.state.store.db.commit()
    class Bridge(BaseHTTPRequestHandler):
        def do_GET(self):
            self.forward()
        def do_POST(self):
            self.forward()
        def forward(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            response = client.request(self.command, self.path, content=raw, headers=dict(self.headers))
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response.content)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = dict(os.environ, MAS_API_URL=f"http://127.0.0.1:{server.server_port}/api/v1", MAS_AGENT_TOKEN=secret,
                   MAS_PROJECT_ID="mas-self", MAS_RUN_ID=active["run_id"], MAS_LOG_ID="main", PYTHONUTF8="1")
        command = Path(sys.executable).with_name("mas.exe" if os.name == "nt" else "mas")
        result = subprocess.run([str(command), "call", "Fable", "--thread", "AGENT-001", "--note", 'Unicode caf\u00e9 "quoted"'],
                                env=env, capture_output=True, text=True, encoding="utf-8", timeout=15)
        assert result.returncode == 0, result.stderr
        child = json.loads(result.stdout)
        assert child["agent_id"] == "fable"
        assert child["parent_delivery_id"] == parent["delivery_id"]
        assert child["correlation_id"] == parent["correlation_id"]
        assert child["hop_count"] == 1
        assert child["state"] == "queued"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
