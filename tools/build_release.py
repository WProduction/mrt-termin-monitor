# SPDX-License-Identifier: Apache-2.0
"""Baut das Release-ZIP ``dist/mrt-termin-monitor-<version>.zip``.

Aufruf: ``uv run python tools/build_release.py``

Inhalt, flach an der ZIP-Wurzel: alles unter ``release/`` (cmd-Skripte, Task,
``LIESMICH.txt``), ``wheels/`` mit dem eigenen Wheel und allen Abhängigkeiten als
Windows-Wheels je Version aus ``PYTHONS``, ``docs/benutzerhandbuch.html``. Läuft
nur auf Windows x64, weil die Wheels für den Build-Rechner gebaut werden. Damit braucht ``install.cmd`` auf
dem Bediener-Laptop kein Netz. Die Abhängigkeiten kommen mit Hashes aus
``requirements.txt`` (aus ``uv.lock`` exportiert), sind also reproduzierbar.
"""

import os
import subprocess
import sys
import sysconfig
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE_DIR = ROOT / "release"
HANDBUCH = ROOT / "docs" / "benutzerhandbuch.html"
# Python-Versionen, für die das ZIP Wheels enthält. install.cmd lässt genau diese
# zu, requires-python beginnt bei der ersten (beides prüft test_release.py).
PYTHONS = ("3.14", "3.15")


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
    # pip wheel baut für den eigenen Rechner, nicht für eine angegebene Plattform;
    # auf einem anderen Build-Rechner kämen still die falschen Binär-Wheels ins ZIP.
    if sysconfig.get_platform() != "win-amd64":
        raise SystemExit(f"build on win-amd64, not {sysconfig.get_platform()}")
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dest)], cwd=ROOT, check=True
    )
    # Je Version ein eigener Satz Binär-Wheels (lxml, charset_normalizer); reine
    # Wheels landen unter demselben Namen und werden einfach überschrieben.
    # ponytail: PyYAML hat kein Wheel für 3.15, darum aus dem Quellpaket ohne
    # C-Teil (PYYAML_FORCE_LIBYAML=0) als reines Wheel für alle Versionen. Gibt es
    # ein cp315-Wheel, können --no-binary und die Variable wieder raus.
    for python in PYTHONS:
        subprocess.run(
            [
                *("uv", "tool", "run", "--python", python, "--from", "pip"),
                *("pip", "wheel", "-r", "requirements.txt", "-w", str(dest)),
                *("--only-binary=:all:", "--no-binary=pyyaml"),
                *("--disable-pip-version-check", "--quiet"),
            ],
            cwd=ROOT,
            check=True,
            env={**os.environ, "PYYAML_FORCE_LIBYAML": "0"},
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
