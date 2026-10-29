# SPDX-License-Identifier: Apache-2.0
"""Tests des GET-Layers – komplett ohne Netz (Session als Fake injiziert).

Abgedeckt: Retry, Budget-Abbruch, Fremdhost-Redirect abgelehnt, Same-Host-Redirect
verfolgt, Hostsperre, Mindestabstand je Host, README-Zahl, CA-Bundle als
Package-Data und der Nachweis „kein anderer HTTP-Verb-Codepfad“ per Quelltext.
"""

import inspect
from pathlib import Path

import certifi
import pytest
import requests

from mrt_termin_monitor import __version__
from mrt_termin_monitor.fetch import (
    BlockedHostError,
    BudgetExceededError,
    CrossHostRedirectError,
    FetchError,
    get,
    request_count,
    set_budget,
)
from mrt_termin_monitor.fetch import http as fetch_http
from mrt_termin_monitor.fetch import post as fetch_post
from mrt_termin_monitor.messages import KONTAKT_MAIL

README = Path(__file__).parents[1] / "README.md"
URL = "https://dh3.radiologie.at/AppointmentSearch/directAppointmentSearch?exas=mrknr"


class FakeResponse:
    def __init__(self, status_code=200, content=b"", location=None):
        self.status_code = status_code
        self.content = content
        self.headers = {"Location": location} if location else {}


class FakeSession:
    """Gibt vorbereitete Antworten/Exceptions der Reihe nach aus und protokolliert
    jeden Aufruf (URL + kwargs) für Assertions."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def _next(self, url, kwargs):
        self.calls.append((url, kwargs))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, **kwargs):
        return self._next(url, kwargs)

    def request(self, method, url, **kwargs):
        return self._next(url, kwargs)


class FakeClock:
    """Ersetzt time.monotonic/time.sleep: sleep schiebt die Uhr nur vor."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    # Budget und Zeitstempel sind modulglobal – je Test neutralisieren, damit Tests
    # sich nicht gegenseitig beeinflussen; kein Test wartet echt.
    fake = FakeClock()
    monkeypatch.setattr(fetch_http.time, "monotonic", fake.monotonic)
    monkeypatch.setattr(fetch_http.time, "sleep", fake.sleep)
    monkeypatch.setattr(fetch_http, "_last_request_at", {})
    set_budget(None)
    fetch_post.set_budget(None)
    yield fake
    set_budget(None)
    fetch_post.set_budget(None)


def test_get_returns_url_status_bytes() -> None:
    sess = FakeSession([FakeResponse(200, b"<html>MR Kniegelenk</html>")])
    result = get(URL, session=sess, delay=0)
    assert result.url == URL
    assert result.status_code == 200
    assert result.content == b"<html>MR Kniegelenk</html>"


def test_user_agent_names_version_and_contact_and_extra_headers_win() -> None:
    sess = FakeSession([FakeResponse(200)])
    get(URL, session=sess, delay=0, extra_headers={"Referer": "https://example.at/"})
    headers = sess.calls[0][1]["headers"]
    assert headers["User-Agent"].startswith(f"mrt-termin-monitor/{__version__} ")
    assert KONTAKT_MAIL in headers["User-Agent"]
    assert headers["User-Agent"].isascii()  # HTTP-Header sind Latin-1
    assert headers["Referer"] == "https://example.at/"


def test_timeout_default_and_override() -> None:
    sess = FakeSession([FakeResponse(200), FakeResponse(200)])
    get(URL, session=sess, delay=0)
    get(URL, session=sess, delay=0, timeout=5)
    assert sess.calls[0][1]["timeout"] == 30.0
    assert sess.calls[1][1]["timeout"] == 5


def test_tls_verification_is_never_disabled() -> None:
    sess = FakeSession([FakeResponse(200)])
    get(URL, session=sess, delay=0)
    assert sess.calls[0][1]["verify"] not in (False, None)


def test_retry_second_attempt_succeeds() -> None:
    sess = FakeSession([requests.ConnectionError("kaputt"), FakeResponse(200, b"ok")])
    result = get(URL, session=sess, delay=0)
    assert result.status_code == 200
    assert len(sess.calls) == 2


def test_retry_both_attempts_fail() -> None:
    sess = FakeSession([requests.ConnectionError("1"), requests.ConnectionError("2")])
    with pytest.raises(FetchError):
        get(URL, session=sess, delay=0)
    assert len(sess.calls) == 2  # max. 2 Versuche, kein dritter


def test_budget_stops_run() -> None:
    set_budget(2)
    sess = FakeSession([FakeResponse(200), FakeResponse(200)])
    get(URL, session=sess, delay=0)
    get(URL, session=sess, delay=0)
    assert request_count() == 2
    with pytest.raises(BudgetExceededError):
        get(URL, session=FakeSession([FakeResponse(200)]), delay=0)


def test_exhausted_budget_never_reaches_network() -> None:
    set_budget(0)
    sess = FakeSession([FakeResponse(200)])
    with pytest.raises(BudgetExceededError):
        get(URL, session=sess, delay=0)
    assert sess.calls == []


def test_same_host_redirect_is_followed() -> None:
    # XR-WEB: 302 auf ?para=<token> auf demselben Host.
    target = "https://dh3.radiologie.at/AppointmentSearch?para=abc123"
    sess = FakeSession([FakeResponse(302, location=target), FakeResponse(200, b"x")])
    result = get(URL, session=sess, delay=0)
    assert result.url == target
    assert result.status_code == 200
    assert result.content == b"x"


def test_relative_redirect_stays_on_host() -> None:
    sess = FakeSession(
        [FakeResponse(302, location="/Anders?para=x"), FakeResponse(200)]
    )
    result = get(URL, session=sess, delay=0)
    assert result.url == "https://dh3.radiologie.at/Anders?para=x"


def test_cross_host_redirect_is_refused() -> None:
    sess = FakeSession([FakeResponse(302, location="https://boese-seite.example/w")])
    with pytest.raises(CrossHostRedirectError):
        get(URL, session=sess, delay=0)
    assert len(sess.calls) == 1  # dem Fremdhost-Redirect wurde nicht gefolgt


def test_redirect_hops_are_bounded() -> None:
    loop = [FakeResponse(302, location="/again") for _ in range(10)]
    with pytest.raises(FetchError):
        get(URL, session=FakeSession(loop), delay=0)


@pytest.mark.parametrize(
    "blocked_url",
    [
        "https://ctmr.expert/irgendwas",
        "https://www.ctmr.expert/",
        "https://azs.at/",
        "https://termin.azs.at/pat/",
        "https://vera.care/",
        "https://termine.vera.care/PKkubin/",
    ],
)
def test_blocked_hosts_incl_subdomains_never_queried(blocked_url: str) -> None:
    sess = FakeSession([FakeResponse(200)])
    with pytest.raises(BlockedHostError):
        get(blocked_url, session=sess, delay=0)
    assert sess.calls == []  # kein Request ging raus


def test_blocked_hosts_are_exactly_the_three() -> None:
    assert fetch_http.BLOCKED_HOSTS == ("ctmr.expert", "azs.at", "vera.care")


def test_blocklist_has_no_false_positives() -> None:
    # Suffix-Logik darf nur echte (Sub-)Domains treffen.
    sess = FakeSession([FakeResponse(200)])
    assert get("https://notazs.at/", session=sess, delay=0).status_code == 200


def test_second_request_to_same_host_waits_for_delay(clock: FakeClock) -> None:
    sess = FakeSession([FakeResponse(200), FakeResponse(200)])
    get(URL, session=sess, delay=10)
    clock.now += 3  # Parser-Zeit o. ä. zählt zum Abstand
    get(URL, session=sess, delay=10)
    assert clock.sleeps == [pytest.approx(7)]


def test_other_host_does_not_wait(clock: FakeClock) -> None:
    sess = FakeSession([FakeResponse(200), FakeResponse(200)])
    get(URL, session=sess, delay=10)
    get("https://www.dzstadlau.radiologie.at/", session=sess, delay=10)
    assert clock.sleeps == []


def test_redirect_hop_is_paced_too(clock: FakeClock) -> None:
    sess = FakeSession([FakeResponse(302, location="/x?para=1"), FakeResponse(200)])
    get(URL, session=sess, delay=10)
    assert clock.sleeps == [pytest.approx(10)]


def test_delay_zero_never_sleeps(clock: FakeClock) -> None:
    sess = FakeSession([FakeResponse(200), FakeResponse(200)])
    get(URL, session=sess, delay=0)
    get(URL, session=sess, delay=0)
    assert clock.sleeps == []


def test_get_and_post_share_the_host_timestamp(clock: FakeClock) -> None:
    # Ein Host, zwei Methoden (IRIS: Session per POST, Rest per GET) – der Abstand
    # gilt über beide Module hinweg.
    base = "https://smart.mein-dok.at/terminbuchung"
    sess = FakeSession([FakeResponse(200), FakeResponse(200)])
    fetch_post.json_post(f"{base}/api/session", {}, session=sess, delay=10)
    get(f"{base}/iris/katalog", session=sess, delay=10)
    assert clock.sleeps == [pytest.approx(10)]


def test_default_delay_is_the_constant() -> None:
    assert fetch_http.REQUEST_DELAY_SECONDS == 10
    for fn in (get, fetch_post.soap, fetch_post.json_post):
        default = inspect.signature(fn).parameters["delay"].default
        assert default == fetch_http.REQUEST_DELAY_SECONDS


def test_readme_states_the_delay_verbatim() -> None:
    # Die Aussage im README ist nur haltbar, solange der Code sie erzwingt.
    text = README.read_text(encoding="utf-8")
    assert f"mindestens {fetch_http.REQUEST_DELAY_SECONDS} Sekunden" in text
    assert "REQUEST_DELAY_SECONDS" in text


def test_ca_bundle_is_certifi_plus_package_data() -> None:
    assert fetch_http.EXTRA_CA.is_file()
    bundle = Path(fetch_http.ca_bundle()).read_text(encoding="utf-8")
    assert bundle.startswith(certifi.contents())
    assert bundle.endswith(fetch_http.EXTRA_CA.read_text(encoding="utf-8"))
    assert bundle.count("BEGIN CERTIFICATE") > certifi.contents().count(
        "BEGIN CERTIFICATE"
    )


def test_no_other_http_verb_in_module_source() -> None:
    # Guardrail strukturell: der Quelltext des GET-Moduls enthält das andere Verb
    # nirgends – weder session.<verb> noch method="<VERB>" noch im Kommentar.
    assert "post" not in inspect.getsource(fetch_http).lower()
