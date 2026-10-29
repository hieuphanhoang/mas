import argparse
import json
from pathlib import Path

import uvicorn

from .app import create_app
from .common import Problem

REPO = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(prog="mas", description="Single-process loopback MAS backend")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", choices=["127.0.0.1", "::1"], default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8790)
    serve.add_argument("--settings", type=Path, default=REPO / "backend/dev.settings.json")
    serve.add_argument("--state-dir", type=Path, default=REPO / "backend/state")
    serve.add_argument("--contract-dir", type=Path, default=REPO / "docs/contract")
    serve.add_argument("--static-dir", type=Path, default=REPO / "frontend/dist")
    serve.add_argument("--register", type=Path, help="Register fixture on first run, preserving any existing draft")
    adapter_mode = serve.add_mutually_exclusive_group()
    adapter_mode.add_argument("--fake-adapter", action="store_true", help="Enable simulated runs; never invokes provider CLIs")
    adapter_mode.add_argument("--real-adapters", action="store_true", help="Enable real Claude/Codex managed turns; model calls require Owner authorization")
    smoke = sub.add_parser("smoke-adapters", help="Four live CLI turns; requires explicit Owner approval")
    smoke.add_argument("--workspace", type=Path, required=True)
    smoke.add_argument("--claude-model", default="claude-opus-5-5")
    smoke.add_argument("--codex-model", default="gpt-6-astra")
    smoke.add_argument("--turn-timeout", type=int, default=120)
    smoke.add_argument("--harness", choices=["both", "claude", "codex"], default="both")
    smoke.add_argument("--plan", action="store_true", help="Print the procedure without probes, writes or model calls")
    call = sub.add_parser("call", help="Queue a call using the current agent run's scoped credentials")
    call.add_argument("agent")
    call.add_argument("--thread", required=True)
    call.add_argument("--log")
    call.add_argument("--note", default="")
    args = parser.parse_args()
    try:
        if args.command == "call":
            from .agent_cli import call as agent_call
            print(json.dumps(agent_call(args.agent, args.thread, args.log, args.note), ensure_ascii=False))
            return
        if args.command == "smoke-adapters":
            import asyncio
            from .smoke import plan, run_smoke
            models = dict(claude=args.claude_model, codex=args.codex_model)
            if args.harness != "both":
                models = {args.harness: models[args.harness]}
            if args.turn_timeout < 1 or any(not value or value.startswith("-") for value in models.values()):
                parser.error("Explicit model values and a positive timeout are required.")
            if args.plan:
                print(json.dumps(plan(models, args.workspace), indent=2))
            else:
                receipts = asyncio.run(run_smoke(args.workspace.resolve(), models, args.turn_timeout))
                print(f"Completed {len(receipts)} smoke turns; receipt: {args.workspace / 'smoke-receipt.json'}")
            return
        settings = json.loads(args.settings.read_text(encoding="utf-8")) if args.settings.is_file() else {}
        if not isinstance(settings, dict) or set(settings) - {"dev_allowed_origins"}:
            parser.error("Settings support only dev_allowed_origins.")
        origins = settings.get("dev_allowed_origins", [])
        if not isinstance(origins, list) or any(not isinstance(o, str) for o in origins):
            parser.error("dev_allowed_origins must be a list of origins.")
        # No reload/workers: one registry/process owner. A second service process
        # using this state directory is rejected by the held OS lock below.
        with state_lock(args.state_dir.resolve()):
            app = create_app(args.state_dir.resolve(), args.contract_dir.resolve(), args.static_dir.resolve(), origins,
                             fake_adapter=args.fake_adapter, real_adapters=args.real_adapters)
            app.state.runtime.api_url = f"http://{'[' + args.host + ']' if ':' in args.host else args.host}:{args.port}/api/v1"
            try:
                if args.register:
                    config = app.state.validator.validate(json.loads(args.register.read_text(encoding="utf-8")))
                    record = app.state.store.register(config, first_run=True)
                    app.state.store.db.commit()
                    print(f"Registered {record['config']['project']['id']}: {record['scaffold_state']} (no apply)")
                uvicorn.run(app, host=args.host, port=args.port, workers=1, access_log=False,
                            proxy_headers=False)
            finally:
                app.state.store.db.close()
    except (OSError, ValueError, Problem) as error:
        parser.error(str(error))


class state_lock:
    def __init__(self, directory):
        self.directory = directory

    def __enter__(self):
        import os
        self.directory.mkdir(parents=True, exist_ok=True)
        self.stream = (self.directory / "service.lock").open("a+b")
        self.stream.seek(0)
        if not self.stream.read(1):
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise ValueError("Another MAS service owns this state directory.")
        return self

    def __exit__(self, *args):
        self.stream.close()
