"""Durable per-agent session queues with an explicitly enabled fake adapter.

All DB transitions run synchronously on the service event loop. Await points
occur only between committed transitions; one task owns each active session.
"""

import asyncio
import copy
import json
from datetime import timedelta
import re

from .common import Problem, digest, stamp, token, utcnow
from .config import resolve
from .logs import LIVE
from .scaffold import read_file
from .adapters import Adapter, Outcome
from .busy import ExternalSessions

TERMINAL = {"completed", "failed", "cancelled"}


def session_label(record, agent):
    return " ".join(f"{record['config']['project']['name']} / {agent['name']}".splitlines())


class Runtime:
    def __init__(
        self,
        store,
        logs,
        handoff,
        capabilities,
        fake=False,
        delay=0.3,
        real=False,
        adapters=None,
    ):
        self.store, self.logs, self.handoff = store, logs, handoff
        self.capabilities, self.fake, self.delay = capabilities, fake, delay
        self.adapters = (
            (
                adapters
                if adapters is not None
                else {h: Adapter(h) for h in ("claude", "codex", "opencode")}
            )
            if real
            else {}
        )
        self.api_url = "http://127.0.0.1:8790/api/v1"
        self.external_reason = ExternalSessions().reason
        self.tasks = {}
        self.pump_task = None
        self.closing = False
        for delivery in store.documents("delivery"):
            if delivery["state"] in ("dispatching", "running"):
                delivery.update(
                    state="uncertain",
                    reason="service_restarted",
                    process_outcome="unknown",
                )
                self.save_delivery(delivery)
                status = self.status(delivery["project_id"], delivery["agent_id"])
                status.update(
                    state="unknown",
                    reason="Interrupted run requires reconciliation.",
                    queue_paused=True,
                )
                self.save_status(delivery["project_id"], status)
                run = store.get("run", delivery["run_id"] or "")
                if run:
                    run.update(state="unknown", finished_at=stamp())
                    store.put("run", run["run_id"], run)
                    store.emit(
                        delivery["project_id"],
                        "run.finished",
                        run["run_id"],
                        run,
                        correlation=delivery["correlation_id"],
                    )
        store.db.commit()

    def agent(self, project_id, agent_id):
        record = self.store.project(project_id)
        agent = next(
            (a for a in record["config"]["agents"] if a["id"] == agent_id), None
        )
        if agent is None:
            raise Problem(404, "not_found", "Unknown agent.")
        return record, agent

    def status(self, project_id, agent_id):
        saved = self.store.get("agent_status", f"{project_id}:{agent_id}")
        if saved is None:
            _, agent = self.agent(project_id, agent_id)
            manual = agent["launch_mode"] == "manual" or agent["harness"] == "relay"
            saved = dict(
                agent_id=agent_id,
                revision=token(),
                state="offline",
                observed_at=stamp(),
                source=(
                    "manual"
                    if manual
                    else "supervisor" if self.fake or self.adapters else "unavailable"
                ),
                reason=(
                    "Manual delivery only."
                    if manual
                    else (
                        "Fake adapter enabled."
                        if self.fake
                        else (
                            "Real adapters explicitly enabled."
                            if self.adapters
                            else "Enable an explicit adapter mode to dispatch."
                        )
                    )
                ),
                queue_length=0,
                queue_paused=False,
                session_id=None,
                session_generation=None,
                active_run_id=None,
            )
            self.store.put("agent_status", f"{project_id}:{agent_id}", saved)
        saved["queue_length"] = sum(
            d["state"] == "queued" for d in self.calls(project_id, agent_id)
        )
        return saved

    def save_status(self, project_id, status):
        status.update(revision=token(), observed_at=stamp())
        status["queue_length"] = sum(
            d["state"] == "queued" for d in self.calls(project_id, status["agent_id"])
        )
        self.store.put("agent_status", f"{project_id}:{status['agent_id']}", status)
        self.store.emit(
            project_id,
            "agent.status_changed",
            status["agent_id"],
            status,
            revision=status["revision"],
        )

    def calls(self, project_id, agent_id=None):
        return sorted(
            (
                d
                for d in self.store.documents("delivery")
                if d["project_id"] == project_id
                and (agent_id is None or d["agent_id"] == agent_id)
            ),
            key=lambda d: (d["created_at"], d["delivery_id"]),
        )

    def delivery(self, project_id, delivery_id):
        value = self.store.get("delivery", delivery_id)
        if value is None or value["project_id"] != project_id:
            raise Problem(404, "not_found", "Unknown delivery.")
        return value

    def save_delivery(self, delivery, queued=False):
        delivery.update(revision=token(), updated_at=stamp())
        self.store.put("delivery", delivery["delivery_id"], delivery)
        self.store.emit(
            delivery["project_id"],
            "delivery.queued" if queued else "delivery.state_changed",
            delivery["delivery_id"],
            delivery,
            correlation=delivery["correlation_id"],
            revision=delivery["revision"],
        )

    def capability(self, agent):
        existing = next(
            (
                c
                for c in self.capabilities.get("adapters", [])
                if c["harness"] == agent["harness"]
            ),
            None,
        )
        if existing:
            result = copy.deepcopy(existing)
        else:
            result = dict(
                harness=agent["harness"],
                availability="unavailable",
                version=None,
                reason="Adapter unavailable.",
                modes=[],
                resume=False,
                live_delivery=False,
                attach=False,
                stop=False,
                guard_coverage=dict(
                    tool_paths="unknown",
                    shell_commands="unknown",
                    sandbox="unknown",
                    limitations=[],
                ),
            )
        if self.fake and agent["harness"] in ("claude", "codex", "opencode"):
            result.update(
                availability="available",
                version="fake-i2",
                reason="Simulated adapter; no provider process or model call.",
                modes=["managed", "manual"],
                resume=True,
                stop=True,
            )
        return result

    def views(self, project_id):
        record = self.store.project(project_id)
        items = [
            dict(
                config=a,
                status=self.status(project_id, a["id"]),
                capabilities=self.capability(a),
            )
            for a in record["config"]["agents"]
        ]
        self.store.db.commit()
        return dict(items=items, event_cursor=self.store.cursor(project_id))

    def validate_target(self, project_id, agent_id, *, applied=True, capacity=True):
        record, agent = self.agent(project_id, agent_id)
        if agent["harness"] == "gemini":
            raise Problem(
                422,
                "unsupported_capability",
                "This adapter is planned, not executable.",
            )
        if agent["launch_mode"] == "managed" and not self.fake:
            adapter = self.adapters.get(agent["harness"])
            if not adapter or not adapter.command:
                raise Problem(
                    422,
                    "unsupported_capability",
                    "A usable real adapter or explicit --fake-adapter is required.",
                )
            available = next(
                (
                    c
                    for c in self.capabilities.get("adapters", [])
                    if c["harness"] == agent["harness"]
                ),
                None,
            )
            if available and available["availability"] != "available":
                raise Problem(
                    422,
                    "unsupported_capability",
                    "Installed adapter failed its local probe.",
                )
            if not agent["model"] or agent["model"].startswith("-"):
                raise Problem(
                    422,
                    "validation_error",
                    "Model identifier must be an explicit value.",
                )
        if agent["permission_profile"] not in ("default", "member"):
            raise Problem(
                422, "unsupported_capability", "Choose default or member permissions at setup."
            )
        if applied and (
            record["scaffold_state"] != "applied"
            or record["applied_revision"] != record["revision"]
        ):
            raise Problem(
                409,
                "config_not_applied",
                "Apply the current configuration before dispatch.",
            )
        if self.status(project_id, agent_id)["state"] == "unknown":
            raise Problem(
                409,
                "uncertain",
                "Unknown session liveness; reconcile before submitting work.",
            )
        if (
            capacity
            and sum(d["state"] == "queued" for d in self.calls(project_id, agent_id))
            >= 100
        ):
            raise Problem(429, "queue_limit", "The per-agent queue is full.")
        return record, agent

    def issue_credential(self, project_id, agent_id, run_id):
        """Supervisor-only: no browser route exposes this credential."""
        secret = token()
        self.store.put(
            "agent_credential",
            digest(secret.encode()),
            dict(project_id=project_id, agent_id=agent_id, run_id=run_id),
        )
        return secret

    def authenticate(self, secret):
        credential = self.store.get("agent_credential", digest(secret.encode()))
        run = self.store.get("run", credential["run_id"]) if credential else None
        if not credential or not run or run["state"] != "running":
            raise Problem(
                401,
                "unauthorized",
                "Agent credential is absent, expired or no longer active.",
            )
        status = self.status(credential["project_id"], credential["agent_id"])
        if status["active_run_id"] != credential["run_id"] or status["state"] not in (
            "starting",
            "busy",
        ):
            raise Problem(401, "unauthorized", "Agent run is no longer current.")
        return credential

    def authorize(self, credential, method, path):
        project_id, caller = credential["project_id"], credential["agent_id"]
        prefix = f"/api/v1/projects/{project_id}"
        if not path.startswith(prefix + "/"):
            raise Problem(
                403, "forbidden", "Agent credential is scoped to one project."
            )
        suffix = path[len(prefix) :]
        permitted = method == "GET" and (
            suffix == "/agents"
            or suffix == "/logs"
            or re.fullmatch(r"/calls(?:/[A-Za-z0-9_-]+)?", suffix)
            or re.fullmatch(
                r"/logs/[A-Za-z0-9_-]+/(?:index|threads/(?:AGENT|ASK)-[0-9]{3,})",
                suffix,
            )
        )
        permitted = permitted or (
            method == "POST" and re.fullmatch(r"/agents/[A-Za-z0-9_-]+/call", suffix)
        )
        if not permitted:
            raise Problem(
                403,
                "forbidden",
                "Agent credential cannot perform this Owner operation.",
            )
        _, agent = self.agent(project_id, caller)
        match = re.match(r"/logs/([^/]+)/", suffix)
        if match and match.group(1) not in agent["log_ids"]:
            raise Problem(403, "forbidden", "Agent is not a member of that log.")

    def caller_policy(self, record, target, data, caller):
        if caller is None:
            return None, 0, None
        if caller["project_id"] != record["config"]["project"]["id"]:
            raise Problem(403, "forbidden", "Cross-project agent call is forbidden.")
        _, agent = self.agent(caller["project_id"], caller["agent_id"])
        policy = record["config"]["call_policy"]
        edge = dict(from_agent_id=agent["id"], to_agent_id=target["id"])
        if (
            policy["mode"] == "independent"
            or edge not in policy["allowed_edges"]
            or target["invocation"] != "callable"
        ):
            raise Problem(
                403,
                "forbidden",
                "Invocation mode, target policy or call edge forbids this call.",
            )
        reference = data.get("thread_ref")
        if reference and reference["log_id"] not in agent["log_ids"]:
            raise Problem(
                403, "forbidden", "Caller must be a member of the referenced log."
            )
        if target["log_duty"] == "helper" and target["sponsor_agent_id"] != agent["id"]:
            raise Problem(
                403, "forbidden", "Only a helper's sponsor or the Owner may call it."
            )
        run = self.store.get("run", caller["run_id"])
        parent = self.delivery(caller["project_id"], run["delivery_id"])
        hop = parent["hop_count"] + 1
        count = sum(
            d["correlation_id"] == parent["correlation_id"]
            for d in self.calls(caller["project_id"])
        )
        if hop > policy["max_chain_depth"] or count >= policy["max_calls_per_chain"]:
            raise Problem(429, "chain_limit", "Agent call chain limit reached.")
        return parent["delivery_id"], hop, parent["correlation_id"]

    def thread(self, record, agent, reference):
        project_id = record["config"]["project"]["id"]
        if (
            reference["project_id"] != project_id
            or reference["log_id"] not in agent["log_ids"]
        ):
            raise Problem(
                403,
                "forbidden",
                "Target must be a member of the referenced project log.",
            )
        document = self.logs.thread(record, reference["log_id"], reference["thread_id"])
        if document["freshness"]["state"] != "current":
            raise Problem(
                409, "thread_unavailable", "A current parseable thread is required."
            )
        return document

    def pending(self, record, agent):
        if agent["log_duty"] != "member":
            raise Problem(422, "unsupported_capability", "Wake is for members only.")
        pending = []
        for log_id in agent["log_ids"]:
            log = self.logs.config(record, log_id)
            directory = self.logs.base(record, log) / "threads"
            if not directory.is_dir():
                raise Problem(
                    503,
                    "log_unavailable",
                    "Cannot determine waiting work from an unavailable log.",
                )
            for path in sorted(directory.glob("*.md")):
                match = re.match(r"((?:AGENT|ASK)-[0-9]{3,})-", path.name)
                if not match:
                    continue
                document = self.logs.thread(record, log_id, match.group(1))
                metadata = document["metadata"]
                if document["freshness"]["state"] != "current":
                    raise Problem(
                        409,
                        "thread_unavailable",
                        "Cannot determine waiting work from a stale/malformed log.",
                    )
                if (
                    metadata["status"] in LIVE
                    and (metadata["owes_reply"] or "").casefold()
                    == agent["name"].casefold()
                ):
                    pending.append(metadata["thread_ref"])
                if len(pending) >= 100:
                    return pending
        return pending

    def enqueue(
        self,
        project_id,
        agent_id,
        kind,
        data,
        *,
        allow_paused=False,
        caller=None,
        purpose="task",
    ):
        record, agent = self.validate_target(project_id, agent_id)
        parent, hop, correlation = self.caller_policy(record, agent, data, caller)
        status = self.status(project_id, agent_id)
        reference, pending, before = data.get("thread_ref"), [], None
        if purpose == "notification":
            if (
                kind != "wake"
                or caller is not None
                or agent["log_duty"] != "member"
                or not reference
                or not reference["thread_id"].startswith("ASK-")
            ):
                raise Problem(
                    422,
                    "validation_error",
                    "Notification requires the answered ASK and a member target.",
                )
        elif kind == "wake":
            if status["queue_paused"] and not allow_paused:
                raise Problem(
                    409, "queue_paused", "Wake does not resume a paused queue."
                )
            pending = self.pending(record, agent)
            if not pending:
                raise Problem(
                    409,
                    "no_pending_work",
                    "No pending thread is waiting on this member.",
                )
            reference = pending[0]
        if agent["log_duty"] == "member":
            if reference is None or "brief" in data:
                raise Problem(
                    422,
                    "validation_error",
                    "Member calls require thread_ref, not a helper brief.",
                )
            before = self.thread(record, agent, reference)["metadata"]["revision"]
        else:
            if reference is not None or "brief" not in data:
                raise Problem(422, "validation_error", "Helper calls require a brief.")
            path = resolve(record["config"], data["brief"])
            allowed = [
                resolve(record["config"], ref) for ref in agent["reads"] + agent["owns"]
            ]
            if not any(path == p or path.is_relative_to(p) for p in allowed):
                raise Problem(
                    403,
                    "forbidden",
                    "Helper brief is outside its declared readable paths.",
                )
            raw = read_file(path)
            if raw is None or len(raw) > 65536:
                raise Problem(
                    422,
                    "validation_error",
                    "Helper brief must be a readable UTF-8 file of at most 65536 bytes.",
                )
            try:
                raw.decode("utf-8")
            except UnicodeError:
                raise Problem(422, "validation_error", "Helper brief must be UTF-8.")
        if data.get("mode", agent["launch_mode"]) != agent["launch_mode"]:
            raise Problem(
                422,
                "unsupported_capability",
                "Requested mode must match agent configuration.",
            )
        ident, now = token(), stamp()
        manual = agent["launch_mode"] == "manual" or agent["harness"] == "relay"
        delivery = dict(
            delivery_id=ident,
            project_id=project_id,
            agent_id=agent_id,
            revision=token(),
            kind=kind,
            purpose=purpose,
            state="awaiting_manual" if manual else "queued",
            reason="Manual delivery required." if manual else None,
            created_at=now,
            updated_at=now,
            thread_ref=reference,
            run_id=None,
            process_outcome="not_applicable" if manual else "not_started",
            thread_reply_observed=False,
            correlation_id=correlation or ident,
            parent_delivery_id=parent,
            hop_count=hop,
            status_url=f"/api/v1/projects/{project_id}/calls/{ident}",
        )
        self.store.put(
            "delivery_input",
            ident,
            dict(
                data=data,
                config_revision=record["revision"],
                pending=pending,
                thread_before=before,
                cancel=False,
                caller_agent_id=caller["agent_id"] if caller else None,
            ),
        )
        self.save_delivery(delivery, queued=not manual)
        self.save_status(project_id, status)
        return delivery

    def control(self, project_id, agent_id, action):
        self.agent(project_id, agent_id)
        status = self.status(project_id, agent_id)
        if action == "resume-queue":
            self.validate_target(project_id, agent_id, capacity=False)
            if status["state"] in ("stopping", "unknown"):
                raise Problem(
                    409,
                    "uncertain",
                    "Stopping or unknown run prevents resuming the queue.",
                )
            status["queue_paused"] = False
        else:
            status["queue_paused"] = True
            if status["active_run_id"] and status["state"] != "unknown":
                run = self.store.get("run", status["active_run_id"])
                if run:
                    self.cancel(project_id, run["delivery_id"])
                    status["state"] = "stopping"
        self.save_status(project_id, status)
        return status

    def cancel(self, project_id, delivery_id):
        delivery = self.delivery(project_id, delivery_id)
        if delivery["state"] in TERMINAL:
            return delivery
        if delivery["state"] == "uncertain":
            raise Problem(
                409, "uncertain", "Reconcile uncertain execution before cancelling."
            )
        if delivery["state"] in ("queued", "awaiting_manual"):
            delivery.update(state="cancelled", reason="cancelled_before_dispatch")
        else:
            intent = self.store.get("delivery_input", delivery_id)
            intent["cancel"] = True
            self.store.put("delivery_input", delivery_id, intent)
            delivery["reason"] = "cancellation_requested"
        self.save_delivery(delivery)
        self.save_status(project_id, self.status(project_id, delivery["agent_id"]))
        return delivery

    def active(self, project_id):
        return any(
            d["state"] in ("dispatching", "running", "uncertain")
            for d in self.calls(project_id)
        )

    async def start(self):
        self.closing = False
        self.pump_task = asyncio.create_task(self.pump())

    async def close(self):
        self.closing = True
        if self.pump_task:
            self.pump_task.cancel()
            await asyncio.gather(self.pump_task, return_exceptions=True)
        for task in list(self.tasks.values()):
            task.cancel()
        await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)

    async def pump(self):
        while not self.closing:
            self.tick()
            await asyncio.sleep(0.05)

    def tick(self):
        if not self.fake and not self.adapters:
            return
        for record in self.store.projects():
            project_id = record["config"]["project"]["id"]
            cap = min(2, record["config"]["call_policy"]["max_parallel"])
            for delivery in self.calls(project_id):
                global_active = sum(
                    d["state"] in ("dispatching", "running", "uncertain")
                    for d in self.store.documents("delivery")
                )
                if global_active >= 2:
                    break
                running = sum(
                    d["state"] in ("dispatching", "running", "uncertain")
                    for d in self.calls(project_id)
                )
                if running >= cap:
                    break
                if delivery["state"] != "queued":
                    continue
                agent_id = delivery["agent_id"]
                status = self.status(project_id, agent_id)
                if (
                    status["queue_paused"]
                    or status["active_run_id"]
                    or status["state"] in ("unknown", "stopping")
                ):
                    continue
                intent = self.store.get("delivery_input", delivery["delivery_id"])
                try:
                    current, agent = self.validate_target(
                        project_id, agent_id, capacity=False
                    )
                    if not self.fake and status["session_id"]:
                        held = self.external_reason(agent["harness"], status["session_id"])
                        if held:
                            if delivery["reason"] != held:
                                delivery["reason"] = held
                                self.save_delivery(delivery)
                                self.store.db.commit()
                            continue
                    if intent["config_revision"] != current["revision"]:
                        raise Problem(
                            409,
                            "revision_conflict",
                            "Queued configuration changed; resubmit explicitly.",
                        )
                    if delivery["thread_ref"]:
                        document = self.thread(current, agent, delivery["thread_ref"])
                        intent["thread_before"] = document["metadata"]["revision"]
                        intent["reply_count_before"] = len(
                            re.findall(
                                r"^\*\*\["
                                + re.escape(agent["name"])
                                + r",\s*\d{4},\s*\d{4}\]\*\*",
                                document["markdown"],
                                re.M | re.I,
                            )
                        )
                        self.store.put(
                            "delivery_input", delivery["delivery_id"], intent
                        )
                    elif "brief" in intent["data"]:
                        brief = read_file(
                            resolve(current["config"], intent["data"]["brief"])
                        )
                        if brief is None or len(brief) > 65536:
                            raise Problem(
                                422,
                                "invalid_brief",
                                "Helper brief is no longer readable/bounded.",
                            )
                except Problem as error:
                    delivery.update(state="failed", reason=error.code)
                    self.save_delivery(delivery)
                    self.save_status(project_id, status)
                    self.store.db.commit()
                    continue
                if self.fake and status["session_id"] is None:
                    status.update(session_id="fake-" + token(), session_generation=1)
                if status["session_generation"] is None:
                    status["session_generation"] = 1
                if (
                    not self.fake
                    and status["session_id"]
                    and status["session_id"].startswith("fake-")
                ):
                    status.update(
                        state="unknown",
                        queue_paused=True,
                        reason="Fake session cannot be adopted by a real provider.",
                    )
                    self.save_status(project_id, status)
                    self.store.db.commit()
                    continue
                run_id = token()
                run = dict(
                    run_id=run_id,
                    delivery_id=delivery["delivery_id"],
                    agent_id=agent_id,
                    session_generation=status["session_generation"],
                    state="running",
                    started_at=stamp(),
                    finished_at=None,
                    exit_code=None,
                )
                self.store.put("run", run_id, run)
                # Retain the hash only. A real adapter will receive the secret via
                # its launch environment in I3; the fake never calls back itself.
                retention = current["config"]["retention"]
                self.store.put(
                    "output",
                    run_id,
                    dict(
                        project_id=project_id,
                        run_id=run_id,
                        chunks=[],
                        eof=False,
                        enabled=retention["capture_output"],
                        expires_at=stamp(
                            utcnow() + timedelta(days=retention["output_days"])
                        ),
                    ),
                )
                delivery.update(state="dispatching", run_id=run_id, reason=None)
                self.save_delivery(delivery)
                status.update(
                    state="starting",
                    active_run_id=run_id,
                    source="supervisor",
                    reason=(
                        "Fake adapter starting."
                        if self.fake
                        else "Managed adapter starting."
                    ),
                )
                self.save_status(project_id, status)
                self.store.db.commit()
                task = asyncio.create_task(
                    self.execute(delivery["delivery_id"])
                    if self.fake
                    else self.execute_real(delivery["delivery_id"])
                )
                self.tasks[run_id] = task
                task.add_done_callback(lambda _, rid=run_id: self.tasks.pop(rid, None))

    async def execute(self, delivery_id):
        delivery = self.store.get("delivery", delivery_id)
        project_id, agent_id, run_id = (
            delivery["project_id"],
            delivery["agent_id"],
            delivery["run_id"],
        )
        run = self.store.get("run", run_id)
        cancelled, failed = False, False
        try:
            await asyncio.sleep(self.delay)
            if self.store.get("delivery_input", delivery_id)["cancel"]:
                cancelled = True
                return
            delivery.update(state="running", process_outcome="running")
            self.save_delivery(delivery)
            status = self.status(project_id, agent_id)
            status.update(state="busy", reason="Fake adapter is emitting output.")
            self.save_status(project_id, status)
            self.store.emit(
                project_id,
                "run.started",
                run_id,
                run,
                correlation=delivery["correlation_id"],
            )
            self.store.db.commit()
            for text in (
                "[fake] Session started.\n",
                "[fake] Processing queued work; no provider was called.\n",
                "[fake] Finished; no member reply was fabricated.\n",
            ):
                await asyncio.sleep(self.delay)
                if self.store.get("delivery_input", delivery_id)["cancel"]:
                    cancelled = True
                    break
                output = self.store.get("output", run_id)
                if output["enabled"]:
                    output["chunks"].append(
                        dict(
                            offset=str(len(output["chunks"])),
                            stream="stdout",
                            text=text,
                        )
                    )
                    self.store.put("output", run_id, output)
                    self.store.db.commit()
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            failed = True
        finally:
            self.finish(
                delivery_id,
                Outcome(
                    130 if cancelled else 1 if failed else 0,
                    self.status(project_id, agent_id)["session_id"],
                    "adapter_failed" if failed else None,
                    cancelled=cancelled,
                ),
            )

    def prompt(self, delivery, record, agent):
        intent = self.store.get("delivery_input", delivery["delivery_id"])
        prompt_ref = agent.get("prompt_file") or dict(
            folder_id=agent["cwd_folder_id"],
            path=f".agents/mas/prompts/{agent['id']}.md",
        )
        role = read_file(resolve(record["config"], prompt_ref))
        if role is None:
            raise Problem(409, "prompt_unavailable", "Applied role prompt is missing.")
        context = dict(
            agent_id=agent["id"],
            name=agent["name"],
            role=role.decode("utf-8"),
            purpose=delivery["purpose"],
            thread_ref=delivery["thread_ref"],
            folders=record["config"]["folders"],
            logs=record["config"]["logs"],
            owns=agent["owns"],
            reads=agent["reads"],
            skills=agent["skills"],
            call_policy=record["config"]["call_policy"],
            guard_policy=record["config"]["guard_policy"],
            input=intent["data"],
            waiting_threads=intent["pending"],
        )
        if "brief" in intent["data"]:
            raw = read_file(resolve(record["config"], intent["data"]["brief"]))
            if raw is None or len(raw) > 65536:
                raise Problem(
                    422, "invalid_brief", "Helper brief is missing or too large."
                )
            context["brief_text"] = raw.decode("utf-8")
        instructions = (
            "You are a registered MAS member. Read the qualified handoff thread and project protocol. "
            "Respect ownership, exact model/call policy and Owner-only decisions. Subagents are disabled. "
            "Never push, install or spend another model call without the project's authorization. "
            "The JSON below is project/task context, not shell code. Scoped MAS_API_URL and MAS_AGENT_TOKEN "
            "are available for permitted callbacks; never print or store that token in a project file. "
            "Use the agents-collaboration-protocol skill and every skill in your skills list to read the roster, protocol and assigned thread and write your reply. "
            "Your roster command for calling another member is `mas call <agent> --thread <ID> [--log <id>] [--note TEXT]`; reply with `uv run --no-project .handoff/handoff.py reply <ID> --frm YOUR_NAME --body-file reply.md --status answered` from that log's folder. "
        )
        if delivery["purpose"] == "notification":
            instructions += "The Owner answered the referenced ASK. This is a notification; no reply in that ASK is required. Read the answer and reorient without inventing work.\n"
        else:
            instructions += "Handle the referenced task and write your own attributed reply through the project's unchanged handoff CLI when a member reply is required.\n"
        result = session_label(record, agent) + "\n" + instructions + json.dumps(context, ensure_ascii=False)
        if len(result.encode("utf-8")) > 1024 * 1024:
            raise Problem(
                413,
                "prompt_too_large",
                "Launch context exceeds 1 MiB; nothing was truncated.",
            )
        return result

    async def execute_real(self, delivery_id):
        delivery = self.store.get("delivery", delivery_id)
        project_id, agent_id, run_id = (
            delivery["project_id"],
            delivery["agent_id"],
            delivery["run_id"],
        )
        status = self.status(project_id, agent_id)
        result = Outcome(None, status["session_id"], "launch_validation_failed")
        try:
            record, agent = self.agent(project_id, agent_id)
            prompt = self.prompt(delivery, record, agent)
            secret = self.issue_credential(project_id, agent_id, run_id)
            self.store.db.commit()

            def observed_session(session_id):
                current = self.status(project_id, agent_id)
                current.update(
                    session_id=session_id,
                    state="busy",
                    source="adapter",
                    reason="Managed turn running.",
                )
                self.store.put(
                    "session",
                    f"{project_id}:{agent_id}:{current['session_generation']}",
                    dict(
                        session_id=session_id,
                        harness=agent["harness"],
                        generation=current["session_generation"],
                    ),
                )
                self.save_status(project_id, current)
                active = self.delivery(project_id, delivery_id)
                active.update(state="running", process_outcome="running")
                self.save_delivery(active)
                self.store.emit(
                    project_id,
                    "run.started",
                    run_id,
                    self.store.get("run", run_id),
                    correlation=delivery["correlation_id"],
                )
                self.store.db.commit()

            def output(stream, text):
                captured = self.store.get("output", run_id)
                if captured["enabled"]:
                    captured["chunks"].append(
                        dict(
                            offset=str(len(captured["chunks"])),
                            stream=stream,
                            text=text,
                        )
                    )
                    self.store.put("output", run_id, captured)
                    self.store.db.commit()

            cwd = resolve(
                record["config"], dict(folder_id=agent["cwd_folder_id"], path=".")
            )
            result = await self.adapters[agent["harness"]].run(
                model=agent["model"],
                session_label=session_label(record, agent),
                prompt=prompt,
                cwd=cwd,
                session_id=status["session_id"],
                effort=agent.get("effort"),
                timeout=record["config"]["call_policy"]["run_timeout_seconds"],
                cancelled=lambda: self.store.get("delivery_input", delivery_id)[
                    "cancel"
                ],
                on_session=observed_session,
                on_output=output,
                extra_env=dict(
                    UV_CACHE_DIR=str(cwd / ".agents" / "mas" / "uv-cache"),
                    UV_OFFLINE="true",
                    MAS_API_URL=self.api_url,
                    MAS_AGENT_TOKEN=secret,
                    MAS_PROJECT_ID=project_id,
                    MAS_AGENT_ID=agent_id,
                    MAS_RUN_ID=run_id,
                    MAS_LOG_ID=delivery["thread_ref"]["log_id"] if delivery["thread_ref"] else "",
                ),
                permission_profile=agent["permission_profile"],
            )
        except asyncio.CancelledError:
            result = Outcome(None, status["session_id"], "cancelled", cancelled=True)
        except (Problem, UnicodeError, OSError):
            result = Outcome(None, status["session_id"], "launch_validation_failed")
        except Exception:
            # No unverified retry after an unexpected supervisor failure.
            result = Outcome(
                None, status["session_id"], "supervisor_error", uncertain=True
            )
        finally:
            self.finish(delivery_id, result)

    def finish(self, delivery_id, result):
        # Read fresh intent/status; do not overwrite a Stop pause or cancellation.
        delivery = self.store.get("delivery", delivery_id)
        project_id, agent_id, run_id = (
            delivery["project_id"],
            delivery["agent_id"],
            delivery["run_id"],
        )
        run = self.store.get("run", run_id)
        status = self.status(project_id, agent_id)
        cancelled = result.cancelled
        failed = result.reason is not None and not cancelled
        outcome = (
            "unknown"
            if result.uncertain
            else "cancelled" if cancelled else "failed" if failed else "succeeded"
        )
        run.update(state=outcome, finished_at=stamp(), exit_code=result.exit_code)
        self.store.put("run", run_id, run)
        observed = False
        reference = delivery["thread_ref"]
        if reference and not cancelled and not failed:
            try:
                record, agent = self.agent(project_id, agent_id)
                document = self.thread(record, agent, reference)
                prior = self.store.get("delivery_input", delivery_id)["thread_before"]
                # Require an attributed target comment added since launch,
                # not a header-only edit or an Owner closing the thread.
                stamps = re.findall(
                    r"^\*\*\[([^,\]]+),\s*\d{4},\s*\d{4}\]\*\*",
                    document["markdown"],
                    re.M,
                )
                observed = (
                    document["metadata"]["revision"] != prior
                    and bool(stamps)
                    and stamps[-1].casefold() == agent["name"].casefold()
                    and sum(s.casefold() == agent["name"].casefold() for s in stamps)
                    > self.store.get("delivery_input", delivery_id).get(
                        "reply_count_before", 0
                    )
                )
            except Problem:
                pass
        missing = (
            delivery["purpose"] == "task"
            and reference is not None
            and not observed
            and not cancelled
            and not failed
        )
        delivery.update(
            state=(
                "uncertain"
                if result.uncertain
                else (
                    "cancelled"
                    if cancelled
                    else "failed" if failed or missing else "completed"
                )
            ),
            process_outcome=outcome,
            thread_reply_observed=observed,
            reason=(
                result.reason
                if result.uncertain
                else (
                    "cancelled"
                    if cancelled
                    else (
                        result.reason
                        if failed
                        else "missing_reply" if missing else None
                    )
                )
            ),
        )
        self.save_delivery(delivery)
        status.update(
            state=(
                "unknown"
                if result.uncertain
                else "needs_input" if missing else "error" if failed else "idle"
            ),
            active_run_id=run_id if result.uncertain else None,
            reason=delivery["reason"],
        )
        if result.uncertain:
            status["queue_paused"] = True
        self.save_status(project_id, status)
        output = self.store.get("output", run_id)
        output["eof"] = True
        self.store.put("output", run_id, output)
        self.store.emit(
            project_id,
            "run.finished",
            run_id,
            run,
            correlation=delivery["correlation_id"],
        )
        self.store.db.commit()

    def output(self, project_id, run_id, offset, limit):
        value = self.store.get("output", run_id)
        if value is None or value["project_id"] != project_id:
            raise Problem(404, "not_found", "Unknown run output.")
        if not value["enabled"]:
            raise Problem(
                409, "output_disabled", "Output capture was disabled for this run."
            )
        if value["expires_at"] <= stamp():
            raise Problem(
                410, "output_expired", "Captured output retention has expired."
            )
        if offset > len(value["chunks"]):
            raise Problem(400, "invalid_offset", "Offset is ahead of available output.")
        chunks = value["chunks"][offset : offset + limit]
        return dict(
            run_id=run_id,
            chunks=chunks,
            next_offset=str(offset + len(chunks)),
            eof=value["eof"] and offset + len(chunks) == len(value["chunks"]),
            expires_at=value["expires_at"],
        )
