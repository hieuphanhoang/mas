"""The agent-side doorbell. Standard library only; all work enters the queue."""
import hashlib
import json
import os
import re
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


def call(agent, thread, log=None, note="", *, env=None, opener=None):
    env = os.environ if env is None else env
    base = env.get("MAS_API_URL", "").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("MAS_API_URL must be the local backend URL supplied by the run.")
    project, run_id, token = (env.get(k) for k in ("MAS_PROJECT_ID", "MAS_RUN_ID", "MAS_AGENT_TOKEN"))
    log = log or env.get("MAS_LOG_ID")
    if not all((project, run_id, token, log)) or not re.fullmatch(r"(?:AGENT|ASK)-[0-9]{3,}", thread):
        raise ValueError("Run credentials, a valid --thread and --log (or MAS_LOG_ID) are required.")
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = opener or build_opener(ProxyHandler({}), NoRedirect())
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    prefix = base + "/projects/" + quote(project, safe="")
    def send(request):
        try:
            with opener.open(request, timeout=15) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                body = json.load(error)
                message = body.get("code", "http_error") + ": " + body.get("message", str(error.code))
            except (ValueError, TypeError):
                message = "Backend HTTP " + str(error.code)
            raise ValueError(message) from None
    views = send(Request(prefix + "/agents", headers=headers))
    agents = [item["config"] for item in views["items"]]
    selected = next((a for a in agents if a["id"] == agent), None)
    selected = selected or next((a for a in agents if a["name"].casefold() == agent.casefold()), None)
    if selected is None:
        raise ValueError("Unknown agent name or ID.")
    body = dict(thread_ref=dict(project_id=project, log_id=log, thread_id=thread), note=note)
    data = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    headers["Idempotency-Key"] = hashlib.sha256(run_id.encode() + b"\0" + selected["id"].encode() + b"\0" + data).hexdigest()
    return send(Request(prefix + "/agents/" + quote(selected["id"], safe="") + "/call", data=data, headers=headers, method="POST"))
