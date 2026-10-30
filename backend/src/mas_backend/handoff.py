"""Journalled calls to the application's trusted handoff CLI, not project code."""
import os
from pathlib import Path
import re
import shutil
import subprocess

from .common import Problem, digest, stamp, token
from .config import resolve
from .scaffold import read_file


class Handoff:
    def __init__(self, store, logs, cli):
        self.store, self.logs, self.cli = store, logs, cli.resolve()

    def execute(self, record, log_id, args, body=None):
        log = self.logs.config(record, log_id)
        root = self.logs.base(record, log).parent
        # Resolve all CLI write targets before running the trusted tool.
        for relative in (".handoff", ".handoff/threads", ".handoff/INDEX.md"):
            resolve(record["config"], dict(folder_id=log["folder_id"], path=relative))
        for path in (root / ".handoff/threads").glob("*.md"):
            resolve(record["config"], dict(folder_id=log["folder_id"], path=path.relative_to(root).as_posix()))
        uv = shutil.which("uv")
        if not uv or not self.cli.is_file():
            raise Problem(503, "handoff_unavailable", "uv or the trusted handoff CLI is unavailable.")
        command = [uv, "run", "--no-project", str(Path(__file__).with_name("handoff_bridge.py")), "--cli", str(self.cli)]
        body_path = None
        if body is not None:
            body_path = self.store.directory / ("body-" + token() + ".txt")
            body_path.write_bytes(body.encode("utf-8"))
            command += ["--body-file", str(body_path)]
        command += ["--", "--root", str(root), "--state-dir", ".handoff", *args]
        env = dict(os.environ, UV_CACHE_DIR=str(self.store.directory / "uv-cache"),
                   UV_OFFLINE="true", UV_PYTHON_DOWNLOADS="never", PYTHONUTF8="1")
        try:
            return subprocess.run(command, cwd=self.store.directory, env=env, capture_output=True,
                                  timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            raise Problem(409, "uncertain", "Handoff execution was interrupted; inspect its journal before retry.")
        finally:
            if body_path:
                body_path.unlink(missing_ok=True)

    def append(self, record, log_id, body, *, thread_id=None, expected=None, target=None):
        project_id = record["config"]["project"]["id"]
        log = self.logs.config(record, log_id)
        base = self.logs.base(record, log)
        if not (base / "threads").is_dir():
            raise Problem(503, "log_unavailable", "Log threads directory is unavailable.")
        # Block *fresh keys* too when a prior append has an ambiguous outcome.
        scope = f"{project_id}:{log_id}"
        for old in self.store.documents("append_journal"):
            if old["scope"] == scope and old["state"] in ("pending", "uncertain", "appended"):
                raise Problem(409, "uncertain", "An earlier log write needs reconciliation; no repeat append allowed.")
        before = None
        path = None
        existing = {p.name for p in (base / "threads").glob("AGENT-*.md")}
        if thread_id:
            document = self.logs.thread(record, log_id, thread_id)
            if document["freshness"]["state"] != "current":
                raise Problem(409, "thread_unavailable", "A current, parseable thread is required for writing.")
            before = document["metadata"]["revision"]
            if expected is not None and before != expected:
                raise Problem(409, "revision_conflict", "Thread changed since it was read.")
            path = next((base / "threads").glob(thread_id + "-*.md"))
        journal_id = token()
        journal = dict(scope=scope, state="pending", thread_id=thread_id, before=before,
                       body_sha256=digest(body.encode()), started_at=stamp())
        self.store.put("append_journal", journal_id, journal)
        self.store.db.commit()
        if path and digest(read_file(path) or b"") != before:
            journal["state"] = "conflict"
            self.store.put("append_journal", journal_id, journal)
            self.store.db.commit()
            raise Problem(409, "revision_conflict", "Thread changed immediately before append.")
        args = (["reply", thread_id, "--frm", "Owner", "--status", "answered"] if thread_id else
                ["new", "Owner message", "--frm", "Owner", "--to", target, "--type", "REQUEST"])
        try:
            result = self.execute(record, log_id, args, body)
            if not thread_id:
                created = [p for p in (base / "threads").glob("AGENT-*.md") if p.name not in existing]
                if len(created) != 1:
                    raise Problem(409, "uncertain", "Cannot uniquely identify the created thread.")
                thread_id = re.match(r"AGENT-[0-9]{3,}", created[0].name).group()
                path = created[0]
            # Nonzero exit may mean append succeeded but sync failed. Verify the
            # exact submitted text in the newly appended tail before reporting it.
            raw = read_file(path)
            text = raw.decode("utf-8") if raw is not None else ""
            last = text.rsplit("\n---\n", 1)[-1]
            expected_body = body.replace("\r\n", "\n").replace("\r", "\n")
            if "**[Owner," not in last or not text.replace("\r\n", "\n").endswith(expected_body + "\n"):
                raise Problem(409, "uncertain", "Cannot prove the Owner text was appended; reconcile before retry.")
            document = self.logs.thread(record, log_id, thread_id)
            journal.update(state="appended", thread_id=thread_id, after=document["metadata"]["revision"],
                           sync_state="synced" if result.returncode == 0 else "failed")
            self.store.put("append_journal", journal_id, journal)
            self.store.db.commit()
        except Problem:
            journal["state"] = "uncertain"
            self.store.put("append_journal", journal_id, journal)
            self.store.db.commit()
            raise
        reference = dict(project_id=project_id, log_id=log_id, thread_id=thread_id)
        metadata = document["metadata"]
        self.store.emit(project_id, "thread.changed", f"{log_id}/{thread_id}",
                        dict(thread_ref=reference, revision=metadata["revision"], change="updated" if before else "created",
                             status=metadata["status"]), correlation=journal_id)
        self.store.emit(project_id, "inbox.changed", f"{log_id}/{thread_id}", dict(thread_ref=reference), correlation=journal_id)
        self.store.db.commit()
        return dict(reply_id=journal_id, thread_ref=reference, revision=metadata["revision"], stamped_at=stamp(),
                    sync_state=journal["sync_state"], wake_state="not_requested", wake_delivery=None,
                    reason=None if journal["sync_state"] == "synced" else "Append committed; index sync failed.")

    def complete(self, receipt):
        # Caller commits this together with its delivery/HTTP receipt. A crash
        # before that commit leaves appended, blocking even a fresh request key.
        journal = self.store.get("append_journal", receipt["reply_id"])
        journal["state"] = "complete"
        self.store.put("append_journal", receipt["reply_id"], journal)
