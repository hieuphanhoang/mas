import base64
import json

import pytest

from mas_backend import resume_window
from mas_backend.adapters import Adapter
from mas_backend.runtime import Runtime
from conftest import mutate
from test_adapters import real_runtime
from test_api import contract_response
from test_runtime import A, P, REF, poll

SESSION = "11111111-1111-4111-8111-111111111111"


class Window:
    exited = False

    def poll(self):
        return 0 if self.exited else None


def ready(app):
    runtime = app.state.runtime
    status = runtime.status("mas-self", "codex")
    status.update(session_id=SESSION, session_generation=1, state="idle", active_run_id=None)
    runtime.save_status("mas-self", status)
    app.state.store.db.commit()
    return runtime


@pytest.mark.parametrize("harness", ["claude", "codex", "opencode"])
def test_terminal_command_uses_explicit_session_profile_and_private_environment(harness, tmp_path, monkeypatch):
    agent = dict(harness=harness, model="ollama/qwen3.5:latest" if harness == "opencode" else "exact-model",
                 permission_profile="member", effort="high" if harness == "opencode" else None)
    session = "ses_example" if harness == "opencode" else SESSION
    cwd = tmp_path / "owner's $(1+1) [folder]"
    owned = cwd / "member"
    owned.mkdir(parents=True)
    monkeypatch.setenv("GEMINI_API_KEY", "private-provider-key")
    monkeypatch.setenv("MAS_AGENT_TOKEN", "never-forward-this-token")
    command, env = resume_window.prepare(Adapter(harness, ["fake-harness.exe"]), agent, session,
        cwd, [owned], [cwd / ".handoff/handoff.py"])
    assert "Set-Location -LiteralPath " + resume_window.literal(cwd) in command
    assert "owner''s $(1+1) [folder]" in command
    assert "'" + session + "'" in command
    assert "private-provider-key" not in command
    assert "MAS_AGENT_TOKEN" not in env
    assert env["UV_OFFLINE"] == "true"
    assert "--print" not in command and "'exec'" not in command and "'run'" not in command
    if harness == "claude":
        assert "'--resume'" in command and "Edit(member/**)" in command
        assert "'--permission-prompts' 'none'" in command
    elif harness == "codex":
        assert "'resume'" in command and "'--sandbox' 'workspace-write'" in command
        assert 'approval_policy="never"' in command
        assert "sandbox_workspace_write.network_access=true" in command
    else:
        settings = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        assert "--variant" not in command
        assert settings["agent"]["mas"]["variant"] == "high"
        assert settings["agent"]["mas"]["model"] == agent["model"]
        assert settings["provider"]["ollama"]["models"]["qwen3.5:latest"]["options"]["options"]["num_ctx"] == 32768
        assert settings["permission"]["edit"]["*"] == "deny"
        assert env["GOOGLE_GENERATIVE_AI_API_KEY"] == "private-provider-key"
        assert "$env:OPENCODE_CONFIG_CONTENT = " in command and "'--agent' 'mas'" in command
    captured = {}
    def popen(argv, **kwargs):
        captured.update(argv=argv, **kwargs)
        return Window()
    monkeypatch.setattr(resume_window.subprocess, "Popen", popen)
    resume_window.launch(command, env, cwd)
    assert "-NoExit" in captured["argv"]
    assert base64.b64decode(captured["argv"][-1]).decode("utf-16le") == command
    assert captured["creationflags"] == 0x10
    assert captured["cwd"] == cwd
    assert not any(k in captured for k in ("stdout", "stderr", "stdin"))


def test_resume_window_reserves_before_launch_replays_and_holds_queue(real_runtime, monkeypatch):
    client, app, _, _ = real_runtime
    runtime = client.portal.call(ready, app)
    window = Window()
    launches = []
    monkeypatch.setattr(resume_window, "supported", lambda: True)
    def launch(command, env, cwd):
        assert runtime.windows.reason("mas-self", "codex")
        assert app.state.store.get("resume_window", "mas-self:codex")["state"] == "opening"
        launches.append(command)
        return window
    monkeypatch.setattr(resume_window, "launch", launch)
    opened = mutate(client, "POST", A + "/resume-window", key="open-terminal-1")
    assert opened.status_code == 202, opened.text
    contract_response(opened, "/projects/{project_id}/agents/{agent_id}/resume-window", "post", "202")
    assert mutate(client, "POST", A + "/resume-window", key="open-terminal-1").json() == opened.json()
    assert len(launches) == 1
    assert mutate(client, "POST", A + "/resume-window").json()["code"] == "agent_busy"
    assert runtime.active("mas-self")
    call = mutate(client, "POST", A + "/call", dict(thread_ref=REF)).json()
    held = poll(client, P + "/calls/" + call["delivery_id"], lambda d: d["reason"] is not None).json()
    assert held["state"] == "queued" and held["run_id"] is None
    assert "Owner terminal" in held["reason"]
    mutate(client, "POST", A + "/stop")
    assert not window.exited  # Stop owns only managed work.
    window.exited = True
    mutate(client, "POST", A + "/resume-queue")
    done = poll(client, P + "/calls/" + call["delivery_id"], lambda d: d["state"] == "failed").json()
    assert done["reason"] == "missing_reply"
    assert runtime.status("mas-self", "codex")["session_id"] == SESSION
    assert mutate(client, "POST", A + "/resume-window", key="open-terminal-1").json() == opened.json()
    assert len(launches) == 1


def test_resume_window_errors_release_and_restart_hold(real_runtime, monkeypatch):
    client, app, _, adapters = real_runtime
    runtime = app.state.runtime
    monkeypatch.setattr(resume_window, "supported", lambda: True)
    assert mutate(client, "POST", A + "/resume-window").json()["code"] == "no_session"
    client.portal.call(ready, app)
    assert client.post("/api/v1" + A + "/resume-window", headers={"X-MAS-CSRF": "", "Idempotency-Key": "no-csrf-1"}).status_code == 403
    assert client.post("/api/v1" + A + "/resume-window").status_code == 422
    status = runtime.status("mas-self", "codex")
    status.update(state="busy", active_run_id="active")
    runtime.save_status("mas-self", status)
    app.state.store.db.commit()
    assert mutate(client, "POST", A + "/resume-window").json()["code"] == "agent_busy"
    client.portal.call(ready, app)
    runtime.external_reason = lambda *_: "session open elsewhere"
    assert mutate(client, "POST", A + "/resume-window").json()["code"] == "agent_busy"
    runtime.external_reason = lambda *_: None
    def fail(*args):
        raise OSError("test terminal launch failure")
    monkeypatch.setattr(resume_window, "launch", fail)
    failed = mutate(client, "POST", A + "/resume-window")
    assert failed.status_code == 503 and failed.json()["code"] == "terminal_unavailable"
    assert runtime.windows.reason("mas-self", "codex") is None
    monkeypatch.setattr(resume_window, "supported", lambda: False)
    assert mutate(client, "POST", A + "/resume-window").json()["code"] == "unsupported_capability"
    monkeypatch.setattr(resume_window, "supported", lambda: True)
    monkeypatch.setattr(resume_window, "launch", lambda *_: Window())
    assert mutate(client, "POST", A + "/resume-window").status_code == 202
    restarted = Runtime(app.state.store, app.state.logs, runtime.handoff, {}, real=True, adapters=adapters)
    assert restarted.status("mas-self", "codex")["state"] == "unknown"
    assert restarted.status("mas-self", "codex")["queue_paused"]
    assert "reconciliation" in restarted.windows.reason("mas-self", "codex")


def test_call_history_metadata_and_snapshot(real_runtime):
    client, app, _, _ = real_runtime
    runtime = client.portal.call(ready, app)
    runtime.external_reason = lambda *_: "session open elsewhere"
    first = mutate(client, "POST", A + "/call", dict(thread_ref=REF)).json()
    second = mutate(client, "POST", A + "/call", dict(thread_ref=REF)).json()
    listing = client.get("/api/v1" + P + "/calls?agent_id=codex&limit=1")
    contract_response(listing, "/projects/{project_id}/calls")
    row = listing.json()["items"][0]
    assert row["caller"] == dict(kind="owner", agent_id=None)
    assert row["run_started_at"] is row["run_finished_at"] is None
    cursor = listing.json()["next_cursor"]
    def change_caller():
        intent = app.state.store.get("delivery_input", first["delivery_id"])
        intent["caller_agent_id"] = "fable"
        app.state.store.put("delivery_input", first["delivery_id"], intent)
        app.state.store.db.commit()
    client.portal.call(change_caller)
    frozen = client.get("/api/v1" + P + "/calls?agent_id=codex&limit=1&cursor=" + cursor).json()["items"][0]
    assert frozen["caller"]["kind"] == "owner"
    runtime.external_reason = lambda *_: None
    poll(client, P + "/calls/" + second["delivery_id"], lambda d: d["state"] == "failed")
    listing = client.get("/api/v1" + P + "/calls?agent_id=codex")
    contract_response(listing, "/projects/{project_id}/calls")
    rows = {d["delivery_id"]: d for d in listing.json()["items"]}
    assert rows[first["delivery_id"]]["caller"] == dict(kind="agent", agent_id="fable")
    for row in rows.values():
        run = client.portal.call(app.state.store.get, "run", row["run_id"])
        assert row["run_started_at"] == run["started_at"]
        assert row["run_finished_at"] == run["finished_at"]
    assert "caller" not in client.portal.call(app.state.store.get, "delivery", first["delivery_id"])
