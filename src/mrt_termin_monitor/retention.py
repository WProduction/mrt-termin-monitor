# SPDX-License-Identifier: Apache-2.0
"""Begrenzt die Zahl der Lauf-Logs, damit der Dokumente-Ordner nicht wächst."""

import logging
from pathlib import Path

KEEP_LOGS = 30  # ≈ ein Monat Tagesbetrieb

log = logging.getLogger(__name__)


def prune_logs(log_dir: Path, keep: int = KEEP_LOGS) -> list[Path]:
    """Löscht alle ``run_*.log`` außer den ``keep`` jüngsten.

    Sortiert nach Dateiname (= Lauf-Kennung, chronologisch), nicht nach mtime:
    deterministisch und unabhängig davon, ob jemand eine Datei kopiert oder öffnet.

    Args:
        log_dir: Ordner der Lauf-Logs.
        keep: Anzahl der jüngsten Logs, die bleiben (inkl. des laufenden).

    Returns:
        Die tatsächlich gelöschten Dateien.
    """
    removed = []
    for old in sorted(log_dir.glob("run_*.log"), reverse=True)[keep:]:
        try:
            old.unlink()
        except OSError as exc:
            # Ein Log, das nicht löschbar ist (z. B. im Editor geöffnet), darf den
            # Lauf nicht abbrechen.
            log.warning("cannot delete old log %s (%s)", old, exc)
        else:
            removed.append(old)
    return removed
