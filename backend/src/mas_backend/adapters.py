"""Headless Claude/Codex/OpenCode adapters. No shell or session guessing.

Protocol sources: https://learn.chatgpt.com/docs/non-interactive-mode and
https://code.claude.com/docs/en/cli-reference; installed CLI --help is also
checked by probe(). Model turns are never part of the probe.
"""

import asyncio
import codecs
from dataclasses import dataclass
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import uuid

from .guard_paths import handoff_commands, claude_edits, mas_commands


class AdapterError(Exception):
    def __init__(self, reason, uncertain=False):
        self.reason, self.uncertain = reason, uncertain
        super().__init__(reason)


@dataclass
class Outcome:
    exit_code: int | None
    session_id: str | None
    reason: str | None = None
    cancelled: bool = False
    uncertain: bool = False


def executable(harness):
    found = shutil.which(harness)
    if found and Path(found).suffix.lower() not in (".cmd", ".bat", ".ps1"):
        return found
    if harness == "codex" and os.name == "nt":
        # npm's shell shim is not used for launch. Resolve only its installed
        # native package, without interpreting wrapper contents or shell text.
        parents = [Path(found).parent] if found else []
        if os.environ.get("APPDATA"):
            parents.append(Path(os.environ["APPDATA"]) / "npm")
        for parent in parents:
            package = parent / "node_modules/@openai/codex/node_modules/@openai"
            candidates = sorted(set(package.glob("codex-win32-*/vendor/*/bin/codex.exe")) |
                                set(package.glob("codex-win32-*/vendor/*/codex/codex.exe")))
            if len(candidates) == 1 and candidates[0].is_file():
                return str(candidates[0])
    if harness == "opencode" and os.name == "nt":
        parents = [Path(found).parent] if found else []
        if os.environ.get("APPDATA"):
            parents.append(Path(os.environ["APPDATA"]) / "npm")
        for parent in parents:
            binary = parent / "node_modules/opencode-ai/bin/opencode.exe"
            if binary.is_file():
                return str(binary)
    return None


def clean_environment(extra=None):
    allowed = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMDATA",
        "USERNAME",
        "USERDOMAIN",
        "LANG",
        "LC_ALL",
        "CODEX_HOME",
        "ANTHROPIC_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "OLLAMA_HOST",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "NODE_EXTRA_CA_CERTS",
    }
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    if extra:
        env.update(extra)
    return env


def valid_session(harness, value):
    if not isinstance(value, str):
        return False
    if harness == "opencode":
        return re.fullmatch(r"ses_[A-Za-z0-9]{1,120}", value) is not None
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


class OwnedTree:
    """Hold an OS job/process group for exactly this spawned process tree."""

    def __init__(self, process):
        self.process = process
        self.job = None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes as w

            class Basic(ctypes.Structure):
                _fields_ = [
                    ("process_time", ctypes.c_longlong),
                    ("job_time", ctypes.c_longlong),
                    ("flags", w.DWORD),
                    ("min_ws", ctypes.c_size_t),
                    ("max_ws", ctypes.c_size_t),
                    ("active", w.DWORD),
                    ("affinity", ctypes.c_size_t),
                    ("priority", w.DWORD),
                    ("scheduling", w.DWORD),
                ]

            class Counters(ctypes.Structure):
                _fields_ = [
                    (n, ctypes.c_ulonglong)
                    for n in (
                        "read_ops",
                        "write_ops",
                        "other_ops",
                        "read_bytes",
                        "write_bytes",
                        "other_bytes",
                    )
                ]

            class Extended(ctypes.Structure):
                _fields_ = [
                    ("basic", Basic),
                    ("io", Counters),
                    ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t),
                    ("peak_process", ctypes.c_size_t),
                    ("peak_job", ctypes.c_size_t),
                ]

            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
            self.kernel.CreateJobObjectW.restype = w.HANDLE
            self.kernel.SetInformationJobObject.argtypes = [
                w.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                w.DWORD,
            ]
            self.kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
            self.kernel.OpenProcess.restype = w.HANDLE
            self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
            self.kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
            self.kernel.CloseHandle.argtypes = [w.HANDLE]
            job = self.kernel.CreateJobObjectW(None, None)
            limits = Extended()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            handle = self.kernel.OpenProcess(0x0100 | 0x0001, False, process.pid)
            ok = (
                job
                and handle
                and self.kernel.SetInformationJobObject(
                    job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
                )
            )
            ok = ok and self.kernel.AssignProcessToJobObject(job, handle)
            if handle:
                self.kernel.CloseHandle(handle)
            if not ok:
                if job:
                    self.kernel.CloseHandle(job)
                raise AdapterError("process_tree_unavailable", uncertain=True)
            self.job = job

    async def stop(self):
        if self.process.stdin:
            self.process.stdin.close()
        if os.name == "nt":
            # No interactive console is owned for print-mode children. EOF is
            # the graceful attempt; then terminate this held job only.
            try:
                await asyncio.wait_for(self.process.wait(), 0.3)
            except asyncio.TimeoutError:
                self.kernel.TerminateJobObject(self.job, 130)
        else:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.process.wait(), 0.3)
            except asyncio.TimeoutError:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        await asyncio.wait_for(self.process.wait(), 5)

    def close(self):
        if self.job:
            self.kernel.CloseHandle(self.job)
            self.job = None
        elif os.name != "nt":
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


class Adapter:
    def __init__(self, harness, command=None):
        self.harness = harness
        native = executable(harness) if command is None else None
        self.command = (
            list(command) if command is not None else [native] if native else []
        )

    def probe(self):
        if not self.command:
            return None, "Executable not found."
        try:
            opts = dict(
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                env=clean_environment(),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            version = subprocess.run([*self.command, "--version"], **opts)
            help_text = subprocess.run(
                [
                    *self.command,
                    *(["exec"] if self.harness == "codex" else ["run"] if self.harness == "opencode" else []),
                    "--help",
                ],
                **opts,
            )
            needed = ("--format", "--model", "--session", "--agent", "--pure", "--title") if self.harness == "opencode" else (
                ("--json", "--sandbox", "--model")
                if self.harness == "codex"
                else (
                    "--session-id",
                    "--resume",
                    "--output-format",
                    "--permission-prompts",
                    "--name",
                )
            )
            help_output = help_text.stdout + (help_text.stderr if self.harness == "opencode" else "")
            if (
                version.returncode
                or help_text.returncode
                or not all(flag in help_output for flag in needed)
            ):
                return (
                    None,
                    "Installed CLI does not expose the required structured-output/session/permission flags.",
                )
            if self.harness == "codex":
                resume = subprocess.run(
                    [*self.command, "exec", "resume", "--help"], **opts
                )
                if (
                    resume.returncode
                    or "SESSION_ID" not in resume.stdout
                    or "--json" not in resume.stdout
                ):
                    return None, "Installed Codex resume interface is unsupported."
            return version.stdout.strip().splitlines()[0][:100], None
        except (OSError, subprocess.TimeoutExpired, IndexError):
            return None, "Executable probe failed or timed out."

    def argv(self, model, session_id=None, effort=None, candidate=None, smoke=False, permission_profile="default", *, owned_paths=(), handoff_paths=(), cwd=None, session_label=None):
        if permission_profile not in ("default", "member"):
            raise AdapterError("unsupported_configuration")
        if not self.command or not model or model.startswith("-"):
            raise AdapterError("unsupported_configuration")
        if session_id and not valid_session(self.harness, session_id):
            raise AdapterError("invalid_session_id", uncertain=True)
        if self.harness == "opencode":
            if not re.fullmatch(r"[^/\s]+/[^\s]+", model) or smoke:
                raise AdapterError("unsupported_configuration")
            args = [*self.command, "run", "--pure", "--format", "json",
                    "--model", model, "--agent", "mas"]
            if session_id:
                args += ["--session", session_id]
            elif session_label:
                args += ["--title", session_label]
            if effort:
                args += ["--variant", effort]
            return args
        if self.harness == "claude":
            args = [
                *self.command,
                "--print",
                "--verbose",
                "--output-format",
                "stream-json",
                "--model",
                model,
                "--permission-mode",
                "manual",
                "--permission-prompts",
                "none",
                "--disallowedTools",
                "Agent,Task",
            ]
            args += (
                ["--resume", session_id] if session_id else ["--session-id", candidate]
            )
            if session_id is None and session_label:
                args += ["--name", session_label]
            if effort:
                args += ["--effort", effort]
            if permission_profile == "member" and not smoke:
                args += ["--allowedTools",
                         *[tool + "(" + command + ":*)" for tool in ("Bash", "PowerShell")
                           for command in [*mas_commands(), *handoff_commands(handoff_paths)]],
                         *claude_edits(owned_paths, cwd)]
            if smoke:
                args += [
                    "--tools",
                    "",
                    "--strict-mcp-config",
                    "--mcp-config",
                    '{"mcpServers":{}}',
                ]
            return args
        args = [
            *self.command,
            "exec",
            "--json",
            "--model",
            model,
            "--sandbox",
            "read-only" if smoke else "workspace-write",
            "--skip-git-repo-check",
            "-c",
            'approval_policy="never"',
            "-c",
            "features.multi_agent=false",
        ]
        if effort:
            args += ["-c", "model_reasoning_effort=" + json.dumps(effort)]
        if permission_profile == "member" and not smoke:
            args += ["-c", "sandbox_workspace_write.network_access=true"]
        if session_id:
            args += ["resume", session_id]
        return [*args, "-"]

    async def run(
        self,
        *,
        model,
        prompt,
        cwd,
        session_id,
        effort,
        timeout,
        cancelled,
        on_session,
        on_output,
        extra_env=None,
        smoke=False,
        permission_profile="default",
        owned_paths=(),
        handoff_paths=None,
        session_label=None,
    ):
        started = asyncio.get_running_loop().time()
        candidate = (
            str(uuid.uuid4())
            if self.harness == "claude" and session_id is None
            else None
        )
        handoff_paths = [Path(cwd) / ".handoff/handoff.py"] if handoff_paths is None else handoff_paths
        argv = self.argv(model, session_id, effort, candidate, smoke, permission_profile,
                         owned_paths=owned_paths, handoff_paths=handoff_paths, cwd=cwd,
                         session_label=session_label)
        env = clean_environment(extra_env)
        if self.harness == "opencode":
            from .opencode import launch_environment
            try:
                env.update(launch_environment(model, permission_profile, env, cwd=cwd,
                    owned_paths=owned_paths, handoff_paths=handoff_paths))
            except ValueError:
                return Outcome(None, session_id, "unsupported_configuration")
        secrets = [
            v
            for k, v in env.items()
            if any(word in k.upper() for word in ("TOKEN", "API_KEY")) and len(v) > 6
        ]
        observed, terminal, protocol_error = None, False, None
        total = 0
        process = None
        tree = None

        async def output(stream, text):
            nonlocal total
            for secret in secrets:
                text = text.replace(secret, "[redacted]")
            total += len(text.encode("utf-8"))
            if total > 8 * 1024 * 1024:
                raise AdapterError("output_limit")
            for start in range(0, len(text), 4096):
                on_output(stream, text[start : start + 4096])

        async def drain_stdout():
            nonlocal observed, terminal, protocol_error
            while raw := await process.stdout.readline():
                if len(raw) > 1024 * 1024:
                    raise AdapterError("protocol_line_limit")
                try:
                    text = raw.decode("utf-8")
                    event = json.loads(text)
                    if not isinstance(event, dict):
                        raise ValueError()
                except (ValueError, UnicodeError):
                    raise AdapterError("invalid_structured_output", uncertain=True)
                found = (
                    event.get("thread_id")
                    if event.get("type") == "thread.started"
                    else None
                )
                if self.harness == "claude":
                    found = event.get("session_id")
                elif self.harness == "opencode":
                    found = event.get("sessionID")
                if found:
                    if not valid_session(self.harness, found):
                        raise AdapterError("invalid_session_id", uncertain=True)
                    if (
                        (session_id and found != session_id)
                        or (candidate and found != candidate)
                        or (observed and found != observed)
                    ):
                        raise AdapterError("session_mismatch", uncertain=True)
                    if observed is None:
                        observed = found
                        on_session(found)
                if self.harness == "codex":
                    if event.get("type") == "turn.completed":
                        terminal = True
                    elif event.get("type") in ("turn.failed", "error"):
                        protocol_error = "provider_error"
                elif self.harness == "opencode":
                    if event.get("type") == "error":
                        protocol_error = "provider_error"
                    elif event.get("type") == "step_start":
                        terminal = False
                    elif event.get("type") == "step_finish":
                        reason = (event.get("part") or {}).get("reason")
                        # A tool step is not the final assistant answer.
                        terminal = reason in ("stop", "length")
                        if reason in ("error", "content-filter"):
                            protocol_error = "provider_error"
                elif event.get("type") == "result":
                    terminal = True
                    if (
                        event.get("is_error")
                        or event.get("subtype", "success") != "success"
                    ):
                        protocol_error = "provider_error"
                await output("stdout", text)

        async def drain_stderr():
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            pending = ""
            while raw := await process.stderr.read(4096):
                pending += decoder.decode(raw)
                # Retain a small tail across read boundaries so a bearer secret
                # split between writes cannot be persisted in separate chunks.
                if "\n" in pending:
                    last = pending.rfind("\n") + 1
                    await output("stderr", pending[:last])
                    pending = pending[last:]
                if len(pending) > 65536:
                    raise AdapterError("stderr_line_limit")
            pending += decoder.decode(b"", final=True)
            if pending:
                await output("stderr", pending)

        async def wait_cancel():
            while not cancelled():
                await asyncio.sleep(0.05)

        jobs = []
        try:
            kwargs = dict(
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                limit=2 * 1024 * 1024,
            )
            if os.name == "nt":
                kwargs["creationflags"] = (
                    subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                kwargs["start_new_session"] = True
            process = await asyncio.create_subprocess_exec(*argv, **kwargs)
            tree = OwnedTree(process)
            process.stdin.write(prompt.encode("utf-8"))
            await asyncio.wait_for(process.stdin.drain(), timeout=min(10, timeout))
            process.stdin.close()

            async def collect():
                await asyncio.gather(drain_stdout(), drain_stderr())
                return await process.wait()

            collected = asyncio.create_task(collect())
            cancel = asyncio.create_task(wait_cancel())
            jobs = [collected, cancel]
            remaining = max(0, timeout - (asyncio.get_running_loop().time() - started))
            done, _ = await asyncio.wait(
                jobs, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            if cancel in done:
                await tree.stop()
                return Outcome(
                    process.returncode, observed, "cancelled", cancelled=True
                )
            if collected not in done:
                await tree.stop()
                return Outcome(process.returncode, observed, "run_timeout")
            exit_code = collected.result()
            reason = protocol_error or ("process_failed" if exit_code else None)
            if observed is None or not terminal:
                return Outcome(
                    exit_code,
                    observed,
                    reason or "session_or_result_missing",
                    uncertain=observed is None or not bool(reason),
                )
            return Outcome(exit_code, observed, reason)
        except AdapterError as error:
            if tree:
                await tree.stop()
            return Outcome(
                process.returncode if process else None,
                observed,
                error.reason,
                uncertain=error.uncertain,
            )
        except asyncio.CancelledError:
            if tree:
                await tree.stop()
            return Outcome(
                process.returncode if process else None,
                observed,
                "cancelled",
                cancelled=True,
            )
        except asyncio.TimeoutError:
            if tree:
                await tree.stop()
            return Outcome(
                process.returncode if process else None, observed, "run_timeout"
            )
        except (OSError, BrokenPipeError):
            if tree:
                await tree.stop()
            return Outcome(
                process.returncode if process else None,
                observed,
                "spawn_or_io_failed",
                uncertain=process is not None,
            )
        finally:
            for job in jobs:
                job.cancel()
            if jobs:
                await asyncio.gather(*jobs, return_exceptions=True)
            if tree:
                tree.close()
            elif process and process.returncode is None:
                process.kill()
                await process.wait()
