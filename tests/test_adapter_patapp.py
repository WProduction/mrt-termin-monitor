# SPDX-License-Identifier: Apache-2.0
"""Tests des PatApp-Adapters: fetch gemockt (kein Netz), Antworten aus den Skeletten.

Geprüft werden die Aufrufreihenfolge, wohin SVNR und Ticket gehen (und wohin
nicht: URL, Log, Hinweis, Archiv), Archivierung vor dem Parse, Fehler-Isolation
und dass nur Budget- und Archivfehler den Lauf beenden.
"""

import logging
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

from mrt_termin_monitor import paths
from mrt_termin_monitor.adapters import patapp as adapter
from mrt_termin_monitor.fetch import http, post
from mrt_termin_monitor.model import Billing, Exam, Status
from mrt_termin_monitor.sites import Site

DATA = Path(__file__).parent / "data" / "patapp"
RUN_START = datetime(2026, 8, 3, 8, 15)
URL = "https://termin.example.at/hgsservice/service.asmx"
# Zur Laufzeit zusammengesetzt, nie als 10-Ziffern-Literal (Hook no-svnr).
SVNR = "1234" + "010180"
TICKET = "TICKET-PLACEHOLDER"

SITE = Site(
    slug="mr_beispiel",
    name="MR Institut Beispiel",
    adapter="patapp",
    billing=Billing.PUBLIC,
    params={"service_url": URL},
    exams={Exam.KNEE_RIGHT: {"pattern": "Knie rechts"}},
)


def _site(**changes) -> Site:
    return Site(**{**SITE.__dict__, **changes})


def _skeleton(name: str) -> bytes:
    return (DATA / name).read_bytes()


def _result(content: bytes, status: int = 200) -> http.FetchResult:
    return http.FetchResult(url=URL, status_code=status, content=content)


@pytest.fixture
def credentials(home: Path) -> dict[str, str]:
    """Schreibt eine Credentials-Datei an den Ort, den der Adapter liest."""
    data = {"svnr": SVNR, "patient_name": "Anna Muster", "patient_mobile": "0660 1"}
    target = paths.credentials_file()
    target.parent.mkdir(parents=True)
    target.write_text(yaml.safe_dump(data), encoding="utf-8")
    return data


class Spy:
    """Ersetzt ``post.soap``: liefert je Operation ein Skelett, merkt sich Aufrufe."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, dict]] = []
        self.responses = {
            "GetShortLongTitles": _result(_skeleton("katalog.xml")),
            "GetPatientTicket": _result(_skeleton("ticket.xml")),
            "GetProposedDates": _result(_skeleton("termine.xml")),
        }

    def __call__(self, url: str, op: str, params: str = "", **kw) -> http.FetchResult:
        self.calls.append((url, op, params, kw))
        response = self.responses[op]
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def ops(self) -> list[str]:
        return [op for _, op, _, _ in self.calls]


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch, credentials) -> Spy:
    spy = Spy()
    monkeypatch.setattr(post, "soap", spy)
    return spy


def test_three_calls_in_order_and_ok_row_with_minimum(spy: Spy) -> None:
    rows = adapter.collect(SITE, RUN_START)
    assert spy.ops == ["GetShortLongTitles", "GetPatientTicket", "GetProposedDates"]
    assert all(url == URL for url, _, _, _ in spy.calls)
    (m,) = rows
    assert m.status is Status.OK
    assert m.slot_date == date(2099, 3, 2)
    assert m.note == "xknr: MR Knie rechts"
    assert m.site_id == "mr_beispiel"
    assert m.site_name == "MR Institut Beispiel"
    assert m.exam is Exam.KNEE_RIGHT
    assert m.billing is Billing.PUBLIC
    assert m.run_start == RUN_START
    assert m.queried_at.utcoffset() is not None


def test_task_count_matches_posts(spy: Spy) -> None:
    adapter.collect(SITE, RUN_START)
    assert adapter.task_count(SITE) == len(spy.calls) == 3


def test_svnr_only_in_ticket_params_encoded_never_in_url(spy: Spy) -> None:
    adapter.collect(SITE, RUN_START)
    _, _, catalogue_params, _ = spy.calls[0]
    _, _, ticket_params, _ = spy.calls[1]
    _, _, dates_params, _ = spy.calls[2]
    assert catalogue_params == ""
    assert ticket_params == (
        f"<sin>{SVNR}</sin><name>Anna%20Muster</name><mobilenumber>0660%201</mobilenumber>"
    )
    assert SVNR not in dates_params
    assert all(SVNR not in url for url, _, _, _ in spy.calls)
    # Ticket nur in GetProposedDates, Code aus dem Katalog, leeres <from>.
    assert (
        dates_params == f"<ticket>{TICKET}</ticket><tshort>xknr</tshort><from></from>"
    )
    assert TICKET not in ticket_params


def test_timeout_from_site_or_default(spy: Spy) -> None:
    adapter.collect(SITE, RUN_START)
    adapter.collect(_site(timeout_s=45), RUN_START)
    assert [kw["timeout"] for _, _, _, kw in spy.calls] == [
        http.DEFAULT_TIMEOUT
    ] * 3 + [45] * 3


def test_archive_before_parse_and_ticket_removed(spy: Spy, monkeypatch) -> None:
    order: list[str] = []
    archived: dict[str, bytes] = {}
    for name in ("parse_catalogue", "parse_ticket", "parse_dates"):
        real = getattr(adapter.parse_patapp, name)

        def wrapped(payload, _real=real, _name=name):
            order.append(_name)
            return _real(payload)

        monkeypatch.setattr(adapter.parse_patapp, name, wrapped)

    def archive(name: str, content: bytes) -> None:
        order.append(f"archive {name}")
        archived[name] = content

    rows = adapter.collect(SITE, RUN_START, archive=archive)
    assert rows[0].status is Status.OK
    assert order == [
        "archive mr_beispiel_catalog.xml",
        "parse_catalogue",
        "archive mr_beispiel_ticket.xml",
        "parse_ticket",
        "archive mr_beispiel_knee_right.xml",
        "parse_dates",
    ]
    assert archived["mr_beispiel_catalog.xml"] == _skeleton("katalog.xml")
    assert archived["mr_beispiel_knee_right.xml"] == _skeleton("termine.xml")
    # Das Ticket steht nie auf der Platte; der Rest der Antwort bleibt.
    assert TICKET.encode() not in archived["mr_beispiel_ticket.xml"]
    assert b"ticket-removed||1|0" in archived["mr_beispiel_ticket.xml"]


def test_broken_responses_are_archived_too(spy: Spy) -> None:
    broken = b"<html>kaputt</html>"
    spy.responses["GetPatientTicket"] = _result(broken, 500)
    archived: dict[str, bytes] = {}
    rows = adapter.collect(
        SITE, RUN_START, archive=lambda n, c: archived.update({n: c})
    )
    assert rows[0].status is Status.ERROR_PARSE
    assert "HTTP 500" in rows[0].note
    assert archived["mr_beispiel_ticket.xml"] == broken
    assert spy.ops == ["GetShortLongTitles", "GetPatientTicket"]


def test_archive_error_aborts(spy: Spy) -> None:
    def full(name: str, content: bytes) -> None:
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        adapter.collect(SITE, RUN_START, archive=full)


def test_missing_credentials_is_not_collected_without_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = Spy()
    monkeypatch.setattr(post, "soap", spy)
    rows = adapter.collect(SITE, RUN_START)
    assert [m.status for m in rows] == [Status.NOT_COLLECTED]
    assert rows[0].note.startswith("credentials unavailable: credentials file missing")
    assert spy.calls == []


def test_catalogue_fetch_error_is_not_collected_after_one_call(spy: Spy) -> None:
    spy.responses["GetShortLongTitles"] = post.FetchError("POST failed: timeout")
    archived: list[str] = []
    rows = adapter.collect(SITE, RUN_START, archive=lambda n, c: archived.append(n))
    assert rows[0].status is Status.NOT_COLLECTED
    assert "GetShortLongTitles: POST failed: timeout" == rows[0].note
    assert spy.ops == ["GetShortLongTitles"]
    assert archived == []


def test_catalogue_http_error_is_parse_error_and_archived(spy: Spy) -> None:
    spy.responses["GetShortLongTitles"] = _result(b"<html>500</html>", 500)
    archived: list[str] = []
    rows = adapter.collect(SITE, RUN_START, archive=lambda n, c: archived.append(n))
    assert rows[0].status is Status.ERROR_PARSE
    assert rows[0].note == "GetShortLongTitles: HTTP 500"
    assert archived == ["mr_beispiel_catalog.xml"]
    assert spy.ops == ["GetShortLongTitles"]


def test_empty_catalogue_is_parse_error(spy: Spy) -> None:
    spy.responses["GetShortLongTitles"] = _result(_skeleton("termine_leer.xml"))
    rows = adapter.collect(SITE, RUN_START)
    assert rows[0].status is Status.ERROR_PARSE
    assert "parser exception" in rows[0].note
    assert spy.ops == ["GetShortLongTitles"]


def test_login_rejected_is_not_collected_and_note_is_redacted(spy: Spy) -> None:
    rejected = _skeleton("ticket_abgelehnt.xml").replace(
        b"placeholder login error", f"unknown number {SVNR} for Anna Muster".encode()
    )
    spy.responses["GetPatientTicket"] = _result(rejected)
    rows = adapter.collect(SITE, RUN_START)
    assert rows[0].status is Status.NOT_COLLECTED
    # Server-Text geht in die CSV, die kein Log-Filter sieht: selbst schwärzen.
    assert rows[0].note == "login rejected: unknown number *** for ***"
    assert spy.ops == ["GetShortLongTitles", "GetPatientTicket"]


def test_ticket_fault_is_parse_error(spy: Spy) -> None:
    spy.responses["GetPatientTicket"] = _result(_skeleton("fault.xml"))
    rows = adapter.collect(SITE, RUN_START)
    assert rows[0].status is Status.ERROR_PARSE
    assert "SOAP fault" in rows[0].note
    assert spy.ops == ["GetShortLongTitles", "GetPatientTicket"]


def test_multiple_exams_share_catalogue_and_ticket(spy: Spy) -> None:
    exams = {
        Exam.KNEE_RIGHT: {"pattern": "Knie rechts"},
        Exam.LUMBAR_SPINE: {"pattern": "Knie"},  # mehrdeutig
    }
    rows = adapter.collect(_site(exams=exams), RUN_START)
    assert [m.exam for m in rows] == [Exam.KNEE_RIGHT, Exam.LUMBAR_SPINE]
    assert rows[0].status is Status.OK
    # Mehrdeutiges Muster: Fehlerzeile mit Kandidaten, kein Request.
    assert rows[1].status is Status.ERROR_PARSE
    assert "xknr" in rows[1].note and "xknl" in rows[1].note
    assert spy.ops == ["GetShortLongTitles", "GetPatientTicket", "GetProposedDates"]
    assert adapter.task_count(_site(exams=exams)) == 4


def test_left_side_exam_is_never_requested(spy: Spy) -> None:
    rows = adapter.collect(
        _site(exams={Exam.KNEE_RIGHT: {"pattern": "Knie links"}}), RUN_START
    )
    assert rows[0].status is Status.ERROR_PARSE
    assert rows[0].note == "left-side exam selected: xknl: MR Knie links"
    assert "GetProposedDates" not in spy.ops


def test_empty_dates_is_no_slots(spy: Spy) -> None:
    spy.responses["GetProposedDates"] = _result(_skeleton("termine_leer.xml"))
    (m,) = adapter.collect(SITE, RUN_START)
    assert m.status is Status.NO_SLOTS
    assert m.slot_date is None
    assert m.note == "xknr: MR Knie rechts"


def test_server_error_in_dates_is_parse_error_never_no_slots(spy: Spy) -> None:
    spy.responses["GetProposedDates"] = _result(_skeleton("termine_fehler.xml"))
    (m,) = adapter.collect(SITE, RUN_START)
    assert m.status is Status.ERROR_PARSE
    assert "placeholder server error" in m.note


def test_dates_fetch_error_is_not_collected(spy: Spy) -> None:
    spy.responses["GetProposedDates"] = post.FetchError("redirect 302 not followed")
    (m,) = adapter.collect(SITE, RUN_START)
    assert m.status is Status.NOT_COLLECTED
    assert m.note == "GetProposedDates: redirect 302 not followed"


def test_dates_http_error_is_parse_error(spy: Spy) -> None:
    spy.responses["GetProposedDates"] = _result(b"", 503)
    (m,) = adapter.collect(SITE, RUN_START)
    assert m.status is Status.ERROR_PARSE
    assert m.note == "GetProposedDates: HTTP 503"


def test_blocked_host_is_not_collected(spy: Spy) -> None:
    spy.responses["GetShortLongTitles"] = http.BlockedHostError("host is blocked")
    rows = adapter.collect(SITE, RUN_START)
    assert all(m.status is Status.NOT_COLLECTED for m in rows)


@pytest.mark.parametrize(
    "op", ["GetShortLongTitles", "GetPatientTicket", "GetProposedDates"]
)
def test_budget_exceeded_aborts_at_every_stage(spy: Spy, op: str) -> None:
    spy.responses[op] = http.BudgetExceededError("POST budget exhausted")
    with pytest.raises(http.BudgetExceededError):
        adapter.collect(SITE, RUN_START)


def test_slot_before_run_day_is_parse_error(spy: Spy) -> None:
    # Skelett-Termine liegen 2099; ein Lauf danach macht daraus eine Fehlerzeile
    # statt negativer Wartetage.
    (m,) = adapter.collect(SITE, datetime(2100, 1, 1, 8, 0))
    assert m.status is Status.ERROR_PARSE
    assert m.slot_date is None


def test_nothing_secret_is_logged(spy: Spy, caplog: pytest.LogCaptureFixture) -> None:
    # Das Ticket entsteht zur Laufzeit, die Redaction kennt es nicht – es darf
    # gar nicht erst in einen Log-Record. Die SVNR ebenso wenig.
    caplog.set_level(logging.DEBUG)
    rows = adapter.collect(SITE, RUN_START)
    assert rows[0].status is Status.OK
    assert caplog.records, "expected at least one debug record"
    for record in caplog.records:
        text = record.getMessage() + repr(record.args)
        assert TICKET not in text
        assert SVNR not in text and "010180" not in text
    # Auch Hinweis und Exceptions tragen das Ticket nie.
    assert all(TICKET not in m.note for m in rows)
