# SPDX-License-Identifier: Apache-2.0
"""Tests des IRIS-Adapters: POST und GET gemockt (kein Netz), Antworten aus Skeletten.

Geprüft werden Request-Folge und URL-Bau, das Minimum über Terminarten und
Ressourcen, der Abschneide-Guard, Archivierung vor dem Parse, das Fehler-Mapping
und dass das Bearer-Token nirgends außer im Header auftaucht.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from mrt_termin_monitor.adapters import iris as adapter
from mrt_termin_monitor.fetch import http, post
from mrt_termin_monitor.model import Billing, Exam, Status
from mrt_termin_monitor.sites import Site

DATA = Path(__file__).parent / "data" / "iris"
BASE = "https://iris.example.at/terminbuchung"
# Zusammengesetzt, damit kein Token-förmiges Literal im Repo steht.
TOKEN = "tok-" + "platzhalter-" + "geheim"
SESSION_OK = json.dumps({"success": True, "token": TOKEN}).encode()
# Termine der Skelette liegen 2099: unabhängig von der Uhr immer in der Zukunft.
RUN_START = datetime(2099, 3, 2, 7, 0)

# Schrägstrich am Ende der base_url: der Adapter muss ihn abschneiden.
SITE = Site(
    slug="dok_beispiel",
    name="Kompetenzzentrum Beispiel",
    adapter="iris",
    billing=Billing.PUBLIC,
    params={
        "base_url": f"{BASE}/",
        "kategorie": "MRT",
        "kalender": "M",
        "ressource": "A,B",
        "horizon_days": 180,
    },
    exams={Exam.KNEE_RIGHT: {"pattern": "Knie rechts"}},
)
# VonDatum = Lauf-Tag + 1 (2099-03-03), BisDatum = + 180 Tage, als $HOROLOG.
SLOT_URL = (
    f"{BASE}/iris/getFreieTermineForTerminart?Kalender=M&Ressource=A%2CB"
    "&VonDatum=94295&BisDatum=94475&VonZeit=21600&BisZeit=70000"
    "&Terminart={}&Anzahl=5000"
)


def _data(name: str) -> bytes:
    return (DATA / name).read_bytes()


def _site(**changes) -> Site:
    return Site(**{**SITE.__dict__, **changes})


def _slots(*days: int) -> bytes:
    slots = [{"Datum": d, "Zeit": 25200, "Ressource": "A"} for d in days]
    return json.dumps(slots).encode()


@dataclass
class Portal:
    """Spielt das Portal: Antworten je Route, zeichnet jeden Request auf."""

    session: bytes = SESSION_OK
    session_status: int = 200
    catalogue: bytes = field(default_factory=lambda: _data("catalogue.json"))
    types: bytes = field(default_factory=lambda: _data("appointment_types.json"))
    slots: dict[str, bytes] = field(
        default_factory=lambda: {
            "TA1": _data("slots_empty.json"),
            "TA2": _data("slots_two_resources.json"),
        }
    )
    # HTTP-Status je Terminart; fehlt sie, 200.
    slot_status: dict[str, int] = field(default_factory=dict)
    posts: list[tuple[str, dict, dict]] = field(default_factory=list)
    gets: list[tuple[str, dict]] = field(default_factory=list)

    def post(self, url: str, payload: dict, **kw) -> http.FetchResult:
        self.posts.append((url, payload, kw))
        return http.FetchResult(url, self.session_status, self.session)

    def get(self, url: str, **kw) -> http.FetchResult:
        self.gets.append((url, kw))
        path, _, query = url.partition("?")
        if path.endswith("/getOnlineTerminList"):
            return http.FetchResult(url, 200, self.catalogue)
        if path.endswith("/getTerminartenForUntersuchung"):
            return http.FetchResult(url, 200, self.types)
        terminart = parse_qs(query)["Terminart"][0]
        status = self.slot_status.get(terminart, 200)
        return http.FetchResult(url, status, self.slots[terminart])

    @property
    def requests(self) -> int:
        return len(self.posts) + len(self.gets)


@pytest.fixture
def portal(monkeypatch: pytest.MonkeyPatch) -> Portal:
    fake = Portal()
    monkeypatch.setattr(post, "json_post", fake.post)
    monkeypatch.setattr(http, "get", fake.get)
    return fake


def _raise(exc: Exception):
    def boom(*args, **kw):
        raise exc

    return boom


def test_request_sequence_and_urls(portal: Portal) -> None:
    adapter.collect(SITE, RUN_START)
    assert [url for url, _, _ in portal.posts] == [f"{BASE}/api/session"]
    payload = portal.posts[0][1]
    assert payload["action"] == "create"
    assert payload["metadata"]["type"] == "anonymous"
    assert payload["metadata"]["userAgent"] == http.USER_AGENT
    urls = [url for url, _ in portal.gets]
    assert urls == [
        f"{BASE}/iris/getOnlineTerminList?Kategorie=MRT",
        f"{BASE}/iris/getTerminartenForUntersuchung?Untersuchung=U-KNR",
        SLOT_URL.format("TA1"),
        SLOT_URL.format("TA2"),
    ]
    # Beide Geräte in einem Request, und die Grenze, an der der Guard ansetzt.
    assert "Ressource=A%2CB" in urls[2]
    assert "Anzahl=5000" in urls[2]
    for _, kw in portal.gets:
        assert kw["extra_headers"]["Authorization"] == f"Bearer {TOKEN}"


def test_minimum_lies_in_resource_b_not_first_entry(portal: Portal) -> None:
    slots = json.loads(_data("slots_two_resources.json"))
    # Vorbedingung des Skeletts: der erste Eintrag ist Ressource A und nicht das
    # Minimum – wer nur den ersten Eintrag nimmt, fällt hier durch.
    assert slots[0]["Ressource"] == "A"
    assert min(slots, key=lambda s: s["Datum"])["Ressource"] == "B"
    (row,) = adapter.collect(SITE, RUN_START)
    assert row.status is Status.OK
    assert row.slot_date == date(2099, 3, 5)
    assert row.note == "Knie rechts [TA1=-, TA2=2099-03-05]"
    assert row.site_id == "dok_beispiel"
    assert row.site_name == "Kompetenzzentrum Beispiel"
    assert row.billing is Billing.PUBLIC
    assert row.exam is Exam.KNEE_RIGHT
    assert row.run_start == RUN_START
    assert row.queried_at.utcoffset() is not None


def test_empty_slot_lists_are_no_slots(portal: Portal) -> None:
    portal.slots = {"TA1": _data("slots_empty.json"), "TA2": b"[]"}
    (row,) = adapter.collect(SITE, RUN_START)
    assert row.status is Status.NO_SLOTS
    assert row.slot_date is None
    assert "TA1=-, TA2=-" in row.note


def test_pattern_matching_three_exams_stops_after_catalogue(portal: Portal) -> None:
    site = _site(exams={Exam.KNEE_RIGHT: {"pattern": "Knie"}})
    (row,) = adapter.collect(site, RUN_START)
    assert row.status is Status.ERROR_PARSE
    assert "matches 3 exams" in row.note
    # Nur Session und Katalog – kein Terminarten- und kein Slot-Request.
    assert len(portal.posts) == 1
    assert [url for url, _ in portal.gets] == [
        f"{BASE}/iris/getOnlineTerminList?Kategorie=MRT"
    ]


def test_no_match_lists_candidates(portal: Portal) -> None:
    site = _site(exams={Exam.KNEE_RIGHT: {"pattern": "Hüfte"}})
    (row,) = adapter.collect(site, RUN_START)
    assert row.status is Status.ERROR_PARSE
    assert "matches no MRT exam" in row.note
    assert "Knie beidseits" in row.note
    # CT-Einträge sind keine Kandidaten.
    assert row.note.count("Knie rechts") == 1


def test_kategorie_from_config_filters_modality(portal: Portal) -> None:
    adapter.collect(_site(params={**SITE.params, "kategorie": "CT"}), RUN_START)
    assert portal.gets[0][0] == f"{BASE}/iris/getOnlineTerminList?Kategorie=CT"
    assert portal.gets[1][0].endswith("Untersuchung=C-KNR")


def test_horizon_from_config(portal: Portal) -> None:
    adapter.collect(_site(params={**SITE.params, "horizon_days": 30}), RUN_START)
    assert "&VonDatum=94295&BisDatum=94325&" in portal.gets[2][0]


def test_truncated_101_slot_skeleton_is_parse_error(
    portal: Portal, monkeypatch: pytest.MonkeyPatch
) -> None:
    truncated = _data("slots_truncated_101.json")
    slots = json.loads(truncated)
    # Struktur einer gekürzten Antwort: Anzahl+1 Einträge, nur die erste Ressource.
    assert len(slots) == 101
    assert {s["Ressource"] for s in slots} == {"A"}
    monkeypatch.setattr(adapter, "_ANZAHL", 100)
    portal.slots = {"TA1": _data("slots_empty.json"), "TA2": truncated}
    (row,) = adapter.collect(SITE, RUN_START)
    assert row.status is Status.ERROR_PARSE
    assert row.slot_date is None
    assert "truncated" in row.note
    assert "Anzahl=100" in portal.gets[-1][0]


@pytest.mark.parametrize(("count", "status"), [(2, Status.OK), (3, Status.ERROR_PARSE)])
def test_truncation_boundary(
    portal: Portal, monkeypatch: pytest.MonkeyPatch, count: int, status: Status
) -> None:
    monkeypatch.setattr(adapter, "_ANZAHL", 3)
    portal.slots = {"TA1": b"[]", "TA2": _slots(*range(94297, 94297 + count))}
    (row,) = adapter.collect(SITE, RUN_START)
    assert row.status is status
    if status is Status.OK:
        assert row.slot_date == date(2099, 3, 5)
    else:
        assert "truncated" in row.note


def test_earliest_boundary_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "_ANZAHL", 3)
    two = [{"Datum": 94298}, {"Datum": "94297"}]
    assert adapter._earliest(two) == date(2099, 3, 5)
    with pytest.raises(ValueError, match="truncated"):
        adapter._earliest([*two, {"Datum": 94299}])


def test_task_count_covers_actual_requests(portal: Portal) -> None:
    adapter.collect(SITE, RUN_START)
    assert portal.requests == 5
    assert adapter.task_count(SITE) == 6 >= portal.requests


def test_task_count_is_exact_at_three_types(portal: Portal) -> None:
    portal.types = json.dumps([{"ID": "TA1"}, {"ID": "TA2"}, {"ID": "TA3"}]).encode()
    portal.slots["TA3"] = b"[]"
    adapter.collect(SITE, RUN_START)
    assert adapter.task_count(SITE) == portal.requests == 6


def test_exams_are_isolated_and_share_session(portal: Portal) -> None:
    site = _site(
        exams={
            Exam.KNEE_RIGHT: {"pattern": "Knie rechts"},
            Exam.LUMBAR_SPINE: {"pattern": "Wirbelsäule"},
        }
    )
    rows = adapter.collect(site, RUN_START)
    assert [m.exam for m in rows] == [Exam.KNEE_RIGHT, Exam.LUMBAR_SPINE]
    assert [m.status for m in rows] == [Status.OK, Status.ERROR_PARSE]
    assert len(portal.posts) == 1
    assert sum("getOnlineTerminList" in url for url, _ in portal.gets) == 1
    assert adapter.task_count(site) == 10 >= portal.requests


def test_archive_before_parse_and_names(
    portal: Portal, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    archived: dict[str, bytes] = {}
    real = adapter._json_list

    def parse(result: http.FetchResult) -> list:
        order.append("parse")
        return real(result)

    def archive(name: str, content: bytes) -> None:
        order.append(name)
        archived[name] = content

    monkeypatch.setattr(adapter, "_json_list", parse)
    adapter.collect(SITE, RUN_START, archive=archive)
    names = [
        "dok_beispiel_catalogue.json",
        "dok_beispiel_knee_right_appointment_types.json",
        "dok_beispiel_knee_right_TA1.json",
        "dok_beispiel_knee_right_TA2.json",
    ]
    assert order == [step for name in names for step in (name, "parse")]
    # Die erfolgreiche Session-Antwort trägt das Token und wird nie abgelegt.
    assert list(archived) == names
    assert archived["dok_beispiel_knee_right_TA2.json"] == _data(
        "slots_two_resources.json"
    )


@pytest.mark.parametrize("fail_on", ["catalogue", "TA2"])
def test_archive_error_propagates(portal: Portal, fail_on: str) -> None:
    def archive(name: str, content: bytes) -> None:
        if fail_on in name:
            raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        adapter.collect(SITE, RUN_START, archive=archive)


def test_session_http_error_is_parse_error_and_archived(portal: Portal) -> None:
    portal.session_status = 401
    portal.session = b'{"success": false, "message": "unauthorized"}'
    archived: dict[str, bytes] = {}
    site = _site(exams={**SITE.exams, Exam.LUMBAR_SPINE: {"pattern": "x"}})
    rows = adapter.collect(site, RUN_START, archive=archived.__setitem__)
    # Auch ein 401 ist nie „keine Termine“.
    assert [m.status for m in rows] == [Status.ERROR_PARSE, Status.ERROR_PARSE]
    assert rows[0].note == "session: HTTP 401"
    assert archived == {"dok_beispiel_session.json": portal.session}
    assert portal.gets == []


@pytest.mark.parametrize("body", [b'{"success": true}', b"<html>", b"[]"])
def test_session_without_token_is_parse_error(portal: Portal, body: bytes) -> None:
    portal.session = body
    archived: list[str] = []
    (row,) = adapter.collect(SITE, RUN_START, archive=lambda n, c: archived.append(n))
    assert row.status is Status.ERROR_PARSE
    assert "without success flag or token" in row.note
    assert archived == ["dok_beispiel_session.json"]


def test_failed_session_with_token_is_not_archived(portal: Portal) -> None:
    portal.session = json.dumps({"success": False, "token": TOKEN}).encode()
    archived: list[str] = []
    (row,) = adapter.collect(SITE, RUN_START, archive=lambda n, c: archived.append(n))
    assert row.status is Status.ERROR_PARSE
    assert archived == []
    assert TOKEN not in row.note


@pytest.mark.parametrize(
    "exc",
    [
        http.FetchError("POST failed after 2 attempts: timeout"),
        post.OperationNotAllowedError("JSON route not on the read whitelist"),
        http.BlockedHostError("host is blocked"),
    ],
)
def test_session_fetch_error_is_not_collected(
    portal: Portal, monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    monkeypatch.setattr(post, "json_post", _raise(exc))
    (row,) = adapter.collect(SITE, RUN_START)
    assert row.status is Status.NOT_COLLECTED
    assert row.note.startswith("session: ")
    assert portal.gets == []


@pytest.mark.parametrize("where", ["post", "get"])
def test_budget_exceeded_propagates(
    portal: Portal, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    broke = _raise(http.BudgetExceededError("request budget exhausted"))
    if where == "post":
        monkeypatch.setattr(post, "json_post", broke)
    else:
        monkeypatch.setattr(http, "get", broke)
    with pytest.raises(http.BudgetExceededError):
        adapter.collect(SITE, RUN_START)


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (
            http.CrossHostRedirectError("redirect to foreign host"),
            Status.ERROR_REDIRECT,
        ),
        (http.FetchError("GET failed after 2 attempts"), Status.NOT_COLLECTED),
    ],
)
def test_catalogue_fetch_errors(
    portal: Portal, monkeypatch: pytest.MonkeyPatch, exc: Exception, status: Status
) -> None:
    monkeypatch.setattr(http, "get", _raise(exc))
    site = _site(exams={**SITE.exams, Exam.LUMBAR_SPINE: {"pattern": "x"}})
    rows = adapter.collect(site, RUN_START)
    assert [m.status for m in rows] == [status, status]
    assert rows[0].note.startswith("catalogue: ")


def test_catalogue_http_error_is_parse_error(portal: Portal) -> None:
    portal.catalogue = b'{"error": "maintenance"}'
    (row,) = adapter.collect(SITE, RUN_START)
    assert row.status is Status.ERROR_PARSE
    assert row.note == "catalogue: response is a JSON dict, not a list"


def test_failing_candidate_fails_exam_never_later_date(portal: Portal) -> None:
    portal.slot_status = {"TA1": 401}
    (row,) = adapter.collect(SITE, RUN_START)
    assert row.status is Status.ERROR_PARSE
    assert row.slot_date is None
    assert row.note == "slots[TA1]: HTTP 401"
    # Der zweite Kandidat wird nicht mehr abgefragt.
    assert len(portal.gets) == 3


def test_slot_fetch_error_is_not_collected(
    portal: Portal, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = portal.get

    def flaky(url: str, **kw) -> http.FetchResult:
        if "Terminart=TA2" in url:
            raise http.FetchError("GET failed after 2 attempts: timeout")
        return real(url, **kw)

    monkeypatch.setattr(http, "get", flaky)
    (row,) = adapter.collect(SITE, RUN_START)
    assert row.status is Status.NOT_COLLECTED
    assert "timeout" in row.note


@pytest.mark.parametrize(
    ("types", "match"),
    [
        (
            [{"ID": "TA1"}, {"ID": "TA2"}, {"ID": "TA3"}, {"ID": "TA4"}],
            "4 appointment types",
        ),
        ([], "no appointment type"),
        ([{"ID": "../x"}], "unexpected appointment type ids"),
        ({"ID": "TA1"}, "not a list"),
    ],
)
def test_bad_appointment_types_skip_slot_requests(
    portal: Portal, types: object, match: str
) -> None:
    portal.types = json.dumps(types).encode()
    (row,) = adapter.collect(SITE, RUN_START)
    assert row.status is Status.ERROR_PARSE
    assert match in row.note
    assert len(portal.gets) == 2


@pytest.mark.parametrize(
    ("body", "match"),
    [
        (b'{"error": "x"}', "not a list"),
        (b'[{"Zeit": 25200}]', "without 'Datum'"),
        (b"<html>", "slots[TA2]: "),
    ],
)
def test_unexpected_slot_answer_is_parse_error(
    portal: Portal, body: bytes, match: str
) -> None:
    portal.slots["TA2"] = body
    (row,) = adapter.collect(SITE, RUN_START)
    assert row.status is Status.ERROR_PARSE
    assert match in row.note
    assert row.slot_date is None


def test_slot_before_run_day_is_parse_error(portal: Portal) -> None:
    (row,) = adapter.collect(SITE, datetime(2099, 3, 6, 7, 0))
    assert row.status is Status.ERROR_PARSE
    assert row.slot_date is None
    assert "before run day" in row.note


def test_horolog_both_directions() -> None:
    assert adapter._horolog(date(2026, 10, 30)) == 67873
    assert adapter._from_horolog("67873") == date(2026, 10, 30)
    assert adapter._from_horolog(94297) == date(2099, 3, 5)
    assert adapter._horolog(date(1840, 12, 31)) == 0


def test_label_joins_text_and_side() -> None:
    assert adapter._label({"Bezeichnung": "Knie ", "Lateralität": "rechts"}) == (
        "Knie rechts"
    )
    assert adapter._label({"Bezeichnung": "Schädel ", "Lateralität": ""}) == "Schädel"


def test_token_never_in_log_or_note(
    portal: Portal, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    notes = [m.note for m in adapter.collect(SITE, RUN_START)]
    portal.slot_status = {"TA1": 401}
    notes += [m.note for m in adapter.collect(SITE, RUN_START)]
    portal.session = json.dumps({"success": False, "token": TOKEN}).encode()
    notes += [m.note for m in adapter.collect(SITE, RUN_START)]
    assert caplog.records  # der Adapter loggt überhaupt
    assert TOKEN not in caplog.text
    assert all(TOKEN not in note for note in notes)


def test_timeout_from_site_or_default(portal: Portal) -> None:
    adapter.collect(SITE, RUN_START)
    adapter.collect(_site(timeout_s=45), RUN_START)
    assert [kw["timeout"] for _, _, kw in portal.posts] == [http.DEFAULT_TIMEOUT, 45]
    assert [kw["timeout"] for _, kw in portal.gets] == [http.DEFAULT_TIMEOUT] * 4 + [
        45
    ] * 4
