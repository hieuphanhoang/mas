"""Launch permission regressions from the Qwen workflow, no live model calls."""
import asyncio
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath

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
def test_member_launch_has_exact_handoff_and_owned_edits(harness, tmp_path, monkeypatch):
    scripts = tmp_path / "service venv" / "Scripts"
    monkeypatch.setattr("mas_backend.guard_paths.sysconfig.get_path", lambda _: str(scripts))
    binary = scripts / ("mas.exe" if os.name == "nt" else "mas")
    binaries = [binary, binary.with_suffix("")] if os.name == "nt" else [binary]
    command_paths = {str(p) for p in binaries} | {p.as_posix() for p in binaries}
    if os.name == "nt":
        command_paths |= {"/" + p.drive[0].lower() + p.as_posix()[2:] for p in binaries}
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
        for value in command_paths:
            for quoted in (value, '"' + value + '"', "'" + value + "'"):
                assert allowed(shell, quoted + " call sonnet --thread AGENT-007")
                assert not allowed(shell, quoted + " serve")
        assert not allowed(shell, str(scripts / "elsewhere/mas") + " call sonnet")
        assert not allowed(shell, str(binary) + ".evil call sonnet")
        assert record["config"]["agent"]["mas"]["permission"] == permissions
    else:
        argv = record["argv"]
        assert "Edit" not in argv and "Write" not in argv
        def absolute(path):
            text = path.as_posix()
            return "//" + (path.drive[0].lower() + text[2:] if os.name == "nt" else text.lstrip("/"))
        edits = {rule for rule in argv if rule.startswith("Edit(")}
        assert edits == {
            f"Edit({absolute(owned)})", f"Edit({absolute(owned)}/**)",
            "Edit(qwen)", "Edit(qwen/**)",
            f"Edit({absolute(owned_file)})",
            f"Edit({absolute(external)})", f"Edit({absolute(external)}/**)",
        }
        assert not any(rule.startswith("Write(") for rule in argv)
        for tool in ("Bash", "PowerShell"):
            for value in command_paths:
                for quoted in (value, '"' + value + '"', "'" + value + "'"):
                    assert f"{tool}({quoted} call:*)" in argv
                    assert f"{tool}({quoted} serve:*)" not in argv
            for value in (str(script), script.as_posix()):
                assert f'{tool}(uv run --no-project "{value}":*)' in argv
        assert not any("elsewhere" in rule for rule in argv)


def test_claude_windows_path_normalization():
    from mas_backend.guard_paths import posix_drive
    assert posix_drive(PureWindowsPath("D:/temp/mas-levels/sonnet")) == "/d/temp/mas-levels/sonnet"
    assert posix_drive(PurePosixPath("/tmp/sonnet")) == "/tmp/sonnet"


def test_default_profile_does_not_gain_member_permissions(tmp_path):
    from mas_backend.opencode import launch_environment
    env = launch_environment("google/exact", "default", {}, cwd=tmp_path,
        owned_paths=[tmp_path / "owned"], handoff_paths=[tmp_path / ".handoff/handoff.py"])
    permission = json.loads(env["OPENCODE_CONFIG_CONTENT"])["permission"]
    assert permission["edit"] == permission["bash"] == "deny"
    argv = Adapter("claude", ["fake"]).argv("exact", owned_paths=[tmp_path / "owned"])
    assert "--allowedTools" not in argv
