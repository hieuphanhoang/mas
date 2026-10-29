"""Read-only handoff projection. The local CLI is never imported or executed."""
import copy
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .common import Problem, digest, stamp
from .config import resolve
from .scaffold import read_file

THREAD_ID = r"(?:AGENT|ASK)-[0-9]{3,}"
LIVE = {"open", "answered", "blocked"}
STATUSES = LIVE | {"closed", "withdrawn", "superseded"}
TYPES = {"STATUS", "QUESTION", "REQUEST", "ANSWER", "DECISION", "BLOCKER", "ACK"}


def freshness(state="current", observed=None, reason=None):
    return dict(state=state, observed_at=observed or stamp(), reason=reason)


def parse_thread(raw, reference, zone):
    text = raw.decode("utf-8-sig")
    errors = []
    header = text.split("\n---", 1)[0]
    fields = dict(re.findall(r"^\|\s*\*\*(.*?)\*\*\s*\|\s*(.*?)\s*\|\s*$", header, re.M))
    title_match = re.match(r"#\s+`" + re.escape(reference["thread_id"]) + r"`\s*[-:]\s*(.+)", text)
    title = title_match.group(1).strip() if title_match else None
    if title is None:
        errors.append("Missing or mismatched thread title.")
    status, kind = fields.get("Status"), fields.get("Type")
    if status not in STATUSES:
        errors.append("Missing or unrecognized Status.")
        status = None
    if kind not in TYPES:
        errors.append("Missing or unrecognized Type.")
        kind = None
    participants = fields.get("From -> To", "").split("->")
    frm, to = (p.strip() for p in participants) if len(participants) == 2 else (None, None)
    if not frm or not to:
        errors.append("Missing or ambiguous From -> To.")
        frm, to = None, None
    speakers = []
    fence = None
    for line in text.splitlines():
        match = re.match(r"^\s*(`{3,}|~{3,})", line)
        if match:
            marker = match.group(1)[0]
            fence = None if fence == marker else marker if fence is None else fence
        if fence is None:
            match = re.fullmatch(r"\*\*\[([^,\]]+),\s*\d{4},\s*\d{4}\]\*\*\s*", line)
            if match:
                speakers.append(match.group(1).strip())
    owes = to if status in LIVE else None
    if owes and frm and to:
        for speaker in reversed(speakers):
            if speaker.casefold() == frm.casefold():
                owes = to
                break
            if speaker.casefold() == to.casefold():
                owes = frm
                break
    # An Owner answer stays answered even when the requesting member subsequently
    # acknowledges it. Only reopening the thread starts another Owner question.
    if reference["thread_id"].startswith("ASK-") and status == "answered" and any(s.casefold() == "owner" for s in speakers):
        owes = frm
    updated = None
    try:
        naive = datetime.strptime(fields.get("Updated", fields.get("Time", "")), "%Y-%m-%d %H:%M")
        tz = ZoneInfo(zone)
        first, second = naive.replace(tzinfo=tz, fold=0), naive.replace(tzinfo=tz, fold=1)
        if first.utcoffset() != second.utcoffset() or first.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != naive:
            raise ValueError("ambiguous timestamp")
        updated = stamp(first.astimezone(timezone.utc))
    except (ValueError, KeyError):
        errors.append("Missing, invalid or ambiguous local timestamp.")
    metadata = dict(thread_ref=reference, title=title, type=kind, status=status, from_name=frm,
                    to_name=to, owes_reply=owes, updated_at=updated, revision=digest(raw), parse_errors=errors)
    return dict(metadata=metadata, markdown=text, freshness=freshness("parse_error" if errors else "current",
                reason="; ".join(errors) or None), event_cursor="0")


def section_text(text, section):
    if section == "history":
        match = re.search(r"^## Conversation history\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    else:
        marker = {"awaiting_owner": "awaiting", "open": "open", "all": "threads"}[section]
        match = re.search(r"<!-- handoff:" + marker + r":start -->(.*?)<!-- handoff:" + marker + r":end -->", text, re.S)
    return match.group(1) if match else None


def table_rows(text):
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)[1:-1]]
        if cells and not all(re.fullmatch(r"[: -]*", c) for c in cells):
            yield cells


class Logs:
    def __init__(self, store):
        self.store = store

    def config(self, record, log_id):
        log = next((l for l in record["config"]["logs"] if l["id"] == log_id), None)
        if log is None:
            raise Problem(404, "not_found", "Unknown log.")
        return log

    def base(self, record, log):
        return resolve(record["config"], dict(folder_id=log["folder_id"], path=log["relative_path"]))

    def view(self, record, log, fresh):
        return dict(project_id=record["config"]["project"]["id"], log_id=log["id"],
                    folder_id=log["folder_id"], members=log["members"], freshness=fresh)

    def cached_read(self, key, reader):
        try:
            value = reader()
        except (OSError, UnicodeError, Problem) as error:
            # Oversized content must remain an explicit 413 even with a cache.
            if isinstance(error, Problem) and error.status == 413:
                raise
            saved = self.store.get("log_cache", key)
            if saved:
                value = copy.deepcopy(saved)
                fresh = value.get("freshness", value.get("log", {}).get("freshness"))
                fresh.update(state="stale", reason=f"Source unavailable: {type(error).__name__}")
                return value
            if isinstance(error, Problem) and error.status == 404:
                raise
            raise Problem(503, "log_unavailable", "Log source is unavailable and has no cached data.")
        self.store.put("log_cache", key, value)
        self.store.db.commit()
        return value

    def thread(self, record, log_id, thread_id):
        if not re.fullmatch(THREAD_ID, thread_id):
            raise Problem(422, "validation_error", "Invalid thread ID.")
        log = self.config(record, log_id)
        project_id = record["config"]["project"]["id"]
        key = f"thread:{project_id}:{log_id}:{record['revision']}:{thread_id}"

        def read():
            base = self.base(record, log)
            directory = base / "threads"
            if not directory.is_dir():
                raise OSError("Thread directory unavailable")
            # glob scans a configured directory, never an untrusted link from markdown.
            paths = [p for p in directory.glob(thread_id + "-*.md") if p.is_file()]
            if not paths:
                raise Problem(404, "not_found", "Unknown thread.")
            if len(paths) != 1:
                raise Problem(503, "ambiguous_thread", "Duplicate thread ID filenames.")
            ref = dict(folder_id=log["folder_id"], path=paths[0].relative_to(base.parent).as_posix())
            path = resolve(record["config"], ref)
            raw = read_file(path)
            if raw is None:
                raise OSError("Thread disappeared")
            return parse_thread(raw, dict(project_id=project_id, log_id=log_id, thread_id=thread_id),
                                record["config"]["project"]["timezone"])

        return self.cached_read(key, read)

    def index(self, record, log_id, section):
        log = self.config(record, log_id)
        project_id = record["config"]["project"]["id"]
        key = f"index:{project_id}:{log_id}:{record['revision']}:{section}"

        def read():
            path = resolve(record["config"], dict(folder_id=log["folder_id"], path=log["relative_path"] + "/INDEX.md"))
            raw = read_file(path)
            if raw is None:
                raise OSError("Index missing")
            text = raw.decode("utf-8-sig")
            content = section_text(text, section)
            errors, items = [], []
            if content is None:
                errors.append("Missing index section: " + section)
            else:
                for cells in table_rows(content):
                    if section == "history":
                        if cells[0] == "Time" or not any(cells):
                            continue
                        if len(cells) != 4:
                            errors.append("Malformed history row.")
                            continue
                        items.append(dict(time_text=cells[0], speaker=cells[1],
                                          threads=re.findall(THREAD_ID, cells[2]), summary=cells[3]))
                    else:
                        match = re.search(THREAD_ID, cells[0])
                        if not match:
                            if cells[0] not in ("ID", "-", ""):
                                errors.append("Unrecognized thread row.")
                            continue
                        thread_id = match.group(0)
                        try:
                            document = self.thread(record, log_id, thread_id)
                            items.append(document["metadata"])
                            if document["freshness"]["state"] != "current":
                                errors.append(f"{thread_id}: {document['freshness']['state']}")
                        except Problem as error:
                            if error.status == 413:
                                raise
                            errors.append(f"{thread_id}: {error.code}")
                            items.append(dict(thread_ref=dict(project_id=project_id, log_id=log_id, thread_id=thread_id),
                                              title=None, type=None, status=None, from_name=None, to_name=None,
                                              owes_reply=None, updated_at=None, revision=digest(encoded_ref(thread_id)),
                                              parse_errors=[error.message]))
            fresh = freshness("parse_error" if errors else "current", reason="; ".join(errors)[:2000] or None)
            return dict(log=self.view(record, log, fresh), revision=digest(raw), section=section, items=items,
                        next_cursor=None, event_cursor="0")

        return self.cached_read(key, read)

    def list(self, record):
        views = []
        for log in record["config"]["logs"]:
            try:
                views.append(self.index(record, log["id"], "all")["log"])
            except Problem as error:
                views.append(self.view(record, log, dict(state="unavailable", observed_at=None, reason=error.message)))
        return views

    def inbox(self):
        items, sources = [], []
        for record in self.store.projects():
            for log in record["config"]["logs"]:
                try:
                    # Enumerate actual files so a stale INDEX cannot hide a new ASK.
                    directory = self.base(record, log) / "threads"
                    if not directory.is_dir():
                        raise OSError("Thread directory unavailable")
                    source = self.index(record, log["id"], "all")["log"]
                    for path in sorted(directory.glob("ASK-*.md")):
                        match = re.match(r"(ASK-[0-9]{3,})-", path.name)
                        if not match:
                            continue
                        document = self.thread(record, log["id"], match.group(1))
                        metadata = document["metadata"]
                        if document["freshness"]["state"] != "current":
                            source["freshness"] = document["freshness"]
                        if metadata["status"] in LIVE and (metadata["owes_reply"] or "").casefold() == "owner":
                            items.append(metadata)
                    sources.append(source)
                except (OSError, Problem) as error:
                    sources.append(self.view(record, log, dict(state="unavailable", observed_at=None,
                                        reason=error.message if isinstance(error, Problem) else "Log directory unavailable.")))
        items.sort(key=lambda i: (i["updated_at"] or "", *i["thread_ref"].values()))
        return items, sources


def encoded_ref(thread_id):
    return ("missing:" + thread_id).encode()
