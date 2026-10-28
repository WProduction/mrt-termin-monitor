# SPDX-License-Identifier: Apache-2.0
"""Credentials-Datei: Einrichtungs-Dialog (schreiben) und Laden (prüfen).

Schreiben und Lesen stehen beieinander, damit das Dateiformat nur an einer Stelle
definiert ist. Der Dialog ist die einzige Stelle des Programms mit ``input()`` –
der Lauf selbst bleibt nicht-interaktiv (Scheduler).
"""

import re
from collections.abc import Callable
from pathlib import Path

import yaml

from mrt_termin_monitor import messages
from mrt_termin_monitor.errors import ConfigError

# Schlüssel wie im POC, damit der patapp-Adapter sie unverändert übernimmt.
SVNR = "svnr"
NAME = "patient_name"
MOBILE = "patient_mobile"


def normalize_svnr(text: str) -> str | None:
    """Entfernt Leerzeichen; liefert die 10 Ziffern oder ``None`` bei falschem Format."""
    digits = re.sub(r"\s", "", text)
    # [0-9] statt \d: \d träfe auch Nicht-ASCII-Ziffern (z. B. arabisch-indisch).
    return digits if re.fullmatch(r"[0-9]{10}", digits) else None


def run_dialog(
    target: Path,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
) -> dict[str, str]:
    """Fragt SVNR (Pflicht) sowie Name und Mobilnummer (optional) ab und speichert.

    Eine ungültige SVNR wird erneut abgefragt, bis sie 10 Ziffern hat. Eine
    vorhandene Datei wird überschrieben (Neu-Einrichtung, z. B. nach Update).

    Args:
        target: Ziel-Datei, i. d. R. ``paths.credentials_file()``.
        ask: Eingabefunktion (Tests ersetzen ``input``).
        say: Ausgabefunktion (Tests ersetzen ``print``).

    Returns:
        Die gespeicherten Werte (für die Redaction).
    """
    say(messages.SETUP_TITEL)
    while (svnr := normalize_svnr(ask(messages.SETUP_SVNR))) is None:
        say(messages.SETUP_SVNR_UNGUELTIG)
    data = {
        SVNR: svnr,
        NAME: ask(messages.SETUP_NAME).strip(),
        MOBILE: ask(messages.SETUP_MOBIL).strip(),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    # safe_dump quotet die SVNR als String – unquotet würde YAML sie als Zahl lesen
    # (führende Null als Oktalzahl).
    target.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    say(messages.SETUP_GESPEICHERT.format(path=target))
    return data


def load_credentials(path: Path) -> dict[str, str]:
    """Lädt und prüft die Credentials-Datei.

    Args:
        path: Pfad der Datei.

    Returns:
        ``svnr`` (10 Ziffern) sowie ``patient_name``/``patient_mobile`` (ggf. leer).

    Raises:
        ConfigError: Datei fehlt, ist kein gültiges YAML-Mapping oder die SVNR
            fehlt bzw. hat nicht 10 Ziffern. Fehlertexte nennen nie Werte.
    """
    if not path.is_file():
        raise ConfigError(f"credentials file missing: {path}")
    try:
        # BaseLoader liest jeden Skalar als String: eine von Hand eingetragene,
        # ungequotete SVNR mit führender Null würde sonst als Oktalzahl gelesen.
        # Baut wie safe_load keine Python-Objekte.
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        # Der YAML-Fehlertext zitiert die Zeile; die Redaction schwärzt SVNR-Formen.
        raise ConfigError(f"credentials file unreadable: {path}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"credentials file is not a mapping: {path}")
    svnr = normalize_svnr(str(data.get(SVNR) or ""))
    if svnr is None:
        raise ConfigError(f"svnr missing or not 10 digits in {path}")
    return {
        SVNR: svnr,
        NAME: str(data.get(NAME) or ""),
        MOBILE: str(data.get(MOBILE) or ""),
    }
