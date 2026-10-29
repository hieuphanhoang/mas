import copy
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mas_backend.app import create_app
from mas_backend.config import ConfigValidator

from conftest import CONTRACT, mutate, write_log


def contract_response(response, path, method="get", status="200"):
    base = "https://mas.invalid/"
    spec = yaml.safe_load((CONTRACT / "openapi.yaml").read_text())
    registry = Registry().with_resources([
        (base + "openapi.yaml", Resource.from_contents(spec, default_specification=DRAFT202012)),
        *[(base + name, Resource.from_contents(json.loads((CONTRACT / name).read_text())))
          for name in ("project.schema.json", "events.schema.json")],
    ])
    result = spec["paths"][path][method]["responses"][status]
    if "$ref" in result:
        result = spec["components"]["responses"][result["$ref"].rsplit("/", 1)[1]]
    schema = result["content"]["application/json"]["schema"]
    # Resolve local fragments against the complete OpenAPI document.
    validator = Draft202012Validator(schema, registry=registry,
        _resolver=registry.resolver(base + "openapi.yaml"), format_checker=FormatChecker())
    validator.validate(response.json())


def test_fixture_schema_and_semantics():
    fixture = json.loads((Path(__file__).parent / "fixtures/self-project.json").read_text())
    ConfigValidator(CONTRACT).validate(fixture)


def test_bootstrap_security_and_reuse(app):
    with TestClient(app, base_url="http://127.0.0.1:8766") as client:
        assert client.get("/api/v1/projects").status_code == 401
        response = client.get("/api/v1/session")
        contract_response(response, "/session")
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert "Domain=" not in response.headers["set-cookie"]
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/api/v1/session").json() == response.json()
        assert client.get("/api/v1/session", headers={"Origin": "http://evil.test"}).status_code == 403
        assert client.get("/api/v1/session", headers={"Host": "evil.test"}).status_code == 403
        assert client.get("/api/v1/session", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert client.get("/api/v1/session", headers={"Origin": "http://127.0.0.1:5173"}).status_code == 200
        assert client.get("/api/v1/session", headers={"Origin": "http://127.0.0.1:9999"}).status_code == 403
        response = mutate(client, "POST", "/projects", {})
        assert response.status_code == 403
        contract_response(response, "/projects", "post", "default")


def test_default_origins_closed(tmp_path):
    app = create_app(tmp_path / "state", CONTRACT, capabilities={})
    try:
        with TestClient(app, base_url="http://127.0.0.1:8766") as client:
            assert client.get("/api/v1/session", headers={"Origin": "http://127.0.0.1:5173"}).status_code == 403
    finally:
        app.state.store.db.close()
    with pytest.raises(ValueError):
        create_app(tmp_path / "other", CONTRACT, dev_allowed_origins=["https://remote.test"])


def test_project_crud_retries_and_etags(client, config, tmp_path):
    before = list(Path(config["project"]["root"]).rglob("*"))
    response = mutate(client, "POST", "/projects", config, key="create-key")
    contract_response(response, "/projects", "post", "201")
    record = response.json()
    assert record["config"] == config
    assert record["scaffold_state"] == "draft"
    assert list(Path(config["project"]["root"]).rglob("*")) == before
    assert response.headers["etag"] == '"' + record["revision"] + '"'
    assert mutate(client, "POST", "/projects", config, key="create-key").json() == record
    assert mutate(client, "POST", "/projects", config).status_code == 409
    changed = copy.deepcopy(config)
    changed["project"]["name"] = "Edited"
    assert mutate(client, "POST", "/projects", changed, key="create-key").json()["code"] == "idempotency_conflict"
    route = "/projects/mas-self"
    assert mutate(client, "PUT", route, changed).status_code == 428
    assert mutate(client, "PUT", route, changed, "stale").json()["code"] == "revision_conflict"
    updated = mutate(client, "PUT", route, changed, record["revision"], "update-key")
    assert updated.status_code == 200, updated.text
    contract_response(updated, "/projects/{project_id}", "put")
    # Existing receipt is resolved before the now-stale If-Match.
    assert mutate(client, "PUT", route, changed, record["revision"], "update-key").json() == updated.json()
    assert client.get("/api/v1" + route).json() == updated.json()
    summaries = client.get("/api/v1/projects")
    contract_response(summaries, "/projects")
    assert summaries.json()["items"][0]["agent_count"] == 2
    changed["project"]["id"] = "other"
    assert mutate(client, "PUT", route, changed, updated.json()["revision"]).json()["code"] == "immutable_field"


@pytest.mark.parametrize("mutation", [
    lambda c: c["agents"].append(copy.deepcopy(c["agents"][0])),
    lambda c: c["agents"][1].update(name="Fable"),
    lambda c: c["agents"][1].update(level_id="missing"),
    lambda c: c["agents"][1].update(log_ids=[]),
    lambda c: c["agents"][1].update(owns=c["agents"][0]["owns"]),
    lambda c: c["agents"][1].update(owns=[dict(folder_id="root", path=".git/file")]),
    lambda c: c["agents"][1].update(owns=[dict(folder_id="root", path=".handoff")]),
    lambda c: c["agents"][1].update(reads=[dict(folder_id="root", path="../escape")]),
    lambda c: c["project"].update(timezone="invalid/zone"),
    lambda c: c["call_policy"]["allowed_edges"].append(dict(from_agent_id="codex", to_agent_id="codex")),
    lambda c: c["agents"][1].update(log_duty="helper", sponsor_agent_id="codex"),
    lambda c: c.update(dev_allowed_origins=["http://evil.test"]),
])
def test_invalid_config_rejected(client, config, mutation):
    mutation(config)
    response = mutate(client, "POST", "/projects", config)
    assert response.status_code == 422, response.text
    contract_response(response, "/projects", "post", "default")


def test_validation_error_envelope(client):
    for url in ("/api/v1/projects?limit=0", "/api/v1/projects?limit=no", "/api/v1/inbox?cursor=bogus"):
        result = client.get(url)
        assert result.status_code in (400, 422)
        assert set(result.json()) == {"code", "message", "details", "request_id", "retryable"}
    response = client.post("/api/v1/projects", content="{", headers={"Idempotency-Key": "json-test"})
    assert response.status_code == 422
    response = client.post("/api/v1/projects", content="x" * (4 * 1024 * 1024 + 1), headers={"Idempotency-Key": "size-test"})
    assert response.status_code == 413


def test_pagination_snapshot_survives_change(client, config, registered, tmp_path):
    for ident in ("second", "third"):
        second = copy.deepcopy(config)
        second["project"]["id"] = ident
        root = tmp_path / ident
        root.mkdir()
        second["project"]["root"] = second["folders"][0]["path"] = root.as_posix()
        assert mutate(client, "POST", "/projects", second).status_code == 201
    page = client.get("/api/v1/projects?limit=1").json()
    config["project"]["name"] = "Changed after snapshot"
    mutate(client, "PUT", "/projects/mas-self", config, registered["revision"])
    cursor = page["next_cursor"]
    result = client.get("/api/v1/projects", params=dict(limit=100, cursor=cursor))
    assert [i["project_id"] for i in result.json()["items"]] == ["second", "third"]
    assert client.get("/api/v1/inbox", params=dict(cursor=cursor)).status_code == 400


def test_all_log_sections_thread_inbox(client, config, registered):
    root = write_log(config)
    base = "/api/v1/projects/mas-self/logs/main"
    response = client.get("/api/v1/projects/mas-self/logs")
    contract_response(response, "/projects/{project_id}/logs")
    for section, count in (("awaiting_owner", 1), ("open", 1), ("all", 3), ("history", 1)):
        response = client.get(base + "/index", params=dict(section=section))
        assert response.status_code == 200, response.text
        assert len(response.json()["items"]) == count
        contract_response(response, "/projects/{project_id}/logs/{log_id}/index")
    response = client.get(base + "/threads/AGENT-001")
    contract_response(response, "/projects/{project_id}/logs/{log_id}/threads/{thread_id}")
    assert response.json()["metadata"]["owes_reply"] == "Codex"
    assert response.json()["metadata"]["updated_at"] == "2026-10-24T00:12:00Z"
    assert "<script>" in response.json()["markdown"]  # rendering/sanitization belongs to the UI
    inbox = client.get("/api/v1/inbox")
    contract_response(inbox, "/inbox")
    assert [i["thread_ref"]["thread_id"] for i in inbox.json()["items"]] == ["ASK-001"]
    # Owner answer plus member acknowledgement must not resurrect answered ASK.
    path = root / "threads/ASK-002-test.md"
    path.write_text(path.read_text() + "\n**[Fable, 2410, 0713]**\n\nThanks.\n")
    assert len(client.get("/api/v1/inbox").json()["items"]) == 1
    # Discovery does not rely on INDEX sync.
    text = (root / "threads/ASK-001-test.md").read_text().replace("ASK-001", "ASK-003")
    (root / "threads/ASK-003-new.md").write_text(text)
    assert len(client.get("/api/v1/inbox").json()["items"]) == 2


def test_missing_stale_malformed_logs(client, config, registered):
    base = "/api/v1/projects/mas-self/logs/main"
    assert client.get(base + "/index").status_code == 503
    assert client.get("/api/v1/inbox").json()["sources"][0]["freshness"]["state"] == "unavailable"
    root = write_log(config)
    assert client.get(base + "/index").json()["log"]["freshness"]["state"] == "current"
    (root / "INDEX.md").rename(root / "INDEX.saved")
    assert client.get(base + "/index").json()["log"]["freshness"]["state"] == "stale"
    thread = root / "threads/AGENT-001-test.md"
    thread.write_text("bad metadata\n\nOriginal content")
    response = client.get(base + "/threads/AGENT-001")
    assert response.status_code == 200
    assert response.json()["metadata"]["parse_errors"]
    assert response.json()["freshness"]["state"] == "parse_error"
    thread.write_text("x" * (2097152 + 1))
    assert client.get(base + "/threads/AGENT-001").status_code == 413


def test_static_spa_and_api_fallback(client, tmp_path):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<main>MAS</main>")
    (root / "app.js").write_text("const x = 1")
    assert client.get("/projects/mas-self").text == "<main>MAS</main>"
    assert client.get("/app.js").status_code == 200
    assert client.get("/missing.js").status_code == 404
    assert client.get("/%2e%2e/secret.txt").status_code == 404
    response = client.get("/api/v1/not-implemented")
    assert response.json()["code"] == "unsupported_capability"
