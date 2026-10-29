"""OpenCode integration uses fake subprocesses only, never a model."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from mas_backend.adapters import Adapter, AdapterError, clean_environment
import mas_backend.adapters as adapter_module
from mas_backend.capabilities import probe_capabilities
from mas_backend.opencode import launch_environment, OLLAMA_SDK
from conftest import mutate
from test_adapters import fake, real_runtime, turn
from test_runtime import A, P, REF, poll


@pytest.mark.parametrize("model", ["google/gemini-3.8-flash", "ollama/qwen3.5:latest"])
def test_opencode_provider_environment_and_profile(model, tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-google-key-do-not-log")
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11435")
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"permission":"allow"}')
    adapter = fake("opencode", tmp_path, "secret")
    emitted = []
    result = asyncio.run(adapter.run(
        model=model, prompt='caf\u00e9 \U0001f680 "quotes"\nsecond line',
        cwd=tmp_path, session_id=None, effort="low", timeout=3,
        cancelled=lambda: False, on_session=lambda _: None,
        on_output=lambda _, text: emitted.append(text), permission_profile="member",
    ))
    assert result.reason is None and result.session_id.startswith("ses_")
    record = json.loads((tmp_path / "opencode.jsonl").read_text(encoding="utf-8"))
    assert record["key_mapped"] is True
    assert record["ollama_host"] == "http://127.0.0.1:11435"
    assert record["argv"][record["argv"].index("--model") + 1] == model
    assert record["argv"][record["argv"].index("--variant") + 1] == "low"
    assert "--auto" not in record["argv"] and "--pure" in record["argv"]
    config = record["config"]
    assert config["agent"]["mas"]["permission"] == config["permission"]
    assert config["permission"]["bash"] == {
        "*": "deny", "mas call *": "allow",
        "uv run --no-project .handoff/handoff.py *": "allow",
        "uv run --no-project .handoff\\handoff.py *": "allow",
    }
    assert config["permission"]["task"] == "deny"
    assert config["permission"]["edit"] == "allow"
    assert config["share"] == "disabled" and config["autoupdate"] is False
    assert record["auto_updates"] == "true"
    assert "fake-google-key-do-not-log" not in "".join(emitted)
    assert "[redacted]" in "".join(emitted)
    assert not list(tmp_path.glob("opencode.json"))
    if model.startswith("ollama/"):
        provider = config["provider"]["ollama"]
        assert provider["npm"] == OLLAMA_SDK
        assert provider["options"]["baseURL"] == "http://127.0.0.1:11435/api"
        assert provider["models"]["qwen3.5:latest"]["options"]["options"]["num_ctx"] == 32768
    else:
        assert "provider" not in config


def test_opencode_default_and_explicit_key_precedence(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "alias-not-the-explicit-key")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "explicit-sdk-key")
    env = clean_environment()
    env.update(launch_environment("google/selected", "default", env))
    assert env["GOOGLE_GENERATIVE_AI_API_KEY"] == "explicit-sdk-key"
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert config["permission"]["bash"] == "deny"
    assert config["permission"]["edit"] == "deny"
    assert config["permission"]["read"] == "allow"
    assert config["permission"]["skill"] == "allow"
    assert all(value != "ask" for value in config["permission"].values())


def test_opencode_tool_step_is_not_terminal_and_ids_are_explicit(tmp_path):
    result, _, _ = turn(fake("opencode", tmp_path, "tool_only"), tmp_path)
    assert result.reason == "session_or_result_missing" and result.uncertain
    adapter = fake("opencode", tmp_path)
    for model, session in [("unqualified", None), ("google/selected", "--last")]:
        with pytest.raises(AdapterError):
            adapter.argv(model, session)


def test_opencode_windows_npm_lookup_and_capabilities(tmp_path, monkeypatch):
    npm = tmp_path / "npm"
    binary = npm / "node_modules/opencode-ai/bin/opencode.exe"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setattr(adapter_module.shutil, "which", lambda _: str(npm / "opencode.ps1"))
    monkeypatch.setattr(adapter_module, "os", SimpleNamespace(name="nt", environ={}))
    assert adapter_module.executable("opencode") == str(binary)
    monkeypatch.setattr(Adapter, "probe", lambda _: ("fake-opencode", None))
    caps = probe_capabilities()
    assert next(a for a in caps["adapters"] if a["harness"] == "opencode")["availability"] == "available"
    assert {p["id"] for p in caps["permission_profiles"] if p["harness"] == "opencode"} == {"default", "member"}
    assert next(a for a in caps["adapters"] if a["harness"] == "gemini")["availability"] == "planned"


def test_opencode_runtime_start_resume_and_busy_queue(real_runtime, tmp_path):
    client, app, config, adapters = real_runtime
    config["agents"][1].update(harness="opencode", model="ollama/qwen3.5:latest", permission_profile="member")
    record = app.state.store.project("mas-self")
    record["config"] = config
    app.state.store.save_project(record)
    app.state.store.db.commit()
    adapters["opencode"] = fake("opencode", tmp_path, "sleep")
    first = mutate(client, "POST", A + "/call", dict(thread_ref=REF)).json()
    poll(client, P + "/calls/" + first["delivery_id"], lambda d: d["state"] == "running")
    second = mutate(client, "POST", A + "/call", dict(thread_ref=REF)).json()
    assert client.get(second["status_url"]).json()["state"] == "queued"
    mutate(client, "POST", A + "/stop")
    poll(client, P + "/calls/" + first["delivery_id"], lambda d: d["state"] == "cancelled")
    session = app.state.runtime.status("mas-self", "codex")["session_id"]
    assert session.startswith("ses_")
    adapters["opencode"] = fake("opencode", tmp_path)
    mutate(client, "POST", A + "/resume-queue")
    done = poll(client, P + "/calls/" + second["delivery_id"], lambda d: d["state"] == "failed").json()
    assert done["reason"] == "missing_reply" and done["process_outcome"] == "succeeded"
    assert app.state.runtime.status("mas-self", "codex")["session_id"] == session
    rows = [json.loads(line) for line in (tmp_path / "opencode.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert "--session" not in rows[0]["argv"]
    assert rows[1]["argv"][rows[1]["argv"].index("--session") + 1] == session
    label = config["project"]["name"] + " / " + config["agents"][1]["name"]
    assert rows[0]["argv"][rows[0]["argv"].index("--title") + 1] == label
    assert "--title" not in rows[1]["argv"]
    assert rows[0]["prompt"].splitlines()[0] == label
