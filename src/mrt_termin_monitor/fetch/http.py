# SPDX-License-Identifier: Apache-2.0
"""Netzzugriff per GET auf Basis ``requests.Session`` – fest verdrahtete Guardrails.

- Nur GET: dieses Modul stellt strukturell keine andere HTTP-Methode bereit (das
  Wort dafür kommt hier bewusst nicht vor, ein Test prüft das per Quelltext).
  Die einzige Ausnahme, die schmale Lese-Whitelist für SOAP/JSON, lebt im
  Zwillingsmodul daneben (Name bewusst nicht genannt, er enthält das Wort).
- Request-Budget: modulweiter Zähler; das Soll setzt die Orchestrierung.
- Hostsperre ``BLOCKED_HOSTS``: unabhängig von jeder Config.
- Mindestabstand ``REQUEST_DELAY_SECONDS`` zwischen zwei Requests an denselben Host.
- Redirects nur innerhalb desselben Hosts (XR-WEB-``?para=``-Fall).

``check_blocked()``, ``pace()`` und ``ca_bundle()`` sind bewusst öffentlich: das
Zwillingsmodul teilt sich genau diese Guardrails, statt sie zu kopieren (kopierte
Sperrlisten und getrennte Zeitstempel driften auseinander).
"""

import logging
import tempfile
import time
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import certifi
import requests

from mrt_termin_monitor import __version__
from mrt_termin_monitor.messages import KONTAKT_MAIL

log = logging.getLogger(__name__)

# Sprechender User-Agent mit Kontakt: ein Institut, das die Abrufe im Server-Log
# sieht, soll ohne Recherche erkennen, wer abfragt und wen es erreicht. Nur ASCII,
# weil HTTP-Header Latin-1 sind.
USER_AGENT = (
    f"mrt-termin-monitor/{__version__} "
    "(+https://github.com/WProduction/mrt-termin-monitor; "
    f"scientific study of MRI appointment availability; contact: {KONTAKT_MAIL})"
)

# Mindestabstand in Sekunden zwischen zwei Requests an denselben Host – gilt für
# jeden Request auf der Leitung (GET, die Lese-Requests des Zwillingsmoduls,
# Redirect-Hops und Wiederholungen). Die Zahl steht wörtlich im README-Abschnitt
# „Responsible use“; ein Test hält beide gleich. Weil die Hosts im Lauf wechseln,
# bleibt ein Gesamtlauf trotzdem bei wenigen Minuten.
REQUEST_DELAY_SECONDS = 10

# Diese Hosts werden NIE angefragt, inklusive aller Subdomains:
#   ctmr.expert – robots.txt "Disallow: /" (DBS/Dr. Kubin Schallmoos)
#   azs.at      – Buchungsportal desselben Instituts (termin.azs.at)
#   vera.care   – gemeinsame VERA-Plattform mit Instanz desselben Instituts
# Die Radiologie Doringer läuft über patient-portal.miranext.ai und ist nicht betroffen.
BLOCKED_HOSTS = ("ctmr.expert", "azs.at", "vera.care")

DEFAULT_TIMEOUT = 30.0  # Sekunden je Versuch

# Zusatz-Zertifikate neben den certifi-Wurzeln (Begründung im Kopf der Datei
# selbst): manche Institutsserver liefern ihr Zwischenzertifikat nicht mit, und
# requests holt es – anders als ein Browser – nicht selbst nach. Die Prüfung wird
# deshalb nie abgeschaltet, sondern das fehlende Glied ergänzt. Package-Data, weil
# nach ``pip install`` kein Repo-Ordner existiert und das cwd undefiniert ist.
EXTRA_CA = files("mrt_termin_monitor") / "extra-ca.pem"

# Kombiniertes Bundle, einmal je Prozess erzeugt: die Wurzeln bleiben die von
# certifi (wandern also mit dessen Updates mit), im Paket liegt nur der Zusatz.
# None = noch nicht erzeugt.
_ca_bundle_path: str | None = None

# Feste Grenzen der internen Schleifen – zusammen mit dem Budget der Schutz gegen
# Schleifen-Bugs.
_MAX_ATTEMPTS = 2  # max. 2 Versuche je URL
_RETRY_PAUSE_S = 2.0  # kurze Pause zwischen den Versuchen
_MAX_REDIRECT_HOPS = 5  # XR-WEB braucht 1 Hop; mehr ist verdächtig


class FetchError(Exception):
    """Basisfehler des fetch-Layers (auch: beide Versuche fehlgeschlagen)."""


class BlockedHostError(FetchError):
    """Anfrage an einen gesperrten Host – darf nie rausgehen."""


class BudgetExceededError(FetchError):
    """Request-Budget überschritten – Abbruch des Laufs."""


class CrossHostRedirectError(FetchError):
    """Redirect auf fremden Host – wird nicht verfolgt."""


@dataclass(frozen=True)
class FetchResult:
    """Roh-Ergebnis eines Requests: finale URL, Status, Bytes.

    Die Bytes archiviert der Aufrufer VOR jedem Parse-Versuch – deshalb roh und
    unangetastet, keine Dekodierung hier.
    """

    url: str
    status_code: int
    content: bytes


# Budget-Zustand: None = kein Budget gesetzt (Unittests des Layers selbst); die
# Orchestrierung setzt vor dem Lauf das aus der Config berechnete Soll.
# ponytail: modulglobaler Zustand reicht, weil der Lauf sequenziell und
# single-threaded ist; bei Parallelisierung Lock oder Zustand je Lauf-Objekt.
_budget: int | None = None
_request_count = 0

# Startzeit (time.monotonic) des letzten Requests je Host, für ``pace()``.
_last_request_at: dict[str, float] = {}


def set_budget(limit: int | None) -> None:
    """Setzt das Request-Soll und setzt den Zähler zurück.

    Args:
        limit: maximale Zahl von ``get()``-Aufrufen; ``None`` deaktiviert die
            Prüfung (nur für Tests, die Orchestrierung setzt immer ein Soll).
    """
    global _budget, _request_count
    _budget = limit
    _request_count = 0


def request_count() -> int:
    """Bisher gezählte ``get()``-Aufrufe seit dem letzten ``set_budget()``."""
    return _request_count


def ca_bundle() -> str | bool:
    """Liefert das Verifikationsziel für ``verify=`` (Pfad oder ``True``).

    Mit aktivem truststore prüft Windows zuerst gegen den System-Speicher; die
    Zertifikate dieses Bundles zieht truststore nur heran, wenn das scheitert.

    Returns:
        Pfad eines Bundles aus den certifi-Wurzeln plus ``extra-ca.pem``;
        ``True`` (requests-Default), falls die Package-Data fehlt. Abgeschaltet
        wird die Prüfung in keinem Fall.
    """
    global _ca_bundle_path
    if _ca_bundle_path is not None:
        return _ca_bundle_path
    if not EXTRA_CA.is_file():
        return True
    combined = Path(tempfile.gettempdir()) / "mrt-termin-monitor-ca-bundle.pem"
    # Bei jedem Prozessstart neu schreiben statt Alter zu vergleichen: die Datei ist
    # klein und kann so nicht veraltet zurückbleiben. certifi.contents() endet
    # bereits mit Zeilenumbruch, deshalb ohne Trenner.
    combined.write_text(
        certifi.contents() + EXTRA_CA.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _ca_bundle_path = str(combined)
    return _ca_bundle_path


def host_of(url: str) -> str:
    """Hostname einer absoluten URL.

    Raises:
        FetchError: URL ohne Host.
    """
    host = urlsplit(url).hostname
    if not host:
        raise FetchError(f"URL without host: {url!r}")
    return host


def check_blocked(host: str) -> None:
    """Wirft, wenn ``host`` oder eine seiner Eltern-Domains gesperrt ist.

    Raises:
        BlockedHostError: Host steht (als Domain oder Subdomain) in ``BLOCKED_HOSTS``.
    """
    # Subdomain-Treffer mitzählen (termin.azs.at), aber keine False Positives wie
    # "notazs.at".
    for blocked in BLOCKED_HOSTS:
        if host == blocked or host.endswith("." + blocked):
            raise BlockedHostError(f"host {host!r} is blocked, never queried")


def pace(host: str, delay: float) -> None:
    """Wartet, bis seit dem letzten Request an ``host`` ``delay`` Sekunden vergangen sind.

    Gemessen wird Start-zu-Start; der Aufruf vermerkt den jetzigen Request als
    letzten. Muss direkt vor jedem Request auf der Leitung stehen.

    Args:
        host: Ziel-Host des folgenden Requests.
        delay: Mindestabstand in Sekunden; Tests setzen ihn auf 0.
    """
    last = _last_request_at.get(host)
    if last is not None:
        wait = last + delay - time.monotonic()
        if wait > 0:
            # Im Log sichtbar, damit ein langer Lauf nicht wie ein Hänger aussieht.
            log.debug("pacing %s: waiting %.1f s", host, wait)
            time.sleep(wait)
    _last_request_at[host] = time.monotonic()


def get(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    extra_headers: dict[str, str] | None = None,
    session: requests.Session | None = None,
    delay: float = REQUEST_DELAY_SECONDS,
) -> FetchResult:
    """Führt einen GET aus.

    Args:
        url: Ziel-URL (absolut, mit Host).
        timeout: Timeout in Sekunden je Versuch.
        extra_headers: zusätzliche Header, z. B. Referer/Origin für MiraNext;
            überschreiben bei Kollision die Defaults.
        session: vorhandene Session (Wiederverwendung/Tests); ohne Angabe wird
            eine frische erzeugt.
        delay: Mindestabstand zum vorigen Request an denselben Host (Tests: 0).

    Returns:
        ``FetchResult`` mit finaler URL, Status und Roh-Bytes. Auch 4xx/5xx kommen
        zurück (der Aufrufer archiviert und entscheidet) – Exceptions gibt es nur
        für Guardrail-Verstöße und Netzfehler nach beiden Versuchen.

    Raises:
        BlockedHostError: Ziel ist ein gesperrter Host.
        BudgetExceededError: Request-Soll erreicht.
        CrossHostRedirectError: Redirect will den Host verlassen.
        FetchError: Netzfehler auch im zweiten Versuch.
    """
    global _request_count

    start_host = host_of(url)
    check_blocked(start_host)

    # Das Budget zählt logische Abrufe (ein Zähler je get()-Aufruf), nicht einzelne
    # Hops: das Soll wird aus der Task-Zahl der Config berechnet und kennt
    # Redirect-/Retry-Verhalten nicht. Aufrufer-Schleifen fängt das Budget, interne
    # Schleifen fangen die festen Grenzen oben.
    if _budget is not None and _request_count >= _budget:
        raise BudgetExceededError(
            f"request budget exhausted ({_request_count}/{_budget})"
        )
    _request_count += 1

    headers = {"User-Agent": USER_AGENT}
    if extra_headers:
        headers.update(extra_headers)

    sess = session if session is not None else requests.Session()

    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        if attempt > 0:
            time.sleep(_RETRY_PAUSE_S)
        try:
            return _get_following_same_host_redirects(
                sess, url, start_host, headers, timeout, delay
            )
        except requests.RequestException as exc:
            # Nur echte Netz-/Timeout-Fehler lösen den zweiten Versuch aus;
            # Guardrail-Exceptions (FetchError-Familie) fliegen sofort durch.
            last_error = exc
    raise FetchError(
        f"GET {url} failed after {_MAX_ATTEMPTS} attempts: {last_error}"
    ) from last_error


def _get_following_same_host_redirects(
    sess: requests.Session,
    url: str,
    start_host: str,
    headers: dict[str, str],
    timeout: float,
    delay: float,
) -> FetchResult:
    """Verfolgt Redirects manuell und lehnt Fremdhosts ab.

    Manuell statt ``allow_redirects=True``, weil requests sonst kommentarlos auf
    fremde Hosts folgen würde – der XR-WEB-``?para=``-302 bleibt aber auf demselben
    Host und ist genau der erlaubte Fall.
    """
    current_url = url
    for _ in range(_MAX_REDIRECT_HOPS + 1):
        pace(start_host, delay)
        resp = sess.get(
            current_url,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
            verify=ca_bundle(),
        )
        location = resp.headers.get("Location")
        if not (300 <= resp.status_code < 400 and location):
            # Kein Redirect (auch 4xx/5xx): finale Antwort, roh zurückgeben.
            return FetchResult(
                url=current_url, status_code=resp.status_code, content=resp.content
            )
        next_url = urljoin(current_url, location)
        if host_of(next_url) != start_host:
            raise CrossHostRedirectError(
                f"redirect from {current_url} to foreign host refused: {next_url}"
            )
        current_url = next_url
    raise FetchError(f"more than {_MAX_REDIRECT_HOPS} redirect hops for {url}")
