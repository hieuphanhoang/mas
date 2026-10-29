"""Per-run OpenCode 1 config. Never writes provider keys or global settings.

Sources: opencode.ai/docs/config and /permissions; native Ollama options:
github.com/nordwestt/ollama-ai-provider-v2 (3.x / AI SDK 6).
The native Ollama SDK must be provisioned separately with Owner approval.
"""
import json
from urllib.parse import urlsplit


OLLAMA_SDK = "ollama-ai-provider-v2@3.6.0"


def launch_environment(model, profile, env):
    permission = dict.fromkeys(
        ("*", "bash", "edit", "task", "question", "webfetch", "websearch",
         "external_directory", "lsp", "todowrite", "todoread"), "deny"
    )
    permission.update(dict.fromkeys(("read", "glob", "grep", "list", "skill"), "allow"))
    if profile == "member":
        permission.update(edit="allow", bash={
            "*": "deny",
            "mas call *": "allow",
            "uv run --no-project .handoff/handoff.py *": "allow",
            "uv run --no-project .handoff\\handoff.py *": "allow",
        })
    config = dict(
        model=model, small_model=model, share="disabled", autoupdate=False,
        lsp=False, formatter=False, permission=permission,
        agent={"mas": dict(mode="primary", permission=permission),
               "title": dict(disable=True), "summary": dict(disable=True)},
    )
    if model.startswith("ollama/"):
        host = env.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
        if "://" not in host:
            host = "http://" + host
        parsed = urlsplit(host)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("OLLAMA_HOST must be an HTTP(S) URL without credentials/query.")
        config["provider"] = {"ollama": dict(
            npm=OLLAMA_SDK, name="Ollama local",
            options=dict(baseURL=host.rstrip("/").removesuffix("/api") + "/api"),
            models={"qwen3.5:latest": dict(
                name="Qwen 3.5", tool_call=True,
                limit=dict(context=32768, output=8192),
                options=dict(options=dict(num_ctx=32768)),
            )},
        )}
    result = dict(
        OPENCODE_CONFIG_CONTENT=json.dumps(config),
        OPENCODE_DISABLE_AUTOUPDATE="true",
        OPENCODE_DISABLE_DEFAULT_PLUGINS="true",
        OPENCODE_DISABLE_LSP_DOWNLOAD="true",
        OPENCODE_DISABLE_MODELS_FETCH="true",
    )
    # An explicit Google SDK key wins over the compatibility alias.
    if not env.get("GOOGLE_GENERATIVE_AI_API_KEY") and env.get("GEMINI_API_KEY"):
        result["GOOGLE_GENERATIVE_AI_API_KEY"] = env["GEMINI_API_KEY"]
    return result
