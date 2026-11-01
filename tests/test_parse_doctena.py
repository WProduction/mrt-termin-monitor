# SPDX-License-Identifier: Apache-2.0
"""Tests des Doctena-Parsers gegen handgebaute Struktur-Skelette (kein Netz).

Kernpunkt: nur eine strukturell korrekte, leere Slot-Liste darf „keine Termine“
sein; jeder Strukturbruch muss als Parse-Fehler auffallen.
"""

from datetime import date
from pathlib import Path

import pytest

from mrt_termin_monitor.model import Status
from mrt_termin_monitor.parse.doctena import parse

DATA = Path(__file__).parent / "data" / "doctena"


def _skeleton(name: str) -> bytes:
    # Bytes wie im Betrieb: der Parser bekommt die archivierten Roh-Bytes.
    return (DATA / name).read_bytes()


def _doc(slots: str) -> bytes:
    """Gültige Hülle um eine beliebige ``slots``-JSON-Darstellung."""
    return (
        '{"_embedded":{"agendas":[{"_embedded":{"doctor":{"slots":' + slots + "}}}]}}"
    ).encode()


def test_earliest_slot_by_local_date() -> None:
    # Das Minimum steht nicht vorn, und 00:30+02:00 am 05.08. wäre in UTC der
    # 04.08.: gewonnen hat das früheste lokale Datum, nicht das erste Element.
    result = parse(_skeleton("termine.json"))
    assert result.status is Status.OK
    assert result.slot_date == date(2099, 8, 5)


def test_empty_slot_list_is_no_slots() -> None:
    result = parse(_skeleton("leer.json"))
    assert result.status is Status.NO_SLOTS
    assert result.slot_date is None


def test_accepts_str() -> None:
    raw = _skeleton("termine.json").decode("utf-8")
    assert parse(raw).slot_date == date(2099, 8, 5)


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(b"<html><body>challenge</body></html>", id="html"),
        pytest.param(b"{}", id="empty-object"),
        pytest.param(b'{"_embedded":{"agendas":[]}}', id="no-agenda"),
        pytest.param(b'{"_embedded":{"agendas":[{"_embedded":{}}]}}', id="no-doctor"),
        pytest.param(_doc('{"a":{"start":{"date":"2099-08-05"}}}'), id="slots-dict"),
        pytest.param(_doc('[{"end":{"date":"2099-08-05"}}]'), id="no-start"),
        pytest.param(_doc('[{"start":{"date":"05.08.2099"}}]'), id="bad-date"),
        pytest.param(_doc('["2099-08-05"]'), id="slot-not-object"),
        pytest.param(b"[]", id="top-level-list"),
        pytest.param(b"\xff", id="invalid-utf8"),
    ],
)
def test_structure_break_is_parse_error(raw: bytes) -> None:
    result = parse(raw)
    assert result.status is Status.ERROR_PARSE
    assert result.slot_date is None
