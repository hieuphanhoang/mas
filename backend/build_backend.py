"""MAS-only PEP 517 wheel build using the standard library.

An editable install points at src; a normal wheel contains the package. This
keeps the approved dependency set unchanged. No downloads or external commands.
"""
import base64
import csv
import hashlib
import io
from pathlib import Path
import tomllib
import zipfile

ROOT = Path(__file__).parent


def _build(wheel_directory, editable=False):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    name = project["name"].replace("-", "_")
    version = project["version"]
    info = f"{name}-{version}.dist-info"
    metadata = (f"Metadata-Version: 2.3\nName: {project['name']}\nVersion: {version}\n"
                f"Requires-Python: {project['requires-python']}\n")
    metadata += "".join(f"Requires-Dist: {dep}\n" for dep in project["dependencies"])
    files = {
        f"{info}/METADATA": metadata.encode(),
        f"{info}/WHEEL": b"Wheel-Version: 1.0\nGenerator: mas-stdlib\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{info}/entry_points.txt": b"[console_scripts]\nmas = mas_backend.cli:main\n",
    }
    if editable:
        files["mas_backend.pth"] = (str(ROOT / "src") + "\n").encode()
    else:
        for path in (ROOT / "src").rglob("*.py"):
            files[path.relative_to(ROOT / "src").as_posix()] = path.read_bytes()
    rows = []
    for path, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        rows.append((path, f"sha256={digest}", len(data)))
    rows.append((f"{info}/RECORD", "", ""))
    output = io.StringIO(newline="")
    csv.writer(output).writerows(rows)
    files[f"{info}/RECORD"] = output.getvalue().encode()
    filename = f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(Path(wheel_directory) / filename, "w", zipfile.ZIP_DEFLATED) as wheel:
        for path, data in sorted(files.items()):
            wheel.writestr(path, data)
    return filename


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    return _build(wheel_directory)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    return _build(wheel_directory, editable=True)
