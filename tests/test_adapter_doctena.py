# SPDX-License-Identifier: Apache-2.0
"""Tests des Doctena-Adapters: fetch gemockt (kein Netz), Antworten aus den Skeletten.

Geprüft werden URL-Bau mit Suchfenster, Referer, Archivierung vor dem Parse,
Fehler-Isolation je Abfrage und dass nur der Budget-Abbruch den Lauf beendet.
"""

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from mrt_termin_monitor.adapters import doctena as adapter
from mrt_termin_monitor.fetch import http
from mrt_termin_monitor.model import Billing, Exam, Status
from mrt_termin_monitor.sites import Site

DATA = Path(__file__).parent / "data" / "doctena"
SKELETON = (DATA / "termine.json").read_bytes()
EMPTY = (DATA / "leer.json").read_bytes()
# Jahr 2099 wie die Skelett-Termine: der Lauf-Tag liegt vor dem frühesten Slot.
RUN_START = datetime(2099, 8, 3, 8, 15)

SITE = Site(
    slug="doebling_beispiel",
    name="Ambulatorium Beispiel",
    adapter="doctena",
    billing=Billing.COMBINED,
    params={"doctor": 111},
    exams={Exam.KNEE_RIGHT: {"reason": 222}},
)


def _url(run_start: datetime, reason: int) -> str:
    # Erwartung zur Laufzeit aus dem lokalen Lauf-Tag berechnen: die Epoch-Werte
    # hängen von der Zeitzone der Maschine ab.
    start = int(datetime.combine(run_start.date(), datetime.min.time()).timestamp())
    end = start + 30 * 86400
    return (
        f"https://api.doctena.at/agendaSlot?from={start}&to={end}"
        f"&language=de&weight=front_search_change_date&doctor=111&reason={reason}"
    )


def _site(**changes) -> Site:
    fields = {**SITE.__dict__, **changes}
    return Site(**fields)


def _respond(content: bytes, status_code: int = 200):
    def get(url: str, **_kw) -> http.FetchResult:
        return http.FetchResult(url=url, status_code=status_code, content=content)

    return get


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    """Ersetzt ``http.get`` durch einen Spion, der das Skelett liefert."""
    seen: list[tuple[str, dict]] = []

    def spy(url: str, **kw) -> http.FetchResult:
        seen.append((url, kw))
        return http.FetchResult(url=url, status_code=200, content=SKELETON)

    monkeypatch.setattr(http, "get", spy)
    return seen


def test_one_get_with_window_and_referer(calls) -> None:
    rows = adapter.collect(SITE, RUN_START)
    assert [url for url, _ in calls] == [_url(RUN_START, 222)]
    assert calls[0][1]["extra_headers"] == {"Referer": "https://www.doctena.at/"}
    (m,) = rows
    assert m.status is Status.OK
    assert m.slot_date == date(2099, 8, 5)
    assert m.exam is Exam.KNEE_RIGHT
    assert m.billing is Billing.COMBINED
    assert m.site_id == "doebling_beispiel"
    assert m.site_name == "Ambulatorium Beispiel"
    assert m.run_start == RUN_START
    assert m.queried_at.utcoffset() is not None


def test_window_starts_at_local_midnight_of_run_day(calls) -> None:
    # Unabhängig von der URL-Erwartung in _url: from ist 00:00 lokal des
    # Lauf-Tags, nicht die Uhrzeit des Lauf-Starts und nicht „heute“.
    adapter.collect(SITE, RUN_START)
    query = dict(p.split("=") for p in calls[0][0].split("?")[1].split("&"))
    start = datetime.fromtimestamp(int(query["from"]))
    assert start == datetime(2099, 8, 3)
    assert int(query["to"]) - int(query["from"]) == timedelta(days=30).total_seconds()


def test_timeout_from_site_or_default(calls) -> None:
    adapter.collect(SITE, RUN_START)
    adapter.collect(_site(timeout_s=45), RUN_START)
    assert [kw["timeout"] for _, kw in calls] == [http.DEFAULT_TIMEOUT, 45]


@pytest.mark.parametrize("status_code", [200, 403])
def test_archive_receives_raw_bytes_before_parse(monkeypatch, status_code) -> None:
    order: list[str] = []
    archived: dict[str, bytes] = {}
    monkeypatch.setattr(http, "get", _respond(SKELETON, status_code))
    real_parse = adapter.parse_doctena.parse

    def parse(*args, **kw):
        order.append("parse")
        return real_parse(*args, **kw)

    def archive(name: str, content: bytes) -> None:
        order.append("archive")
        archived[name] = content

    monkeypatch.setattr(adapter.parse_doctena, "parse", parse)
    adapter.collect(SITE, RUN_START, archive=archive)
    # Auch die abgelehnte Antwort liegt im Archiv – genau dann braucht man sie.
    expected = ["archive", "parse"] if status_code == 200 else ["archive"]
    assert order == expected
    assert archived == {"doebling_beispiel_knee_right.json": SKELETON}


def test_archive_error_aborts(calls) -> None:
    def full(name: str, content: bytes) -> None:
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        adapter.collect(SITE, RUN_START, archive=full)


def test_http_error_status_is_parse_error(monkeypatch) -> None:
    monkeypatch.setattr(http, "get", _respond(b"<html>denied</html>", 403))
    (m,) = adapter.collect(SITE, RUN_START)
    assert m.status is Status.ERROR_PARSE
    assert "HTTP 403" in m.note
    assert m.slot_date is None


def test_empty_slot_list_is_no_slots_with_window_note(monkeypatch) -> None:
    monkeypatch.setattr(http, "get", _respond(EMPTY))
    (m,) = adapter.collect(SITE, RUN_START)
    assert m.status is Status.NO_SLOTS
    assert m.slot_date is None
    assert "30-day" in m.note


def test_fetch_error_is_not_collected_and_not_archived(monkeypatch) -> None:
    def broken(url: str, **kw) -> http.FetchResult:
        raise http.FetchError("GET failed: timeout")

    monkeypatch.setattr(http, "get", broken)
    archived: list[str] = []
    (m,) = adapter.collect(SITE, RUN_START, archive=lambda n, c: archived.append(n))
    assert m.status is Status.NOT_COLLECTED
    assert "timeout" in m.note
    # Ohne Antwort gibt es nichts zu archivieren.
    assert archived == []


def test_blocked_host_is_not_collected(monkeypatch) -> None:
    def blocked(url: str, **kw) -> http.FetchResult:
        raise http.BlockedHostError("host is blocked")

    monkeypatch.setattr(http, "get", blocked)
    (m,) = adapter.collect(SITE, RUN_START)
    assert m.status is Status.NOT_COLLECTED


def test_cross_host_redirect_is_redirect_error(monkeypatch) -> None:
    def redirect(url: str, **kw) -> http.FetchResult:
        raise http.CrossHostRedirectError("redirect to foreign host refused")

    monkeypatch.setattr(http, "get", redirect)
    (m,) = adapter.collect(SITE, RUN_START)
    assert m.status is Status.ERROR_REDIRECT
    assert "foreign host" in m.note


def test_budget_exceeded_aborts(monkeypatch) -> None:
    def broke(url: str, **kw) -> http.FetchResult:
        raise http.BudgetExceededError("request budget exhausted")

    monkeypatch.setattr(http, "get", broke)
    with pytest.raises(http.BudgetExceededError):
        adapter.collect(SITE, RUN_START)


def test_parser_exception_is_parse_error(calls, monkeypatch) -> None:
    def boom(*args, **kw):
        raise RuntimeError("unexpected payload")

    monkeypatch.setattr(adapter.parse_doctena, "parse", boom)
    (m,) = adapter.collect(SITE, RUN_START)
    assert m.status is Status.ERROR_PARSE
    assert "parser exception" in m.note
    assert "unexpected payload" in m.note


def test_slot_before_run_day_is_parse_error(calls) -> None:
    # Skelett-Termin 05.08. liegt vor diesem Lauf-Tag: Fehlerzeile statt Abbruch
    # oder negativer Wartetage.
    (m,) = adapter.collect(SITE, datetime(2099, 9, 1, 8, 0))
    assert m.status is Status.ERROR_PARSE
    assert m.slot_date is None


def test_reason_per_exam_and_task_count_matches_gets(calls) -> None:
    exams = {
        Exam.KNEE_RIGHT: {"reason": 222},
        Exam.LUMBAR_SPINE: {"reason": 333},
    }
    site = _site(exams=exams)
    rows = adapter.collect(site, RUN_START)
    assert [url for url, _ in calls] == [_url(RUN_START, 222), _url(RUN_START, 333)]
    assert [m.exam for m in rows] == [Exam.KNEE_RIGHT, Exam.LUMBAR_SPINE]
    assert adapter.task_count(site) == len(calls) == 2
