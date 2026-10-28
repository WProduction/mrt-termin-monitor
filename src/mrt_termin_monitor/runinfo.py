# SPDX-License-Identifier: Apache-2.0
"""Lauf-Kennung und Run-Header – die Provenienz jedes Laufs ohne Rückfrage.

Der Header steht als erste Zeilen in jeder Log-Datei, damit der Support aus der
einen geschickten Datei Version, Umgebung und Konfigurationsstand ablesen kann.
"""

import hashlib
import locale
import platform
import sys
from datetime import datetime
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from mrt_termin_monitor import __version__


def lauf_id(start: datetime) -> str:
    """Kennung eines Laufs aus seiner lokalen Startzeit, z. B. ``2026-10-25_0815``.

    Benennt Log- und CSV-Datei; die Namen sortieren damit chronologisch.
    """
    return start.strftime("%Y-%m-%d_%H%M")


def sites_file() -> Traversable:
    """Ort der ``sites.yaml`` als Package-Data (muss nicht existieren)."""
    return files("mrt_termin_monitor") / "sites.yaml"


def _sha256(source: Traversable) -> str:
    if not source.is_file():
        return "fehlt"
    return hashlib.sha256(source.read_bytes()).hexdigest()


def header_lines(
    argv: list[str], credentials: Path, sites: Traversable | None = None
) -> list[str]:
    """Erzeugt die Run-Header-Zeilen.

    Args:
        argv: CLI-Argumente ohne Programmnamen.
        credentials: Pfad der Credentials-Datei; geloggt wird nur, ob sie
            existiert – nie ihr Inhalt.
        sites: Datei, deren SHA-256 geloggt wird; ``None`` = Package-Data
            ``sites.yaml``.

    Returns:
        Eine Zeile je Angabe, ohne Zeilenumbrüche.
    """
    return [
        f"mrt-termin-monitor {__version__}",
        f"Python {sys.version.replace(chr(10), ' ')}",
        f"Platform {platform.platform()}",
        (
            f"Encoding utf8_mode={sys.flags.utf8_mode}"
            f" preferred={locale.getpreferredencoding(False)}"
        ),
        f"sites.yaml sha256={_sha256(sites if sites is not None else sites_file())}",
        f"credentials.yaml {'vorhanden' if credentials.is_file() else 'fehlt'}",
        f"Argumente {argv!r}",
    ]
