"""Run the unchanged handoff CLI with a UTF-8 body supplied as an in-memory argv.

The CLI's --body-file strips boundary newlines. Its --body path preserves them;
using an in-memory argv also avoids shell quoting and Windows command-line size
limits. This bridge is stdlib-only and is invoked via uv run --no-project.
"""
import argparse
from pathlib import Path
import runpy
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--body-file", type=Path)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    args = options.args[1:] if options.args[:1] == ["--"] else options.args
    if options.body_file:
        # Normalize text line endings once before the CLI's native text writer;
        # otherwise CRLF input would become CRCRLF on Windows. No whitespace or
        # boundary newline stripping is performed.
        with options.body_file.open(encoding="utf-8") as stream:
            args += ["--body", stream.read()]
    sys.argv = [str(options.cli), *args]
    runpy.run_path(str(options.cli), run_name="__main__")


if __name__ == "__main__":
    main()
