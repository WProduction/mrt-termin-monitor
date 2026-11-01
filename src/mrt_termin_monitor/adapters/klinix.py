# SPDX-License-Identifier: Apache-2.0
"""klinix-Adapter (Diagnostikum-Portale): Institut → ein GET je Untersuchung.

Die Portale bieten eine öffentliche, anonyme GET-Route, die den nächsten freien
Termin eines Untersuchungscodes direkt als JSON-String liefert::

    GET https://<host>/services/klinixservice/api/public/
        appointment-slot/first-available-slot-time?exas=<code>
    -> "2099-01-15T07:45:00"   (Termin)   |   leerer Body (kein Termin)

Die Antwort ist schon der Messwert; die Auswertung sind wenige Zeilen mit der
Standardbibliothek und steht deshalb hier statt in einem eigenen Parser-Modul.
Wie bei XR-WEB geht die Roh-Antwort IMMER vor der Auswertung an ``archive``, und
Fehler einer Abfrage brechen nie den Lauf ab – außer dem Request-Budget.
"""

import json
from collections.abc import Callable
from datetime import date, datetime
from functools import partial
from urllib.parse import quote

from mrt_termin_monitor.fetch import http
from mrt_termin_monitor.model import Measurement, Status
from mrt_termin_monitor.sites import Site

_SLOT_PATH = (
    "/services/klinixservice/api/public/appointment-slot/first-available-slot-time"
)

# Ein leerer Body heißt nur „die Route liefert keinen Zeitstempel“. Meist ist das
# „kein freier Termin“, es kann aber auch ein serverseitig unbekannter oder
# umbenannter Code sein – die Antwort unterscheidet beides nicht. Damit ein solcher
# Code-Drift nicht unbemerkt als Dauer-„keine Termine“ durchläuft, steht der
# Vorbehalt in jeder dieser Zeilen.
_NOTE_NO_SLOTS = "empty response: no free slot or exas code unknown to server"

# Empfänger der Roh-Antwort: (Dateiname, Bytes). Die Ablage selbst ist Sache des
# Aufrufers.
Archive = Callable[[str, bytes], None]


def task_count(site: Site) -> int:
    """Zahl der GETs, die ``collect`` für dieses Institut ausführt.

    Die Orchestrierung summiert das zum Request-Budget; die Rechnung muss deshalb
    exakt der Schleife in ``collect`` entsprechen (ein GET je Untersuchung, kein
    Katalog- oder Session-Vorabruf).
    """
    return len(site.exams)


def collect(
    site: Site, run_start: datetime, *, archive: Archive | None = None
) -> list[Measurement]:
    """Erhebt je Untersuchung des Instituts eine Messzeile.

    Args:
        site: validiertes Institut mit ``adapter: klinix``.
        run_start: Lauf-Start (lokal, naiv, minutengenau) für alle Zeilen.
        archive: erhält je Antwort ``<slug>_<untersuchung>.json`` und die
            Roh-Bytes, bevor ausgewertet wird – auch bei HTTP-Fehlerstatus;
            ``None`` = nicht archivieren (Live-Probe).

    Returns:
        Messzeilen in der Reihenfolge von ``site.exams``; Fehler einer Abfrage
        erscheinen als Zeile mit Fehlerstatus und Grund in ``note``.

    Raises:
        http.BudgetExceededError: bricht den Lauf bewusst ab.
        Exception: was ``archive`` wirft, unverändert – ohne Archiv keine Evidenz.
    """
    host = site.params["host"]
    timeout = site.timeout_s if site.timeout_s is not None else http.DEFAULT_TIMEOUT

    rows: list[Measurement] = []
    for exam, values in site.exams.items():
        # Code percent-encoden, Groß-/Kleinschreibung unverändert aus der Config.
        url = f"https://{host}{_SLOT_PATH}?exas={quote(values['code'], safe='')}"

        # Alles außer Status, Termin und Hinweis steht vor dem Request fest.
        row = partial(
            Measurement,
            run_start=run_start,
            queried_at=datetime.now().astimezone(),
            site_id=site.slug,
            site_name=site.name,
            exam=exam,
            billing=site.billing,
        )

        try:
            result = http.get(url, timeout=timeout)
        except http.BudgetExceededError:
            raise
        except http.CrossHostRedirectError as exc:
            rows.append(row(status=Status.ERROR_REDIRECT, note=str(exc)))
            continue
        except http.FetchError as exc:
            # Netz- oder Guardrail-Fehler ohne Antwort: nichts erhoben.
            rows.append(row(status=Status.NOT_COLLECTED, note=str(exc)))
            continue

        if archive is not None:
            archive(f"{site.slug}_{exam}.json", result.content)

        # Anders als bei XR-WEB zählt der Status: ein 503 oder ein 3xx ohne
        # Location kommt oft mit leerem Body – ungeprüft sähe das genau wie
        # „kein Termin“ aus und wäre ein stiller Messfehler über die ganze Studie.
        # Bewusste Abweichung vom POC, der nur >= 400 abfing: auch 1xx und ein
        # 3xx ohne Location (der HTTP-Client reicht ihn als finale Antwort durch)
        # sind keine verwertbare Auskunft und werden deshalb Fehlerzeilen.
        if not 200 <= result.status_code < 300:
            rows.append(
                row(
                    status=Status.ERROR_PARSE,
                    note=f"HTTP {result.status_code} from {host}",
                )
            )
            continue

        try:
            slot_date = _slot_date(result.content)
            # Im try: Measurement lehnt z. B. ein Datum vor dem Lauf-Tag ab – auch
            # das ist eine unerwartete Antwort und wird eine Fehlerzeile.
            if slot_date is None:
                rows.append(row(status=Status.NO_SLOTS, note=_NOTE_NO_SLOTS))
            else:
                rows.append(row(status=Status.OK, slot_date=slot_date))
        except Exception as exc:  # noqa: BLE001
            # Bewusst breit: eine geänderte Antwortform kann Decode-, JSON- oder
            # Datumsfehler auslösen. Fehlerzeile statt Laufabbruch; die Roh-Antwort
            # liegt schon im Archiv.
            rows.append(row(status=Status.ERROR_PARSE, note=f"parser exception: {exc}"))
    return rows


def _slot_date(content: bytes) -> date | None:
    """Wertet die Roh-Antwort aus.

    Args:
        content: Roh-Bytes der Antwort (JSON-String oder leer).

    Returns:
        Datumsanteil des nächsten freien Termins; ``None`` bei leerem Body, JSON
        ``null`` oder leerem JSON-String (= kein Termin).

    Raises:
        ValueError: Body ist kein UTF-8, kein JSON oder kein ISO-Zeitstempel
            (``UnicodeDecodeError`` und ``json.JSONDecodeError`` sind ValueErrors).
        TypeError: JSON-Wert ist kein String. Bewusst streng: ``0``, ``false``,
            ``[]`` oder ``{}`` sind kein „kein Termin“, sondern eine geänderte
            Schnittstelle und müssen als Fehler auffallen.
    """
    text = content.decode("utf-8").strip()
    if not text:
        return None
    value = json.loads(text)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise TypeError(f"expected a JSON string, got {type(value).__name__}")
    # fromisoformat statt Abschneiden nach 10 Zeichen: ein geändertes
    # Zeitstempel-Format fällt so als Fehler auf, statt falsch geschnitten zu werden.
    return datetime.fromisoformat(value).date()
