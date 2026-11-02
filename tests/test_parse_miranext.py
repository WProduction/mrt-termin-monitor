# SPDX-License-Identifier: Apache-2.0
"""Tests des MiraNext-Parsers gegen handgebaute Struktur-Skelette (kein Netz).

Jeder Filter der Service-Auflösung schützt davor, still eine andere Leistung oder
den Privatpool zu messen; ``parse_slots`` darf eine unerwartete Antwort nie als
„keine Termine“ werten.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from mrt_termin_monitor.model import Status
from mrt_termin_monitor.parse.miranext import (
    ResolvedService,
    parse_slots,
    resolve_service,
)

DATA = Path(__file__).parent / "data" / "miranext"
NAME = "MR Kniegelenk rechts"
DEVICE = "MR"
ID_MR = "00000000-0000-4000-8000-aaaaaaaaaa01"


def _skeleton(name: str) -> bytes:
    # Bytes wie im Betrieb: der Parser bekommt die archivierten Roh-Bytes.
    return (DATA / name).read_bytes()


def _catalog() -> list[dict]:
    return json.loads(_skeleton("service_assignments.json"))


def _resolve(entries: list[dict], name: str = NAME, device: str = DEVICE):
    return resolve_service(json.dumps(entries).encode(), name, device)


def test_skeleton_resolves_exactly_the_cash_device_entry() -> None:
    # Das Skelett enthält denselben Namen auch auf Privatgerät, nicht online
    # buchbarem Gerät und ohne Gerät – getroffen wird nur der Kassen-Eintrag.
    assert resolve_service(_skeleton("service_assignments.json"), NAME, DEVICE) == (
        ResolvedService(assignment_id=ID_MR, adjustable_buffer_time=0)
    )


def test_device_name_selects_the_pool() -> None:
    # Der Gerätename ist der Kasse/Privat-Schalter; der Buffer kommt aus dem Eintrag.
    resolved = resolve_service(_skeleton("service_assignments.json"), NAME, "PMR-S")
    assert resolved == ResolvedService(
        assignment_id="00000000-0000-4000-8000-aaaaaaaaaa02", adjustable_buffer_time=5
    )


def test_name_is_exact_match() -> None:
    # „MR Kniegelenk“ ist Teilstring aller Knie-Leistungen, aber kein exakter Name.
    assert _resolve(_catalog(), name="MR Kniegelenk") is None


def test_no_substitute_without_the_right_side_entry() -> None:
    # Fehlt der rechte Kassen-Eintrag, springen links, bds. oder „je Seite“ auf
    # demselben Gerät nicht still als Ersatz ein.
    entries = [e for e in _catalog() if e["id"] != ID_MR]
    assert _resolve(entries) is None


def test_not_online_bookable_device_is_skipped() -> None:
    assert _resolve(_catalog(), device="PMR-SF") is None


@pytest.mark.parametrize("flag", ["active", "is_patient_online_bookable"])
def test_service_without_flag_is_skipped(flag: str) -> None:
    # Der Katalog führt auch Leistungen, die auf einem buchbaren Gerät stehen, aber
    # selbst nicht online buchbar oder nur aus dem Standardkatalog vererbt sind
    # (``service.active`` false); ohne Service-Filter würde ihr Datum still als
    # ``ok`` gemeldet.
    entries = _catalog()
    entries[0]["service"][flag] = False
    assert _resolve(entries) is None


def test_other_modality_is_skipped() -> None:
    assert _resolve(_catalog(), name="CT Knie rechts", device="PCCT") is None


@pytest.mark.parametrize("where", ["entry", "device"])
def test_inactive_entry_or_device_is_skipped(where: str) -> None:
    entries = _catalog()
    target = entries[0] if where == "entry" else entries[0]["device"]
    target["active"] = False
    assert _resolve(entries) is None


def test_entry_without_device_is_skipped() -> None:
    # Nur der Eintrag mit ``device: null`` trägt den Namen – kein Treffer, kein Crash.
    entries = [e for e in _catalog() if e["device"] is None]
    assert entries
    assert _resolve(entries) is None


def test_duplicate_match_is_catalog_drift() -> None:
    entries = _catalog()
    twin = {**entries[0], "id": "00000000-0000-4000-8000-aaaaaaaaaa09"}
    with pytest.raises(ValueError, match="catalog drift"):
        _resolve([*entries, twin])


@pytest.mark.parametrize("bad_id", [None, "", 7])
def test_match_without_string_id_is_error(bad_id) -> None:
    entries = _catalog()
    entries[0]["id"] = bad_id
    with pytest.raises(ValueError, match="string id"):
        _resolve(entries)


def test_forbidden_object_is_value_error_with_text() -> None:
    with pytest.raises(ValueError, match="not a JSON list.*forbidden"):
        resolve_service(_skeleton("forbidden.json"), NAME, DEVICE)


def test_missing_buffer_counts_as_zero() -> None:
    entries = _catalog()
    entries[0]["adjustable_buffer_time"] = None
    assert _resolve(entries).adjustable_buffer_time == 0


def test_empty_catalog_resolves_nothing() -> None:
    assert _resolve([]) is None


def test_slots_earliest_bookable_date() -> None:
    # 14.08. steht zuerst, 10.08. hat keine Uhrzeit: gewonnen hat der 11.08.
    result = parse_slots(_skeleton("slots.json"), ID_MR)
    assert result.status is Status.OK
    assert result.slot_date == date(2099, 8, 11)


def test_slots_earliest_across_several_lists() -> None:
    data = json.loads(_skeleton("slots.json"))
    data[0]["slots"].append(
        {
            "date_time_list": [
                {"on_date": "2099-08-09", "available_time_list": [{"time": "07:00"}]}
            ]
        }
    )
    assert parse_slots(json.dumps(data), ID_MR).slot_date == date(2099, 8, 9)


def test_slots_without_times_are_no_slots() -> None:
    result = parse_slots(_skeleton("slots_leer.json"), ID_MR)
    assert result.status is Status.NO_SLOTS
    assert result.slot_date is None


@pytest.mark.parametrize(
    "payload",
    [
        b"[]",  # leere Antwort ist kein leerer Kalender
        b"{not json",
        b"\xff\xfe",
    ],
)
def test_slots_broken_or_empty_response_is_parse_error(payload: bytes) -> None:
    assert parse_slots(payload, ID_MR).status is Status.ERROR_PARSE


def test_slots_forbidden_object_is_parse_error() -> None:
    assert parse_slots(_skeleton("forbidden.json"), ID_MR).status is Status.ERROR_PARSE


def test_slots_foreign_schedule_id_is_parse_error() -> None:
    other = "00000000-0000-4000-8000-aaaaaaaaaa02"
    assert parse_slots(_skeleton("slots.json"), other).status is Status.ERROR_PARSE


def test_slots_broken_date_raises() -> None:
    # Der Adapter fängt das als Parser-Ausnahme; hier nur: kein stilles Ergebnis.
    payload = _skeleton("slots.json").replace(b"2099-08-11", b"11.08.2099")
    with pytest.raises(ValueError):
        parse_slots(payload, ID_MR)


def test_accepts_str() -> None:
    text = _skeleton("slots.json").decode("utf-8")
    assert parse_slots(text, ID_MR).slot_date == date(2099, 8, 11)
