# SPDX-License-Identifier: Apache-2.0
"""Messzeilen-Modell: Roundtrip, wartetage-Ableitung, Enum-Mapping vollständig."""

from datetime import date, datetime, timedelta, timezone

import pytest

from mrt_termin_monitor import csv_output
from mrt_termin_monitor.model import Billing, Exam, Measurement, Status

CET = timezone(timedelta(hours=1))


def measurement(**changes: object) -> Measurement:
    values: dict[str, object] = {
        "run_start": datetime(2026, 10, 25, 8, 15),
        "queried_at": datetime(2026, 10, 25, 8, 16, 42, tzinfo=CET),
        "site_id": "institut_musterstadt",
        "site_name": "Röntgeninstitut Musterstadt",
        "exam": Exam.KNEE_RIGHT,
        "billing": Billing.PUBLIC,
        "status": Status.OK,
        "slot_date": date(2026, 11, 3),
        "note": "",
    }
    values.update(changes)
    return Measurement(**values)  # type: ignore[arg-type]


def test_to_row_has_fields_in_order() -> None:
    assert tuple(measurement().to_row()) == csv_output.FIELDS


def test_to_row_values() -> None:
    row = measurement(note="Termin nur vormittags").to_row()
    assert row == {
        "schema_version": "1",
        "lauf_id": "2026-10-25_0815",
        "lauf_datum": "2026-10-25",
        "lauf_zeit": "08:15",
        "abfrage_zeitpunkt": "2026-10-25T08:16:42+01:00",
        "institut_id": "institut_musterstadt",
        "institut_name": "Röntgeninstitut Musterstadt",
        "untersuchung": "knie_rechts",
        "abrechnung": "kasse",
        "quelle": "online_abfrage",
        "naechster_termin": "2026-11-03",
        "wartetage": "9",
        "status": "ok",
        "hinweis": "Termin nur vormittags",
    }


@pytest.mark.parametrize(
    "m",
    [
        measurement(),
        measurement(exam=Exam.LUMBAR_SPINE, billing=Billing.COMBINED),
        measurement(
            exam=Exam.RENAL_MRA_CONTRAST,
            status=Status.NO_SLOTS,
            slot_date=None,
            note="=1+1",
        ),
        measurement(status=Status.ERROR_PARSE, slot_date=None, note="a;b\r\nc"),
    ],
)
def test_roundtrip(m: Measurement) -> None:
    row = m.to_row()
    assert Measurement.from_row(row) == m
    assert Measurement.from_row(row).to_row() == row


@pytest.mark.parametrize(
    ("slot", "expected"),
    [(date(2026, 10, 25), 0), (date(2026, 10, 26), 1), (date(2027, 1, 1), 68)],
)
def test_waiting_days(slot: date, expected: int) -> None:
    m = measurement(slot_date=slot)
    assert m.waiting_days == expected
    assert m.to_row()["wartetage"] == str(expected)


def test_waiting_days_counts_from_run_date_not_query_time() -> None:
    # Abfrage nach Mitternacht: maßgeblich bleibt der Lauf-Tag.
    m = measurement(
        queried_at=datetime(2026, 10, 26, 0, 5, tzinfo=CET),
        slot_date=date(2026, 10, 27),
    )
    assert m.waiting_days == 2


@pytest.mark.parametrize("status", [s for s in Status if s is not Status.OK])
def test_no_slot_leaves_date_and_waiting_days_empty(status: Status) -> None:
    row = measurement(status=status, slot_date=None).to_row()
    assert row["naechster_termin"] == "" and row["wartetage"] == ""


def test_ok_requires_slot_date() -> None:
    with pytest.raises(ValueError, match="ok"):
        measurement(slot_date=None)


@pytest.mark.parametrize("status", [s for s in Status if s is not Status.OK])
def test_slot_date_only_with_ok(status: Status) -> None:
    with pytest.raises(ValueError, match="ok"):
        measurement(status=status)


def test_slot_before_run_date_rejected() -> None:
    with pytest.raises(ValueError, match="vor dem Lauf-Tag"):
        measurement(slot_date=date(2026, 10, 24))


def test_queried_at_needs_offset() -> None:
    with pytest.raises(ValueError, match="Offset"):
        measurement(queried_at=datetime(2026, 10, 25, 8, 16))


@pytest.mark.parametrize(
    ("enum", "mapping"),
    [
        (Exam, csv_output.EXAM_VALUES),
        (Billing, csv_output.BILLING_VALUES),
        (Status, csv_output.STATUS_VALUES),
    ],
)
def test_enum_mapping_complete(enum: type, mapping: dict[str, str]) -> None:
    # Jeder Code-Wert hat genau einen CSV-Wert und umgekehrt (kein Doppel).
    assert set(mapping) == {m.value for m in enum}
    assert len(set(mapping.values())) == len(mapping)


def test_csv_values_as_specified() -> None:
    assert set(csv_output.EXAM_VALUES.values()) == {
        "knie_rechts",
        "lws",
        "mr_angio_nieren_km",
    }
    assert set(csv_output.BILLING_VALUES.values()) == {"kasse", "kombiniert"}
    assert set(csv_output.STATUS_VALUES.values()) == {
        "ok",
        "keine_termine",
        "fehler_weiterleitung",
        "fehler_parsen",
        "nicht_erhoben",
    }


def test_from_row_rejects_unknown_value() -> None:
    row = measurement().to_row()
    row["abrechnung"] = "privat"
    with pytest.raises(ValueError, match="privat"):
        Measurement.from_row(row)
