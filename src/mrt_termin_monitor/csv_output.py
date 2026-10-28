# SPDX-License-Identifier: Apache-2.0
"""Lauf-CSV – das Schema ist die einzige öffentliche Schnittstelle des Tools.

``FIELDS`` ist die einzige Quelle für Header, Writer, Golden-Test und Codebook
(``docs/datenfelder.md``). Jede Änderung an ``FIELDS`` oder an einem CSV-Wert der
Mappings unten ist eine Schema-Änderung: Commit mit ``feat!``, ``SCHEMA_VERSION``
erhöhen, Codebook nachziehen.

Format für Excel mit Windows-Region ``de-AT``/``de-DE`` per Doppelklick:

- Trenner ``;``: Excel liest den Listentrenner aus der Windows-Region, nicht aus
  der Datei; ``,`` ist dort Dezimaltrenner. Kein ``sep=;``-Kopf – er bricht jeden
  Nicht-Excel-Leser.
- UTF-8 mit BOM: der einzige Weg, Excel per Doppelklick auf UTF-8 zu zwingen.
- CRLF, Quoting nur wo nötig (``dialect="excel"``); Datum ``YYYY-MM-DD``; nur
  Ganzzahlen, weil Dezimalzahlen je nach Region anders gelesen würden.
"""

import csv
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mrt_termin_monitor.model import Measurement

SCHEMA_VERSION = 1
CSV_DELIMITER = ";"
QUELLE = "online_abfrage"

# Spalten in fester Reihenfolge (Schema v1).
FIELDS: tuple[str, ...] = (
    "schema_version",
    "lauf_id",
    "lauf_datum",
    "lauf_zeit",
    "abfrage_zeitpunkt",
    "institut_id",
    "institut_name",
    "untersuchung",
    "abrechnung",
    "quelle",
    "naechster_termin",
    "wartetage",
    "status",
    "hinweis",
)

# Code-Wert (englisch, Enum in model.py) → CSV-Wert (deutsch). Geschlüsselt über den
# String-Wert, weil model.py dieses Modul importiert; ein StrEnum-Mitglied ist als
# Schlüssel gleichwertig. Vollständigkeit prüft tests/test_model.py.
EXAM_VALUES: dict[str, str] = {
    "knee_right": "knie_rechts",
    "lumbar_spine": "lws",
    "renal_mra_contrast": "mr_angio_nieren_km",
}
BILLING_VALUES: dict[str, str] = {
    "public": "kasse",
    "combined": "kombiniert",
}
STATUS_VALUES: dict[str, str] = {
    "ok": "ok",
    "no_slots": "keine_termine",
    "error_redirect": "fehler_weiterleitung",
    "error_parse": "fehler_parsen",
    "not_collected": "nicht_erhoben",
}

# Zellanfänge, die Excel als Formel bzw. Steuerzeichen deutet (OWASP CSV Injection).
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def neutralize(value: str) -> str:
    """Stellt einer Zelle, die als Formel gelesen würde, ein ``'`` voran.

    Instituts-Antworten landen im ``hinweis``; aus Fremddaten darf in Excel nie eine
    Formel entstehen. Gilt für jede Zelle, betrifft praktisch aber nur ``hinweis``
    und ``institut_name`` – die übrigen Spalten beginnen nie so.
    """
    return "'" + value if value.startswith(_FORMULA_PREFIXES) else value


def write_run(path: Path, measurements: Iterable[Measurement]) -> None:
    """Schreibt die Lauf-CSV mit Header, eine Zeile je Messung.

    Args:
        path: Zieldatei ``<lauf_id>.csv``; fehlende Ordner werden angelegt.
        measurements: Messungen des Laufs, in Ausgabe-Reihenfolge.

    Raises:
        FileExistsError: Die Datei existiert schon – Lauf-Dateien sind
            unveränderlich, Überschreiben wäre stiller Datenverlust.
        OSError: Ordner oder Datei nicht schreibbar.

    Bricht das Schreiben ab (Fehler, Strg+C), wird die angefangene Datei gelöscht:
    eine halbe CSV fiele in der Auswertung nicht auf und blockierte den Wiederanlauf.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Öffnen vor dem try: ein FileExistsError darf die fremde Datei nie löschen.
    # newline="": der csv-Writer setzt selbst CRLF; sonst würde Windows \r\r\n schreiben.
    f = path.open("x", encoding="utf-8-sig", newline="")
    try:
        with f:
            writer = csv.writer(f, dialect="excel", delimiter=CSV_DELIMITER)
            writer.writerow(FIELDS)
            for m in measurements:
                row = m.to_row()
                writer.writerow([neutralize(row[name]) for name in FIELDS])
    except BaseException:
        path.unlink()
        raise
