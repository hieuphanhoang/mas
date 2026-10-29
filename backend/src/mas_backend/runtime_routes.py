"""I2 routes registered before the API catch-all."""
import re

from fastapi import Query, Request

from .common import Problem
from .generated import CallRequest, MessageRequest, ReplyRequest
from .events import BoundedEventResponse
from pydantic import ValidationError


def install_routes(app, runtime, events, body, mutation):
    store = runtime.store

    def validate(model, value):
        try:
            model.model_validate(value)
        except ValidationError as error:
            raise Problem(422, "validation_error", "Invalid request body.", [
                dict(location="/".join(map(str, e["loc"])), code=e["type"], message=e["msg"][:2000])
                for e in error.errors()[:100]])
        return value

    def no_body(data):
        if data is not None:
            raise Problem(422, "validation_error", "This operation takes no request body.")

    @app.get("/api/v1/projects/{project_id}/agents")
    async def agents(project_id: str):
        return runtime.views(project_id)

    @app.post("/api/v1/projects/{project_id}/agents/{agent_id}/call")
    async def call(project_id: str, agent_id: str, request: Request):
        data = await body(request)
        def action():
            validate(CallRequest, data)
            return dict(status=202, body=runtime.enqueue(project_id, agent_id, "call", data, caller=request.state.agent_credential))
        return mutation(request, data, action)

    @app.post("/api/v1/projects/{project_id}/agents/{agent_id}/message")
    async def message(project_id: str, agent_id: str, request: Request):
        data = await body(request)
        def action():
            validate(MessageRequest, data)
            record, agent = runtime.validate_target(project_id, agent_id)
            if agent["log_duty"] != "member":
                raise Problem(422, "unsupported_capability", "Use call with a brief for helpers.")
            reference = data.get("thread_ref")
            if reference:
                document = runtime.thread(record, agent, reference)
                if not reference["thread_id"].startswith("AGENT-"):
                    raise Problem(422, "validation_error", "Use the Owner reply endpoint for ASK answers.")
                receipt = runtime.handoff.append(record, reference["log_id"], data["text"],
                           thread_id=reference["thread_id"], expected=document["metadata"]["revision"])
            else:
                if data["log_id"] not in agent["log_ids"]:
                    raise Problem(403, "forbidden", "Target is not a member of that log.")
                receipt = runtime.handoff.append(record, data["log_id"], data["text"], target=agent["name"])
            try:
                delivery = runtime.enqueue(project_id, agent_id, "message", dict(thread_ref=receipt["thread_ref"]))
            except Exception:
                raise Problem(409, "uncertain", "Owner message appended but enqueue failed; reconcile instead of reappending.")
            runtime.handoff.complete(receipt)
            return dict(status=202, body=delivery)
        return mutation(request, data, action)

    @app.post("/api/v1/projects/{project_id}/agents/{agent_id}/wake")
    async def wake(project_id: str, agent_id: str, request: Request):
        data = await body(request)
        def action():
            no_body(data)
            return dict(status=202, body=runtime.enqueue(project_id, agent_id, "wake", {}))
        return mutation(request, data, action)

    @app.post("/api/v1/projects/{project_id}/agents/{agent_id}/stop")
    @app.post("/api/v1/projects/{project_id}/agents/{agent_id}/resume-queue")
    async def control(project_id: str, agent_id: str, request: Request):
        data = await body(request)
        def action():
            no_body(data)
            return dict(status=200, body=runtime.control(project_id, agent_id, request.url.path.rsplit("/", 1)[1]))
        return mutation(request, data, action)

    @app.get("/api/v1/projects/{project_id}/calls")
    async def calls(project_id: str, request: Request, agent_id: str | None = None,
                    limit: int = Query(50, ge=1, le=100), cursor: str | None = Query(None, min_length=1, max_length=2048)):
        store.project(project_id)
        if agent_id:
            runtime.agent(project_id, agent_id)
        items = list(reversed(runtime.calls(project_id, agent_id)))
        credential = request.state.agent_credential
        if credential:
            items = [item for item in items if item["agent_id"] == credential["agent_id"] or
                     (store.get("delivery_input", item["delivery_id"]) or {}).get("caller_agent_id") == credential["agent_id"]]
        items, cursor = store.paginate(items, f"{request.state.principal}:calls:{project_id}:{agent_id}", limit, cursor)
        return dict(items=items, next_cursor=cursor, event_cursor=store.cursor(project_id))

    @app.get("/api/v1/projects/{project_id}/calls/{call_id}")
    async def get_call(project_id: str, call_id: str, request: Request):
        delivery = runtime.delivery(project_id, call_id)
        credential = request.state.agent_credential
        if credential and delivery["agent_id"] != credential["agent_id"] and (store.get("delivery_input", call_id) or {}).get("caller_agent_id") != credential["agent_id"]:
            raise Problem(403, "forbidden", "Agent can read only calls it sent or received.")
        return delivery

    @app.post("/api/v1/projects/{project_id}/calls/{call_id}/cancel")
    async def cancel(project_id: str, call_id: str, request: Request):
        data = await body(request)
        def action():
            no_body(data)
            return dict(status=200, body=runtime.cancel(project_id, call_id))
        return mutation(request, data, action)

    @app.get("/api/v1/projects/{project_id}/runs/{run_id}/output")
    async def output(project_id: str, run_id: str, offset: str = Query("0", pattern=r"^(0|[1-9][0-9]*)$", max_length=32),
                     limit: int = Query(50, ge=1, le=100)):
        return runtime.output(project_id, run_id, int(offset), limit)

    @app.get("/api/v1/projects/{project_id}/events")
    async def stream(project_id: str, request: Request, after: str | None = None):
        store.project(project_id)
        cursor = request.headers.get("last-event-id", after)
        if cursor is not None and not re.fullmatch(r"(?:0|[1-9][0-9]{0,31})", cursor):
            raise Problem(400, "invalid_cursor", "Event cursor must be an unsigned decimal string.")
        position = int(cursor if cursor is not None else store.cursor(project_id))
        return BoundedEventResponse(events.stream(project_id, position, request.state.principal, request.is_disconnected),
                                 media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/v1/projects/{project_id}/logs/{log_id}/threads/{thread_id}/reply")
    async def reply(project_id: str, log_id: str, thread_id: str, request: Request):
        data = await body(request)
        def action():
            validate(ReplyRequest, data)
            record = store.project(project_id)
            document = runtime.logs.thread(record, log_id, thread_id)
            metadata = document["metadata"]
            if not thread_id.startswith("ASK-") or metadata["status"] not in ("open", "answered", "blocked"):
                raise Problem(422, "validation_error", "Owner replies require a live ASK thread.")
            target = data.get("wake_agent_id")
            if target:
                _, agent = runtime.validate_target(project_id, target)
                if log_id not in agent["log_ids"] or agent["log_duty"] != "member":
                    raise Problem(403, "forbidden", "Wake target must be a member of this log.")
            receipt = runtime.handoff.append(record, log_id, data["body"], thread_id=thread_id, expected=data["expected_revision"])
            if target:
                try:
                    receipt["wake_delivery"] = runtime.enqueue(project_id, target, "wake", {"thread_ref": receipt["thread_ref"]},
                                                              allow_paused=True, purpose="notification")
                    receipt["wake_state"] = "queued"
                except Problem as error:
                    receipt.update(wake_state="failed", reason="Reply committed; wake failed: " + error.code)
            runtime.handoff.complete(receipt)
            return dict(status=201, body=receipt)
        return mutation(request, data, action)
