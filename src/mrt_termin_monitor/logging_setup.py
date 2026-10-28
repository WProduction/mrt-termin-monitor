# SPDX-License-Identifier: Apache-2.0
"""Logging-Konfiguration: zwei Kanäle, beide geschwärzt.

- Konsole (stderr, INFO): nur die Nachricht, für die Operatorin. Keine Farben –
  ob die Windows-Konsole der Bediener-Laptops ANSI-Sequenzen darstellt, ist nicht
  geprüft, und Escape-Müll wäre schlimmer als keine Farbe. ``--no-color`` und
  ``NO_COLOR`` sind damit ohne weiteren Code erfüllt.
- Datei (DEBUG, ``logs/run_<lauf_id>.log``): alles inkl. Tracebacks, für den Support.
"""

import logging
import logging.config
from pathlib import Path

from mrt_termin_monitor.redaction import RedactionFilter

FILE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure(log_file: Path, redaction: RedactionFilter) -> None:
    """Richtet Root-Logger, Konsolen- und Datei-Handler ein.

    Ersetzt eine vorherige Konfiguration vollständig (alte Handler werden
    geschlossen).

    Args:
        log_file: Ziel-Log-Datei; der Ordner wird bei Bedarf angelegt.
        redaction: Filter, der an beide Handler gehängt wird. Dieselbe Instanz,
            damit später per ``add_secrets`` ergänzte Werte überall wirken.

    Raises:
        OSError: Log-Ordner oder -Datei nicht anlegbar.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"redact": {"()": lambda: redaction}},
            "formatters": {
                "console": {"format": "%(message)s"},
                "file": {"format": FILE_FORMAT},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stderr",
                    "level": "INFO",
                    "formatter": "console",
                    "filters": ["redact"],
                },
                "file": {
                    "class": "logging.FileHandler",
                    "filename": str(log_file),
                    # utf-8 + backslashreplace: ein UnicodeEncodeError im Handler
                    # erreicht die Anwendung nie und kostete still die Log-Zeile –
                    # das einzige Artefakt für die Fehlersuche.
                    "encoding": "utf-8",
                    "errors": "backslashreplace",
                    "level": "DEBUG",
                    "formatter": "file",
                    "filters": ["redact"],
                },
            },
            # urllib3 loggt unterhalb WARNING URLs samt Query – möglicher Leak-Pfad.
            "loggers": {
                "urllib3": {"level": "WARNING"},
                "requests": {"level": "WARNING"},
            },
            "root": {"level": "DEBUG", "handlers": ["console", "file"]},
        }
    )
