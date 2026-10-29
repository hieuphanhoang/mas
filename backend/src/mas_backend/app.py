"""Loopback-only I1 HTTP service, with contract response models."""
import copy
import json
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException

from .capabilities import probe_capabilities
from .common import Problem, digest, token
from .config import ConfigValidator
from .generated import Preview, ProjectRecord, ThreadDocument
from .logs import Logs
from .scaffold import Scaffold
from .store import Store
from .runtime import Runtime
from .runtime_routes import install_routes
from .events import Events
from .handoff import Handoff

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
MAX_BODY = 4 * 1024 * 1024


def origin_valid(value):
    try:
        parsed = urlsplit(value)
        return (parsed.scheme in ("http", "https") and parsed.hostname in LOOPBACK
                and parsed.username is None and parsed.password is None
                and parsed.path == "" and not parsed.query and not parsed.fragment
                and (parsed.port is None or 1 <= parsed.port <= 65535))
    except ValueError:
        return False


def create_app(state_dir: Path, contract_dir: Path, static_dir: Path | None = None,
               dev_allowed_origins=(), capabilities=None, fake_adapter=False, fake_delay=0.3,
               real_adapters=False, adapters=None):
    if fake_adapter and real_adapters:
        raise ValueError("Choose fake or real adapters, not both")
    if any(not origin_valid(value) for value in dev_allowed_origins):
        raise ValueError("dev_allowed_origins must contain explicit loopback HTTP(S) origins only")
    @asynccontextmanager
    async def lifespan(app):
        await app.state.runtime.start()
        try:
            yield
        finally:
            await app.state.runtime.close()

    app = FastAPI(title="MAS slice 1", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    store = Store(state_dir)
    validator, scaffold, logs = ConfigValidator(contract_dir), Scaffold(store), Logs(store)
    app.state.store, app.state.validator = store, validator
    app.state.scaffold, app.state.logs = scaffold, logs
    app.state.capabilities = capabilities if capabilities is not None else probe_capabilities()
    handoff = Handoff(store, logs, Path(__file__).resolve().parents[3] / ".handoff/handoff.py")
    runtime = Runtime(store, logs, handoff, app.state.capabilities, fake=fake_adapter, delay=fake_delay,
                      real=real_adapters, adapters=adapters)
    events = Events(store)
    app.state.runtime, app.state.events = runtime, events

    def error_response(problem, request):
        return JSONResponse(problem.body(getattr(request.state, "request_id", token())),
                            status_code=problem.status, headers={"Cache-Control": "no-store"})

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        request.state.request_id = token()
        try:
            host = request.headers.get("host", "")
            if not origin_valid(f"{request.url.scheme}://{host}") or len(request.headers.getlist("host")) != 1:
                raise Problem(403, "forbidden_host", "Only a loopback Host is accepted.")
            origin = request.headers.get("origin")
            if origin and origin not in {f"{request.url.scheme}://{host}", *dev_allowed_origins}:
                raise Problem(403, "forbidden_origin", "Origin is not approved for this local service.")
            if request.headers.get("sec-fetch-site") == "cross-site":
                raise Problem(403, "forbidden_origin", "Cross-site browser requests are rejected.")
            if request.url.path.startswith("/api/"):
                cookie = request.cookies.get("mas_session")
                session = store.session(cookie)
                request.state.principal = cookie
                request.state.agent_credential = None
                authorization = request.headers.get("authorization")
                if authorization:
                    if not authorization.startswith("Bearer "):
                        raise Problem(401, "unauthorized", "Expected a scoped Bearer credential.")
                    secret = authorization[7:]
                    credential = runtime.authenticate(secret)
                    runtime.authorize(credential, request.method, request.url.path)
                    request.state.agent_credential = credential
                    request.state.principal = "agent:" + digest(secret.encode())
                if request.url.path not in ("/api/v1/health", "/api/v1/session"):
                    if not session and not request.state.agent_credential:
                        raise Problem(401, "unauthorized", "Bootstrap a local session first.")
                    if request.method not in ("GET", "HEAD", "OPTIONS"):
                        import secrets
                        if not request.state.agent_credential and not secrets.compare_digest(request.headers.get("x-mas-csrf", ""), session["csrf_token"]):
                            raise Problem(403, "csrf_invalid", "Missing or invalid CSRF token.")
                        key = request.headers.get("idempotency-key", "")
                        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", key):
                            raise Problem(422, "validation_error", "A valid Idempotency-Key is required.")
                if request.method in ("POST", "PUT", "PATCH"):
                    data = bytearray()
                    async for chunk in request.stream():
                        data.extend(chunk)
                        if len(data) > MAX_BODY:
                            raise Problem(413, "body_too_large", "Request body exceeds 4 MiB.")
                    request._body = bytes(data)
            response = await call_next(request)
        except Problem as problem:
            response = error_response(problem, request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(Problem)
    async def handle_problem(request, error):
        return error_response(error, request)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request, error):
        details = [dict(location="/".join(map(str, e["loc"])), code=e["type"], message=e["msg"][:2000])
                   for e in error.errors()[:100]]
        return error_response(Problem(422, "validation_error", "Request validation failed.", details), request)

    @app.exception_handler(HTTPException)
    async def handle_http(request, error):
        return error_response(Problem(error.status_code, "http_error", str(error.detail)), request)

    @app.exception_handler(Exception)
    async def handle_unexpected(request, error):
        return error_response(Problem(500, "internal_error", "Unexpected service error; reconcile before retrying a mutation."), request)

    async def body(request):
        raw = await request.body()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise Problem(422, "validation_error", "Expected valid JSON.")

    def check_revision(request, record):
        match = request.headers.get("if-match")
        if match is None:
            raise Problem(428, "precondition_required", "If-Match is required.")
        if match != '"' + record["revision"] + '"':
            raise Problem(409, "revision_conflict", "Configuration revision has changed.")

    def response_record(record, status=200):
        # Generated models enforce output shape; JSON Schema enforces full input semantics.
        value = ProjectRecord.model_validate(record).model_dump(mode="json", exclude_unset=True)
        headers = {"ETag": '"' + record["revision"] + '"'}
        if status == 201:
            headers["Location"] = "/api/v1/projects/" + record["config"]["project"]["id"]
        return dict(status=status, body=value, headers=headers)

    def mutation(request, data, action):
        result = store.mutate(request.state.principal, request.method, request.url.path,
                              request.headers["idempotency-key"], data, action)
        if "problem" in result:
            return error_response(Problem(result["status"], **result["problem"]), request)
        return JSONResponse(result["body"], status_code=result["status"], headers=result.get("headers", {}))

    @app.get("/api/v1/health")
    async def health():
        return dict(status="ok", api_version="v1")

    @app.get("/api/v1/session")
    async def session(request: Request):
        cookie = request.cookies.get("mas_session")
        value = store.session(cookie)
        created = value is None
        if created:
            cookie, value = store.new_session()
        response = JSONResponse(value, headers={"Cache-Control": "no-store"})
        if created:
            response.set_cookie("mas_session", cookie, httponly=True, samesite="strict", path="/",
                                secure=request.url.scheme == "https", max_age=43200)
        return response

    @app.get("/api/v1/capabilities")
    async def capabilities_route():
        value = copy.deepcopy(app.state.capabilities)
        if fake_adapter:
            value["adapters"] = [runtime.capability({"harness": h}) for h in ("claude", "codex", "opencode", "gemini", "relay")]
            value["permission_profiles"] = [dict(id=profile, harness=h, label="Fake adapter: " + profile,
                description="Simulated execution. Real Codex member has Owner-approved network on; default is unchanged.")
                for h in ("claude", "codex") for profile in ("default", "member")]
        return value

    @app.get("/api/v1/projects")
    async def projects(request: Request, limit: int = Query(50, ge=1, le=100),
                       cursor: str | None = Query(None, min_length=1, max_length=2048)):
        items = []
        for record in store.projects():
            config = record["config"]
            items.append(dict(project_id=config["project"]["id"], name=config["project"]["name"],
                root=config["project"]["root"], revision=record["revision"], scaffold_state=record["scaffold_state"],
                agent_count=len(config["agents"]), active_run_count=0))
        items, next_cursor = store.paginate(items, request.state.principal + ":projects", limit, cursor)
        return dict(items=items, next_cursor=next_cursor)

    @app.post("/api/v1/projects")
    async def create_project(request: Request):
        data = await body(request)
        return mutation(request, data, lambda: response_record(store.register(validator.validate(data)), 201))

    @app.get("/api/v1/projects/{project_id}")
    async def project(project_id: str):
        result = response_record(store.project(project_id))
        return JSONResponse(result["body"], headers=result["headers"])

    @app.put("/api/v1/projects/{project_id}")
    async def update(project_id: str, request: Request):
        data = await body(request)

        def action():
            record = store.project(project_id)
            check_revision(request, record)
            if runtime.active(project_id):
                raise Problem(409, "active_run_conflict", "Stop and reconcile active runs before replacing configuration.")
            config = validator.validate(data)
            old, new = record["config"]["project"], config["project"]
            if old["id"] != new["id"] or old["root"] != new["root"]:
                raise Problem(422, "immutable_field", "Project ID and root are immutable.")
            record.update(config=config, revision=token(), scaffold_state="draft")
            store.save_project(record)
            store.project_changed(record, "config_saved")
            return response_record(record)

        return mutation(request, data, action)

    @app.post("/api/v1/projects/{project_id}/preview")
    async def preview(project_id: str, request: Request):
        data = await body(request)

        def action():
            if data is not None:
                raise Problem(422, "validation_error", "Preview has no request body.")
            record = store.project(project_id)
            check_revision(request, record)
            result = Preview.model_validate(scaffold.preview(record)).model_dump(mode="json")
            return dict(status=200, body=result)

        return mutation(request, data, action)

    @app.post("/api/v1/projects/{project_id}/apply")
    async def apply(project_id: str, request: Request):
        data = await body(request)

        def action():
            if not isinstance(data, dict) or set(data) != {"preview_id"} or not isinstance(data["preview_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", data["preview_id"]):
                raise Problem(422, "validation_error", "Expected a preview_id only.")
            record = store.project(project_id)
            check_revision(request, record)
            if runtime.active(project_id):
                raise Problem(409, "active_run_conflict", "Active or uncertain runs prevent file apply.")
            record = scaffold.apply(record, data["preview_id"])
            store.project_changed(record, "applied")
            return response_record(record)

        return mutation(request, data, action)

    @app.get("/api/v1/projects/{project_id}/logs")
    async def list_logs(project_id: str, request: Request):
        items = logs.list(store.project(project_id))
        credential = request.state.agent_credential
        if credential:
            items = [item for item in items if credential["agent_id"] in item["members"]]
        return dict(items=items, event_cursor=store.cursor(project_id))

    @app.get("/api/v1/projects/{project_id}/logs/{log_id}/index")
    async def log_index(project_id: str, log_id: str, request: Request,
                        section: Literal["awaiting_owner", "open", "history", "all"] = "open",
                        limit: int = Query(50, ge=1, le=100), cursor: str | None = Query(None, min_length=1, max_length=2048)):
        result = copy.deepcopy(logs.index(store.project(project_id), log_id, section))
        scope = f"{request.state.principal}:{project_id}:{log_id}:{section}"
        result["items"], result["next_cursor"] = store.paginate(result["items"], scope, limit, cursor)
        result["event_cursor"] = store.cursor(project_id)
        return JSONResponse(result, headers={"ETag": '"' + result["revision"] + '"'})

    @app.get("/api/v1/projects/{project_id}/logs/{log_id}/threads/{thread_id}")
    async def thread(project_id: str, log_id: str, thread_id: str):
        result = logs.thread(store.project(project_id), log_id, thread_id)
        result["event_cursor"] = store.cursor(project_id)
        result = ThreadDocument.model_validate(result).model_dump(mode="json")
        return JSONResponse(result, headers={"ETag": '"' + result["metadata"]["revision"] + '"'})

    @app.get("/api/v1/inbox")
    async def inbox(request: Request, limit: int = Query(50, ge=1, le=100),
                    cursor: str | None = Query(None, min_length=1, max_length=2048)):
        items, sources = logs.inbox()
        items, next_cursor = store.paginate(items, request.state.principal + ":inbox", limit, cursor)
        return dict(items=items, next_cursor=next_cursor, sources=sources)

    install_routes(app, runtime, events, body, mutation)

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def unsupported(path: str):
        raise Problem(422, "unsupported_capability", "This route is not implemented in backend increment I1.")

    @app.get("/{path:path}")
    async def static(path: str):
        if static_dir is None or not static_dir.is_dir():
            raise Problem(404, "not_found", "Build frontend/dist or use the Vite development server.")
        root = static_dir.resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise Problem(404, "not_found", "Unknown frontend asset.")
        if not target.is_file():
            if Path(path).suffix:
                raise Problem(404, "not_found", "Unknown frontend asset.")
            target = root / "index.html"
        if not target.is_file() or not target.resolve().is_relative_to(root):
            raise Problem(404, "not_found", "Frontend entry point unavailable.")
        return FileResponse(target)

    return app
