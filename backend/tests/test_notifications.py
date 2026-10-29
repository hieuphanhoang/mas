import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from mas_backend.store import Store
from mas_backend.runtime import Runtime

from conftest import CONTRACT, mutate, write_log
from test_api import contract_response
from test_runtime import live, poll, P, A, REF


def notify(client, target="fable", key="notification-key"):
    route = P + "/logs/main/threads/ASK-001"
    metadata = client.get("/api/v1" + route).json()["metadata"]
    data = dict(body="Owner approved this answer.", expected_revision=metadata["revision"], wake_agent_id=target)
    response = mutate(client, "POST", route + "/reply", data, key=key)
    assert response.status_code == 201, response.text
    contract_response(response, "/projects/{project_id}/logs/{log_id}/threads/{thread_id}/reply", "post", "201")
    return response, data


def test_notification_targets_answered_ask_completes_without_comment(live):
    client, app, config = live
    # Another thread owed by Fable sorts earlier than the answered ASK.
    path = Path(config["project"]["root"]) / ".handoff/threads/AGENT-001-test.md"
    path.write_text(path.read_text().replace("Fable -> Codex", "Codex -> Fable").replace("**[Fable,", "**[Codex,"))
    response, data = notify(client)
    delivery = response.json()["wake_delivery"]
    assert delivery["purpose"] == "notification"
    assert delivery["thread_ref"]["thread_id"] == "ASK-001"
    done = poll(client, P + "/calls/" + delivery["delivery_id"], lambda d: d["state"] in ("completed", "failed"))
    assert done.json()["state"] == "completed"
    assert done.json()["process_outcome"] == "succeeded"
    assert done.json()["reason"] is None
    assert done.json()["thread_reply_observed"] is False
    route = P + "/logs/main/threads/ASK-001/reply"
    assert mutate(client, "POST", route, data, key="notification-key").json() == response.json()
    assert len(app.state.runtime.calls("mas-self")) == 1


def test_notification_no_pending_and_paused(live):
    client, app, config = live
    write_log(config, asks=[("ASK-001", "open", "Fable", "Owner", "Fable")])
    mutate(client, "POST", P + "/agents/fable/stop")
    response, _ = notify(client)
    delivery = response.json()["wake_delivery"]
    assert delivery["purpose"] == "notification"
    assert delivery["state"] == "queued"
    status = app.state.runtime.status("mas-self", "fable")
    assert status["queue_paused"] is True
    mutate(client, "POST", P + "/agents/fable/resume-queue")
    done = poll(client, P + "/calls/" + delivery["delivery_id"], lambda d: d["state"] == "completed")
    assert done.json()["reason"] is None


def test_task_wake_unchanged_requests_cannot_override_purpose(live):
    client, _, _ = live
    bad = mutate(client, "POST", A + "/call", dict(thread_ref=REF, purpose="notification"))
    assert bad.status_code == 422
    bad = mutate(client, "POST", A + "/wake", dict(purpose="notification"))
    assert bad.status_code == 422
    response = mutate(client, "POST", A + "/wake")
    assert response.json()["purpose"] == "task"
    done = poll(client, P + "/calls/" + response.json()["delivery_id"], lambda d: d["state"] == "failed")
    assert done.json()["reason"] == "missing_reply"


def test_notification_cancellation_and_uncertainty_preserved(live):
    client, app, _ = live
    app.state.runtime.delay = 0.3
    response, _ = notify(client)
    delivery = response.json()["wake_delivery"]
    poll(client, P + "/calls/" + delivery["delivery_id"], lambda d: d["state"] == "running")
    mutate(client, "POST", P + "/calls/" + delivery["delivery_id"] + "/cancel")
    done = poll(client, P + "/calls/" + delivery["delivery_id"], lambda d: d["state"] == "cancelled")
    assert done.json()["process_outcome"] == "cancelled"
    assert done.json()["purpose"] == "notification"


def test_notification_process_failure_visible(live, monkeypatch):
    client, app, _ = live
    original_get = app.state.store.get
    once = [True]
    def fail_output(kind, key):
        if kind == "output" and once[0]:
            once[0] = False
            raise OSError("Injected fake-adapter output failure")
        return original_get(kind, key)
    monkeypatch.setattr(app.state.store, "get", fail_output)
    response, _ = notify(client)
    delivery = response.json()["wake_delivery"]
    done = poll(client, P + "/calls/" + delivery["delivery_id"], lambda d: d["state"] == "failed")
    assert done.json()["reason"] == "adapter_failed"
    assert done.json()["process_outcome"] == "failed"


def test_manual_notification_and_restart_keep_actual_states(live):
    client, app, _ = live
    record = app.state.store.project("mas-self")
    record["config"]["agents"][0]["launch_mode"] = "manual"
    app.state.store.save_project(record)
    app.state.store.db.commit()
    response, _ = notify(client)
    delivery = response.json()["wake_delivery"]
    assert delivery["state"] == "awaiting_manual"
    assert delivery["purpose"] == "notification"
    # Simulate the durable interruption boundary without starting a subprocess.
    delivery.update(state="running", process_outcome="running")
    app.state.store.put("delivery", delivery["delivery_id"], delivery)
    app.state.store.db.commit()
    recovered = Runtime(app.state.store, app.state.logs, app.state.runtime.handoff, {}, fake=True)
    result = recovered.delivery("mas-self", delivery["delivery_id"])
    assert result["purpose"] == "notification"
    assert result["state"] == "uncertain"
    assert result["process_outcome"] == "unknown"
    assert recovered.status("mas-self", "fable")["queue_paused"] is True


def test_old_delivery_shape_migration_and_receipt_audit(live, tmp_path):
    client, app, _ = live
    mutate(client, "POST", A + "/stop")
    current = mutate(client, "POST", A + "/call", {"thread_ref": REF}).json()
    old = copy.deepcopy(current)
    old.pop("purpose")
    old.update(kind="wake", state="failed", reason="missing_reply", process_outcome="succeeded")
    directory = tmp_path / "old-registry"
    store = Store(directory)
    store.put("delivery", old["delivery_id"], old)
    store.put("page", "old-page", dict(items=[old], scope="old", expires_at="2099-01-01T00:00:00Z"))
    receipt = dict(state="complete", body_hash="keep", response=dict(status=201, body=dict(wake_delivery=old)))
    store.put("receipt", "old-receipt", receipt)
    store.emit("mas-self", "delivery.state_changed", old["delivery_id"], old)
    original_event = store.db.execute("SELECT data FROM events").fetchone()[0]
    store.db.execute("DELETE FROM documents WHERE kind='migration'")
    store.db.commit()
    store.db.close()
    store = Store(directory)
    try:
        upgraded = store.get("delivery", old["delivery_id"])
        assert upgraded == dict(old, purpose="task")
        assert store.get("receipt_original", "old-receipt") == receipt
        assert store.get("receipt", "old-receipt")["response"]["body"]["wake_delivery"] == upgraded
        assert store.get("page", "old-page")["items"] == [upgraded]
        event = json.loads(store.db.execute("SELECT data FROM events").fetchone()[0])
        prior = json.loads(original_event)
        assert event == dict(prior, payload=upgraded)
        schema = json.loads((CONTRACT / "events.schema.json").read_text())
        project = json.loads((CONTRACT / "project.schema.json").read_text())
        registry = Registry().with_resources([("events.schema.json", Resource.from_contents(schema)),
                                              ("project.schema.json", Resource.from_contents(project))])
        Draft202012Validator.check_schema(schema)
        Draft202012Validator.check_schema(project)
        Draft202012Validator(schema, registry=registry).validate(event)
        Draft202012Validator({"$ref": "events.schema.json#/$defs/Delivery"}, registry=registry).validate(upgraded)
        store.migrate_delivery_purpose()
        assert store.get("receipt_original", "old-receipt") == receipt
        assert not store.documents("run")
    finally:
        store.db.close()
