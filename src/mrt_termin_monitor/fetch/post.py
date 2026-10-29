# SPDX-License-Identifier: Apache-2.0
"""Zweite (und letzte) Netz-Schicht: HTTP POST, eng gefasst auf Lese-Operationen.

Warum überhaupt POST, wo ``http.py`` strukturell GET-only ist: die HGS-PatApp-Portale
sprechen ausschließlich SOAP über POST – auch ihre reinen Lese-Operationen –, und
das Lukassoftware/InterSystems-IRIS-Portal gibt seinen Lese-Token nur gegen einen
POST auf die eigene Session-Route heraus. Ein GET darauf existiert bei beiden
Produkten nicht (die ASMX-Hilfeseiten bieten nur „SOAP 1.1“/„SOAP 1.2“, die
HTTP-GET/POST-Protokolle sind abgeschaltet).

Die GET-Garantie von ``http.py`` bleibt davon unberührt: dieses Modul ist ein
eigener, kleiner Zwilling und bringt eine **Whitelist** mit, die enger ist als die
dortige Hostsperre – erlaubt sind genau die drei lesenden PatApp-Operationen und die
anonyme IRIS-Session. Jede buchende, sperrende oder stornierende Operation
(``SetPatLock``, ``FixPatientDate``, ``CancelBookedDate``, ``lockTermin``,
``saveAppointment``, ``getTAN`` …) ist damit nicht „verboten“, sondern technisch
nicht aufrufbar: ihr Name steht in keiner erlaubten Liste, und die Prüfung sitzt vor
dem Socket, nicht im Adapter.

Geteilt mit ``http.py``: Hostsperre (``check_blocked``), Mindestabstand je Host
(``pace``, ein gemeinsamer Zeitstempel je Host für beide Methoden) und CA-Bundle
(``ca_bundle``) – bewusst dieselbe Funktion, nicht dieselbe Logik zweimal. Eigen: das
Request-Budget (getrennter Zähler, damit ein Schleifen-Bug im SOAP-Pfad nicht das
GET-Budget aufbraucht und umgekehrt) und die Regel, dass Redirects **nie** verfolgt
werden – eine Umleitung auf einen POST ist bei beiden Produkten immer ein Fehler,
nie ein erwarteter Fall.
"""

import json
import logging
import time
from urllib.parse import urlsplit

import requests

from mrt_termin_monitor.fetch.http import (
    DEFAULT_TIMEOUT,
    REQUEST_DELAY_SECONDS,
    USER_AGENT,
    BudgetExceededError,
    FetchError,
    FetchResult,
    ca_bundle,
    check_blocked,
    host_of,
    pace,
)

log = logging.getLogger(__name__)

# Erlaubte SOAP-Operationen (PatApp). Alle drei sind rein lesend:
#   GetShortLongTitles  – Untersuchungskatalog, braucht kein Ticket
#   GetPatientTicket    – Anmeldung mit SVNR, liefert das 10-Minuten-Ticket
#   GetProposedDates    – Terminvorschlagsliste zu einem Untersuchungscode
# Bewusst NICHT enthalten und damit nicht aufrufbar: SetPatLock (setzt schon beim
# ersten Klick auf einen Termin einen serverseitigen Hold!), FixPatientDate,
# CancelBookedDate, PinLogin, ConfirmPin, GetEkosData, GetEkosDocument, StudyList,
# GetReport, BookedDates, HasMammaToken.
ALLOWED_SOAP_OPS = ("GetShortLongTitles", "GetPatientTicket", "GetProposedDates")

# Erlaubte JSON-Routen (IRIS), als Pfad-Suffix geprüft. Nur die anonyme
# Session-Erzeugung; alles Lesende dort läuft über GET (``http.get``).
# Nicht enthalten: /iris/lockTermin, /iris/saveAppointment, /iris/getTAN,
# /iris/checkTAN, /iris/addZuweisungToTermin, /iris/addWartelisteToTermin.
ALLOWED_JSON_PATHS = ("/api/session",)

# SOAP-1.2-Envelope exakt wie im ausgelieferten Client (script.js,
# ``getSoapRequest``): derselbe Präfix, dieselbe Reihenfolge der Namespaces,
# derselbe Default-Namespace http://tempuri.org/ am Operations-Element.
# Nachgebaut statt „sinnvoll vereinfacht“, weil der Server keine WSDL ausliefert
# (?WSDL -> HTTP 500) und der Client die einzige Doku ist.
_SOAP_TEMPLATE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<soap12:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    ' xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
    ' xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">'
    "  <soap12:Body>"
    '    <{op} xmlns="http://tempuri.org/">{params}    </{op}>'
    "  </soap12:Body>"
    "</soap12:Envelope>"
)

_MAX_ATTEMPTS = 2
_RETRY_PAUSE_S = 2.0


class OperationNotAllowedError(FetchError):
    """Aufruf einer Operation, die nicht auf der Lese-Whitelist steht.

    Das ist immer ein Programmierfehler, nie ein Betriebsfall – deshalb fliegt die
    Ausnahme durch bis zum Adapter und wird dort als Fehlzeile sichtbar.
    """


# Eigener Budget-Zustand (siehe Modulkopf). None = keine Prüfung (Unittests).
_budget: int | None = None
_request_count = 0


def set_budget(limit: int | None) -> None:
    """Setzt das Soll für POST-Aufrufe und nullt den Zähler.

    Args:
        limit: maximale Zahl von POSTs; ``None`` schaltet die Prüfung ab (nur für
            Tests – die Orchestrierung setzt immer ein Soll).
    """
    global _budget, _request_count
    _budget = limit
    _request_count = 0


def request_count() -> int:
    """Bisher gezählte POSTs seit dem letzten ``set_budget()``."""
    return _request_count


def soap_body(op: str, params: str = "") -> str:
    """Baut den Envelope einer erlaubten Operation.

    Args:
        op: Operationsname, muss in ``ALLOWED_SOAP_OPS`` stehen.
        params: bereits serialisierte Parameter-Elemente (z. B.
            ``"<sin>…</sin>"``); Werte muss der Aufrufer kodieren.

    Returns:
        Vollständiger SOAP-1.2-Envelope als String.

    Raises:
        OperationNotAllowedError: bei jeder anderen Operation.
    """
    if op not in ALLOWED_SOAP_OPS:
        raise OperationNotAllowedError(
            f"SOAP operation {op!r} is not on the read whitelist "
            f"({', '.join(ALLOWED_SOAP_OPS)}), not sent"
        )
    return _SOAP_TEMPLATE.format(op=op, params=params)


def soap(
    url: str,
    op: str,
    params: str = "",
    *,
    timeout: float = DEFAULT_TIMEOUT,
    session: requests.Session | None = None,
    delay: float = REQUEST_DELAY_SECONDS,
) -> FetchResult:
    """Sendet eine erlaubte SOAP-Operation an einen ASMX-Endpunkt.

    Args:
        url: Endpunkt ohne Query, z. B. ``https://host/hgsservice/service.asmx``.
        op: Operationsname (Whitelist ``ALLOWED_SOAP_OPS``).
        params: serialisierte Parameter-Elemente.
        timeout: Timeout je Versuch in Sekunden.
        session: vorhandene Session (Wiederverwendung/Tests).
        delay: Mindestabstand zum vorigen Request an denselben Host (Tests: 0).

    Returns:
        ``FetchResult`` mit Status und Roh-Bytes; auch 4xx/5xx kommen zurück (der
        Aufrufer archiviert und entscheidet).

    Raises:
        OperationNotAllowedError: Operation nicht auf der Whitelist.
        BlockedHostError: Ziel ist ein gesperrter Host.
        BudgetExceededError: POST-Soll erreicht.
        FetchError: Netzfehler auch im zweiten Versuch, oder Redirect.
    """
    body = soap_body(op, params)
    # ?op=<Name> wie im Client: die ASMX-Route wertet den Parameter nicht aus (die
    # Operation steht im Envelope), aber so steht der Name im Server-Log des
    # Instituts – nachvollziehbar, welche Operation kam.
    full_url = f"{url}?op={op}"
    # Content-Type wörtlich wie jQuery ihn bei contentType: 'text/xml' sendet.
    headers = {"Content-Type": "text/xml; charset=UTF-8"}
    # Nur die Länge loggen: der Envelope von GetPatientTicket enthält die SVNR.
    log.debug("SOAP %s -> %s (%d byte envelope)", op, url, len(body))
    result = _send(full_url, body.encode("utf-8"), headers, timeout, session, delay)
    log.debug(
        "SOAP %s <- HTTP %d, %d byte", op, result.status_code, len(result.content)
    )
    return result


def json_post(
    url: str,
    payload: dict,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    session: requests.Session | None = None,
    delay: float = REQUEST_DELAY_SECONDS,
) -> FetchResult:
    """Sendet einen JSON-POST an eine erlaubte Route (IRIS-Session).

    Args:
        url: vollständige Ziel-URL; ihr Pfad muss auf einen Eintrag aus
            ``ALLOWED_JSON_PATHS`` enden.
        payload: JSON-serialisierbarer Rumpf.
        timeout: Timeout je Versuch in Sekunden.
        session: vorhandene Session (Wiederverwendung/Tests).
        delay: Mindestabstand zum vorigen Request an denselben Host (Tests: 0).

    Returns:
        ``FetchResult`` mit Status und Roh-Bytes.

    Raises:
        OperationNotAllowedError: Route nicht auf der Whitelist.
    """
    path = urlsplit(url).path
    if not any(path.endswith(allowed) for allowed in ALLOWED_JSON_PATHS):
        raise OperationNotAllowedError(
            f"JSON route {path!r} is not on the read whitelist "
            f"({', '.join(ALLOWED_JSON_PATHS)}), not sent"
        )
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    log.debug("JSON POST -> %s (%d byte)", url, len(body))
    result = _send(url, body, headers, timeout, session, delay)
    log.debug("JSON POST <- HTTP %d, %d byte", result.status_code, len(result.content))
    return result


def _send(
    url: str,
    body: bytes,
    headers: dict[str, str],
    timeout: float,
    session: requests.Session | None,
    delay: float,
) -> FetchResult:
    """Gemeinsamer Versand: Guardrails, Budget, ein Retry, keine Redirects."""
    global _request_count

    host = host_of(url)
    check_blocked(host)

    if _budget is not None and _request_count >= _budget:
        raise BudgetExceededError(f"POST budget exhausted ({_request_count}/{_budget})")
    _request_count += 1

    sess = session if session is not None else requests.Session()
    send_headers = {"User-Agent": USER_AGENT, **headers}

    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        if attempt > 0:
            # DEBUG statt WARNING: die Konsole zeigt nur Texte aus ``messages``.
            log.debug("retry after network error: %s", last_error)
            time.sleep(_RETRY_PAUSE_S)
        try:
            pace(host, delay)
            started = time.monotonic()
            resp = sess.request(
                "POST",
                url,
                data=body,
                headers=send_headers,
                timeout=timeout,
                allow_redirects=False,
                verify=ca_bundle(),
            )
            log.debug("%s in %.1f s", url, time.monotonic() - started)
            if 300 <= resp.status_code < 400:
                # Kein Redirect-Folgen: bei SOAP/JSON ist eine Umleitung immer ein
                # Symptom (Wartungsseite, Login-Wand), nie der Nutzfall.
                raise FetchError(
                    f"redirect {resp.status_code} to "
                    f"{resp.headers.get('Location')!r} not followed"
                )
            return FetchResult(
                url=url, status_code=resp.status_code, content=resp.content
            )
        except requests.RequestException as exc:
            last_error = exc
    raise FetchError(
        f"POST {url} failed after {_MAX_ATTEMPTS} attempts: {last_error}"
    ) from last_error
