"""Version probes only: never start a model turn or change authentication."""
from .common import stamp
from .adapters import Adapter


def probe_capabilities():
    adapters, profiles = [], []
    for harness in ("claude", "codex", "opencode", "gemini", "relay"):
        available, version = "unavailable", None
        reason = "Executable not found on the service PATH."
        if harness in ("claude", "codex", "opencode"):
            version, reason = Adapter(harness).probe()
            if version:
                available = "available"
                reason = "Version/help probes passed. Managed turns require explicit --real-adapters and Owner approval. Live smoke verification pending."
        elif harness == "relay":
            available, reason = "manual", "Human relay only; no process adapter."
        else:
            available, reason = "planned", "Adapter is planned and cannot execute in slice 1."
        adapters.append(dict(harness=harness, availability=available, version=version, reason=reason,
            modes=["manual"] if harness == "relay" else ["managed", "manual"] if available == "available" else [],
            resume=available == "available", live_delivery=False,
            attach=False, stop=available == "available", guard_coverage=dict(tool_paths="unsupported", shell_commands="unknown",
            sandbox="unknown", limitations=["Lifecycle tested with fake subprocesses; live smoke and sandbox coverage remain unverified.",
                "Only MAS-managed process trees are owned; external sessions are not adopted or killed.",
                "Role/ownership instructions are workflow context, not OS enforcement."])))
        if available == "available":
            if harness == "opencode":
                for profile in ("default", "member"):
                    profiles.append(dict(id=profile, harness=harness,
                        label="OpenCode " + profile,
                        description=("Read/skill tools; other tools denied." if profile == "default" else
                                     "Read/skill tools, owned-path edits, mas call and exact registered-log handoff CLI shell prefixes; other tools denied.") +
                                    " No sandbox isolation or runtime prompts. Models use provider/model (google/... or ollama/...). "
                                    "Native Ollama num_ctx=32768 needs separately approved provisioning of ollama-ai-provider-v2@3.6.0; not bundled by MAS."))
                continue
            profiles.append(dict(id="default", harness=harness, label="Default local profile",
                description=("Codex workspace-write with approval_policy=never (requests requiring approval denied)." if harness == "codex" else
                             "Claude manual permissions with permission-prompts=none (requests requiring approval denied).") +
                            " No bypass or model fallback; independent ownership isolation is unverified."))
            profiles.append(dict(id="member", harness=harness, label="Member collaboration",
                description=("Allow the handoff CLI and mas call Bash/PowerShell prefixes plus owned-path Edit rules (also cover Write); other approval-requiring commands are denied." if harness == "claude" else
                             "Network on: workspace-write with approval_policy=never and command network access enabled. The Owner accepted access to any host for this profile; not restricted to localhost.") +
                            " Owner selects at setup; no runtime permission prompts. Workflow ownership is not OS isolation."))
    return dict(adapters=adapters, permission_profiles=profiles, global_max_parallel=2, observed_at=stamp())
