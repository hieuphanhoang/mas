"""Portable intent validation and local, canonical path resolution."""
import ctypes
import json
import os
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator

from .common import Problem


def overlap(a, b):
    return a == b or a in b.parents or b in a.parents


def local_directory(raw):
    path = Path(raw)
    if not path.is_absolute() or any(p in (".", "..") for p in raw.replace("\\", "/").split("/")[1:]):
        raise Problem(422, "invalid_path", "Folders must be canonical absolute local directories.")
    if os.name == "nt":
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor))
        if drive_type not in (2, 3, 6):
            raise Problem(422, "invalid_path", "Network or unavailable drives cannot be registered.")
    if not path.is_dir() or path.resolve() != path.absolute():
        raise Problem(422, "invalid_path", "Folder is missing or resolves through a reparse point.")
    return path.resolve()


def resolve(config, ref):
    folder = next((f for f in config["folders"] if f["id"] == ref["folder_id"]), None)
    if folder is None:
        raise Problem(422, "invalid_reference", "Unknown folder reference.")
    root = local_directory(folder["path"])
    raw = ref["path"]
    rel = PurePosixPath(raw)
    if rel.is_absolute() or ".." in rel.parts or "\\" in raw or ":" in raw or "\x00" in raw:
        raise Problem(422, "invalid_path", "Path must stay inside its registered folder.")
    path = root.joinpath(*rel.parts)
    actual = path.resolve()
    if not actual.is_relative_to(root) or actual != path.absolute():
        raise Problem(422, "invalid_path", "Symlink/reparse paths are not supported.")
    # Windows aliases and streams must not bypass path identity checks.
    if os.name == "nt" and any(p.endswith((" ", ".")) or Path(p).is_reserved() for p in rel.parts):
        raise Problem(422, "invalid_path", "Windows reserved or ambiguous path.")
    return actual


class ConfigValidator:
    def __init__(self, contract_dir):
        self.schema = json.loads((contract_dir / "project.schema.json").read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema)

    def validate(self, config):
        errors = sorted(self.validator.iter_errors(config), key=lambda e: str(list(e.path)))
        if errors:
            raise Problem(422, "validation_error", "Project configuration is invalid.", [
                dict(location="/" + "/".join(map(str, e.path)), code=str(e.validator), message=e.message[:2000])
                for e in errors[:100]])
        collections = {}
        for name in ("folders", "logs", "levels", "agents", "rituals"):
            entries = config[name]
            collections[name] = {e["id"]: e for e in entries}
            if len(collections[name]) != len(entries):
                raise Problem(422, "duplicate_id", f"Duplicate IDs in {name}.")
        agents, logs = collections["agents"], collections["logs"]
        if len({a["name"].casefold() for a in agents.values()}) != len(agents):
            raise Problem(422, "duplicate_name", "Agent names must be unique.")
        try:
            ZoneInfo(config["project"]["timezone"])
            for ritual in config["rituals"]:
                ZoneInfo(ritual["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise Problem(422, "invalid_timezone", "Use an IANA timezone.")
        root = local_directory(config["project"]["root"])
        folders = [local_directory(f["path"]) for f in config["folders"]]
        if root not in folders:
            raise Problem(422, "invalid_reference", "Register the project root as a folder.")
        if len(set(folders)) != len(folders):
            raise Problem(422, "duplicate_folder", "Folder aliases must not duplicate a directory.")

        def require(name, value):
            if value not in collections[name]:
                raise Problem(422, "invalid_reference", f"Unknown {name} reference: {value}")

        protected = [resolve(config, r) for r in config["guard_policy"]["protected_paths"]]
        owned = []
        log_paths = []
        for log in logs.values():
            log_paths.append(resolve(config, {"folder_id": log["folder_id"], "path": log["relative_path"]}))
            for member in log["members"]:
                require("agents", member)
                if agents[member]["log_duty"] != "member" or log["id"] not in agents[member]["log_ids"]:
                    raise Problem(422, "invalid_membership", "Log and agent membership must agree.")
        for agent in agents.values():
            require("levels", agent["level_id"])
            require("folders", agent["cwd_folder_id"])
            for log_id in agent["log_ids"]:
                require("logs", log_id)
                if agent["id"] not in logs[log_id]["members"]:
                    raise Problem(422, "invalid_membership", "Log and agent membership must agree.")
            if agent["log_duty"] == "helper":
                sponsor = agent["sponsor_agent_id"]
                require("agents", sponsor)
                if sponsor == agent["id"] or agents[sponsor]["log_duty"] != "member" or agent["log_ids"]:
                    raise Problem(422, "invalid_sponsor", "Helpers need a distinct member sponsor and no log membership.")
            for ref in agent["reads"]:
                resolve(config, ref)
            if "prompt_file" in agent:
                resolve(config, agent["prompt_file"])
            for ref in agent["owns"]:
                path = resolve(config, ref)
                if any(overlap(path, p) for p in protected + log_paths):
                    raise Problem(422, "ownership_conflict", "Ownership intersects protected paths or a shared log.")
                if any(other != agent["id"] and overlap(path, p) for other, p in owned):
                    raise Problem(422, "ownership_conflict", "Agent ownership paths overlap.")
                owned.append((agent["id"], path))
        for ritual in config["rituals"]:
            require("agents", ritual["target_agent_id"])
            resolve(config, ritual["prompt_file"])
        for edge in config["call_policy"]["allowed_edges"]:
            require("agents", edge["from_agent_id"])
            require("agents", edge["to_agent_id"])
            if edge["from_agent_id"] == edge["to_agent_id"]:
                raise Problem(422, "invalid_edge", "Self-call edges are forbidden.")
        return config
