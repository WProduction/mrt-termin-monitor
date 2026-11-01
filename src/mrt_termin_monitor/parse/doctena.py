# SPDX-License-Identifier: Apache-2.0
"""Doctena-Parser: agendaSlot-Antwort (HAL+JSON) → frühestes Termin-Datum.

Gelesen wird nur ``_embedded.agendas[0]._embedded.doctor.slots[].start.date``, ein
ISO-8601-String mit UTC-Offset (z. B. ``2026-08-05T00:30:00+02:00``). Jeder
Strukturbruch wird ein Fehlerstatus, nie ein stilles „keine Termine“: eine
umgebaute oder verweigerte Antwort soll im Datensatz auffallen. Reine Funktion –
kein Netz, kein Datei-I/O.
"""

import json
from dataclasses import dataclass
from datetime import date

from mrt_termin_monitor.model import Status


@dataclass(frozen=True)
class DoctenaResult:
    """Parse-Ergebnis: Status und frühestes Slot-Datum (nur bei ``OK``)."""

    status: Status
    slot_date: date | None = None


def parse(raw: bytes | str) -> DoctenaResult:
    """Parst eine Doctena-agendaSlot-Antwort.

    Args:
        raw: Roh-Antwort (Bytes wie archiviert oder str).

    Returns:
        ``DoctenaResult``; ``slot_date`` ist das Datum des frühesten gelieferten
        Slots. Eine strukturell korrekte, leere Slot-Liste ist ``NO_SLOTS``; kein
        JSON, fehlende Pfade, eine leere ``agendas``-Liste oder ein unlesbares
        Datum sind ``ERROR_PARSE``.
    """
    try:
        data = json.loads(raw)
        agendas = data["_embedded"]["agendas"]
        # Eine leere agendas-Liste heißt „Kalender weg oder Besuchsgrund ungültig“,
        # nicht „keine Termine“ – der IndexError macht daraus bewusst einen Alarm.
        slots = agendas[0]["_embedded"]["doctor"]["slots"]
        if not isinstance(slots, list):
            # Ein Objekt statt einer Liste würde sonst über seine Schlüssel
            # iteriert und je nach Inhalt still als leer gewertet.
            raise TypeError("slots is not a list")
        # [:10] nimmt das LOKALE Datum aus dem Offset-String; eine Umrechnung nach
        # UTC würde einen Termin kurz nach Mitternacht auf den Vortag schieben.
        # min() statt des ersten Elements: die Reihenfolge der API ist nicht
        # zugesichert. Kein Filter auf ein Status-Feld der Slots – dessen Semantik
        # ist undokumentiert, und das Buchungs-Widget zeigt alle gelieferten Slots
        # als buchbar an.
        earliest = min(
            (date.fromisoformat(str(s["start"]["date"])[:10]) for s in slots),
            default=None,
        )
    except ValueError, KeyError, TypeError, IndexError:
        # ValueError deckt auch kaputtes JSON und ungültiges UTF-8 ab.
        return DoctenaResult(Status.ERROR_PARSE)

    if earliest is None:
        return DoctenaResult(Status.NO_SLOTS)
    return DoctenaResult(Status.OK, earliest)
