# SPDX-License-Identifier: Apache-2.0
"""Tests der POST-Schicht – vor allem ihrer Grenzen.

Kern ist die Lese-Whitelist: buchende Operationen dürfen nicht nur „nicht aufgerufen
werden“, sie müssen technisch nicht aufrufbar sein. Die Tests gehen nie ins Netz
(der Whitelist-Check sitzt vor dem Socket).
"""

from types import SimpleNamespace

import pytest

from mrt_termin_monitor.fetch import http, post


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(http, "_last_request_at", {})
    post.set_budget(None)
    http.set_budget(None)
    yield
    post.set_budget(None)
    http.set_budget(None)


@pytest.mark.parametrize(
    "op",
    [
        "SetPatLock",  # setzt eine serverseitige Terminsperre
        "FixPatientDate",  # bucht
        "CancelBookedDate",  # storniert
        "GetEkosData",  # fremde Patientendaten
        "PinLogin",
    ],
)
def test_booking_operations_cannot_be_called(op: str) -> None:
    with pytest.raises(post.OperationNotAllowedError):
        post.soap_body(op)


def test_soap_rejects_before_any_request() -> None:
    with pytest.raises(post.OperationNotAllowedError):
        post.soap("https://example.at/hgsservice/service.asmx", "SetPatLock", delay=0)
    assert post.request_count() == 0


def test_read_operations_build_soap12_envelope() -> None:
    body = post.soap_body("GetProposedDates", "<ticket>T</ticket>")
    # Envelope wörtlich wie im ausgelieferten Client (getSoapRequest).
    assert body.startswith('<?xml version="1.0" encoding="utf-8"?><soap12:Envelope')
    assert 'xmlns:soap12="http://www.w3.org/2003/05/soap-envelope"' in body
    assert '<GetProposedDates xmlns="http://tempuri.org/"><ticket>T</ticket>' in body


def test_json_route_outside_whitelist_is_refused() -> None:
    with pytest.raises(post.OperationNotAllowedError):
        post.json_post("https://example.at/terminbuchung/iris/lockTermin", {}, delay=0)


def test_blocked_host_applies_to_post_too() -> None:
    """Die Hostsperre ist geteilt, nicht kopiert – sonst driftet sie auseinander."""
    with pytest.raises(http.BlockedHostError):
        post.json_post("https://termin.azs.at/api/session", {}, delay=0)


def test_budget_counts_separately_from_get() -> None:
    """Eigener Zähler: ein Schleifen-Bug im SOAP-Pfad darf das GET-Budget nicht
    aufbrauchen (und umgekehrt)."""
    post.set_budget(0)
    http.set_budget(5)
    with pytest.raises(http.BudgetExceededError):
        post.soap(
            "https://example.at/hgsservice/service.asmx", "GetShortLongTitles", delay=0
        )
    assert http.request_count() == 0


class _RedirectSession:
    def request(self, method, url, **kwargs):
        return SimpleNamespace(
            status_code=302,
            headers={"Location": "https://example.at/wartung"},
            content=b"",
        )


def test_redirect_is_never_followed() -> None:
    with pytest.raises(http.FetchError):
        post.json_post(
            "https://example.at/terminbuchung/api/session",
            {},
            session=_RedirectSession(),
            delay=0,
        )
