"""Launch permission regressions from the Qwen workflow, no live model calls."""
import asyncio
import fnmatch
import json
from pathlib import Path

import pytest

from mas_backend.adapters import Adapter
from test_adapters import fake


def allowed(rules, value):
    # OpenCode 1: simple * / ? patterns, last matching rule wins.
    action = "deny"
    for pattern, candidate in rules.items():
        if fnmatch.fnmatchcase(value.replace("\\", "/"), pattern.replace("\\", "/")):
            action = candidate
    return action == "allow"


@pytest.mark.parametrize("harness", ["opencode", "claude"])
def test_member_launch_has_exact_handoff_and_owned_edits(harness, tmp_path):
    root = tmp_path / "project with space"
    cwd = root / "team"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    owned = cwd / "qwen"
    owned.mkdir()
    owned_file = root / "shared" / "one.md"
    owned_file.parent.mkdir()
    owned_file.touch()
    external = tmp_path / "external-owned"
    external.mkdir()
    script = root / ".handoff/handoff.py"
    adapter = fake(harness, tmp_path)
    result = asyncio.run(adapter.run(
        model="google/exact" if harness == "opencode" else "exact",
        prompt="Read protocol and AGENT-004. Reply from an owned file.",
        cwd=cwd, session_id=None, effort=None, timeout=3, cancelled=lambda: False,
        on_session=lambda _: None, on_output=lambda *_: None,
        permission_profile="member", owned_paths=[owned, owned_file, external],
        handoff_paths=[script],
    ))
    assert result.reason is None
    record = json.loads((tmp_path / (harness + ".jsonl")).read_text(encoding="utf-8"))
    if harness == "opencode":
        permissions = record["config"]["permission"]
        edits = permissions["edit"]
        assert allowed(edits, "team/qwen/add.py")
        assert allowed(edits, "team/qwen/nested/result.md")
        assert allowed(edits, "shared/one.md")
        assert not allowed(edits, "shared/another.md")
        assert not allowed(edits, ".handoff/logs/main/AGENT-004-reply.md")
        assert not allowed(edits, "team/qwen-other/add.py")
        assert not allowed(edits, "team/other/add.py")
        assert allowed(edits, external.as_posix() + "/add.py")
        assert allowed(permissions["external_directory"], external.as_posix() + "/*")
        shell = permissions["bash"]
        for value in (str(script), script.as_posix()):
            assert allowed(shell, f'uv run --no-project "{value}" reply AGENT-004 --body-file qwen/reply.md')
        assert not allowed(shell, f'uv run --no-project "{root}/elsewhere/handoff.py" reply AGENT-004')
        assert not allowed(shell, f'uv run --no-project "{script}.evil" reply AGENT-004')
        assert record["config"]["agent"]["mas"]["permission"] == permissions
    else:
        argv = record["argv"]
        assert "Edit" not in argv and "Write" not in argv
        assert "Edit(//" + owned.as_posix().lstrip("/") + "/**)" in argv
        assert "Edit(//" + owned_file.as_posix().lstrip("/") + ")" in argv
        assert not any(rule.startswith("Write(") for rule in argv)
        for tool in ("Bash", "PowerShell"):
            for value in (str(script), script.as_posix()):
                assert f'{tool}(uv run --no-project "{value}":*)' in argv
        assert not any("elsewhere" in rule for rule in argv)


def test_default_profile_does_not_gain_member_permissions(tmp_path):
    from mas_backend.opencode import launch_environment
    env = launch_environment("google/exact", "default", {}, cwd=tmp_path,
        owned_paths=[tmp_path / "owned"], handoff_paths=[tmp_path / ".handoff/handoff.py"])
    permission = json.loads(env["OPENCODE_CONFIG_CONTENT"])["permission"]
    assert permission["edit"] == permission["bash"] == "deny"
    argv = Adapter("claude", ["fake"]).argv("exact", owned_paths=[tmp_path / "owned"])
    assert "--allowedTools" not in argv
