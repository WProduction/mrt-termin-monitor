# SPDX-License-Identifier: Apache-2.0
"""MiraNext-Adapter: Institut → je Untersuchung zwei GETs → Messzeilen.

Erst die Service-Zuordnung per Suchbegriff aus dem Katalog, dann die freien Slots
genau dieser Zuordnung. Die Zuordnungs-ID wird bei jedem Lauf neu aufgelöst statt
fest verdrahtet: nummeriert der Betreiber den Katalog um, misst der Lauf weiter
dieselbe Untersuchung; die Abweichung vom Erwartungswert steht dann im Hinweis.

Die Roh-Antworten gehen IMMER vor dem Parse-Versuch an ``archive``. Fehler einer
Abfrage brechen nie den Lauf ab; einzige Ausnahme ist das Request-Budget, das als
Schutz gegen Schleifen-Bugs den ganzen Lauf stoppen muss.
"""

import json
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from functools import partial
from urllib.parse import quote

from mrt_termin_monitor.fetch import http
from mrt_termin_monitor.model import Measurement, Status
from mrt_termin_monitor.parse import miranext as parse_miranext
from mrt_termin_monitor.sites import Site

log = logging.getLogger(__name__)

# Ein Host für alle Mandanten; der Mandant ist der Query-Parameter ``c_Id``. Der
# Parameter hieß früher ``id``; inzwischen beantwortet die API ``id=`` mit 403
# ``{"error": "invalid customer"}``. Kommt dieser Fehler wieder, im ausgelieferten
# Portal-Frontend nachsehen, welchen Namen es selbst sendet, statt zu raten.
_HOST = "patient-portal.miranext.ai"
_API_BASE = f"https://{_HOST}/api/booking"

# Die API verlangt Referer/Origin der Portalseite, ohne sie antwortet sie mit 403
# ``{"error": "forbidden"}`` – erster Kandidat, wenn plötzlich alles fehlschlägt.
# Das ist keine Zugangskontrolle: es gibt weder Schlüssel noch Token. Nie einen
# Authorization-Header setzen; verlangt der Betreiber künftig ein Token, wird das
# als Fehlerzeile sichtbar und ist eine bewusste Entscheidung, kein Workaround.
_HEADERS = {
    "Referer": f"https://{_HOST}/",
    "Origin": f"https://{_HOST}",
    "Accept": "application/json",
}

# Suchfenster der Slot-Abfrage in Tagen ab heute. Start und Ende sind
# Pflichtparameter (ohne sie: 422). Liegt der nächste Termin weiter weg, wird das
# „keine Termine“ statt einer Wartezeit über 90 Tagen.
_WINDOW_DAYS = 90

# Feste Slot-Parameter. Nur der Kassenpool: billing_public an, billing_private
# aus – der Privatpool läuft auf einem eigenen Gerät und wird nie abgefragt.
# contrast_fluid=false, weil das Knie ohne Kontrastmittel untersucht wird; eine
# Untersuchung mit Kontrastmittel braucht diesen Wert je Untersuchung.
_SLOT_FLAGS = (
    "&contrast_fluid=false&request_type=normal"
    "&billing_private=false&billing_public=true&online_booking=true"
)

# Empfänger der Roh-Antwort: (Dateiname, Bytes). Die Ablage selbst ist Sache des
# Aufrufers.
Archive = Callable[[str, bytes], None]


def task_count(site: Site) -> int:
    """Höchstzahl der GETs, die ``collect`` für dieses Institut ausführt.

    Je Untersuchung Katalog-Suche plus Slot-Abfrage. Scheitert die Katalog-Suche,
    entfällt die Slot-Abfrage; das Budget bleibt damit eine Obergrenze und wird im
    Gutfall exakt erreicht.
    """
    return 2 * len(site.exams)


def collect(
    site: Site, run_start: datetime, *, archive: Archive | None = None
) -> list[Measurement]:
    """Erhebt je Untersuchung des Instituts eine Messzeile.

    Args:
        site: validiertes Institut mit ``adapter: miranext``.
        run_start: Lauf-Start (lokal, naiv, minutengenau) für alle Zeilen.
        archive: erhält je Untersuchung ``<slug>_<untersuchung>_services.json``
            (Katalog) und ``<slug>_<untersuchung>.json`` (Slots) mit den Roh-Bytes,
            jeweils bevor geparst wird; ``None`` = nicht archivieren (Live-Probe).

    Returns:
        Messzeilen in der Reihenfolge von ``site.exams``; Fehler einer Abfrage
        erscheinen als Zeile mit Fehlerstatus und Grund in ``note``.

    Raises:
        http.BudgetExceededError: bricht den Lauf bewusst ab.
        Exception: was ``archive`` wirft, unverändert – ohne Archiv keine Evidenz.
    """
    params = site.params
    timeout = site.timeout_s if site.timeout_s is not None else http.DEFAULT_TIMEOUT
    get = partial(http.get, timeout=timeout, extra_headers=_HEADERS)

    rows: list[Measurement] = []
    for exam, values in site.exams.items():
        row = partial(
            Measurement,
            run_start=run_start,
            queried_at=datetime.now().astimezone(),
            site_id=site.slug,
            site_name=site.name,
            exam=exam,
            billing=site.billing,
        )

        # --- GET 1: Service-Zuordnung im Katalog suchen ---------------------
        services_url = (
            f"{_API_BASE}/service-assignments"
            f"?c_Id={params['portal_id']}&search={quote(values['search'], safe='')}"
        )
        try:
            result = get(services_url)
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
            archive(f"{site.slug}_{exam}_services.json", result.content)

        try:
            service = parse_miranext.resolve_service(
                result.content, values["service_name"], params["device"]
            )
        except Exception as exc:  # noqa: BLE001
            # Bewusst breit: Fehlerobjekt, kaputtes JSON oder Katalog-Drift. Der
            # HTTP-Status gehört in den Hinweis, weil die API Fehler als 4xx mit
            # JSON-Körper meldet.
            rows.append(
                row(
                    status=Status.ERROR_PARSE,
                    note=f"service lookup failed (HTTP {result.status_code}): {exc}",
                )
            )
            continue
        if service is None:
            rows.append(
                row(
                    status=Status.ERROR_PARSE,
                    note=(
                        f"no service assignment {values['service_name']!r}"
                        f" on device {params['device']!r}"
                        f" (HTTP {result.status_code})"
                    ),
                )
            )
            continue

        drift = ""
        if service.assignment_id != values["expected_id"]:
            # Kein Fehler: genau dafür wird aufgelöst. Sichtbar im Hinweis der
            # CSV-Zeile, damit der Erwartungswert nachgezogen wird; im Log nur DEBUG,
            # weil die Konsole nur deutsche Sätze aus ``messages`` zeigt.
            drift = (
                f"service id drift: expected {values['expected_id']},"
                f" resolved {service.assignment_id} (measured with resolved id)"
            )
            log.debug("%s: %s", site.slug, drift)

        # --- GET 2: freie Slots der aufgelösten Zuordnung -------------------
        start = date.today()
        end = start + timedelta(days=_WINDOW_DAYS)
        schedules = quote(json.dumps([service.assignment_id]), safe="")
        slots_url = (
            f"{_API_BASE}/slot/get_available_time_list_with_date"
            f"?c_Id={params['portal_id']}"
            f"&schedules_list={schedules}"
            f"&adjustable_buffer_time={service.adjustable_buffer_time}"
            f"{_SLOT_FLAGS}&start_date={start}&end_date={end}"
        )
        try:
            result = get(slots_url)
        except http.BudgetExceededError:
            raise
        except http.CrossHostRedirectError as exc:
            rows.append(row(status=Status.ERROR_REDIRECT, note=_join(drift, exc)))
            continue
        except http.FetchError as exc:
            rows.append(row(status=Status.NOT_COLLECTED, note=_join(drift, exc)))
            continue

        if archive is not None:
            archive(f"{site.slug}_{exam}.json", result.content)

        try:
            parsed = parse_miranext.parse_slots(result.content, service.assignment_id)
            note = drift
            if parsed.status is Status.ERROR_PARSE:
                # Ohne Exception steht der Grund sonst nur im Archiv.
                note = _join(
                    drift, f"unexpected slot response (HTTP {result.status_code})"
                )
            # Im try: Measurement lehnt z. B. ein Datum vor dem Lauf-Tag ab – auch
            # das ist eine unerwartete Antwort und wird eine Fehlerzeile.
            rows.append(
                row(status=parsed.status, slot_date=parsed.slot_date, note=note)
            )
        except Exception as exc:  # noqa: BLE001
            # Bewusst breit: unbekannte Struktur kann jede Exception auslösen.
            # Fehlerzeile statt Laufabbruch; die Roh-Antwort liegt schon im Archiv.
            rows.append(
                row(
                    status=Status.ERROR_PARSE,
                    note=_join(drift, f"parser exception: {exc}"),
                )
            )
    return rows


def _join(*parts: object) -> str:
    """Verbindet nicht-leere Hinweis-Teile mit ``; ``.

    Ein ID-Drift darf den eigentlichen Fehlergrund nicht verdecken und umgekehrt.
    """
    return "; ".join(str(p) for p in parts if str(p))
