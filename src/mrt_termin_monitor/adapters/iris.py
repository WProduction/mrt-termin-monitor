# SPDX-License-Identifier: Apache-2.0
"""IRIS-Adapter (Lukassoftware, InterSystems-IRIS-Backend): anonyme Session → Messzeilen.

Der Lesepfad braucht keine SVNR; der Kalender ist nach einer anonymen Session lesbar::

    1. POST <base_url>/api/session                         -> Bearer-Token
    2. GET  <base_url>/iris/getOnlineTerminList?Kategorie=…  -> Katalog
    3. GET  <base_url>/iris/getTerminartenForUntersuchung?…  -> Terminarten
    4. GET  <base_url>/iris/getFreieTermineForTerminart?…    -> freie Termine

Drei Eigenheiten des Portals bestimmen den Aufbau:

* Der Katalog führt den Klartext in ``Bezeichnung`` (mit angehängtem Leerzeichen)
  und die Seite in ``Lateralität``. Beide allein sind mehrdeutig – „Knie“ trifft
  links, rechts und beidseits –, deshalb läuft das ``pattern`` der Config gegen
  „Bezeichnung Lateralität“, also den Text, den auch ein Patient liest, und muss
  genau einen Eintrag treffen.
* Welche Terminart der Portal-Client für eine Untersuchung nimmt, steht nicht im
  ausgelieferten Code. Der Adapter fragt deshalb alle Terminarten der Untersuchung
  ab (höchstens ``_MAX_TERMINARTEN``) und misst das früheste Datum über alle – eine
  definierte Messgröße ohne die unbekannte Client-Regel.
* Kalender- und Ressourcen-ID führt der Katalog nicht; sie stehen nur im
  Client-Code des Mandanten und kommen deshalb aus der Config.

Fehler einer Abfrage brechen nie den Lauf ab; durchgereicht werden nur
``BudgetExceededError`` (Schutz gegen Schleifen-Bugs) und Fehler des
``archive``-Callbacks (ohne Archiv keine Evidenz). Jede Antwort geht vor dem
Parse-Versuch ans Archiv – mit einer Ausnahme: die erfolgreiche Session-Antwort
enthält das Bearer-Token und wird nie abgelegt. Das Token erscheint auch nie in
Log, Hinweis oder Exception-Text.
"""

import json
import logging
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any
from urllib.parse import urlencode

from mrt_termin_monitor.fetch import http, post
from mrt_termin_monitor.model import Exam, Measurement, Status
from mrt_termin_monitor.sites import Site

log = logging.getLogger(__name__)

# Empfänger der Roh-Antwort: (Dateiname, Bytes). Die Ablage selbst ist Sache des
# Aufrufers. Bewusst dupliziert statt aus einem anderen Adapter importiert: die
# Adapter sollen unabhängig voneinander bleiben.
Archive = Callable[[str, bytes], None]

# $HOROLOG-Epoche von InterSystems: Tag 0 ist der 31.12.1840. Das Portal zählt
# Daten in Tagen seit dieser Epoche, Uhrzeiten in Sekunden seit Mitternacht.
_HOROLOG_EPOCH = date(1840, 12, 31)

# Zeitfenster in Sekunden seit Mitternacht (06:00 bis 19:26:40), wörtlich wie der
# Client des ersten angebundenen Mandanten fragt. Nicht „ganzer Tag“: gemessen wird,
# was ein Patient angeboten bekommt. Ein anderer Mandant fragt 06:10–19:10; seine
# beobachteten Termine liegen in beiden Fenstern, daher gilt ein Fenster für alle.
# Taucht je ein Termin nur in einem der Randstreifen auf, gehört das Fenster je
# Mandant in die Config.
_VON_ZEIT = 21600
_BIS_ZEIT = 70000

# Obergrenze der Slots je Antwort. Das Portal sortiert nach Ressource und erst dann
# nach Datum und kürzt bei Anzahl+1 Einträgen. Mit zwei Ressourcen in einem Request
# (``A,B``) läge das früheste Datum der zweiten Ressource sonst hinter der
# Schnittkante, und das Minimum wäre still zu spät. Deshalb deutlich mehr als die
# Clients fragen, und eine Antwort, die die Grenze erreicht, wird zur Fehlerzeile
# (``_earliest``). Wird der Horizont verlängert oder kommt eine Ressource dazu, die
# Slot-Zahl erneut gegen diese Grenze prüfen.
_ANZAHL = 5000

# Höchstens drei Terminarten je Untersuchung: mehr kennt das Datenmodell des Clients
# nicht (Terminart/Terminart2/Terminart3). Die Zahl geht in ``task_count`` ein; mehr
# Kandidaten werden deshalb ein Fehler statt einer stillen Kürzung.
_MAX_TERMINARTEN = 3

# Terminart-IDs landen im Archiv-Dateinamen; nur harmlose Zeichen zulassen, damit
# eine fremde Antwort keinen Pfad bauen kann.
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]+")

_NOTE_NO_SLOTS = "empty slot list within horizon: no free slot or not bookable online"


class _Failure(Exception):
    """Abfrage gescheitert: Status und Hinweis der Fehlerzeile.

    Trägt nur Texte ohne Token, weil ``note`` in die CSV geht.
    """

    def __init__(self, status: Status, note: str) -> None:
        super().__init__(note)
        self.status = status
        self.note = note


def task_count(site: Site) -> int:
    """Obergrenze der Requests (POST + GET), die ``collect`` ausführt.

    Session und Katalog einmal, je Untersuchung ein Terminarten-Abruf und bis zu
    ``_MAX_TERMINARTEN`` Slot-Abrufe. Die tatsächliche Zahl steht erst zur Laufzeit
    fest (Zahl der Terminarten); ``collect`` lehnt mehr Kandidaten vor dem ersten
    Slot-Request ab, daher liegt sie nie darüber.
    """
    return 2 + len(site.exams) * (1 + _MAX_TERMINARTEN)


def collect(
    site: Site, run_start: datetime, *, archive: Archive | None = None
) -> list[Measurement]:
    """Erhebt je Untersuchung des Instituts eine Messzeile.

    Args:
        site: validiertes Institut mit ``adapter: iris``.
        run_start: Lauf-Start (lokal, naiv, minutengenau) für alle Zeilen; der
            Suchhorizont beginnt am Tag danach, wie im Portal-Client.
        archive: erhält je Antwort Dateiname und Roh-Bytes, bevor geparst wird
            (``<slug>_catalogue.json``, ``<slug>_<untersuchung>_appointment_types.json``,
            ``<slug>_<untersuchung>_<terminart>.json``; ``<slug>_session.json`` nur
            bei einer gescheiterten Session ohne Token); ``None`` = nicht
            archivieren (Live-Probe).

    Returns:
        Messzeilen in der Reihenfolge von ``site.exams``. Scheitern Session oder
        Katalog, bekommt jede Untersuchung dieselbe Fehlerzeile.

    Raises:
        http.BudgetExceededError: bricht den Lauf bewusst ab.
        Exception: was ``archive`` wirft, unverändert – ohne Archiv keine Evidenz.
    """
    params = site.params
    base = params["base_url"].rstrip("/")
    timeout = site.timeout_s if site.timeout_s is not None else http.DEFAULT_TIMEOUT

    # ``queried_at`` wird vor den Requests genommen, nicht beim Bau der Zeile.
    def row(exam: Exam, queried_at: datetime, **fields: Any) -> Measurement:
        return Measurement(
            run_start=run_start,
            queried_at=queried_at,
            site_id=site.slug,
            site_name=site.name,
            exam=exam,
            billing=site.billing,
            **fields,
        )

    started = datetime.now().astimezone()
    try:
        token = _session_token(base, timeout, site.slug, archive)
        # Das Token lebt nur in diesem Header; die URL und jeder Hinweis bleiben frei.
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        url = f"{base}/iris/getOnlineTerminList?" + urlencode(
            {"Kategorie": params["kategorie"]}
        )
        result = _get(url, headers, timeout, "catalogue")
        if archive is not None:
            archive(f"{site.slug}_catalogue.json", result.content)
        catalogue = _parsed("catalogue", partial(_json_list, result))
    except _Failure as failure:
        return [
            row(exam, started, status=failure.status, note=failure.note)
            for exam in site.exams
        ]

    # Wie der Client: ab morgen, bis zum Horizont. Basis ist der Lauf-Tag, nicht
    # „heute“, damit alle Zeilen eines Laufs dieselbe Basis haben.
    von = run_start.date() + timedelta(days=1)
    bis = von + timedelta(days=params["horizon_days"])

    rows: list[Measurement] = []
    for exam, values in site.exams.items():
        measure = partial(row, exam, datetime.now().astimezone())
        try:
            earliest, note = _query_exam(
                site,
                base,
                exam,
                values["pattern"],
                catalogue,
                headers,
                timeout,
                (von, bis),
                archive,
            )
        except _Failure as failure:
            rows.append(measure(status=failure.status, note=failure.note))
            continue
        try:
            if earliest is None:
                rows.append(
                    measure(status=Status.NO_SLOTS, note=f"{_NOTE_NO_SLOTS}; {note}")
                )
            else:
                rows.append(measure(status=Status.OK, slot_date=earliest, note=note))
        except ValueError:
            # Measurement lehnt ein Datum vor dem Lauf-Tag ab – eine unerwartete
            # Antwort, also Fehlerzeile statt Laufabbruch.
            rows.append(
                measure(
                    status=Status.ERROR_PARSE,
                    note=f"slot date {earliest} before run day; {note}",
                )
            )
    return rows


def _query_exam(
    site: Site,
    base: str,
    exam: Exam,
    pattern: str,
    catalogue: list,
    headers: dict[str, str],
    timeout: float,
    window: tuple[date, date],
    archive: Archive | None,
) -> tuple[date | None, str]:
    """Terminarten und Slots einer Untersuchung → (frühestes Datum, Hinweis).

    Scheitert ein einzelner Terminart-Kandidat, scheitert die ganze Untersuchung:
    das Minimum über die übrigen wäre womöglich zu spät, und das fiele in der CSV
    niemandem auf.

    Raises:
        _Failure: jede Abweichung, mit Status und Hinweis der Fehlerzeile.
    """
    params = site.params
    entry = _parsed(
        "exam selection",
        partial(_select_exam, catalogue, pattern, params["kategorie"]),
    )
    label = _label(entry)
    untersuchung = _parsed(f"{label}: catalogue entry", partial(_code, entry))

    url = f"{base}/iris/getTerminartenForUntersuchung?" + urlencode(
        {"Untersuchung": untersuchung}
    )
    result = _get(url, headers, timeout, "appointment types")
    if archive is not None:
        archive(f"{site.slug}_{exam}_appointment_types.json", result.content)
    types = _parsed("appointment types", partial(_type_ids, result))

    earliest: date | None = None
    findings: list[str] = []
    for type_id in types:
        query = {
            "Kalender": params["kalender"],
            # Unverändert durchgereicht: ``A,B`` wird zu ``Ressource=A%2CB`` – genau
            # so fragt der Portal-Client beide Geräte eines Pools in einem Request.
            "Ressource": params["ressource"],
            "VonDatum": _horolog(window[0]),
            "BisDatum": _horolog(window[1]),
            "VonZeit": _VON_ZEIT,
            "BisZeit": _BIS_ZEIT,
            "Terminart": type_id,
            "Anzahl": _ANZAHL,
        }
        url = f"{base}/iris/getFreieTermineForTerminart?" + urlencode(query)
        log.debug("%s/%s: %s", site.slug, exam, url)
        result = _get(url, headers, timeout, f"slots[{type_id}]")
        # Die Terminart gehört in den Dateinamen, sonst überschriebe der zweite
        # Kandidat den ersten.
        if archive is not None:
            archive(f"{site.slug}_{exam}_{type_id}.json", result.content)
        day = _parsed(f"slots[{type_id}]", partial(_slot_day, result))
        # Je Kandidat festhalten: sonst ist bei einem strittigen Datum nicht mehr
        # zu sehen, welche Terminart es geliefert hat.
        log.debug("%s/%s: %s -> %s", site.slug, exam, type_id, day)
        findings.append(f"{type_id}={day.isoformat() if day else '-'}")
        if day is not None and (earliest is None or day < earliest):
            earliest = day
    return earliest, f"{label} [{', '.join(findings)}]"


def _session_token(
    base: str, timeout: float, slug: str, archive: Archive | None
) -> str:
    """Holt ein anonymes Bearer-Token.

    Raises:
        http.BudgetExceededError: durchgereicht.
        _Failure: ``NOT_COLLECTED`` ohne Antwort, ``ERROR_PARSE`` bei einer
            Antwort ohne Token – auch ein HTTP 401 ist nie „keine Termine“.
    """
    payload = {
        "action": "create",
        # metadata wie der Client sie beim Seitenaufruf sendet; ohne userId, weil
        # anonym gelesen wird.
        "metadata": {
            "type": "anonymous",
            "timestamp": int(datetime.now().timestamp() * 1000),
            "userAgent": http.USER_AGENT,
        },
    }
    try:
        result = post.json_post(f"{base}/api/session", payload, timeout=timeout)
    except http.BudgetExceededError:
        raise
    except http.FetchError as exc:
        # Netz-, Guardrail- oder Whitelist-Fehler ohne Antwort: nichts erhoben.
        raise _Failure(Status.NOT_COLLECTED, f"session: {exc}") from exc

    success, token = _session_fields(result.content)
    if result.status_code < 400 and success and token is not None:
        return token
    # Archiviert wird nur eine Antwort ohne Token; trägt sie doch eines, bleibt die
    # Fehlerzeile unbelegt – das Token im Archiv wäre das größere Übel.
    if token is None and archive is not None:
        archive(f"{slug}_session.json", result.content)
    reason = (
        f"HTTP {result.status_code}"
        if result.status_code >= 400
        else "response without success flag or token"
    )
    raise _Failure(Status.ERROR_PARSE, f"session: {reason}")


def _session_fields(content: bytes) -> tuple[bool, str | None]:
    """(success-Flag, Token oder None) aus der Session-Antwort, ohne zu werfen."""
    try:
        data = json.loads(content)
    except ValueError:
        return False, None
    if not isinstance(data, dict):
        return False, None
    token = data.get("token")
    return bool(data.get("success")), token if isinstance(
        token, str
    ) and token else None


def _get(
    url: str, headers: dict[str, str], timeout: float, what: str
) -> http.FetchResult:
    """GET mit dem Fehler-Mapping des Adapters.

    Raises:
        http.BudgetExceededError: durchgereicht.
        _Failure: ``ERROR_REDIRECT`` bei Fremd-Host-Redirect, ``NOT_COLLECTED``
            bei jedem anderen Fetch-Fehler (keine Antwort, nichts zu archivieren).
    """
    try:
        return http.get(url, timeout=timeout, extra_headers=headers)
    except http.BudgetExceededError:
        raise
    except http.CrossHostRedirectError as exc:
        raise _Failure(Status.ERROR_REDIRECT, f"{what}: {exc}") from exc
    except http.FetchError as exc:
        raise _Failure(Status.NOT_COLLECTED, f"{what}: {exc}") from exc


def _parsed[T](what: str, parse: Callable[[], T]) -> T:
    """Führt einen Parse-Schritt aus; jede Exception wird ``ERROR_PARSE``.

    Bewusst breit: eine fremde Antwortform kann jede Exception auslösen. Der
    Archiv-Aufruf liegt immer außerhalb, damit dessen Fehler durchgereicht werden.
    """
    try:
        return parse()
    except Exception as exc:
        raise _Failure(Status.ERROR_PARSE, f"{what}: {exc}") from exc


def _json_list(result: http.FetchResult) -> list:
    """JSON-Liste einer Antwort; HTTP-Fehler und jede andere Form werfen."""
    if result.status_code >= 400:
        raise ValueError(f"HTTP {result.status_code}")
    data = json.loads(result.content)
    if not isinstance(data, list):
        raise TypeError(f"response is a JSON {type(data).__name__}, not a list")
    return data


def _slot_day(result: http.FetchResult) -> date | None:
    """Frühestes Datum einer Slot-Antwort (siehe ``_earliest``)."""
    return _earliest(_json_list(result))


def _label(entry: dict) -> str:
    """Suchtext eines Katalogeintrags: Klartext plus Seite („Knie rechts“).

    Die Normalisierung ist nicht kosmetisch: ``Bezeichnung`` trägt im Katalog ein
    angehängtes Leerzeichen, sonst entstünde „Knie  rechts“ und kein Pattern träfe.
    """
    raw = f"{entry.get('Bezeichnung', '')} {entry.get('Lateralität', '')}"
    return " ".join(raw.split())


def _select_exam(catalogue: list, pattern: str, kategorie: str) -> dict:
    """Genau ein Katalogeintrag der Modalität ``kategorie``, dessen Label passt.

    Raises:
        ValueError: kein oder mehr als ein Treffer; die Meldung listet die
            Kandidaten, damit das Pattern ohne zweiten Lauf korrigierbar ist.
    """
    regex = re.compile(pattern, re.IGNORECASE)
    # Ein CT-Eintrag mit gleichem Text darf nie getroffen werden.
    candidates = [
        e
        for e in catalogue
        if isinstance(e, dict) and str(e.get("Modality", "")) == kategorie
    ]
    hits = [e for e in candidates if regex.search(_label(e))]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        names = "; ".join(_label(e) for e in candidates) or "(none)"
        raise ValueError(
            f"pattern {pattern!r} matches no {kategorie} exam; available: {names}"
        )
    raise ValueError(
        f"pattern {pattern!r} matches {len(hits)} exams, must be exactly one: "
        + "; ".join(_label(e) for e in hits)
    )


def _code(entry: dict) -> str:
    """Untersuchungscode des Katalogeintrags (Schlüssel für die Terminarten)."""
    code = entry.get("Untersuchung")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("catalogue entry without 'Untersuchung'")
    return code


def _type_ids(result: http.FetchResult) -> list[str]:
    """Terminart-IDs in Antwortreihenfolge.

    Raises:
        ValueError: keine, mehr als ``_MAX_TERMINARTEN`` oder unsichere IDs. Mehr
            Kandidaten bewusst als Fehler statt Kürzung: die Kürzung könnte genau
            die Terminart mit dem frühesten Termin unterschlagen.
    """
    ids = [
        str(e["ID"]) for e in _json_list(result) if isinstance(e, dict) and e.get("ID")
    ]
    if not ids:
        raise ValueError("no appointment type")
    if len(ids) > _MAX_TERMINARTEN:
        raise ValueError(
            f"{len(ids)} appointment types ({', '.join(ids)}), "
            f"budget covers {_MAX_TERMINARTEN}"
        )
    unsafe = [i for i in ids if not _SAFE_ID.fullmatch(i)]
    if unsafe:
        raise ValueError(f"unexpected appointment type ids {unsafe!r}")
    return ids


def _earliest(slots: list) -> date | None:
    """Frühestes Datum einer Slot-Liste; ``None`` bei leerer Liste.

    Raises:
        ValueError: Liste erreicht ``_ANZAHL`` (abgeschnitten, das Minimum der
            zweiten Ressource könnte fehlen) oder ein Slot ohne ``Datum`` –
            Format-Drift muss alarmieren, nie still „kein Termin“ werden.
    """
    if not slots:
        return None
    if len(slots) >= _ANZAHL:
        raise ValueError(
            f"slot list truncated ({len(slots)} slots at Anzahl={_ANZAHL}), "
            "earliest date unreliable"
        )
    days = []
    for slot in slots:
        if not isinstance(slot, dict) or "Datum" not in slot:
            raise ValueError("slot without 'Datum'")
        days.append(_from_horolog(slot["Datum"]))
    return min(days)


def _horolog(day: date) -> int:
    """Datum → $HOROLOG-Tagesnummer."""
    return (day - _HOROLOG_EPOCH).days


def _from_horolog(value: int | str) -> date:
    """$HOROLOG-Tagesnummer (Zahl oder Ziffern-String) → Datum."""
    return _HOROLOG_EPOCH + timedelta(days=int(value))
