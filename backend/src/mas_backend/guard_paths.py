"""Exact launch paths for harness workflow permissions, not OS isolation."""
import os
from pathlib import Path
import sysconfig


def posix_drive(path):
    text = path.as_posix()
    if len(path.drive) == 2 and path.drive[1] == ":":
        return "/" + text[0].lower() + text[2:]
    return text


def mas_commands():
    # Only this service environment's entry point, never a PATH search result.
    binary = Path(sysconfig.get_path("scripts")) / ("mas.exe" if os.name == "nt" else "mas")
    paths = [binary, binary.with_suffix("")] if os.name == "nt" else [binary]
    commands = {"mas call"}
    for path in paths:
        for text in (str(path), path.as_posix(), posix_drive(path)):
            for quoted in (text, '"' + text + '"', "'" + text + "'"):
                commands.add(quoted + " call")
                if quoted != text:
                    commands.add("& " + quoted + " call")
    return sorted(commands)


def handoff_commands(paths):
    commands = {"uv run --no-project .handoff/handoff.py",
                "uv run --no-project .handoff\\handoff.py"}
    for path in paths:
        for text in (Path(path).as_posix(), str(Path(path))):
            for quoted in (text, '"' + text + '"', "'" + text + "'"):
                commands.add("uv run --no-project " + quoted)
    return sorted(commands)


def opencode_edits(cwd, owned_paths):
    # OpenCode 1 requests edit permission relative to Instance.worktree,
    # including when launched in a subfolder. A .git file marks a worktree too.
    cwd = Path(cwd).resolve()
    root = next((p for p in (cwd, *cwd.parents) if (p / ".git").exists()), cwd)
    rules = {"*": "deny"}
    for value in owned_paths:
        path = Path(value).resolve()
        relative = os.path.relpath(path, root)
        if relative == ".":
            rules["*"] = "allow"
        for text in (relative, relative.replace("\\", "/"), path.as_posix(), str(path)):
            rules[text] = "allow"
            if not path.is_file():
                rules[text.rstrip("/\\") + "/*"] = "allow"
                rules[text.rstrip("/\\") + "\\*"] = "allow"
    return rules


def opencode_external(owned_paths):
    rules = {"*": "deny"}
    for value in owned_paths:
        path = Path(value).resolve()
        # This gate asks for the containing directory; the edit rules still
        # restrict a single-file grant to that file.
        directory = path.parent if path.is_file() else path
        rules[directory.as_posix().rstrip("/") + "/*"] = "allow"
    return rules


def claude_edits(owned_paths, cwd=None):
    rules = []
    cwd = Path(cwd).resolve() if cwd is not None else None
    for value in owned_paths:
        path = Path(value).resolve()
        patterns = ["//" + posix_drive(path).lstrip("/")]
        if cwd is not None and path.is_relative_to(cwd):
            patterns.append(path.relative_to(cwd).as_posix())
        for pattern in patterns:
            rules.append("Edit(" + pattern + ")")
            if not path.is_file():
                rules.append("Edit(" + pattern.rstrip("/") + "/**)")
    return rules


def claude_python(owned_paths, cwd=None):
    """Owned Python/test command text only; never a sandbox for script effects.

    No argument suffix is granted. Deny traversal and whitespace in the varying
    descendant part so a glob cannot also consume a second pytest target/option.
    """
    allow, deny = set(), set()
    cwd = Path(cwd).resolve() if cwd is not None else None
    commands = ("python", "uv run --no-project python",
                "uv run --no-project pytest", "python -m pytest")
    for value in owned_paths:
        path = Path(value).resolve()
        texts = {"Bash": {posix_drive(path)}, "PowerShell": {str(path)}}
        if path.drive:
            texts["Bash"].add("/" + posix_drive(path))
        if cwd is not None and path.is_relative_to(cwd):
            relative = path.relative_to(cwd)
            texts["Bash"].add(relative.as_posix())
            texts["PowerShell"].update((str(relative), relative.as_posix()))
        is_file = path.is_file()
        if is_file and path.suffix.lower() != ".py":
            continue
        for tool, text in ((tool, text) for tool, values in texts.items() for text in values):
            # Do not interpret configured path characters as shell/rule syntax.
            if text.startswith("-") or any(c in text for c in '*?[]"\'`$;\r\n\t'):
                continue
            # Absolute paths use quotes; relative paths also support the common
            # unquoted form. Avoid redundant variants in Windows' bounded argv.
            absolute = text.startswith("/") or (len(text) > 1 and text[1] == ":")
            quotes = ('"',) if absolute or " " in text else ("", '"')
            for command in commands:
                pytest = command.endswith("pytest")
                for quote in quotes:
                    start = command + " " + quote
                    patterns = []
                    if is_file or pytest:
                        patterns.append(start + text + quote)
                    if not is_file:
                        separators = ("/", "\\") if tool == "PowerShell" and os.name == "nt" and "/" not in text else (("\\",) if "\\" in text else ("/",))
                        for separator in separators:
                            prefix = start + text.rstrip("/\\") + separator
                            patterns.append(prefix + ("*" if pytest else "*.py") + quote)
                            # '*' in Claude shell rules includes whitespace.
                            deny.add(f"{tool}({prefix}*{quote} *)")
                    allow.update(f"{tool}({pattern})" for pattern in patterns)
                for unsafe in ("..", "\t", "\r", "\n"):
                    deny.add(f"{tool}({command} *{unsafe}*)")
    return sorted(allow), sorted(deny)
