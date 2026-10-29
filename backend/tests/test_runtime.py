import asyncio
import copy
import json
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from mas_backend.app import create_app
from mas_backend.common import Problem, stamp
from mas_backend.events import Events
from mas_backend.runtime import Runtime
from mas_backend.store import Store

from conftest import CONTRACT, mutate, write_log
from test_api import contract_response

P = "/projects/mas-self"
A = P + "/agents/codex"
REF = dict(project_id="mas-self", log_id="main", thread_id="AGENT-001")


@pytest.fixture
def live(tmp_path, config):
    app = create_app(tmp_path / "i2-state", CONTRACT, capabilities={}, fake_adapter=True, fake_delay=0.08)
    write_log(config)
    with TestClient(app, base_url="http://127.0.0.1:8766") as client:
        client.headers["X-MAS-CSRF"] = client.get("/api/v1/session").json()["csrf_token"]
        response = mutate(client, "POST", "/projects", config)
        assert response.status_code == 201, response.text
        revision = response.json()["revision"]
        preview = mutate(client, "POST", P + "/preview", revision=revision)
        assert preview.status_code == 200, preview.text
        response = mutate(client, "POST", P + "/apply", {"preview_id": preview.json()["preview_id"]}, revision)
        assert response.status_code == 200, response.text
        yield client, app, config
    app.state.store.db.close()


def poll(client, url, predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = client.get("/api/v1" + url)
        assert result.status_code == 200, result.text
        if predicate(result.json()):
            return result
        time.sleep(0.02)
    pytest.fail(f"Timed out: {url}: {result.text}")


def test_fake_delivery_output_session_reuse_and_contract(live):
    client, app, config = live
    views = client.get("/api/v1" + P + "/agents")
    contract_response(views, "/projects/{project_id}/agents")
    first_session = None
    for _ in range(2):
        response = mutate(client, "POST", A + "/call", {"thread_ref": REF})
        assert response.status_code == 202, response.text
        contract_response(response, "/projects/{project_id}/agents/{agent_id}/call", "post", "202")
        ident = response.json()["delivery_id"]
        done = poll(client, P + "/calls/" + ident, lambda d: d["state"] == "failed")
        assert done.json()["reason"] == "missing_reply"
        assert done.json()["process_outcome"] == "succeeded"
        assert not done.json()["thread_reply_observed"]
        output = client.get("/api/v1" + P + "/runs/" + done.json()["run_id"] + "/output?limit=1")
        contract_response(output, "/projects/{project_id}/runs/{run_id}/output")
        assert output.json()["next_offset"] == "1"
        assert output.json()["eof"] is False
        tail = client.get("/api/v1" + P + "/runs/" + done.json()["run_id"] + "/output?offset=1")
        assert tail.json()["eof"] is True
        assert len(tail.json()["chunks"]) == 2
        statuses = client.get("/api/v1" + P + "/agents").json()["items"]
        status = next(a["status"] for a in statuses if a["config"]["id"] == "codex")
        assert status["state"] == "needs_input"
        assert status["session_generation"] == 1
        if first_session:
            assert status["session_id"] == first_session
        first_session = status["session_id"]
    calls = client.get("/api/v1" + P + "/calls")
    contract_response(calls, "/projects/{project_id}/calls")
    assert len(calls.json()["items"]) == 2


def test_stop_pause_cancel_resume_fifo(live):
    client, app, _ = live
    stop = mutate(client, "POST", A + "/stop")
    contract_response(stop, "/projects/{project_id}/agents/{agent_id}/stop", "post")
    queued = []
    for _ in range(3):
        response = mutate(client, "POST", A + "/call", {"thread_ref": REF})
        assert response.status_code == 202
        queued.append(response.json())
    for delivery in queued:
        poll(client, delivery["status_url"].removeprefix("/api/v1"), lambda d: d["state"] == "queued")
    assert mutate(client, "POST", A + "/wake").json()["code"] == "queue_paused"
    cancelled = mutate(client, "POST", P + "/calls/" + queued[1]["delivery_id"] + "/cancel")
    assert cancelled.json()["state"] == "cancelled"
    assert mutate(client, "POST", A + "/resume-queue").status_code == 200
    first = poll(client, P + "/calls/" + queued[0]["delivery_id"], lambda d: d["state"] == "running")
    assert client.get(queued[2]["status_url"]).json()["state"] == "queued"
    stopped = mutate(client, "POST", A + "/stop")
    assert stopped.json()["state"] == "stopping"
    assert stopped.json()["queue_paused"] is True
    assert mutate(client, "POST", A + "/resume-queue").status_code == 409
    poll(client, P + "/calls/" + first.json()["delivery_id"], lambda d: d["state"] == "cancelled")
    assert client.get(queued[2]["status_url"]).json()["state"] == "queued"
    mutate(client, "POST", A + "/resume-queue")
    poll(client, P + "/calls/" + queued[2]["delivery_id"], lambda d: d["state"] == "failed")


def test_wake_and_no_pending(live):
    client, _, config = live
    wake = mutate(client, "POST", A + "/wake")
    assert wake.status_code == 202, wake.text
    assert wake.json()["thread_ref"] == REF
    path = Path(config["project"]["root"]) / ".handoff/threads/ASK-002-test.md"
    path.write_text(path.read_text().replace("| **Status** | answered |", "| **Status** | closed |"))
    assert mutate(client, "POST", P + "/agents/fable/wake").json()["code"] == "no_pending_work"


def test_guards_and_idempotency(live):
    client, app, config = live
    stop = mutate(client, "POST", A + "/stop")
    response = mutate(client, "POST", A + "/call", {"thread_ref": REF}, key="stable-call-key")
    assert mutate(client, "POST", A + "/call", {"thread_ref": REF}, key="stable-call-key").json() == response.json()
    assert len(client.get("/api/v1" + P + "/calls").json()["items"]) == 1
    wrong = dict(REF, project_id="other")
    assert mutate(client, "POST", A + "/call", {"thread_ref": wrong}).status_code == 403
    assert mutate(client, "POST", A + "/call", {"thread_ref": REF, "caller_id": "owner"}).status_code == 422
    assert mutate(client, "POST", A + "/call", {"brief": {"folder_id": "root", "path": "brief.md"}}).status_code == 422
    old = client.get("/api/v1" + P).json()
    config["project"]["name"] = "New revision"
    assert mutate(client, "PUT", P, config, old["revision"]).status_code == 200
    assert mutate(client, "POST", A + "/call", {"thread_ref": REF}).json()["code"] == "config_not_applied"


def test_active_config_and_apply_blocked(live):
    client, _, config = live
    record = client.get("/api/v1" + P).json()
    preview = mutate(client, "POST", P + "/preview", revision=record["revision"]).json()
    call = mutate(client, "POST", A + "/call", {"thread_ref": REF}).json()
    poll(client, P + "/calls/" + call["delivery_id"], lambda d: d["state"] == "running")
    assert mutate(client, "PUT", P, config, record["revision"]).json()["code"] == "active_run_conflict"
    assert mutate(client, "POST", P + "/apply", {"preview_id": preview["preview_id"]}, record["revision"]).json()["code"] == "active_run_conflict"


def test_owner_reply_exact_body_revision_and_retry(live):
    client, app, config = live
    route = P + "/logs/main/threads/ASK-001"
    before = client.get("/api/v1" + route).json()
    text = "\r\n  Owner exact words: `quoted` $() | Unicode: caf\u00e9\r\n\r\n"
    wrong = mutate(client, "POST", route + "/reply", dict(body=text, expected_revision="stale"))
    assert wrong.status_code == 409
    assert wrong.json()["code"] == "revision_conflict"
    assert client.get("/api/v1" + route).json()["markdown"] == before["markdown"]
    payload = dict(body=text, expected_revision=before["metadata"]["revision"])
    result = mutate(client, "POST", route + "/reply", payload, key="reply-exact-key")
    assert result.status_code == 201, result.text
    contract_response(result, "/projects/{project_id}/logs/{log_id}/threads/{thread_id}/reply", "post", "201")
    after = client.get("/api/v1" + route).json()["markdown"]
    assert after.replace("\r\n", "\n").endswith(text.replace("\r\n", "\n") + "\n")
    assert "\r\r\n" not in after
    assert mutate(client, "POST", route + "/reply", payload, key="reply-exact-key").json() == result.json()
    assert client.get("/api/v1" + route).json()["markdown"] == after
    assert client.get("/api/v1/inbox").json()["items"] == []


def test_message_creates_then_reuses_thread(live):
    client, _, config = live
    mutate(client, "POST", A + "/stop")
    message = mutate(client, "POST", A + "/message", dict(text="First message", log_id="main"))
    assert message.status_code == 202, message.text
    contract_response(message, "/projects/{project_id}/agents/{agent_id}/message", "post", "202")
    reference = message.json()["thread_ref"]
    assert reference["thread_id"] != REF["thread_id"]
    before = list((Path(config["project"]["root"]) / ".handoff/threads").glob("AGENT-*.md"))
    followup = mutate(client, "POST", A + "/message", dict(text="Follow-up", thread_ref=reference))
    assert followup.status_code == 202, followup.text
    assert followup.json()["thread_ref"] == reference
    assert list((Path(config["project"]["root"]) / ".handoff/threads").glob("AGENT-*.md")) == before


def test_reply_paused_wake_and_bad_target_before_append(live):
    client, _, _ = live
    route = P + "/logs/main/threads/ASK-001"
    doc = client.get("/api/v1" + route).json()
    payload = dict(body="Approved.", expected_revision=doc["metadata"]["revision"], wake_agent_id="missing")
    assert mutate(client, "POST", route + "/reply", payload).status_code == 404
    assert client.get("/api/v1" + route).json()["metadata"]["revision"] == doc["metadata"]["revision"]
    mutate(client, "POST", P + "/agents/fable/stop")
    payload["wake_agent_id"] = "fable"
    result = mutate(client, "POST", route + "/reply", payload)
    assert result.status_code == 201, result.text
    assert result.json()["wake_state"] == "queued"
    assert result.json()["wake_delivery"]["state"] == "queued"


def test_event_contract_replay_retention_and_header_precedence(live):
    client, app, _ = live
    mutate(client, "POST", A + "/stop")
    mutate(client, "POST", A + "/call", {"thread_ref": REF})
    batch = app.state.events.batch("mas-self", 0)
    schema = json.loads((CONTRACT / "events.schema.json").read_text())
    project = json.loads((CONTRACT / "project.schema.json").read_text())
    registry = Registry().with_resource("project.schema.json", Resource.from_contents(project))
    validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
    assert any(e["type"] == "delivery.queued" for e in batch)
    for event in batch:
        validator.validate(event)
    last = int(batch[-1]["event_id"])
    assert app.state.events.batch("mas-self", last) == []
    # A finite reset stream exercises actual HTTP framing and precedence.
    response = client.get("/api/v1" + P + "/events?after=0", headers={"Last-Event-ID": str(last + 100)})
    assert response.headers["cache-control"] == "no-cache"
    assert "event: stream.reset_required" in response.text
    assert '"reason": "cursor_ahead"' in response.text
    app.state.store.db.execute("UPDATE events SET occurred_at='2000-01-01T00:00:00Z' WHERE project_id='mas-self'")
    app.state.store.db.commit()
    reset = app.state.events.batch("mas-self", 0)[0]
    validator.validate(reset)
    assert reset["payload"]["reason"] == "cursor_expired"
    assert client.get("/api/v1" + P + "/events?after=-1").status_code == 400


def test_output_disabled_expired_and_ahead(live):
    client, app, _ = live
    result = mutate(client, "POST", A + "/call", {"thread_ref": REF}).json()
    done = poll(client, P + "/calls/" + result["delivery_id"], lambda d: d["state"] == "failed").json()
    route = "/api/v1" + P + "/runs/" + done["run_id"] + "/output"
    assert client.get(route + "?offset=9999").status_code == 400
    output = app.state.store.get("output", done["run_id"])
    output["enabled"] = False
    app.state.store.put("output", done["run_id"], output)
    app.state.store.db.commit()
    assert client.get(route).json()["code"] == "output_disabled"
    output.update(enabled=True, expires_at="2000-01-01T00:00:00Z")
    app.state.store.put("output", done["run_id"], output)
    app.state.store.db.commit()
    assert client.get(route).json()["code"] == "output_expired"


def test_restart_marks_active_uncertain_and_retains_pending(live):
    client, app, config = live
    mutate(client, "POST", A + "/stop")
    first = mutate(client, "POST", A + "/call", {"thread_ref": REF}).json()
    second = mutate(client, "POST", A + "/call", {"thread_ref": REF}).json()
    # Simulate the durable state left by a crash without creating real processes.
    first.update(state="running", process_outcome="running")
    app.state.store.put("delivery", first["delivery_id"], first)
    app.state.store.db.commit()
    recovered = Runtime(app.state.store, app.state.logs, app.state.runtime.handoff, {}, fake=True)
    assert recovered.delivery("mas-self", first["delivery_id"])["state"] == "uncertain"
    assert recovered.delivery("mas-self", second["delivery_id"])["state"] == "queued"
    assert recovered.status("mas-self", "codex")["state"] == "unknown"
    assert mutate(client, "POST", A + "/resume-queue").status_code == 409


def test_no_fake_flag_no_process_start(client, registered):
    result = mutate(client, "POST", A + "/call", {"thread_ref": REF})
    assert result.status_code == 422
    assert result.json()["code"] == "unsupported_capability"


def test_scoped_active_credentials_caller_edges_and_expiry(live):
    client, app, _ = live
    app.state.runtime.delay = 0.8
    parent = mutate(client, "POST", A + "/call", {"thread_ref": REF}).json()
    active = poll(client, P + "/calls/" + parent["delivery_id"], lambda d: d["state"] == "running").json()
    secret = app.state.runtime.issue_credential("mas-self", "codex", active["run_id"])
    app.state.store.db.commit()
    headers = {"Authorization": "Bearer " + secret, "Idempotency-Key": "agent-child-key"}
    assert client.get("/api/v1" + P + "/agents", headers=headers).status_code == 200
    assert client.get("/api/v1/projects", headers=headers).status_code == 403
    assert client.get("/api/v1/projects/other/agents", headers=headers).status_code == 403
    assert client.post("/api/v1" + A + "/stop", headers=headers).status_code == 403
    child = client.post("/api/v1" + P + "/agents/fable/call", json={"thread_ref": REF}, headers=headers)
    assert child.status_code == 202, child.text
    assert child.json()["parent_delivery_id"] == parent["delivery_id"]
    assert child.json()["correlation_id"] == parent["correlation_id"]
    assert child.json()["hop_count"] == 1
    assert client.post("/api/v1" + A + "/call", json={"thread_ref": REF},
                       headers=dict(headers, **{"Idempotency-Key": "self-edge-key"})).status_code == 403
    mutate(client, "POST", A + "/stop")
    poll(client, P + "/calls/" + parent["delivery_id"], lambda d: d["state"] == "cancelled")
    assert client.get("/api/v1" + P + "/agents", headers=headers).status_code == 401


def test_partial_append_uncertain_blocks_fresh_keys(live, monkeypatch):
    client, app, config = live
    route = P + "/logs/main/threads/ASK-001"
    before = client.get("/api/v1" + route).json()
    count = 0
    def interrupted(*args, **kwargs):
        nonlocal count
        count += 1
        raise Problem(409, "uncertain", "Injected interruption")
    monkeypatch.setattr(app.state.runtime.handoff, "execute", interrupted)
    data = dict(body="Do not duplicate", expected_revision=before["metadata"]["revision"])
    first = mutate(client, "POST", route + "/reply", data, key="uncertain-key")
    assert first.status_code == 409
    assert first.json()["code"] == "uncertain"
    assert mutate(client, "POST", route + "/reply", data, key="uncertain-key").status_code == 409
    assert mutate(client, "POST", route + "/reply", data, key="fresh-after-uncertain").status_code == 409
    assert count == 1


def test_reply_committed_when_wake_fails(live, monkeypatch):
    client, app, _ = live
    route = P + "/logs/main/threads/ASK-001"
    before = client.get("/api/v1" + route).json()
    def reject(*args, **kwargs):
        raise Problem(503, "injected_failure", "Queue unavailable")
    monkeypatch.setattr(app.state.runtime, "enqueue", reject)
    data = dict(body="Approved once", expected_revision=before["metadata"]["revision"], wake_agent_id="fable")
    first = mutate(client, "POST", route + "/reply", data, key="wake-failure-key")
    assert first.status_code == 201
    assert first.json()["wake_state"] == "failed"
    assert mutate(client, "POST", route + "/reply", data, key="wake-failure-key").json() == first.json()
    assert client.get("/api/v1" + route).json()["markdown"].count("Approved once") == 1


def test_manual_and_planned_dispatch_rules(live):
    client, app, config = live
    record = app.state.store.project("mas-self")
    agent = next(a for a in record["config"]["agents"] if a["id"] == "codex")
    agent.update(launch_mode="manual")
    app.state.store.save_project(record)
    app.state.store.db.commit()
    manual = mutate(client, "POST", A + "/call", {"thread_ref": REF})
    assert manual.status_code == 202
    assert manual.json()["state"] == "awaiting_manual"
    assert manual.json()["run_id"] is None
    time.sleep(0.1)
    assert not app.state.runtime.tasks
    agent.update(harness="gemini")
    app.state.store.save_project(record)
    app.state.store.db.commit()
    planned = mutate(client, "POST", A + "/call", {"thread_ref": REF})
    assert planned.json()["code"] == "unsupported_capability"


def test_helper_completes_without_fabricated_member_reply(live):
    client, app, config = live
    record = app.state.store.project("mas-self")
    helper = copy.deepcopy(record["config"]["agents"][1])
    helper.update(id="helper", name="Helper", log_duty="helper", sponsor_agent_id="codex", log_ids=[], owns=[])
    record["config"]["agents"].append(helper)
    app.state.store.save_project(record)
    app.state.store.db.commit()
    (Path(config["project"]["root"]) / "brief.md").write_text("A bounded helper task.")
    route = P + "/agents/helper/call"
    response = mutate(client, "POST", route, {"brief": {"folder_id": "root", "path": "brief.md"}})
    assert response.status_code == 202, response.text
    done = poll(client, P + "/calls/" + response.json()["delivery_id"], lambda d: d["state"] == "completed")
    assert done.json()["thread_ref"] is None
    assert done.json()["thread_reply_observed"] is False


def test_persisted_receipt_and_outbox_survive_reopen(live, tmp_path):
    client, app, config = live
    mutate(client, "POST", A + "/stop")
    first = mutate(client, "POST", A + "/call", {"thread_ref": REF}, key="reopen-idempotency-key")
    cursor = app.state.store.cursor("mas-self")
    reopened = Store(app.state.store.directory)
    try:
        assert reopened.cursor("mas-self") == cursor
        assert reopened.get("delivery", first.json()["delivery_id"])["state"] == "queued"
        assert Events(reopened).batch("mas-self", 0)
        principal = client.cookies.get("mas_session")
        receipt = reopened.mutate(principal, "POST", "/api/v1" + A + "/call", "reopen-idempotency-key",
                                 {"thread_ref": REF}, lambda: pytest.fail("Must replay, not enqueue twice"))
        assert receipt["body"] == first.json()
    finally:
        reopened.db.close()
