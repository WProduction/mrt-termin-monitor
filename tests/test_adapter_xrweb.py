# SPDX-License-Identifier: Apache-2.0
"""Tests des XR-WEB-Adapters: fetch gemockt (kein Netz), Antworten aus den Skeletten.

Geprüft werden URL-Bau, Archivierung vor dem Parse, Fehler-Isolation je Abfrage
und dass nur der Budget-Abbruch den Lauf beendet.
"""

from datetime import date, datetime
from pathlib import Path

import pytest

from mrt_termin_monitor.adapters import xrweb as adapter
from mrt_termin_monitor.fetch import http
from mrt_termin_monitor.model import Billing, Exam, Status
from mrt_termin_monitor.sites import Site

SKELETON = (Path(__file__).parent / "data" / "xrweb" / "termine.html").read_bytes()
RUN_START = datetime(2026, 8, 3, 8, 15)
BASE = "https://termine.example.at/AppointmentSearch/directAppointmentSearch"

# Die beiden URL-Fallen: Leerzeichen im Code und Site-Parameter. Zwei
# Untersuchungen, damit Reihenfolge und Fehler-Isolation prüfbar sind.
SITE = Site(
    slug="dz_beispiel",
    name="Diagnosezentrum Beispiel",
    adapter="xrweb",
    billing=Billing.COMBINED,
    params={"host": "termine.example.at", "site_param": "p", "day_table_columns": 2},
    exams={
        Exam.KNEE_RIGHT: {"code": "mknie re", "expected_title": "MR Kniegelenk"},
        Exam.LUMBAR_SPINE: {"code": "lws", "expected_title": "MR Kniegelenk"},
    },
)
URL_KNIE = f"{BASE}?exas=mknie%20re&Site=p"
URL_LWS = f"{BASE}?exas=lws&Site=p"


def _site(**changes) -> Site:
    fields = {**SITE.__dict__, **changes}
    return Site(**fields)


def _ok(url: str, **_kw) -> http.FetchResult:
    return http.FetchResult(url=url, status_code=200, content=SKELETON)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    """Ersetzt ``http.get`` durch einen Spion, der das Skelett liefert."""
    seen: list[tuple[str, dict]] = []

    def spy(url: str, **kw) -> http.FetchResult:
        seen.append((url, kw))
        return _ok(url)

    monkeypatch.setattr(http, "get", spy)
    return seen


def test_one_get_per_exam_and_rows_in_order(calls) -> None:
    rows = adapter.collect(SITE, RUN_START)
    assert [url for url, _ in calls] == [URL_KNIE, URL_LWS]
    assert [m.exam for m in rows] == [Exam.KNEE_RIGHT, Exam.LUMBAR_SPINE]
    for m in rows:
        assert m.status is Status.OK
        assert m.slot_date == date(2026, 8, 11)
        assert m.site_id == "dz_beispiel"
        assert m.site_name == "Diagnosezentrum Beispiel"
        assert m.billing is Billing.COMBINED
        assert m.run_start == RUN_START
        assert m.queried_at.utcoffset() is not None


def test_without_site_param_no_site_in_url(calls) -> None:
    params = {"host": "termine.example.at", "day_table_columns": 2}
    adapter.collect(_site(params=params), RUN_START)
    assert calls[0][0] == f"{BASE}?exas=mknie%20re"


def test_code_and_site_param_are_percent_encoded(calls) -> None:
    params = {**SITE.params, "site_param": "a&b"}
    exams = {Exam.KNEE_RIGHT: {"code": "k/r+1", "expected_title": "MR Knie"}}
    adapter.collect(_site(params=params, exams=exams), RUN_START)
    assert calls[0][0] == f"{BASE}?exas=k%2Fr%2B1&Site=a%26b"


def test_timeout_from_site_or_default(calls) -> None:
    adapter.collect(SITE, RUN_START)
    adapter.collect(_site(timeout_s=45), RUN_START)
    assert [kw["timeout"] for _, kw in calls] == [
        http.DEFAULT_TIMEOUT,
        http.DEFAULT_TIMEOUT,
        45,
        45,
    ]


def test_archive_receives_raw_bytes_before_parse(monkeypatch) -> None:
    order: list[str] = []
    archived: dict[str, bytes] = {}
    broken = b"<html>kaputt</html>"
    monkeypatch.setattr(
        http,
        "get",
        lambda url, **kw: http.FetchResult(url=url, status_code=500, content=broken),
    )
    real_parse = adapter.parse_xrweb.parse

    def parse(*args, **kw):
        order.append("parse")
        return real_parse(*args, **kw)

    def archive(name: str, content: bytes) -> None:
        order.append("archive")
        archived[name] = content

    monkeypatch.setattr(adapter.parse_xrweb, "parse", parse)
    rows = adapter.collect(SITE, RUN_START, archive=archive)
    # Auch eine kaputte Antwort liegt im Archiv – genau dann braucht man sie.
    assert [m.status for m in rows] == [Status.ERROR_PARSE, Status.ERROR_PARSE]
    assert order == ["archive", "parse", "archive", "parse"]
    assert archived == {
        "dz_beispiel_knee_right.html": broken,
        "dz_beispiel_lumbar_spine.html": broken,
    }


def test_archive_error_aborts(calls) -> None:
    def full(name: str, content: bytes) -> None:
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        adapter.collect(SITE, RUN_START, archive=full)


def test_title_and_columns_come_from_config_per_exam(calls) -> None:
    # Fehlverdrahtungen (Titel der ersten Untersuchung für alle, Spaltenzahl fest
    # 2, Code kleingeschrieben) würden die übrigen Tests bestehen.
    exams = {
        Exam.KNEE_RIGHT: {"code": "MKnie RE", "expected_title": "MR Kniegelenk"},
        Exam.LUMBAR_SPINE: {"code": "lws", "expected_title": "MR LWS"},
    }
    rows = adapter.collect(_site(exams=exams), RUN_START)
    assert calls[0][0] == f"{BASE}?exas=MKnie%20RE&Site=p"
    assert [m.status for m in rows] == [Status.OK, Status.ERROR_PARSE]
    params = {**SITE.params, "day_table_columns": 3}
    rows = adapter.collect(_site(params=params), RUN_START)
    assert all(m.status is Status.ERROR_PARSE for m in rows)


def test_fetch_error_is_isolated_per_exam(monkeypatch) -> None:
    def flaky(url: str, **kw) -> http.FetchResult:
        if "mknie" in url:
            raise http.FetchError("GET failed: timeout")
        return _ok(url)

    monkeypatch.setattr(http, "get", flaky)
    archived: list[str] = []
    rows = adapter.collect(SITE, RUN_START, archive=lambda n, c: archived.append(n))
    assert rows[0].status is Status.NOT_COLLECTED
    assert "timeout" in rows[0].note
    assert rows[1].status is Status.OK
    # Ohne Antwort gibt es nichts zu archivieren.
    assert archived == ["dz_beispiel_lumbar_spine.html"]


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


def test_forward_page_final_url_is_redirect_error(monkeypatch) -> None:
    final = "https://termine.example.at/EKOSAppointmentForward/ForwardPage?para=x"
    monkeypatch.setattr(
        http,
        "get",
        lambda url, **kw: http.FetchResult(url=final, status_code=200, content=b""),
    )
    rows = adapter.collect(SITE, RUN_START)
    assert all(m.status is Status.ERROR_REDIRECT for m in rows)
    assert all(m.slot_date is None for m in rows)
    assert all("no online booking" in m.note for m in rows)


def test_budget_exceeded_aborts(monkeypatch) -> None:
    def broke(url: str, **kw) -> http.FetchResult:
        raise http.BudgetExceededError("request budget exhausted")

    monkeypatch.setattr(http, "get", broke)
    with pytest.raises(http.BudgetExceededError):
        adapter.collect(SITE, RUN_START)


def test_parser_exception_is_parse_error(calls, monkeypatch) -> None:
    def boom(*args, **kw):
        raise ValueError("unexpected markup")

    monkeypatch.setattr(adapter.parse_xrweb, "parse", boom)
    rows = adapter.collect(SITE, RUN_START)
    assert all(m.status is Status.ERROR_PARSE for m in rows)
    assert "unexpected markup" in rows[0].note


def test_slot_before_run_day_is_parse_error(calls) -> None:
    # Skelett-Termin 11.08. liegt vor diesem Lauf-Tag: Fehlerzeile statt Abbruch
    # oder negativer Wartetage.
    rows = adapter.collect(SITE, datetime(2026, 9, 1, 8, 0))
    assert all(m.status is Status.ERROR_PARSE for m in rows)
    assert all(m.slot_date is None for m in rows)


def test_task_count_matches_gets(calls) -> None:
    adapter.collect(SITE, RUN_START)
    assert adapter.task_count(SITE) == len(calls) == 2
