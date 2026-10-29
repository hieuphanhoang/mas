import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mas_backend.app import create_app

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / "docs/contract"


@pytest.fixture
def config(tmp_path):
    value = json.loads((Path(__file__).parent / "fixtures/self-project.json").read_text())
    root = tmp_path / "project"
    root.mkdir()
    value["project"]["root"] = root.as_posix()
    value["folders"][0]["path"] = root.as_posix()
    return copy.deepcopy(value)


@pytest.fixture
def app(tmp_path):
    result = create_app(tmp_path / "state", CONTRACT, tmp_path / "dist",
                       ["http://127.0.0.1:5173"], capabilities={})
    yield result
    result.state.store.db.close()


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://127.0.0.1:8766") as value:
        token = value.get("/api/v1/session").json()["csrf_token"]
        value.headers["X-MAS-CSRF"] = token
        yield value


def mutate(client, method, path, body=None, revision=None, key=None):
    import secrets
    headers = {"Idempotency-Key": key or secrets.token_hex(12)}
    if revision is not None:
        headers["If-Match"] = '"' + revision + '"'
    return client.request(method, "/api/v1" + path, json=body, headers=headers)


@pytest.fixture
def registered(client, config):
    response = mutate(client, "POST", "/projects", config)
    assert response.status_code == 201, response.text
    return response.json()


def write_log(config, asks=None):
    root = Path(config["project"]["root"]) / ".handoff"
    (root / "threads").mkdir(parents=True, exist_ok=True)
    default = [("AGENT-001", "open", "Fable", "Codex", "Fable"),
               ("ASK-001", "open", "Fable", "Owner", "Fable"),
               ("ASK-002", "answered", "Fable", "Owner", "Owner")]
    rows = asks if asks is not None else default
    for ident, status, frm, to, speaker in rows:
        content = f"""# `{ident}` - A test thread

| | |
|---|---|
| **From -> To** | {frm} -> {to} |
| **Type** | REQUEST |
| **Status** | {status} |
| **Updated** | 2026-10-24 07:12 |
| **Time** | 2026-10-24 07:12 |

---

**[{speaker}, 2410, 0712]**

Original text <script>alert('untrusted')</script>.
"""
        (root / "threads" / f"{ident}-test.md").write_text(content, encoding="utf-8")
    index = "# INDEX\n\n"
    for section, subset in (("awaiting", [r for r in rows if r[0].startswith("ASK-") and r[1] == "open"]),
                            ("open", [r for r in rows if r[0].startswith("AGENT-")]), ("threads", rows)):
        index += f"<!-- handoff:{section}:start -->\n| ID | Subject |\n|---|---|\n"
        for r in subset:
            index += f"| [`{r[0]}`](threads/{r[0]}-test.md) | Test |\n"
        index += f"<!-- handoff:{section}:end -->\n\n"
    index += "## Conversation history\n\n| Time | Speaker | Threads touched | Summary |\n|---|---|---|---|\n| 2026-10-24 07:12 | Fable | AGENT-001, ASK-001 | Test history |\n"
    (root / "INDEX.md").write_text(index, encoding="utf-8")
    return root
