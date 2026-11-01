# SPDX-License-Identifier: Apache-2.0
"""Tests des XR-WEB-Parsers gegen handgebaute Struktur-Skelette (kein Netz).

Jede Regel des Parsers schützt vor einem stillen Fehler in den Studiendaten:
falsche Untersuchung, Weiterleitung als „keine Termine“, umgebaute Tabelle.
"""

import re
from datetime import date
from pathlib import Path

import pytest

from mrt_termin_monitor.model import Status
from mrt_termin_monitor.parse.xrweb import parse

DATA = Path(__file__).parent / "data" / "xrweb"
URL = "https://termine.example.at/AppointmentSearch/directAppointmentSearch?exas=k"
TITLE = "MR Kniegelenk"


def _skeleton(name: str) -> bytes:
    # Bytes wie im Betrieb: der Parser bekommt die archivierten Roh-Bytes.
    return (DATA / name).read_bytes()


def _parse(html: bytes, *, title: str = TITLE, columns: int = 2, url: str = URL):
    return parse(html, title, day_table_columns=columns, final_url=url)


def test_earliest_date_with_any_counter_above_zero() -> None:
    # 10.08. hat 0/0, 11.08. nur in der zweiten Spalte 0/2, 14.08. steht zuerst in
    # der Tabelle: gewonnen hat das früheste Datum mit Zähler > 0 in irgendeiner
    # Spalte, nicht die erste Zeile und nicht die erste Spalte.
    result = _parse(_skeleton("termine.html"))
    assert result.status is Status.OK
    assert result.slot_date == date(2026, 8, 11)


def test_weekday_without_dot_and_header_row() -> None:
    # „Fr, 14.08.2026“ (ohne Punkt) muss genauso lesen wie „Di., 11.08.2026“;
    # die <th>-Kopfzeile wird übersprungen.
    html = _skeleton("termine.html").replace(b"<div>2</div>", b"<div>0</div>")
    result = _parse(html)
    assert result.status is Status.OK
    assert result.slot_date == date(2026, 8, 14)


def test_wrong_title_is_parse_error() -> None:
    result = _parse(_skeleton("termine.html"), title="MR Schultergelenk")
    assert result.status is Status.ERROR_PARSE
    assert result.slot_date is None


def test_title_is_substring_match() -> None:
    # Mandanten hängen Seite oder Lauftext an („MR Kniegelenk rechts “).
    assert _parse(_skeleton("termine.html"), title="MR Knie").status is Status.OK


def test_forward_page_is_redirect_error_never_no_slots() -> None:
    url = "https://termine.example.at/EKOSAppointmentForward/ForwardPage?para=x"
    result = _parse(_skeleton("weiterleitung.html"), url=url)
    assert result.status is Status.ERROR_REDIRECT
    assert result.slot_date is None
    # Ohne Hinweis sieht die CSV-Zeile wie ein technischer Fehler aus.
    assert "no online booking" in result.note


def test_forward_page_marker_is_case_insensitive() -> None:
    url = "https://termine.example.at/ekosappointmentforward/forwardpage"
    assert _parse(_skeleton("weiterleitung.html"), url=url).status is (
        Status.ERROR_REDIRECT
    )


def test_same_page_without_forward_url_is_parse_error() -> None:
    assert _parse(_skeleton("weiterleitung.html")).status is Status.ERROR_PARSE


def test_para_redirect_url_is_not_an_error() -> None:
    # Der ?para=-Redirect auf demselben Host ist eine normale Antwortvariante.
    url = "https://termine.example.at/AppointmentSearch/directAppointmentSearch?para=x"
    assert _parse(_skeleton("termine.html"), url=url).status is Status.OK


def test_wrong_column_count_is_parse_error() -> None:
    assert _parse(_skeleton("termine.html"), columns=1).status is Status.ERROR_PARSE


def test_missing_day_table_is_parse_error() -> None:
    assert _parse(_skeleton("ohne_tabelle.html")).status is Status.ERROR_PARSE


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b"<div>3</div>", b"<div>drei</div>"),  # Zähler nicht numerisch
        (b"Fr, 14.08.2026", b"Freitag"),  # Datum fehlt
    ],
)
def test_broken_cell_is_parse_error(old: bytes, new: bytes) -> None:
    html = _skeleton("termine.html").replace(old, new)
    assert _parse(html).status is Status.ERROR_PARSE


def test_empty_table_is_no_slots() -> None:
    result = _parse(_skeleton("leere_tabelle.html"))
    assert result.status is Status.NO_SLOTS
    assert result.slot_date is None


def test_all_counters_zero_is_no_slots() -> None:
    html = re.sub(rb"<div>\d+</div>", b"<div>0</div>", _skeleton("termine.html"))
    assert _parse(html).status is Status.NO_SLOTS


def test_accepts_str() -> None:
    html = _skeleton("termine.html").decode("utf-8")
    assert _parse(html).slot_date == date(2026, 8, 11)
