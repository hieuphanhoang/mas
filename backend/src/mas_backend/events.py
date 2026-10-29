import asyncio
from datetime import timedelta
import json

from .common import stamp, token, utcnow
from fastapi.responses import StreamingResponse


class BoundedEventResponse(StreamingResponse):
    async def stream_response(self, send):
        async def bounded_send(message):
            await asyncio.wait_for(send(message), timeout=10)
        try:
            await super().stream_response(bounded_send)
        except asyncio.TimeoutError:
            # Slow clients reconnect from their last committed event ID.
            return


class Events:
    def __init__(self, store):
        self.store = store

    def batch(self, project_id, after):
        record = self.store.project(project_id)
        cutoff = stamp(utcnow() - timedelta(days=record["config"]["retention"]["event_days"]))
        expired = self.store.db.execute("SELECT MAX(seq) FROM events WHERE project_id=? AND occurred_at<?",
                                        (project_id, cutoff)).fetchone()[0]
        if expired is not None:
            self.store.put("event_floor", project_id, {"cursor": str(expired)})
            self.store.db.execute("DELETE FROM events WHERE project_id=? AND occurred_at<?", (project_id, cutoff))
            self.store.db.commit()
        latest = int(self.store.cursor(project_id))
        floor = int((self.store.get("event_floor", project_id) or {"cursor": "0"})["cursor"])
        if after > latest or after < floor:
            first = self.store.db.execute("SELECT MIN(seq) FROM events WHERE project_id=?", (project_id,)).fetchone()[0]
            return [dict(schema_version=1, event_id=str(latest), project_id=project_id, type="stream.reset_required",
                         occurred_at=stamp(), entity_id=project_id, revision=token(), correlation_id=token(),
                         payload=dict(reason="cursor_ahead" if after > latest else "cursor_expired", earliest_event_id=str(first or latest),
                                      latest_event_id=str(latest), snapshot_url=f"/api/v1/projects/{project_id}"))]
        rows = self.store.db.execute("SELECT data FROM events WHERE project_id=? AND seq>? ORDER BY seq LIMIT 100",
                                     (project_id, after)).fetchall()
        return [json.loads(row[0]) for row in rows]

    async def stream(self, project_id, after, principal, disconnected):
        last_heartbeat = asyncio.get_running_loop().time()
        while self.store.session(principal) and not await disconnected():
            batch = self.batch(project_id, after)
            for event in batch:
                yield f"id: {event['event_id']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["type"] == "stream.reset_required":
                    return
                after = int(event["event_id"])
            now = asyncio.get_running_loop().time()
            if now - last_heartbeat >= 10:
                yield ": heartbeat\n\n"
                last_heartbeat = now
            await asyncio.sleep(0.2)
