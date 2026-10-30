import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import sysconfig
import time

from fastapi.testclient import TestClient
import pytest

from mas_backend.adapters import Adapter, clean_environment
import mas_backend.adapters as adapter_module
from mas_backend.app import create_app
from mas_backend.runtime import Runtime
from mas_backend.smoke import run_smoke, plan

from conftest import CONTRACT, mutate, write_log
from test_runtime import P, A, REF, poll

FIXTURE = Path(__file__).parent / "fixtures/fake_provider.py"


def fake(harness, directory, scenario="success"):
    return Adapter(
        harness,
        [
            sys.executable,
            str(FIXTURE),
            "--harness",
            harness,
            "--scenario",
            scenario,
            "--record",
            str(directory / (harness + ".jsonl")),
        ],
    )


def turn(adapter, directory, session=None, timeout=3, cancelled=lambda: False):
    sessions, output = [], []
    result = asyncio.run(
        adapter.run(
            model="google/exact-model" if adapter.harness == "opencode" else "exact-model",
            prompt='Unicode caf\u00e9 \U0001f680 "quotes" $()\nnext line',
            cwd=directory,
            session_id=session,
            effort="high",
            timeout=timeout,
            cancelled=cancelled,
            on_session=sessions.append,
            on_output=lambda stream, text: output.append((stream, text)),
            extra_env=dict(MAS_AGENT_TOKEN="test-scoped-secret"),
        )
    )
    return result, sessions, output


def test_launch_finds_service_mas_without_scripts_on_parent_path(tmp_path, monkeypatch):
    inherited = str(tmp_path / "unrelated-bin")
    monkeypatch.setenv("PATH", inherited)
    result, _, _ = turn(fake("codex", tmp_path), tmp_path)
    assert result.exit_code == 0 and result.reason is None
    record = json.loads((tmp_path / "codex.jsonl").read_text().splitlines()[0])
    scripts = Path(sysconfig.get_path("scripts"))
    assert record["launch_path"] == str(scripts) + os.pathsep + inherited
    assert Path(record["mas_executable"]) == scripts / ("mas.exe" if os.name == "nt" else "mas")


@pytest.mark.parametrize("harness", ["claude", "codex", "opencode"])
def test_probe_start_resume_unicode_and_argv(harness, tmp_path, monkeypatch):
    adapter = fake(harness, tmp_path, "unicode")
    assert adapter.probe() == ("fake-provider 1.0", None)
    monkeypatch.setenv("CLAUDECODE", "inherited-session")
    monkeypatch.setenv("CODEX_THREAD_ID", "parent-thread")
    first, sessions, output = turn(adapter, tmp_path)
    assert first.reason is None and first.exit_code == 0
    assert sessions == [first.session_id]
    assert "\U0001f680" in "".join(t for _, t in output)
    assert any(stream == "stderr" for stream, _ in output)
    second, sessions2, _ = turn(adapter, tmp_path, first.session_id)
    assert second.session_id == first.session_id
    records = [
        json.loads(line)
        for line in (tmp_path / (harness + ".jsonl"))
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(records) == 2
    assert (
        records[0]["prompt"]
        == records[1]["prompt"]
        == 'Unicode caf\u00e9 \U0001f680 "quotes" $()\nnext line'
    )
    assert records[0]["inherited_session"] is False
    assert records[0]["has_scoped_token"] is True
    assert "--last" not in records[1]["argv"]
    assert first.session_id in records[1]["argv"]
    assert records[0]["argv"][records[0]["argv"].index("--model") + 1] == (
        "google/exact-model" if harness == "opencode" else "exact-model"
    )
    assert not any("bypass" in arg or "fallback" in arg for arg in records[0]["argv"])


@pytest.mark.parametrize("harness", ["claude", "codex", "opencode"])
@pytest.mark.parametrize(
    "scenario,reason,uncertain",
    [
        ("crash", "process_failed", False),
        ("silent", "session_or_result_missing", True),
        ("malformed", "invalid_structured_output", True),
        ("fail", "provider_error", False),
    ],
)
def test_process_and_protocol_failures(harness, scenario, reason, uncertain, tmp_path):
    result, _, _ = turn(fake(harness, tmp_path, scenario), tmp_path)
    assert result.reason == reason
    assert result.uncertain is uncertain


@pytest.mark.parametrize("harness", ["claude", "codex", "opencode"])
def test_resume_id_mismatch_is_uncertain(harness, tmp_path):
    result, observed, _ = turn(
        fake(harness, tmp_path, "mismatch"),
        tmp_path,
        session="ses_fakeFirst123" if harness == "opencode" else "11111111-1111-4111-8111-111111111111",
    )
    assert result.reason == "session_mismatch"
    assert result.uncertain is True
    assert not observed


@pytest.mark.parametrize("harness", ["claude", "codex", "opencode"])
def test_stop_and_timeout_own_process_tree(harness, tmp_path):
    started = time.monotonic()
    record_path = tmp_path / (harness + ".jsonl")
    result, _, _ = turn(
        fake(harness, tmp_path, "child"),
        tmp_path,
        cancelled=lambda: record_path.is_file() and record_path.stat().st_size > 0,
    )
    assert result.cancelled is True
    assert time.monotonic() - started < 6
    record = json.loads((tmp_path / (harness + ".jsonl")).read_text().splitlines()[0])
    # Windows checks the exact child handle; never terminate by process name.
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, record["child_pid"])
        if handle:
            try:
                assert kernel.WaitForSingleObject(handle, 2000) == 0
            finally:
                kernel.CloseHandle(handle)
    timeout, _, _ = turn(fake(harness, tmp_path, "sleep"), tmp_path, timeout=0.2)
    assert timeout.reason == "run_timeout"


@pytest.fixture
def real_runtime(tmp_path, config):
    write_log(config)
    adapters = {h: fake(h, tmp_path) for h in ("claude", "codex")}
    app = create_app(
        tmp_path / "real-state",
        CONTRACT,
        capabilities={},
        real_adapters=True,
        adapters=adapters,
    )
    app.state.runtime.external_reason = lambda harness, session_id: None
    with TestClient(app, base_url="http://127.0.0.1:8766") as client:
        client.headers["X-MAS-CSRF"] = client.get("/api/v1/session").json()[
            "csrf_token"
        ]
        registered = mutate(client, "POST", "/projects", config).json()
        preview = mutate(
            client, "POST", P + "/preview", revision=registered["revision"]
        ).json()
        assert (
            mutate(
                client,
                "POST",
                P + "/apply",
                dict(preview_id=preview["preview_id"]),
                registered["revision"],
            ).status_code
            == 200
        )
        yield client, app, config, adapters
    app.state.store.db.close()


@pytest.mark.parametrize("harness,target", [("claude", "fable"), ("codex", "codex")])
def test_runtime_start_resume_one_session_and_no_fake_identity(
    real_runtime, harness, target
):
    client, app, config, adapters = real_runtime
    session = None
    for _ in range(2):
        delivery = mutate(
            client, "POST", P + f"/agents/{target}/call", dict(thread_ref=REF)
        ).json()
        done = poll(
            client,
            P + "/calls/" + delivery["delivery_id"],
            lambda d: d["state"] in ("failed", "uncertain"),
        ).json()
        assert done["reason"] == "missing_reply", done
        assert done["process_outcome"] == "succeeded"
        status = app.state.runtime.status("mas-self", target)
        assert status["session_generation"] == 1
        assert not status["session_id"].startswith("fake-")
        if session:
            assert status["session_id"] == session
        session = status["session_id"]
        output = client.get(
            "/api/v1" + P + "/runs/" + done["run_id"] + "/output"
        ).json()
        assert output["eof"] is True
        assert any(chunk["stream"] == "stderr" for chunk in output["chunks"])
    command = adapters[harness].command
    recorded = Path(command[command.index("--record") + 1])
    rows = [json.loads(line) for line in recorded.read_text(encoding="utf-8").splitlines()]
    prompt = rows[0]["prompt"]
    name = next(a["name"] for a in config["agents"] if a["id"] == target)
    label = config["project"]["name"] + " / " + name
    assert prompt.splitlines()[0] == label
    assert rows[1]["prompt"].splitlines()[0] == label
    if harness == "claude":
        assert rows[0]["argv"][rows[0]["argv"].index("--name") + 1] == label
        assert "--name" not in rows[1]["argv"]
    assert "Use the agents-collaboration-protocol skill and every skill in your skills list" in prompt
    assert "roster command for calling another member is `mas call <agent> --thread <ID>" in prompt


def test_runtime_launch_uses_workspace_local_offline_uv_cache(real_runtime, monkeypatch):
    client, _, _, adapters = real_runtime
    launch = {}
    original_run = adapters["codex"].run

    async def record_launch(**kwargs):
        launch.update(kwargs)
        return await original_run(**kwargs)

    monkeypatch.setattr(adapters["codex"], "run", record_launch)
    delivery = mutate(client, "POST", A + "/call", dict(thread_ref=REF)).json()
    poll(
        client,
        delivery["status_url"].removeprefix("/api/v1"),
        lambda d: d["state"] == "failed",
    )
    assert launch["extra_env"]["UV_CACHE_DIR"] == str(
        launch["cwd"] / ".agents" / "mas" / "uv-cache"
    )
    assert launch["extra_env"]["UV_OFFLINE"] == "true"
    assert launch["owned_paths"]
    assert launch["handoff_paths"] == [launch["cwd"] / ".handoff/handoff.py"]


def test_runtime_busy_queues_stop_and_restart_reconcile(real_runtime, tmp_path):
    client, app, config, adapters = real_runtime
    app.state.runtime.adapters["codex"] = fake("codex", tmp_path, "sleep")
    first = mutate(client, "POST", A + "/call", dict(thread_ref=REF)).json()
    poll(
        client, P + "/calls/" + first["delivery_id"], lambda d: d["state"] == "running"
    )
    second = mutate(client, "POST", A + "/call", dict(thread_ref=REF)).json()
    assert client.get(second["status_url"]).json()["state"] == "queued"
    stop = mutate(client, "POST", A + "/stop").json()
    assert stop["queue_paused"] is True
    poll(
        client,
        P + "/calls/" + first["delivery_id"],
        lambda d: d["state"] == "cancelled",
    )
    assert client.get(second["status_url"]).json()["state"] == "queued"
    # Durable crash marker: no inference from PID or provider auth/transcripts.
    second.update(state="dispatching")
    app.state.store.put("delivery", second["delivery_id"], second)
    app.state.store.db.commit()
    recovered = Runtime(
        app.state.store,
        app.state.logs,
        app.state.runtime.handoff,
        {},
        real=True,
        adapters=adapters,
    )
    assert recovered.delivery("mas-self", second["delivery_id"])["state"] == "uncertain"
    assert recovered.status("mas-self", "codex")["queue_paused"] is True


@pytest.mark.parametrize("harness", ["claude", "codex", "opencode"])
def test_crash_before_session_identity_is_uncertain(harness, tmp_path):
    result, sessions, _ = turn(fake(harness, tmp_path, "crash_before_init"), tmp_path)
    assert result.reason == "process_failed"
    assert result.uncertain is True
    assert not sessions


def test_runtime_crash_and_resume_mismatch_are_not_replayed(real_runtime, tmp_path):
    client, app, _, _ = real_runtime
    app.state.runtime.adapters["codex"] = fake("codex", tmp_path, "crash")
    first = mutate(client, "POST", A + "/call", dict(thread_ref=REF)).json()
    crashed = poll(
        client, P + "/calls/" + first["delivery_id"], lambda d: d["state"] == "failed"
    ).json()
    assert crashed["reason"] == "process_failed"
    app.state.runtime.adapters["codex"] = fake("codex", tmp_path, "mismatch")
    second = mutate(client, "POST", A + "/call", dict(thread_ref=REF)).json()
    mismatch = poll(
        client,
        P + "/calls/" + second["delivery_id"],
        lambda d: d["state"] == "uncertain",
    ).json()
    assert mismatch["reason"] == "session_mismatch"
    assert app.state.runtime.status("mas-self", "codex")["queue_paused"] is True
    assert mutate(client, "POST", A + "/resume-queue").status_code == 409


def test_live_smoke_procedure_uses_only_injected_fake_processes(tmp_path):
    workspace = tmp_path / "scratch"
    models = dict(claude="owner-selected-claude", codex="owner-selected-codex")
    adapters = {h: fake(h, tmp_path) for h in models}
    receipts = asyncio.run(run_smoke(workspace, models, timeout=3, adapters=adapters))
    assert len(receipts) == 4
    assert receipts[0]["session_id"] == receipts[1]["session_id"]
    assert receipts[2]["session_id"] == receipts[3]["session_id"]
    assert [r["model"] for r in receipts] == [models["claude"]] * 2 + [
        models["codex"]
    ] * 2
    assert (workspace / "smoke-receipt.json").is_file()
    assert plan(models, workspace)["maximum_cli_turns"] == 4
    with pytest.raises(ValueError):
        asyncio.run(run_smoke(workspace, models, adapters=adapters))


def test_smoke_stops_after_failure_without_retry(tmp_path):
    workspace = tmp_path / "scratch"
    adapters = {h: fake(h, tmp_path, "fail") for h in ("claude", "codex")}
    with pytest.raises(ValueError):
        asyncio.run(
            run_smoke(workspace, dict(claude="exact", codex="exact"), adapters=adapters)
        )
    assert len((tmp_path / "claude.jsonl").read_text().splitlines()) == 1
    assert not (tmp_path / "codex.jsonl").exists()


def test_scoped_secrets_are_redacted_and_environment_is_not_inherited(tmp_path):
    env = clean_environment(dict(MAS_AGENT_TOKEN="secret-for-one-run"))
    assert env["MAS_AGENT_TOKEN"] == "secret-for-one-run"
    assert "CLAUDECODE" not in env
    assert "CODEX_THREAD_ID" not in env
    fixture = tmp_path / "secret-provider.py"
    fixture.write_text(
        """import json, os, sys
sys.stdin.buffer.read()
s = os.environ["MAS_AGENT_TOKEN"]
sys.stderr.write(s[:5]); sys.stderr.flush()
sys.stderr.write(s[5:] + "\\n"); sys.stderr.flush()
print(json.dumps({"type":"thread.started", "thread_id":"11111111-1111-4111-8111-111111111111"}), flush=True)
print(json.dumps({"type":"turn.completed"}), flush=True)
""",
        encoding="utf-8",
    )
    result, _, output = turn(Adapter("codex", [sys.executable, str(fixture)]), tmp_path)
    assert result.reason is None
    text = "".join(chunk for _, chunk in output)
    assert "test-scoped-secret" not in text
    assert "[redacted]" in text


def test_windows_npm_lookup_uses_installed_bin_layout(tmp_path, monkeypatch):
    from types import SimpleNamespace
    npm = tmp_path / "npm"
    binary = npm / "node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setattr(adapter_module.shutil, "which", lambda name: str(npm / "codex.cmd"))
    monkeypatch.setattr(adapter_module, "os", SimpleNamespace(name="nt", environ={}))
    assert adapter_module.executable("codex") == str(binary)


def test_codex_only_smoke_does_not_start_claude(tmp_path):
    models = dict(codex="gpt-6-astra")
    receipts = asyncio.run(run_smoke(tmp_path / "scratch", models, adapters=dict(codex=fake("codex", tmp_path))))
    assert len(receipts) == 2
    assert receipts[0]["session_id"] == receipts[1]["session_id"]
    assert not (tmp_path / "claude.jsonl").exists()
    assert plan(models, tmp_path)["maximum_cli_turns"] == 2
