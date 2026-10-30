import base64
import json
from types import SimpleNamespace

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
    # Calls created in the same timestamp tick are ordered by ID, not by which
    # HTTP request returned first. Both must finish before asserting run times.
    for delivery in (first, second):
        poll(client, P + "/calls/" + delivery["delivery_id"], lambda d: d["state"] == "failed")
    listing = client.get("/api/v1" + P + "/calls?agent_id=codex")
    contract_response(listing, "/projects/{project_id}/calls")
    rows = {d["delivery_id"]: d for d in listing.json()["items"]}
    assert rows[first["delivery_id"]]["caller"] == dict(kind="agent", agent_id="fable")
    for row in rows.values():
        run = client.portal.call(app.state.store.get, "run", row["run_id"])
        assert row["run_started_at"] == run["started_at"]
        assert row["run_finished_at"] == run["finished_at"]
    assert "caller" not in client.portal.call(app.state.store.get, "delivery", first["delivery_id"])


def test_owner_confirmation_clears_restart_hold_without_replaying_old_work(real_runtime):
    client, app, _, adapters = real_runtime
    runtime, store = app.state.runtime, app.state.store
    first = mutate(client, "POST", A + "/call", dict(thread_ref=REF)).json()
    done = poll(client, P + "/calls/" + first["delivery_id"], lambda d: d["state"] == "failed").json()
    runtime.external_reason = lambda *_: "session open elsewhere"
    queued = mutate(client, "POST", A + "/call", dict(thread_ref=REF)).json()
    run_id = done["run_id"]
    key = "mas-self:codex"
    def restart():
        delivery = store.get("delivery", first["delivery_id"])
        delivery.update(state="running", process_outcome="running")
        store.put("delivery", delivery["delivery_id"], delivery)
        run = store.get("run", run_id)
        run.update(state="running", finished_at=None)
        store.put("run", run_id, run)
        output = store.get("output", run_id)
        output["eof"] = False
        store.put("output", run_id, output)
        status = runtime.status("mas-self", "codex")
        status.update(state="busy", active_run_id=run_id)
        runtime.save_status("mas-self", status)
        store.put("resume_window", key, dict(project_id="mas-self", agent_id="codex", state="open"))
        store.db.commit()
        Runtime(store, app.state.logs, runtime.handoff, {}, real=True, adapters=adapters)
        return runtime.status("mas-self", "codex")
    before = client.portal.call(restart)
    assert before["state"] == "unknown" and before["queue_paused"]
    assert mutate(client, "POST", A + "/resume-queue").status_code == 409
    for body in ({}, {"confirm_stopped": False}, {"confirm_stopped": 1}, {"confirm_stopped": True, "extra": 1}):
        assert mutate(client, "POST", A + "/resume-queue", body).status_code == 422
    confirmation = {"confirm_stopped": True}
    assert mutate(client, "POST", A + "/stop", confirmation).status_code == 422
    assert client.post("/api/v1" + A + "/resume-queue", json=confirmation,
        headers={"X-MAS-CSRF": "", "Idempotency-Key": "confirm-no-csrf"}).status_code == 403
    assert client.post("/api/v1" + A + "/resume-queue", json=confirmation).status_code == 422
    runtime.tasks[run_id] = SimpleNamespace(done=lambda: False)
    assert mutate(client, "POST", A + "/resume-queue", confirmation).json()["code"] == "agent_busy"
    runtime.tasks.pop(run_id)
    runtime.windows.processes[key] = Window()
    assert mutate(client, "POST", A + "/resume-queue", confirmation).json()["code"] == "agent_busy"
    runtime.windows.processes.pop(key)
    assert mutate(client, "POST", A + "/resume-queue", confirmation).json()["code"] == "agent_busy"
    runtime.external_reason = lambda *_: None
    accepted = mutate(client, "POST", A + "/resume-queue", confirmation, key="confirm-stopped-1")
    assert accepted.status_code == 200, accepted.text
    contract_response(accepted, "/projects/{project_id}/agents/{agent_id}/resume-queue", "post", "200")
    status = accepted.json()
    assert status["state"] == "idle" and status["active_run_id"] is None and not status["queue_paused"]
    assert status["session_id"] == before["session_id"]
    assert status["session_generation"] == before["session_generation"]
    historical = client.get("/api/v1" + P + "/calls/" + first["delivery_id"]).json()
    assert historical["state"] == "failed" and historical["process_outcome"] == "unknown"
    assert historical["reason"] == "owner_confirmed_stopped" and historical["run_id"] == run_id
    assert client.portal.call(store.get, "run", run_id)["state"] == "unknown"
    assert client.portal.call(store.get, "output", run_id)["eof"]
    assert client.portal.call(store.get, "resume_window", key)["state"] == "closed"
    assert client.portal.call(store.get, "reconciliation", key)["source"] == "owner"
    poll(client, P + "/calls/" + queued["delivery_id"], lambda d: d["state"] == "failed")
    assert mutate(client, "POST", A + "/resume-queue", confirmation, key="confirm-stopped-1").json() == status
    assert client.portal.call(runtime.status, "mas-self", "codex")["session_id"] == before["session_id"]


def test_window_reason_updates_without_queued_work_and_emits_once(real_runtime, monkeypatch):
    client, app, _, _ = real_runtime
    runtime = client.portal.call(ready, app)
    window = Window()
    monkeypatch.setattr(resume_window, "supported", lambda: True)
    monkeypatch.setattr(resume_window, "launch", lambda *_: window)
    assert mutate(client, "POST", A + "/resume-window").status_code == 202
    def status(view):
        return next(item["status"] for item in view["items"] if item["config"]["id"] == "codex")
    view = client.get("/api/v1" + P + "/agents").json()
    opened = status(view)
    assert opened["state"] == "idle" and opened["reason"] == "Owner terminal open"
    assert opened["queue_length"] == 0 and not opened["queue_paused"]
    client.portal.call(runtime.tick)
    assert client.get("/api/v1" + P + "/agents").json()["event_cursor"] == view["event_cursor"]
    window.exited = True
    closed_view = poll(client, P + "/agents", lambda v: status(v)["reason"] is None).json()
    closed = status(closed_view)
    assert closed["state"] == "idle" and closed["session_id"] == SESSION
    assert not closed["queue_paused"] and closed["active_run_id"] is None
    assert closed["revision"] != opened["revision"]
    def last_event():
        return json.loads(app.state.store.db.execute("SELECT data FROM events ORDER BY seq DESC LIMIT 1").fetchone()[0])
    event = client.portal.call(last_event)
    assert event["type"] == "agent.status_changed" and event["payload"]["reason"] is None
    assert event["payload"]["revision"] == closed["revision"]
