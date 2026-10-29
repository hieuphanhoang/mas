"""Single-process SQLite registry, sessions, receipts and stable list snapshots."""
import json
import sqlite3
import threading
from datetime import timedelta

from .common import Problem, digest, encoded, stamp, token, utcnow


class Store:
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.lock = threading.RLock()
        self.db = sqlite3.connect(directory / "registry.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, root TEXT UNIQUE, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS documents (kind TEXT, id TEXT, data TEXT NOT NULL,
                PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL, occurred_at TEXT NOT NULL, data TEXT NOT NULL);
        """)
        self.migrate_delivery_purpose()
        # An interrupted apply is not success, even if its last file was written.
        for journal in self.documents("journal"):
            if journal["state"] != "complete":
                record = self.project(journal["project_id"])
                record["scaffold_state"] = "apply_failed"
                self.save_project(record)
        self.db.commit()

    def migrate_delivery_purpose(self):
        if self.get("migration", "delivery-purpose-0.2"):
            return

        def upgrade(value):
            if isinstance(value, dict):
                if {"delivery_id", "project_id", "agent_id", "kind", "state", "status_url"} <= value.keys():
                    value.setdefault("purpose", "task")
                for nested in value.values():
                    upgrade(nested)
            elif isinstance(value, list):
                for nested in value:
                    upgrade(nested)

        with self.db:
            rows = self.db.execute("SELECT kind,id,data FROM documents").fetchall()
            for kind, key, raw in rows:
                if kind not in ("delivery", "page", "receipt"):
                    continue
                value = json.loads(raw)
                upgrade(value)
                if encoded(value) != encoded(json.loads(raw)):
                    if kind == "receipt":
                        # Keep the original raw JSON, not a reserialized approximation.
                        self.db.execute("INSERT OR IGNORE INTO documents VALUES (?,?,?)", ("receipt_original", key, raw))
                    self.put(kind, key, value)
            for seq, raw in self.db.execute("SELECT seq,data FROM events").fetchall():
                value = json.loads(raw)
                upgrade(value)
                self.db.execute("UPDATE events SET data=? WHERE seq=?", (encoded(value).decode(), seq))
            self.put("migration", "delivery-purpose-0.2", {"completed_at": stamp()})

    def put(self, kind, key, data):
        self.db.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?)", (kind, key, encoded(data).decode()))

    def get(self, kind, key):
        row = self.db.execute("SELECT data FROM documents WHERE kind=? AND id=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def documents(self, kind):
        return [json.loads(r[0]) for r in self.db.execute("SELECT data FROM documents WHERE kind=?", (kind,))]

    def projects(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT data FROM projects ORDER BY id")]

    def project(self, project_id):
        row = self.db.execute("SELECT data FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise Problem(404, "not_found", "Unknown project.")
        value = json.loads(row[0])
        value["event_cursor"] = self.cursor(project_id)
        return value

    def cursor(self, project_id):
        saved = self.get("event_head", project_id)
        return saved["cursor"] if saved else "0"

    def emit(self, project_id, kind, entity_id, payload, correlation=None, revision=None):
        now = stamp()
        row = self.db.execute("INSERT INTO events(project_id,occurred_at,data) VALUES (?,?,?)",
                              (project_id, now, "{}"))
        event = dict(schema_version=1, event_id=str(row.lastrowid), project_id=project_id,
                     type=kind, occurred_at=now, entity_id=entity_id, revision=revision or token(),
                     correlation_id=correlation or token(), payload=payload)
        self.db.execute("UPDATE events SET data=? WHERE seq=?", (encoded(event).decode(), row.lastrowid))
        self.put("event_head", project_id, {"cursor": event["event_id"]})
        return event

    def project_changed(self, record, change):
        project_id = record["config"]["project"]["id"]
        self.emit(project_id, "project.changed", project_id,
                  dict(project_id=project_id, revision=record["revision"], change=change), revision=record["revision"])
        record["event_cursor"] = self.cursor(project_id)

    def save_project(self, record):
        project = record["config"]["project"]
        self.db.execute("INSERT OR REPLACE INTO projects VALUES (?,?,?)",
                        (project["id"], project["root"].casefold().rstrip("/"), encoded(record).decode()))

    def register(self, config, first_run=False):
        project = config["project"]
        for old in self.projects():
            existing = old["config"]["project"]
            same_id = existing["id"] == project["id"]
            same_root = existing["root"].casefold().rstrip("/") == project["root"].casefold().rstrip("/")
            if same_id or same_root:
                if first_run and same_id and same_root:
                    return old
                raise Problem(409, "project_exists", "Project ID or canonical root already registered.")
        record = dict(config=config, revision=token(), applied_revision=None, scaffold_state="draft", event_cursor="0")
        self.save_project(record)
        self.project_changed(record, "registered")
        return record

    def session(self, cookie):
        session = self.get("session", cookie or "")
        return session if session and session["expires_at"] > stamp() else None

    def new_session(self):
        cookie = token()
        value = dict(csrf_token=token(), expires_at=stamp(utcnow() + timedelta(hours=12)))
        self.put("session", cookie, value)
        self.db.commit()
        return cookie, value

    def mutate(self, principal, method, path, key, body, action):
        scope = digest(encoded([principal, method, path, key]))
        body_hash = digest(encoded(body))
        with self.lock:
            receipt = self.get("receipt", scope)
            if receipt and receipt["expires_at"] > stamp():
                if receipt["body_hash"] != body_hash:
                    raise Problem(409, "idempotency_conflict", "Key was already used with a different body.")
                if receipt["state"] != "complete":
                    raise Problem(409, "uncertain", "Interrupted operation; reconcile project/apply journal before retry.")
                return receipt["response"]
            receipt = dict(body_hash=body_hash, state="pending", expires_at=stamp(utcnow() + timedelta(days=7)))
            self.put("receipt", scope, receipt)
            self.db.commit()
            try:
                response = action()
            except Problem as error:
                self.db.rollback()
                # Apply may already have durably recorded a partial failure.
                response = {"status": error.status, "problem": {
                    "code": error.code, "message": error.message, "details": error.details,
                    "retryable": error.retryable}}
            except Exception:
                self.db.rollback()
                raise
            receipt.update(state="complete", response=response)
            self.put("receipt", scope, receipt)
            self.db.commit()
            return response

    def paginate(self, items, scope, limit, cursor):
        if cursor:
            snapshot = self.get("page", cursor)
            if not snapshot or snapshot["scope"] != scope or snapshot["expires_at"] <= stamp():
                raise Problem(400, "invalid_cursor", "Cursor is invalid or expired; start a fresh list.")
            items = snapshot["items"]
        page, rest = items[:limit], items[limit:]
        next_cursor = None
        if rest:
            next_cursor = token()
            self.put("page", next_cursor, dict(scope=scope, items=rest,
                     expires_at=stamp(utcnow() + timedelta(minutes=15))))
            self.db.commit()
        return page, next_cursor
