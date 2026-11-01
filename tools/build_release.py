# SPDX-License-Identifier: Apache-2.0
"""Baut das Release-ZIP ``dist/mrt-termin-monitor-<version>.zip``.

Aufruf: ``uv run python tools/build_release.py``

Inhalt, flach an der ZIP-Wurzel: alles unter ``release/`` (cmd-Skripte, Task,
``LIESMICH.txt``), ``wheels/`` mit dem eigenen Wheel und allen Abhängigkeiten als
Windows-Wheels, ``docs/benutzerhandbuch.html``. Damit braucht ``install.cmd`` auf
dem Bediener-Laptop kein Netz. Die Abhängigkeiten kommen mit Hashes aus
``requirements.txt`` (aus ``uv.lock`` exportiert), sind also reproduzierbar.
"""

import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE_DIR = ROOT / "release"
HANDBUCH = ROOT / "docs" / "benutzerhandbuch.html"


def _project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]


def collect_wheels(dest: Path) -> None:
    """Legt das eigene Wheel und alle Abhängigkeiten als Wheels in ``dest`` ab.

    Args:
        dest: Zielordner (wird angelegt).

    Raises:
        subprocess.CalledProcessError: Build oder Download gescheitert, z. B. weil
            eine Abhängigkeit kein Wheel für Windows/diese Python-Version hat.
    """
    # Nur die Untergrenze „>=3.x“ ist vorgesehen; sie ist zugleich die Version,
    # für die die Binär-Wheels (lxml, pyyaml …) geholt werden.
    python = _project()["requires-python"].removeprefix(">=")
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dest)], cwd=ROOT, check=True
    )
    # pip statt uv: uv kann keine Wheels für eine fremde Plattform herunterladen.
    subprocess.run(
        [
            *("uv", "run", "--with", "pip", "python", "-m", "pip", "download"),
            *("-r", "requirements.txt", "-d", str(dest)),
            *("--only-binary=:all:", "--platform", "win_amd64"),
            *("--python-version", python),
            *("--disable-pip-version-check", "--quiet"),
        ],
        cwd=ROOT,
        check=True,
    )


def _zip_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix == ".cmd":
        # cmd verarbeitet Sprungmarken bei LF-Zeilenenden unzuverlässig. Die
        # Arbeitskopie hat nicht zwingend CRLF (.gitattributes greift erst beim
        # Checkout), also hier erzwingen.
        data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return data


def build_zip(wheels: Path, target: Path) -> list[str]:
    """Schreibt das ZIP und gibt die enthaltenen Pfade zurück."""
    sources = [
        (p, p.relative_to(RELEASE_DIR).as_posix()) for p in RELEASE_DIR.rglob("*")
    ]
    # Nur *.whl: ``uv build --out-dir`` legt dort auch eine .gitignore ab.
    sources += [(p, f"wheels/{p.name}") for p in wheels.glob("*.whl")]
    sources.append((HANDBUCH, "docs/benutzerhandbuch.html"))
    names = []
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, name in sorted(sources, key=lambda s: s[1]):
            if path.is_file():
                zf.writestr(name, _zip_bytes(path))
                names.append(name)
    return names


def main() -> int:
    """Baut das ZIP und listet seinen Inhalt; Exit 1, wenn das Handbuch fehlt."""
    if not HANDBUCH.is_file():
        print(f"missing {HANDBUCH}", file=sys.stderr)
        return 1
    target = ROOT / "dist" / f"mrt-termin-monitor-{_project()['version']}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        wheels = Path(tmp) / "wheels"
        collect_wheels(wheels)
        names = build_zip(wheels, target)
    print("\n".join(names))
    print(f"{target} ({len(names)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
