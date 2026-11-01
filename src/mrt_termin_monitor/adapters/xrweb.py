# SPDX-License-Identifier: Apache-2.0
"""XR-WEB-Adapter (D.A.T.A.): Institut → ein GET je Untersuchung → Messzeilen.

Die Roh-Antwort geht IMMER vor dem Parse-Versuch an ``archive``, damit eine
Format-Änderung des Portals später am Archiv nachvollziehbar bleibt. Fehler einer
Abfrage brechen nie den Lauf ab; einzige Ausnahme ist das Request-Budget, das als
Schutz gegen Schleifen-Bugs den ganzen Lauf stoppen muss.
"""

from collections.abc import Callable
from datetime import datetime
from functools import partial
from urllib.parse import quote

from mrt_termin_monitor.fetch import http
from mrt_termin_monitor.model import Measurement, Status
from mrt_termin_monitor.parse import xrweb as parse_xrweb
from mrt_termin_monitor.sites import Site

# XR-WEB behandelt den Pfad case-insensitiv (manche Mandanten verlinken
# „DirectAppointmentSearch“); einheitlich diese Form.
_SEARCH_PATH = "/AppointmentSearch/directAppointmentSearch"

# Empfänger der Roh-Antwort: (Dateiname, Bytes). Die Ablage selbst ist Sache des
# Aufrufers.
Archive = Callable[[str, bytes], None]


def task_count(site: Site) -> int:
    """Zahl der GETs, die ``collect`` für dieses Institut ausführt.

    Die Orchestrierung summiert das zum Request-Budget; die Rechnung muss deshalb
    exakt der Schleife in ``collect`` entsprechen.
    """
    return len(site.exams)


def collect(
    site: Site, run_start: datetime, *, archive: Archive | None = None
) -> list[Measurement]:
    """Erhebt je Untersuchung des Instituts eine Messzeile.

    Args:
        site: validiertes Institut mit ``adapter: xrweb``.
        run_start: Lauf-Start (lokal, naiv, minutengenau) für alle Zeilen.
        archive: erhält je Antwort ``<slug>_<untersuchung>.html`` und die
            Roh-Bytes, bevor geparst wird; ``None`` = nicht archivieren
            (Live-Probe).

    Returns:
        Messzeilen in der Reihenfolge von ``site.exams``; Fehler einer Abfrage
        erscheinen als Zeile mit Fehlerstatus und Grund in ``note``.

    Raises:
        http.BudgetExceededError: bricht den Lauf bewusst ab.
        Exception: was ``archive`` wirft, unverändert – ohne Archiv keine Evidenz.
    """
    params = site.params
    timeout = site.timeout_s if site.timeout_s is not None else http.DEFAULT_TIMEOUT

    rows: list[Measurement] = []
    for exam, values in site.exams.items():
        # Code percent-encoden (Codes mit Leerzeichen kommen vor), Groß-/Klein-
        # schreibung unverändert aus der Config übernehmen.
        url = (
            f"https://{params['host']}{_SEARCH_PATH}"
            f"?exas={quote(values['code'], safe='')}"
        )
        if "site_param" in params:
            url += f"&Site={quote(params['site_param'], safe='')}"

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
            archive(f"{site.slug}_{exam}.html", result.content)

        try:
            parsed = parse_xrweb.parse(
                result.content,
                values["expected_title"],
                params["day_table_columns"],
                result.url,
            )
            # Im try: Measurement lehnt z. B. ein Datum vor dem Lauf-Tag ab – auch
            # das ist eine unerwartete Antwort und wird eine Fehlerzeile.
            rows.append(row(status=parsed.status, slot_date=parsed.slot_date))
        except Exception as exc:  # noqa: BLE001
            # Bewusst breit: unbekanntes Markup kann jede Exception auslösen.
            # Fehlerzeile statt Laufabbruch; die Roh-Antwort liegt schon im Archiv.
            rows.append(row(status=Status.ERROR_PARSE, note=f"parser exception: {exc}"))
    return rows
