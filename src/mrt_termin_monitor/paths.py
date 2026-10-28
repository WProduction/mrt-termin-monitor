# SPDX-License-Identifier: Apache-2.0
"""Datei-Orte zur Laufzeit – einzige Quelle für alle Pfade des Programms.

Zwei Wurzeln, bewusst getrennt:

- Konfigurations-Wurzel (``%LOCALAPPDATA%\\mrt-termin-monitor``): Secrets. Liegt nie
  unter *Dokumente*, weil OneDrive-Ordnersicherung *Dokumente* in die Cloud
  verschiebt und die SVNR ein Gesundheitsdatum ist.
- Dokumente-Wurzel (``Dokumente\\mrt-termin-monitor``): Logs, CSV, Roh-Archiv. Liegt
  dort, damit die Operatorin die Dateien findet und per Mail verschicken kann.

``MRT_TERMIN_MONITOR_HOME=<dir>`` setzt beide Wurzeln auf ``<dir>\\config`` und
``<dir>\\documents`` (Tests, Proben). Die Variable wird bei jedem Aufruf gelesen,
nicht beim Import, damit Tests sie per ``monkeypatch`` setzen können.
"""

import os
from pathlib import Path

import platformdirs

APP_NAME = "mrt-termin-monitor"
HOME_ENV = "MRT_TERMIN_MONITOR_HOME"


def _home() -> Path | None:
    value = os.environ.get(HOME_ENV)
    # absolute(): ein relativer Override darf nicht vom cwd des Aufrufers abhängen,
    # der bei Verknüpfung/Scheduler undefiniert ist.
    return Path(value).absolute() if value else None


def config_root() -> Path:
    """Wurzel für Secrets (``%LOCALAPPDATA%\\mrt-termin-monitor``), absolut."""
    home = _home()
    if home:
        return home / "config"
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False)).absolute()


def documents_root() -> Path:
    """Wurzel für Logs, CSV und Roh-Archiv (``Dokumente\\mrt-termin-monitor``), absolut."""
    home = _home()
    if home:
        return home / "documents"
    # user_documents_dir folgt einer OneDrive-Umleitung von *Dokumente* – gewollt.
    return (Path(platformdirs.user_documents_dir()) / APP_NAME).absolute()


def credentials_file() -> Path:
    """Secrets-Datei mit SVNR und optionalen Patientendaten."""
    return config_root() / "credentials.yaml"


def log_dir() -> Path:
    """Ordner der Lauf-Logs ``run_<lauf_id>.log``."""
    return documents_root() / "logs"


def data_dir() -> Path:
    """Ordner der Lauf-CSVs ``<lauf_id>.csv``."""
    return documents_root() / "data"


def raw_dir() -> Path:
    """Ordner des Roh-Archivs, darunter je Lauf ``<lauf_id>/``."""
    return documents_root() / "raw"
