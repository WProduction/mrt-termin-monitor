# SPDX-License-Identifier: Apache-2.0
"""Tests des klinix-Adapters: fetch gemockt (kein Netz), Antworten handgebaut.

Geprüft werden URL-Bau, Archivierung vor der Auswertung, dass weder ein
HTTP-Fehlerstatus noch eine fremde Antwortform still zu „keine Termine“ wird,
Fehler-Isolation je Abfrage und dass nur der Budget-Abbruch den Lauf beendet.
"""

from datetime import date, datetime
from pathlib import Path

import pytest

from mrt_termin_monitor.adapters import klinix as adapter
from mrt_termin_monitor.fetch import http
from mrt_termin_monitor.model import Billing, Exam, Status
from mrt_termin_monitor.sites import Site

# Termin im Jahr 2099: liegt nach jedem denkbaren Lauf-Tag, auch wenn ein Test
# die echte Uhr statt RUN_START sieht.
SKELETON = (Path(__file__).parent / "data" / "klinix" / "termin.json").read_bytes()
RUN_START = datetime(2026, 8, 3, 8, 15)
BASE = (
    "https://termine.example.at/services/klinixservice/api/public"
    "/appointment-slot/first-available-slot-time"
)

# Zwei Untersuchungen, damit Reihenfolge und Fehler-Isolation prüfbar sind.
SITE = Site(
    slug="dz_beispiel",
    name="Diagnosezentrum Beispiel",
    adapter="klinix",
    billing=Billing.COMBINED,
    params={"host": "termine.example.at"},
    exams={
        Exam.KNEE_RIGHT: {"code": "mknr"},
        Exam.LUMBAR_SPINE: {"code": "lws"},
    },
)
URL_KNIE = f"{BASE}?exas=mknr"
URL_LWS = f"{BASE}?exas=lws"


def _site(**changes) -> Site:
    fields = {**SITE.__dict__, **changes}
    return Site(**fields)


def _answer(content: bytes, status_code: int = 200):
    """``http.get``-Ersatz, der für jede URL dieselbe Antwort liefert."""

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


def test_one_get_per_exam_and_rows_in_order(calls) -> None:
    rows = adapter.collect(SITE, RUN_START)
    assert [url for url, _ in calls] == [URL_KNIE, URL_LWS]
    assert [m.exam for m in rows] == [Exam.KNEE_RIGHT, Exam.LUMBAR_SPINE]
    for m in rows:
        assert m.status is Status.OK
        assert m.slot_date == date(2099, 1, 15)
        assert m.note == ""
        assert m.site_id == "dz_beispiel"
        assert m.site_name == "Diagnosezentrum Beispiel"
        assert m.billing is Billing.COMBINED
        assert m.run_start == RUN_START
        assert m.queried_at.utcoffset() is not None


@pytest.mark.parametrize("content", [b"", b"  \n", b"null", b'""'])
def test_empty_answer_is_no_slots_with_caveat(monkeypatch, content: bytes) -> None:
    monkeypatch.setattr(http, "get", _answer(content))
    rows = adapter.collect(SITE, RUN_START)
    assert all(m.status is Status.NO_SLOTS for m in rows)
    assert all(m.slot_date is None for m in rows)
    # Der Vorbehalt „Code evtl. unbekannt“ muss in jeder solchen Zeile stehen.
    assert all("exas" in m.note for m in rows)


@pytest.mark.parametrize(
    "content",
    [
        b"0",
        b"false",
        b"[]",
        b"{}",
        b'"next week"',
        b"<html>maintenance</html>",
        b"\xff\xfe",
    ],
)
def test_foreign_answer_is_parse_error(monkeypatch, content: bytes) -> None:
    # Strenger als „falsy = kein Termin“: eine geänderte Schnittstelle muss auffallen.
    monkeypatch.setattr(http, "get", _answer(content))
    rows = adapter.collect(SITE, RUN_START)
    assert all(m.status is Status.ERROR_PARSE for m in rows)
    assert all(m.note.startswith("parser exception:") for m in rows)


def test_timestamp_with_offset_uses_date_part(monkeypatch) -> None:
    monkeypatch.setattr(http, "get", _answer(b'"2099-03-02T16:30:00+01:00"'))
    rows = adapter.collect(SITE, RUN_START)
    assert [m.slot_date for m in rows] == [date(2099, 3, 2)] * 2


@pytest.mark.parametrize("status_code", [503, 404, 302, 199])
def test_non_2xx_is_error_never_no_slots(monkeypatch, status_code: int) -> None:
    # Leerer Body bei Fehlerstatus sähe ungeprüft genau wie „kein Termin“ aus.
    monkeypatch.setattr(http, "get", _answer(b"", status_code))
    archived: list[str] = []
    rows = adapter.collect(SITE, RUN_START, archive=lambda n, c: archived.append(n))
    assert all(m.status is Status.ERROR_PARSE for m in rows)
    assert rows[0].note == f"HTTP {status_code} from termine.example.at"
    # Auch die Fehlerantwort liegt im Archiv.
    assert archived == ["dz_beispiel_knee_right.json", "dz_beispiel_lumbar_spine.json"]


def test_2xx_other_than_200_is_evaluated(monkeypatch) -> None:
    monkeypatch.setattr(http, "get", _answer(b"", 204))
    rows = adapter.collect(SITE, RUN_START)
    assert all(m.status is Status.NO_SLOTS for m in rows)


def test_archive_receives_raw_bytes_before_parse(monkeypatch) -> None:
    order: list[str] = []
    archived: dict[str, bytes] = {}
    broken = b"<html>kaputt</html>"
    monkeypatch.setattr(http, "get", _answer(broken))
    real_slot_date = adapter._slot_date

    def slot_date(content: bytes):
        order.append("parse")
        return real_slot_date(content)

    def archive(name: str, content: bytes) -> None:
        order.append("archive")
        archived[name] = content

    monkeypatch.setattr(adapter, "_slot_date", slot_date)
    rows = adapter.collect(SITE, RUN_START, archive=archive)
    # Auch eine kaputte Antwort liegt im Archiv – genau dann braucht man sie.
    assert [m.status for m in rows] == [Status.ERROR_PARSE, Status.ERROR_PARSE]
    assert order == ["archive", "parse", "archive", "parse"]
    assert archived == {
        "dz_beispiel_knee_right.json": broken,
        "dz_beispiel_lumbar_spine.json": broken,
    }


def test_archive_error_aborts(calls) -> None:
    def full(name: str, content: bytes) -> None:
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        adapter.collect(SITE, RUN_START, archive=full)


def test_code_is_percent_encoded_and_case_kept(calls) -> None:
    exams = {Exam.KNEE_RIGHT: {"code": "k/r+1"}, Exam.LUMBAR_SPINE: {"code": "MKNR"}}
    adapter.collect(_site(exams=exams), RUN_START)
    assert [url for url, _ in calls] == [f"{BASE}?exas=k%2Fr%2B1", f"{BASE}?exas=MKNR"]


def test_timeout_from_site_or_default(calls) -> None:
    adapter.collect(SITE, RUN_START)
    adapter.collect(_site(timeout_s=45), RUN_START)
    assert [kw["timeout"] for _, kw in calls] == [
        http.DEFAULT_TIMEOUT,
        http.DEFAULT_TIMEOUT,
        45,
        45,
    ]


def test_fetch_error_is_isolated_per_exam(monkeypatch) -> None:
    def flaky(url: str, **kw) -> http.FetchResult:
        if "mknr" in url:
            raise http.FetchError("GET failed: timeout")
        return http.FetchResult(url=url, status_code=200, content=SKELETON)

    monkeypatch.setattr(http, "get", flaky)
    archived: list[str] = []
    rows = adapter.collect(SITE, RUN_START, archive=lambda n, c: archived.append(n))
    assert rows[0].status is Status.NOT_COLLECTED
    assert "timeout" in rows[0].note
    assert rows[1].status is Status.OK
    # Ohne Antwort gibt es nichts zu archivieren.
    assert archived == ["dz_beispiel_lumbar_spine.json"]


def test_blocked_host_is_not_collected(monkeypatch) -> None:
    def blocked(url: str, **kw) -> http.FetchResult:
        raise http.BlockedHostError("host is blocked")

    monkeypatch.setattr(http, "get", blocked)
    rows = adapter.collect(SITE, RUN_START)
    assert all(m.status is Status.NOT_COLLECTED for m in rows)


def test_cross_host_redirect_is_redirect_error(monkeypatch) -> None:
    def redirect(url: str, **kw) -> http.FetchResult:
        raise http.CrossHostRedirectError("redirect to foreign host refused")

    monkeypatch.setattr(http, "get", redirect)
    rows = adapter.collect(SITE, RUN_START)
    assert all(m.status is Status.ERROR_REDIRECT for m in rows)
    assert "foreign host" in rows[0].note


def test_budget_exceeded_aborts(monkeypatch) -> None:
    def broke(url: str, **kw) -> http.FetchResult:
        raise http.BudgetExceededError("request budget exhausted")

    monkeypatch.setattr(http, "get", broke)
    with pytest.raises(http.BudgetExceededError):
        adapter.collect(SITE, RUN_START)


def test_slot_before_run_day_is_parse_error(calls) -> None:
    # Skelett-Termin 15.01.2099 liegt vor diesem Lauf-Tag: Fehlerzeile statt
    # Abbruch oder negativer Wartetage.
    rows = adapter.collect(SITE, datetime(2099, 2, 1, 8, 0))
    assert all(m.status is Status.ERROR_PARSE for m in rows)
    assert all(m.slot_date is None for m in rows)


def test_task_count_matches_gets(calls) -> None:
    adapter.collect(SITE, RUN_START)
    assert adapter.task_count(SITE) == len(calls) == 2
