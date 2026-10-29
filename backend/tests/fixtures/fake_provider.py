"""Offline subprocess fixture implementing the two structured CLI protocols."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time


def option(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


if "--child" in sys.argv:
    time.sleep(20)
    raise SystemExit(0)
if "--version" in sys.argv:
    print("fake-provider 1.0")
    raise SystemExit(0)
if "--help" in sys.argv:
    print(
        "SESSION_ID --json --sandbox --model --session-id --resume --output-format --permission-prompts"
    )
    raise SystemExit(0)
harness = option("--harness")
scenario = option("--scenario", "success")
prompt = sys.stdin.buffer.read().decode("utf-8")
session = option("--session-id") or option("--resume")
if harness == "codex" and "resume" in sys.argv:
    session = sys.argv[sys.argv.index("resume") + 1]
session = session or "11111111-1111-4111-8111-111111111111"
record = dict(
    argv=sys.argv[1:],
    prompt=prompt,
    session=session,
    pid=os.getpid(),
    inherited_session=any(k in os.environ for k in ("CLAUDECODE", "CODEX_THREAD_ID")),
    has_scoped_token="MAS_AGENT_TOKEN" in os.environ,
)
if scenario == "child":
    child = subprocess.Popen(
        [sys.executable, __file__, "--child"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    record["child_pid"] = child.pid
record_path = option("--record")
if record_path:
    with Path(record_path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def emit(value):
    raw = (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
    if scenario == "unicode":
        for byte in raw:
            sys.stdout.buffer.write(bytes([byte]))
        sys.stdout.buffer.flush()
    else:
        sys.stdout.buffer.write(raw)
        sys.stdout.buffer.flush()


if scenario == "crash_before_init":
    raise SystemExit(7)
if scenario == "mismatch":
    session = "22222222-2222-4222-8222-222222222222"
emit(
    dict(type="system", subtype="init", session_id=session)
    if harness == "claude"
    else dict(type="thread.started", thread_id=session)
)
if scenario == "crash":
    raise SystemExit(7)
if scenario in ("sleep", "child"):
    time.sleep(20)
if scenario == "malformed":
    print("not json", flush=True)
    time.sleep(20)
if scenario == "silent":
    raise SystemExit(0)
sys.stderr.buffer.write('diagnostic: "quotes" caf\u00e9 \U0001f680\n'.encode("utf-8"))
sys.stderr.buffer.flush()
emit(
    dict(
        type="assistant",
        session_id=session,
        message=dict(content=[dict(type="text", text="caf\u00e9 \U0001f680 ' \" $()")]),
    )
    if harness == "claude"
    else dict(
        type="item.completed",
        item=dict(type="agent_message", text="caf\u00e9 \U0001f680 ' \" $()"),
    )
)
emit(
    dict(
        type="result",
        session_id=session,
        subtype="error_during_execution" if scenario == "fail" else "success",
        is_error=scenario == "fail",
    )
    if harness == "claude"
    else dict(type="turn.failed" if scenario == "fail" else "turn.completed")
)
