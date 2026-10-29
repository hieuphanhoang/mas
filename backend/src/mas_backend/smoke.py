"""Explicit, finite adapter smoke procedure. Invoke only after Owner approval."""

import json
from pathlib import Path

from .adapters import Adapter

DEFAULT_MODELS = {"claude": "claude-opus-5-5", "codex": "gpt-6-astra"}


def plan(models, workspace):
    return dict(
        workspace=str(workspace.resolve()),
        models=models,
        maximum_cli_turns=2 * len(models),
        sequence=[step for harness in models for step in (f"{harness} first start", f"{harness} explicit-ID resume")],
        permissions="Claude tools disabled; Codex read-only sandbox with approval requests denied; no fallback or retry.",
        checks=[
            "structured output/terminal success",
            "captured session UUID",
            "resume preserves exact session ID",
            "UTF-8 stdin/stdout/stderr",
        ],
        cost=f"{2 * len(models)} short managed turns consume provider subscription/API quota. No fixed currency quote; provider-internal requests may exceed the turn count.",
    )


async def run_smoke(workspace: Path, models, timeout=120, adapters=None):
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError("Smoke workspace must be a new or empty scratch directory.")
    workspace.mkdir(parents=True, exist_ok=True)
    adapters = adapters or {h: Adapter(h) for h in models}
    receipts = []
    for harness in models:
        adapter = adapters[harness]
        version, reason = adapter.probe()
        if reason:
            raise ValueError(f"{harness} probe failed: {reason}")
        session = None
        for number in (1, 2):
            output, observed = [], []
            prompt = f'Reply briefly with MAS {harness} smoke {number}, caf\u00e9 \U0001f680 and "quotes". Do not invoke tools, subagents, models or network requests; do not change files.'
            result = await adapter.run(
                model=models[harness],
                prompt=prompt,
                cwd=workspace,
                session_id=session,
                effort="high",
                timeout=timeout,
                cancelled=lambda: False,
                on_session=observed.append,
                on_output=lambda stream, text: output.append(
                    dict(stream=stream, text=text)
                ),
                smoke=True,
            )
            receipts.append(
                dict(
                    harness=harness,
                    model=models[harness],
                    turn=number,
                    version=version,
                    session_id=result.session_id,
                    exit_code=result.exit_code,
                    reason=result.reason,
                    uncertain=result.uncertain,
                    observed_sessions=observed,
                    output=output,
                )
            )
            (workspace / "smoke-receipt.json").write_text(
                json.dumps(receipts, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if (
                result.reason
                or result.exit_code != 0
                or not result.session_id
                or (session and result.session_id != session)
            ):
                raise ValueError(
                    f"{harness} smoke failed; stopped without retry. Inspect smoke-receipt.json."
                )
            session = result.session_id
    return receipts
