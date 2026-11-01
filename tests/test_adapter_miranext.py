# SPDX-License-Identifier: Apache-2.0
"""Tests des MiraNext-Adapters: fetch gemockt (kein Netz), Antworten aus den Skeletten.

Geprüft werden URL-Bau beider GETs, die festen Header (ohne Zugangsdaten),
Archivierung vor dem Parse, Fehler-Isolation je Schritt und dass nur der
Budget-Abbruch den Lauf beendet.
"""

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from mrt_termin_monitor.adapters import miranext as adapter
from mrt_termin_monitor.fetch import http
from mrt_termin_monitor.model import Billing, Exam, Status
from mrt_termin_monitor.sites import Site

DATA = Path(__file__).parent / "data" / "miranext"
SERVICES = (DATA / "service_assignments.json").read_bytes()
SLOTS = (DATA / "slots.json").read_bytes()
FORBIDDEN = (DATA / "forbidden.json").read_bytes()
# Uhr-Falle: Skelett-Termine liegen im Jahr 2099, damit kein Test mit der echten
# Uhr altert.
RUN_START = datetime(2099, 8, 3, 8, 15)
ID_MR = "00000000-0000-4000-8000-aaaaaaaaaa01"
API = "https://patient-portal.miranext.ai/api/booking"

SITE = Site(
    slug="mn_beispiel",
    name="Radiologie Beispiel",
    adapter="miranext",
    billing=Billing.PUBLIC,
    params={"portal_id": 3, "device": "MR"},
    exams={
        Exam.KNEE_RIGHT: {
            "search": "Knie gelenk",  # Leerzeichen: muss percent-encodet werden
            "service_name": "MR Kniegelenk rechts",
            "expected_id": ID_MR,
        }
    },
)
URL_SERVICES = f"{API}/service-assignments?c_Id=3&search=Knie%20gelenk"


def _site(**changes) -> Site:
    return Site(**{**SITE.__dict__, **changes})


def _slots_url(assignment_id: str, start: date) -> str:
    return (
        f"{API}/slot/get_available_time_list_with_date?c_Id=3"
        f"&schedules_list=%5B%22{assignment_id}%22%5D&adjustable_buffer_time=0"
        "&contrast_fluid=false&request_type=normal"
        "&billing_private=false&billing_public=true&online_booking=true"
        f"&start_date={start}&end_date={start + timedelta(days=90)}"
    )


def _answer(services: bytes = SERVICES, slots: bytes = SLOTS, status: int = 200):
    """Spion-Antwort je URL-Pfad: Katalog oder Slots."""

    def answer(url: str) -> http.FetchResult:
        content = services if "/service-assignments" in url else slots
        return http.FetchResult(url=url, status_code=status, content=content)

    return answer


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch):
    """Ersetzt ``http.get``; ``spy.answer`` ist austauschbar, ``spy.calls`` protokolliert."""

    state = SimpleNamespace(calls=[], answer=_answer())

    def get(url: str, **kw) -> http.FetchResult:
        state.calls.append((url, kw))
        return state.answer(url)

    monkeypatch.setattr(http, "get", get)
    return state


def test_two_gets_in_order_and_one_ok_row(spy) -> None:
    before = date.today()
    rows = adapter.collect(SITE, RUN_START)
    after = date.today()
    urls = [url for url, _ in spy.calls]
    assert urls[0] == URL_SERVICES
    # Datumsfenster ab heute; um Mitternacht darf der Tag dazwischen wechseln.
    assert urls[1] in {_slots_url(ID_MR, before), _slots_url(ID_MR, after)}
    assert len(urls) == 2
    [m] = rows
    assert m.exam is Exam.KNEE_RIGHT
    assert m.billing is Billing.PUBLIC
    assert m.status is Status.OK
    assert m.slot_date == date(2099, 8, 11)
    assert m.note == ""
    assert m.site_id == "mn_beispiel"
    assert m.run_start == RUN_START
    assert m.queried_at.utcoffset() is not None


def test_headers_referer_origin_without_credentials(spy) -> None:
    adapter.collect(SITE, RUN_START)
    for _, kw in spy.calls:
        headers = kw["extra_headers"]
        assert headers == {
            "Referer": "https://patient-portal.miranext.ai/",
            "Origin": "https://patient-portal.miranext.ai",
            "Accept": "application/json",
        }
        # Es gibt keinen Schlüssel; ein Token-Header wäre ein Fehler.
        assert not {k.lower() for k in headers} & {"authorization", "cookie"}


def test_only_cash_pool_is_queried(spy) -> None:
    adapter.collect(SITE, RUN_START)
    assert all("billing_private=true" not in url for url, _ in spy.calls)


def test_buffer_from_catalog_goes_into_slot_url(spy) -> None:
    # Gerät PMR-S hat im Skelett Buffer 5 und eine eigene ID.
    other = "00000000-0000-4000-8000-aaaaaaaaaa02"
    params = {"portal_id": 3, "device": "PMR-S"}
    exams = {Exam.KNEE_RIGHT: {**SITE.exams[Exam.KNEE_RIGHT], "expected_id": other}}
    adapter.collect(_site(params=params, exams=exams), RUN_START)
    assert "adjustable_buffer_time=5" in spy.calls[1][0]
    assert f"%5B%22{other}%22%5D" in spy.calls[1][0]


def test_timeout_from_site_or_default(spy) -> None:
    adapter.collect(SITE, RUN_START)
    adapter.collect(_site(timeout_s=45), RUN_START)
    assert [kw["timeout"] for _, kw in spy.calls] == [
        http.DEFAULT_TIMEOUT,
        http.DEFAULT_TIMEOUT,
        45,
        45,
    ]


def test_archive_before_each_parse(spy, monkeypatch) -> None:
    order: list[str] = []
    archived: dict[str, bytes] = {}
    real_resolve = adapter.parse_miranext.resolve_service
    real_slots = adapter.parse_miranext.parse_slots

    def resolve(*args, **kw):
        order.append("resolve")
        return real_resolve(*args, **kw)

    def slots(*args, **kw):
        order.append("parse")
        return real_slots(*args, **kw)

    def archive(name: str, content: bytes) -> None:
        order.append(f"archive {name}")
        archived[name] = content

    monkeypatch.setattr(adapter.parse_miranext, "resolve_service", resolve)
    monkeypatch.setattr(adapter.parse_miranext, "parse_slots", slots)
    adapter.collect(SITE, RUN_START, archive=archive)
    assert order == [
        "archive mn_beispiel_knee_right_services.json",
        "resolve",
        "archive mn_beispiel_knee_right.json",
        "parse",
    ]
    assert archived == {
        "mn_beispiel_knee_right_services.json": SERVICES,
        "mn_beispiel_knee_right.json": SLOTS,
    }


def test_archive_error_aborts(spy) -> None:
    def full(name: str, content: bytes) -> None:
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        adapter.collect(SITE, RUN_START, archive=full)


def test_services_fetch_error_is_not_collected_without_slot_get(spy) -> None:
    def fail(url: str) -> http.FetchResult:
        raise http.FetchError("GET failed: timeout")

    spy.answer = fail
    archived: list[str] = []
    [m] = adapter.collect(SITE, RUN_START, archive=lambda n, c: archived.append(n))
    assert m.status is Status.NOT_COLLECTED
    assert "timeout" in m.note
    assert len(spy.calls) == 1
    assert archived == []


def test_forbidden_catalog_is_parse_error_with_status(spy) -> None:
    spy.answer = _answer(services=FORBIDDEN, status=403)
    archived: list[str] = []
    [m] = adapter.collect(SITE, RUN_START, archive=lambda n, c: archived.append(n))
    assert m.status is Status.ERROR_PARSE
    assert "HTTP 403" in m.note
    assert "forbidden" in m.note
    # Die Fehlerantwort liegt im Archiv; ohne Zuordnung keine Slot-Abfrage.
    assert archived == ["mn_beispiel_knee_right_services.json"]
    assert len(spy.calls) == 1


def test_no_matching_assignment_is_parse_error_without_slot_get(spy) -> None:
    spy.answer = _answer(services=b"[]")
    [m] = adapter.collect(SITE, RUN_START)
    assert m.status is Status.ERROR_PARSE
    assert "no service assignment 'MR Kniegelenk rechts'" in m.note
    assert len(spy.calls) == 1


def test_id_drift_warns_and_measures_with_resolved_id(spy, caplog) -> None:
    expected = "00000000-0000-4000-8000-bbbbbbbbbb99"
    exams = {Exam.KNEE_RIGHT: {**SITE.exams[Exam.KNEE_RIGHT], "expected_id": expected}}
    with caplog.at_level(logging.DEBUG, logger=adapter.__name__):
        [m] = adapter.collect(_site(exams=exams), RUN_START)
    assert m.status is Status.OK
    assert "service id drift" in m.note
    assert expected in m.note
    assert ID_MR in m.note
    assert f"%5B%22{ID_MR}%22%5D" in spy.calls[1][0]
    # Nur im Log (DEBUG), nie auf der Konsole (INFO): der Text ist englisch.
    [record] = [r for r in caplog.records if "service id drift" in r.getMessage()]
    assert record.levelno == logging.DEBUG


def test_drift_note_keeps_the_error_reason(spy) -> None:
    exams = {Exam.KNEE_RIGHT: {**SITE.exams[Exam.KNEE_RIGHT], "expected_id": "x"}}
    spy.answer = _answer(slots=FORBIDDEN, status=403)
    [m] = adapter.collect(_site(exams=exams), RUN_START)
    assert m.status is Status.ERROR_PARSE
    assert "service id drift" in m.note
    assert "unexpected slot response (HTTP 403)" in m.note


def test_slot_error_object_is_parse_error_with_status(spy) -> None:
    spy.answer = _answer(slots=b'{"detail": []}', status=422)
    [m] = adapter.collect(SITE, RUN_START)
    assert m.status is Status.ERROR_PARSE
    assert m.note == "unexpected slot response (HTTP 422)"


def test_slot_fetch_error_is_not_collected(spy) -> None:
    def answer(url: str) -> http.FetchResult:
        if "/slot/" in url:
            raise http.FetchError("GET failed: timeout")
        return _answer()(url)

    spy.answer = answer
    [m] = adapter.collect(SITE, RUN_START)
    assert m.status is Status.NOT_COLLECTED
    assert "timeout" in m.note


@pytest.mark.parametrize("step", ["/service-assignments", "/slot/"])
def test_cross_host_redirect_is_redirect_error(spy, step: str) -> None:
    def answer(url: str) -> http.FetchResult:
        if step in url:
            raise http.CrossHostRedirectError("redirect to foreign host refused")
        return _answer()(url)

    spy.answer = answer
    [m] = adapter.collect(SITE, RUN_START)
    assert m.status is Status.ERROR_REDIRECT
    assert "foreign host" in m.note


def test_blocked_host_is_not_collected(spy) -> None:
    def blocked(url: str) -> http.FetchResult:
        raise http.BlockedHostError("host is blocked")

    spy.answer = blocked
    [m] = adapter.collect(SITE, RUN_START)
    assert m.status is Status.NOT_COLLECTED


@pytest.mark.parametrize("step", ["/service-assignments", "/slot/"])
def test_budget_exceeded_aborts(spy, step: str) -> None:
    def answer(url: str) -> http.FetchResult:
        if step in url:
            raise http.BudgetExceededError("request budget exhausted")
        return _answer()(url)

    spy.answer = answer
    with pytest.raises(http.BudgetExceededError):
        adapter.collect(SITE, RUN_START)


def test_parser_exception_is_parse_error(spy, monkeypatch) -> None:
    def boom(*args, **kw):
        raise KeyError("on_date")

    monkeypatch.setattr(adapter.parse_miranext, "parse_slots", boom)
    [m] = adapter.collect(SITE, RUN_START)
    assert m.status is Status.ERROR_PARSE
    assert m.note.startswith("parser exception:")


def test_slot_before_run_day_is_parse_error(spy) -> None:
    # Skelett-Termin 11.08.2099 liegt vor diesem Lauf-Tag: Fehlerzeile statt
    # Abbruch oder negativer Wartetage.
    [m] = adapter.collect(SITE, datetime(2099, 9, 1, 8, 0))
    assert m.status is Status.ERROR_PARSE
    assert m.slot_date is None


def test_rows_per_exam_in_order(spy) -> None:
    knee = SITE.exams[Exam.KNEE_RIGHT]
    exams = {Exam.KNEE_RIGHT: knee, Exam.LUMBAR_SPINE: {**knee, "search": "LWS"}}
    rows = adapter.collect(_site(exams=exams), RUN_START)
    assert [m.exam for m in rows] == [Exam.KNEE_RIGHT, Exam.LUMBAR_SPINE]
    assert len(spy.calls) == 4
    assert spy.calls[2][0].endswith("search=LWS")


def test_task_count_matches_gets(spy) -> None:
    adapter.collect(SITE, RUN_START)
    assert adapter.task_count(SITE) == len(spy.calls) == 2
