"""Preview-bound, generated-only writes. Never overwrite harness instructions."""
import difflib
import json
import os
from datetime import timedelta
from pathlib import Path

from .common import Problem, digest, encoded, stamp, token, utcnow
from .config import resolve

MAX_FILE = 2 * 1024 * 1024
PREAMBLE = "# MAS role prompt v1\n\nRead the project's .handoff/PROTOCOL.md and ROSTER.md before work.\nRespect ownership; record decisions in the assigned thread.\n\n## Role\n\n"


def read_file(path):
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_FILE + 1)
    except FileNotFoundError:
        return None
    if len(data) > MAX_FILE:
        raise Problem(413, "file_too_large", "Generated input exceeds the bounded read size.")
    return data


def hash_file(path):
    data = read_file(path)
    return digest(data) if data is not None else None


def atomic_write(path, data, create=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".mas-" + token() + ".tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if create:
            # Hard-link creation is atomic and fails if a concurrent writer won.
            os.link(temp, path)
        else:
            os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class Scaffold:
    def __init__(self, store):
        self.store = store

    def preview(self, record):
        config = record["config"]
        project_id = config["project"]["id"]
        root_folder = next(f["id"] for f in config["folders"]
                           if Path(f["path"]) == Path(config["project"]["root"]))
        intent = {"folder_id": root_folder, "path": ".agents/mas/project.json"}
        targets = [(intent, (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode(), "intent")]
        for agent in config["agents"]:
            explicit = agent.get("prompt_file")
            ref = explicit or {"folder_id": agent["cwd_folder_id"], "path": f".agents/mas/prompts/{agent['id']}.md"}
            targets.append((ref, (PREAMBLE + agent["role"] + "\n").encode(), "explicit" if explicit else "prompt"))
        seen = set()
        changes, inputs, warnings = [], [], [
            "I1 generates project intent and missing role prompts only; existing harness instructions and handoff files are preserved.",
            "Guard coverage and live adapters are not verified in I1. Apply does not authorize dispatch.",
        ]
        manifest = self.store.get("manifest", project_id) or {}
        for ref, desired, kind in targets:
            path = resolve(config, ref)
            identity = str(path).casefold()
            if identity in seen:
                raise Problem(422, "generator_conflict", "Two prompt/config targets resolve to the same file.")
            seen.add(identity)
            conflict = None
            try:
                before = read_file(path)
                before_text = before.decode("utf-8") if before is not None else ""
            except (OSError, UnicodeError) as error:
                before = None
                before_text = ""
                conflict = f"Cannot read target as UTF-8 text: {type(error).__name__}"
            before_hash = digest(before) if before is not None else None
            after = desired
            action = "create" if before is None else "update"
            if kind == "explicit":
                after = before
                action = "unchanged"
                if before is None:
                    conflict = "Explicit prompt_file must already exist and be readable."
            elif kind == "prompt" and before is not None:
                after, action = before, "unchanged"
                if before != desired:
                    warnings.append(f"Existing prompt preserved despite role/preamble drift: {ref['path']}")
            elif before == desired:
                action = "unchanged"
            elif before is not None and manifest.get(identity) != before_hash:
                conflict = "Existing file is unmanaged or has changed since the last MAS apply."
            if conflict:
                action, after = "conflict", before
            diff = "" if after == before else "".join(difflib.unified_diff(
                before_text.splitlines(keepends=True), (after or b"").decode().splitlines(keepends=True),
                fromfile=ref["path"], tofile=ref["path"]))
            if len(diff) > 262144:
                raise Problem(413, "diff_too_large", "Preview diff exceeds the contract limit; nothing was truncated.")
            changes.append(dict(path=ref, action=action, before_sha256=before_hash,
                                after_sha256=digest(after) if after is not None else None,
                                diff=diff, conflict_reason=conflict))
            inputs.append(dict(ref=ref, identity=identity, before=before_hash,
                               after=digest(after) if after is not None else None,
                               text=after.decode() if after is not None else None, action=action))
        preview = dict(preview_id=token(), project_id=project_id, revision=record["revision"],
                       expires_at=stamp(utcnow() + timedelta(minutes=15)),
                       can_apply=all(c["action"] != "conflict" for c in changes), changes=changes, warnings=warnings)
        self.store.put("preview", preview["preview_id"], dict(public=preview, inputs=inputs))
        return preview

    def apply(self, record, preview_id):
        saved = self.store.get("preview", preview_id)
        if not saved or saved["public"]["project_id"] != record["config"]["project"]["id"]:
            raise Problem(404, "not_found", "Unknown preview for this project.")
        preview = saved["public"]
        journal = self.store.get("journal", preview_id)
        if preview["revision"] != record["revision"]:
            raise Problem(409, "revision_conflict", "Preview belongs to a different configuration revision.")
        if not journal and preview["expires_at"] <= stamp():
            raise Problem(409, "preview_expired", "Preview expired; generate a fresh preview.")
        if not preview["can_apply"]:
            raise Problem(409, "apply_conflict", "Preview contains file conflicts.")
        if journal and journal["state"] == "complete":
            return record
        # Check EVERY input before writing the first file. Re-resolve paths now.
        for item in saved["inputs"]:
            path = resolve(record["config"], item["ref"])
            actual = hash_file(path)
            allowed = {item["before"]}
            if journal and item["action"] in ("create", "update"):
                allowed.add(item["after"])
            if actual not in allowed:
                record["scaffold_state"] = "conflict"
                self.store.save_project(record)
                self.store.db.commit()
                raise Problem(409, "file_conflict", "A preview input changed; generate a fresh preview.")
        journal = journal or dict(project_id=preview["project_id"], state="pending", completed=[])
        self.store.put("journal", preview_id, journal)
        self.store.db.commit()
        try:
            manifest = self.store.get("manifest", preview["project_id"]) or {}
            for index, item in enumerate(saved["inputs"]):
                if item["action"] not in ("create", "update"):
                    continue
                path = resolve(record["config"], item["ref"])
                actual = hash_file(path)
                if actual != item["after"]:
                    if actual != item["before"]:
                        raise Problem(409, "file_conflict", "Concurrent external file edit detected during apply.")
                    previous = read_file(path)
                    if previous is not None:
                        backup = self.store.directory / "backups" / preview_id / str(index)
                        if not backup.exists():
                            atomic_write(backup, previous, create=True)
                    # Direct external writers have a check/replace race; the journal
                    # never claims filesystem-wide locking over other processes.
                    atomic_write(path, item["text"].encode(), create=item["before"] is None)
                manifest[item["identity"]] = item["after"]
                if index not in journal["completed"]:
                    journal["completed"].append(index)
                self.store.put("journal", preview_id, journal)
                self.store.db.commit()
            record.update(applied_revision=record["revision"], scaffold_state="applied")
            journal["state"] = "complete"
            self.store.put("manifest", preview["project_id"], manifest)
            self.store.put("journal", preview_id, journal)
            self.store.save_project(record)
            return record
        except (OSError, Problem) as error:
            record["scaffold_state"] = "apply_failed"
            journal["state"] = "failed"
            self.store.put("journal", preview_id, journal)
            self.store.save_project(record)
            self.store.db.commit()
            if isinstance(error, Problem):
                raise
            location = str(error.filename or path)
            os_code = "winerror_" + str(error.winerror) if getattr(error, "winerror", None) is not None else "errno_" + str(error.errno)
            raise Problem(503, "apply_failed", "Partial apply recorded; reconcile the same preview with a new request key.",
                          details=[dict(location=location[:500], code=os_code, message=str(error)[:2000])])
