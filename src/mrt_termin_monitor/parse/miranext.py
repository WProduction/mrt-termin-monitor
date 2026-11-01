# SPDX-License-Identifier: Apache-2.0
"""MiraNext-Parser: Service-Zuordnung auflösen, Slot-JSON → frühestes Termin-Datum.

Zwei Schritte, zwei Funktionen. ``resolve_service`` findet im Katalog genau die
eine Service-Zuordnung (Untersuchung auf einem Gerät), deren ID der Slot-Abfrage
mitgegeben wird; ``parse_slots`` liest aus der Slot-Antwort das früheste Datum mit
buchbarer Uhrzeit. Jede Abweichung von der erwarteten Struktur wird ein
Fehlerstatus oder eine Exception, nie ein stilles „keine Termine“. Reine
Funktionen – kein Netz, kein Datei-I/O.
"""

import json
from dataclasses import dataclass
from datetime import date

from mrt_termin_monitor.model import Status

# Modalität, die der Katalog für MR-Geräte führt. Derselbe Suchbegriff trifft auch
# CT-, Röntgen- und Ultraschall-Leistungen; die Modalität schließt sie aus, falls
# einmal ein Name doppelt vergeben wird.
_MODALITY = "MRT"


@dataclass(frozen=True)
class ResolvedService:
    """Zur Laufzeit aufgelöste Service-Zuordnung.

    Attributes:
        assignment_id: ID der Zuordnung; die Slot-Abfrage fragt genau sie ab.
        adjustable_buffer_time: Puffer der Zuordnung in Minuten. Gehört zur
            Zuordnung und muss in der Slot-Abfrage mitgesendet werden, sonst
            rechnet das Portal mit anderen Slot-Längen.
    """

    assignment_id: str
    adjustable_buffer_time: int


@dataclass(frozen=True)
class MiranextSlotResult:
    """Parse-Ergebnis: Status und frühestes buchbares Datum (nur bei ``OK``)."""

    status: Status
    slot_date: date | None = None


def _load_list(payload: bytes | str) -> list:
    """Lädt JSON und erzwingt die Listen-Form.

    Fehlerantworten der API sind gültiges JSON, aber keine Liste: ein fehlender
    Referer/Origin liefert ``{"error": "forbidden"}``, ein falscher
    Mandanten-Parameter ``{"error": "invalid customer"}``, fehlende Pflichtparameter
    ein Validierungsobjekt (HTTP 422). Der Text landet gekürzt in der Exception,
    damit der Grund ohne Archiv-Suche im Hinweis steht.

    Raises:
        ValueError: kein gültiges JSON oder keine Liste.
    """
    data = json.loads(payload)
    if not isinstance(data, list):
        # ValueError statt TypeError: eine Fehlerantwort ist ein falscher Wert von
        # außen, kein Programmierfehler – und so fängt ``parse_slots`` sie mit
        # demselben ``except`` wie kaputtes JSON.
        raise ValueError(f"response is not a JSON list: {str(data)[:200]}")  # noqa: TRY004
    return data


def resolve_service(
    payload: bytes | str, service_name: str, device: str
) -> ResolvedService | None:
    """Sucht die Service-Zuordnung für Untersuchung und Gerät im Katalog.

    Filter je Eintrag: Name exakt gleich (kein Teilstring – „MR Kniegelenk bds.“
    und „MR Kniegelenk, je Seite“ sind andere Leistungen), Modalität MRT, Gerät
    online buchbar und aktiv, Zuordnung aktiv, Gerätename exakt gleich. Der
    Gerätename ist der Kasse/Privat-Schalter: dieselbe Untersuchung steht mit
    eigener ID auch auf dem Privatgerät, ohne Geräte-Filter würde still der
    falsche Pool gemessen.

    Args:
        payload: Roh-JSON der Katalog-Suche (Liste von Zuordnungen).
        service_name: exakter Leistungsname, z. B. ``MR Kniegelenk rechts``.
        device: exakter Gerätename des Kassengeräts.

    Returns:
        Die eine passende Zuordnung; ``None``, wenn keine passt (der Adapter
        macht daraus eine Fehlerzeile).

    Raises:
        ValueError: Antwort ist keine JSON-Liste, mehr als ein Treffer
            (Katalog-Drift – lieber Alarm als eine willkürliche Wahl) oder der
            Treffer hat keine String-ID.
    """
    found: ResolvedService | None = None
    for entry in _load_list(payload):
        dev = entry.get("device")
        if not dev:
            continue  # Zuordnung ohne Gerät ist nicht buchbar
        if (entry.get("service") or {}).get("name") != service_name:
            continue
        if (dev.get("modality") or {}).get("display") != _MODALITY:
            continue
        # Geräte-Flag statt Standortname: es gibt Geräte, deren Kapazität im
        # Katalog steht, aber online nicht buchbar ist.
        if not dev.get("is_patient_online_bookable"):
            continue
        if not entry.get("active") or not dev.get("active"):
            continue  # stillgelegte Zuordnungen und Geräte nicht mitmessen
        if dev.get("device_name") != device:
            continue
        assignment_id = entry.get("id")
        # Die ID landet in der Slot-URL; alles außer einem nicht-leeren String
        # wäre eine stille Fehlabfrage.
        if not isinstance(assignment_id, str) or not assignment_id:
            raise ValueError(f"service assignment without string id: {assignment_id!r}")
        if found is not None:
            raise ValueError(
                f"several service assignments {service_name!r} on device {device!r}"
                f" ({found.assignment_id}, {assignment_id}) - catalog drift"
            )
        found = ResolvedService(
            assignment_id=assignment_id,
            adjustable_buffer_time=int(entry.get("adjustable_buffer_time") or 0),
        )
    return found


def parse_slots(payload: bytes | str, expected_schedule_id: str) -> MiranextSlotResult:
    """Parst die Slot-Antwort einer Zuordnung.

    Args:
        payload: Roh-JSON der Slot-Abfrage.
        expected_schedule_id: angefragte Zuordnungs-ID. Die Antwort muss sie als
            ``schedule.id`` zurückspiegeln; eine leere Liste oder fremde IDs sind
            ``ERROR_PARSE``, nie „keine Termine“ – sonst sähe ein geändertes
            API-Verhalten aus wie ein leerer Kalender.

    Returns:
        ``MiranextSlotResult``; ``slot_date`` ist das früheste ``on_date`` über
        alle ``slots[].date_time_list[]`` mit nicht-leerer ``available_time_list``.

    Raises:
        KeyError, ValueError, AttributeError, TypeError: unerwartete Struktur
            innerhalb eines passenden Eintrags; der Adapter macht daraus eine
            Fehlerzeile.
    """
    try:
        entries = _load_list(payload)
    except ValueError:  # auch JSONDecodeError und UnicodeDecodeError
        return MiranextSlotResult(Status.ERROR_PARSE)

    matched = [
        e
        for e in entries
        if (e.get("schedule") or {}).get("id") == expected_schedule_id
    ]
    if not matched:
        return MiranextSlotResult(Status.ERROR_PARSE)

    earliest: date | None = None
    for entry in matched:
        for slot in entry.get("slots") or []:
            for day in slot.get("date_time_list") or []:
                # Ein Tag ohne konkrete Uhrzeit ist nicht buchbar.
                if not day.get("available_time_list"):
                    continue
                day_date = date.fromisoformat(day["on_date"])
                if earliest is None or day_date < earliest:
                    earliest = day_date

    if earliest is None:
        # Zuordnung korrekt zurückgespiegelt, aber kein buchbarer Tag im
        # Suchfenster: echtes „keine Termine“.
        return MiranextSlotResult(Status.NO_SLOTS)
    return MiranextSlotResult(Status.OK, earliest)
