"""Owner-owned interactive terminals. No process adoption, output capture or kill."""
import base64
import json
import os
from pathlib import Path
import subprocess

from .adapters import AdapterError, clean_environment, valid_session
from .common import Problem, stamp
from .opencode import launch_environment


def powershell():
    return Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


def supported():
    return os.name == "nt" and powershell().is_file()


def literal(value):
    # PowerShell treats smart single quotes as delimiters too.
    return "'" + "".join(c * 2 if c in "'\u2018\u2019\u201a\u201b" else c for c in str(value)) + "'"


def prepare(adapter, agent, session_id, cwd, owned_paths, handoff_paths):
    harness = agent["harness"]
    if not valid_session(harness, session_id):
        raise Problem(409, "uncertain", "Stored session ID cannot be resumed safely.")
    try:
        args = adapter.argv(agent["model"], session_id, agent.get("effort"),
                            permission_profile=agent["permission_profile"],
                            owned_paths=owned_paths, handoff_paths=handoff_paths, cwd=cwd)
    except AdapterError as error:
        raise Problem(422, "unsupported_configuration", str(error))
    if harness == "claude":
        for flag, size in (("--print", 1), ("--verbose", 1), ("--output-format", 2)):
            index = args.index(flag, len(adapter.command))
            del args[index:index + size]
    elif harness == "codex":
        del args[len(adapter.command)]  # exec
        args.remove("--json")
        args.remove("--skip-git-repo-check")
        args.pop()  # stdin prompt marker
        args += ["-C", str(cwd)]
    elif harness == "opencode":
        del args[len(adapter.command)]  # run -> interactive TUI
        index = args.index("--format", len(adapter.command))
        del args[index:index + 2]
        if agent.get("effort"):
            index = args.index("--variant", len(adapter.command))
            del args[index:index + 2]
    else:
        raise Problem(422, "unsupported_capability", "Harness has no interactive resume.")

    env = clean_environment(dict(UV_CACHE_DIR=str(cwd / ".agents/mas/uv-cache"), UV_OFFLINE="true"))
    settings = {}
    if harness == "opencode":
        try:
            settings = launch_environment(agent["model"], agent["permission_profile"], env,
                cwd=cwd, owned_paths=owned_paths, handoff_paths=handoff_paths)
        except ValueError as error:
            raise Problem(422, "unsupported_configuration", str(error))
        if agent.get("effort"):
            # The TUI has no --variant flag; the agent config selects it.
            config = json.loads(settings["OPENCODE_CONFIG_CONTENT"])
            config["agent"]["mas"].update(model=agent["model"], variant=agent["effort"])
            settings["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
        env.update(settings)
    # Secret provider keys stay in the inherited environment, never in the
    # returned command, encoded command line, receipts or project files.
    statements = ["$ErrorActionPreference = 'Stop'", "Set-Location -LiteralPath " + literal(cwd)]
    statements += ["$env:" + key + " = " + literal(value)
                   for key, value in settings.items() if key.startswith("OPENCODE_")]
    statements.append("& " + " ".join(literal(arg) for arg in args))
    return "; ".join(statements), env


def launch(command, env, cwd):
    return subprocess.Popen(
        [str(powershell()), "-NoLogo", "-NoProfile", "-NoExit", "-EncodedCommand",
         base64.b64encode(command.encode("utf-16le")).decode("ascii")],
        cwd=cwd, env=env, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10),
    )


class Windows:
    def __init__(self, store):
        self.store = store
        self.processes = {}

    def reason(self, project_id, agent_id):
        key = f"{project_id}:{agent_id}"
        if key in self.processes:
            process = self.processes[key]
            if process is None or process.poll() is None:
                return "session open elsewhere (Owner terminal)"
            del self.processes[key]
            self.store.put("resume_window", key, dict(project_id=project_id, agent_id=agent_id, state="closed"))
            self.store.db.commit()
        saved = self.store.get("resume_window", key)
        if saved and saved["state"] != "closed":
            return "Owner terminal liveness unknown after restart; reconciliation required"
        return None

    def open(self, project_id, agent_id, command, env, cwd):
        key = f"{project_id}:{agent_id}"
        self.processes[key] = None  # reserve before spawning, no await gap
        saved = dict(project_id=project_id, agent_id=agent_id, state="opening", started_at=stamp())
        self.store.put("resume_window", key, saved)
        self.store.db.commit()
        try:
            process = launch(command, env, cwd)
        except OSError as error:
            self.processes.pop(key, None)
            saved["state"] = "closed"
            self.store.put("resume_window", key, saved)
            self.store.db.commit()
            raise Problem(503, "terminal_unavailable", "Could not open the Owner terminal: " + str(error))
        self.processes[key] = process
        saved["state"] = "open"
        self.store.put("resume_window", key, saved)
        self.store.db.commit()
