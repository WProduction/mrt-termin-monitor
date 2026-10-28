# SPDX-License-Identifier: Apache-2.0
"""Messzeile der Lauf-CSV: eine Zeile = Institut × Untersuchung × Abrechnung × Lauf.

Im Code englisch (Feldnamen, Enum-Werte), in der CSV deutsch. Die Übersetzung
steht an genau einer Stelle, neben ``FIELDS`` in ``csv_output``; ``to_row`` und
``from_row`` sind die einzigen Übergänge zwischen beiden Welten.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from mrt_termin_monitor import runinfo
from mrt_termin_monitor.csv_output import (
    BILLING_VALUES,
    EXAM_VALUES,
    QUELLE,
    SCHEMA_VERSION,
    STATUS_VALUES,
)


class Exam(StrEnum):
    """Untersuchung (Fall der Studie). Neuer Wert = Schema-Änderung (``feat!``).

    Die Seite steckt im Fall: beim Knie wird nur rechts gemessen.
    """

    KNEE_RIGHT = "knee_right"
    LUMBAR_SPINE = "lumbar_spine"
    RENAL_MRA_CONTRAST = "renal_mra_contrast"


class Billing(StrEnum):
    """Welcher Termin-Pool gemessen wurde. Privat-Pools werden nie abgefragt.

    ``PUBLIC`` = eigener Kassen-Pool; ``COMBINED`` = ein Pool für Kasse und Privat,
    der Kassen-Termin ist darin enthalten.
    """

    PUBLIC = "public"
    COMBINED = "combined"


class Status(StrEnum):
    """Ergebnis einer Abfrage.

    ``ERROR_REDIRECT`` (Portal leitet auf Fehler- oder Fremdseite um) darf nie als
    „keine Termine" gewertet werden – deshalb ein eigener Zustand statt ``NO_SLOTS``.
    """

    OK = "ok"
    NO_SLOTS = "no_slots"
    ERROR_REDIRECT = "error_redirect"
    ERROR_PARSE = "error_parse"
    NOT_COLLECTED = "not_collected"


def _from_csv[E: StrEnum](enum: type[E], mapping: dict[str, str], value: str) -> E:
    for code, csv_value in mapping.items():
        if csv_value == value:
            return enum(code)
    raise ValueError(f"unbekannter CSV-Wert {value!r} für {enum.__name__}")


@dataclass
class Measurement:
    """Eine Messzeile.

    Attributes:
        run_start: Lauf-Start, lokal und naiv, minutengenau; liefert ``lauf_id``,
            ``lauf_datum`` und ``lauf_zeit`` – alle drei aus derselben Quelle.
        queried_at: Zeitpunkt des Requests, mit UTC-Offset (sonst wäre die Spalte
            bei der Sommerzeit-Umstellung mehrdeutig).
        site_id: Slug aus ``sites.yaml``, stabiler Join-Schlüssel der Zeitreihe.
        site_name: lesbarer Institutsname.
        slot_date: nächster Termin; genau dann gesetzt, wenn ``status`` ``OK`` ist.
        note: Adapter-Hinweis (Fremdtext, wird beim Schreiben neutralisiert).
    """

    run_start: datetime
    queried_at: datetime
    site_id: str
    site_name: str
    exam: Exam
    billing: Billing
    status: Status
    slot_date: date | None = None
    note: str = ""

    def __post_init__(self) -> None:
        # Verstöße hier wären still falsche Studiendaten: ein "ok" ohne Datum oder
        # ein Datum, das in der Auswertung als Termin trotz Fehler gezählt würde.
        if (self.status is Status.OK) != (self.slot_date is not None):
            raise ValueError(
                f"Termin nur und immer bei status ok: {self.status}, {self.slot_date}"
            )
        if self.queried_at.utcoffset() is None:
            raise ValueError("queried_at braucht einen UTC-Offset")
        # Ein Termin vor dem Lauf-Tag ist ein Parserfehler; negative wartetage würden
        # in der CSV zudem als Text ('-5) statt als Zahl landen.
        if self.slot_date is not None and self.slot_date < self.run_start.date():
            raise ValueError(
                f"Termin {self.slot_date} liegt vor dem Lauf-Tag {self.run_start.date()}"
            )

    @property
    def waiting_days(self) -> int | None:
        """Tage vom Lauf-Tag bis zum nächsten Termin; ``None`` ohne Termin.

        Gezählt ab dem Lauf-Tag, nicht ab der Abfrage: alle Zeilen eines Laufs
        haben dieselbe Basis, auch wenn der Lauf über Mitternacht geht.
        """
        if self.slot_date is None:
            return None
        return (self.slot_date - self.run_start.date()).days

    def to_row(self) -> dict[str, str]:
        """Übersetzt in eine CSV-Zeile (deutsche Spalten und Werte, ``FIELDS``-Reihenfolge).

        Leerer String = kein Wert. Injection-Schutz ist Sache des Writers.
        """
        waiting = self.waiting_days
        return {
            "schema_version": str(SCHEMA_VERSION),
            "lauf_id": runinfo.lauf_id(self.run_start),
            "lauf_datum": self.run_start.strftime("%Y-%m-%d"),
            "lauf_zeit": self.run_start.strftime("%H:%M"),
            "abfrage_zeitpunkt": self.queried_at.isoformat(timespec="seconds"),
            "institut_id": self.site_id,
            "institut_name": self.site_name,
            "untersuchung": EXAM_VALUES[self.exam],
            "abrechnung": BILLING_VALUES[self.billing],
            "quelle": QUELLE,
            "naechster_termin": self.slot_date.isoformat() if self.slot_date else "",
            "wartetage": "" if waiting is None else str(waiting),
            "status": STATUS_VALUES[self.status],
            "hinweis": self.note,
        }

    @classmethod
    def from_row(cls, row: dict[str, str]) -> Measurement:
        """Umkehrung von ``to_row``.

        Abgeleitete und konstante Spalten (``lauf_id``, ``wartetage``,
        ``schema_version``, ``quelle``) werden nicht gelesen. Zellen, die der
        Writer gegen Formel-Injection mit ``'`` versehen hat, kommen so zurück.

        Raises:
            ValueError: unbekannter Enum-Wert, ungültiges Datum oder verletzte
                Invariante.
        """
        return cls(
            run_start=datetime.fromisoformat(f"{row['lauf_datum']}T{row['lauf_zeit']}"),
            queried_at=datetime.fromisoformat(row["abfrage_zeitpunkt"]),
            site_id=row["institut_id"],
            site_name=row["institut_name"],
            exam=_from_csv(Exam, EXAM_VALUES, row["untersuchung"]),
            billing=_from_csv(Billing, BILLING_VALUES, row["abrechnung"]),
            status=_from_csv(Status, STATUS_VALUES, row["status"]),
            slot_date=(
                date.fromisoformat(row["naechster_termin"])
                if row["naechster_termin"]
                else None
            ),
            note=row["hinweis"],
        )
