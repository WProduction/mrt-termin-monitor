# SPDX-License-Identifier: Apache-2.0
"""Doctena-Adapter: Institut → ein GET je Untersuchung auf agendaSlot → Messzeilen.

Doctena liefert die freien Slots eines Kalenders (``doctor``) für einen
Besuchsgrund (``reason``) als HAL+JSON, ohne Session, Cookie oder Token. Die
Roh-Antwort geht IMMER vor dem Parse-Versuch an ``archive``, damit eine
Format-Änderung später am Archiv nachvollziehbar bleibt. Fehler einer Abfrage
brechen nie den Lauf ab; einzige Ausnahme ist das Request-Budget, das als Schutz
gegen Schleifen-Bugs den ganzen Lauf stoppen muss.
"""

from collections.abc import Callable
from datetime import datetime, time, timedelta
from functools import partial

from mrt_termin_monitor.fetch import http
from mrt_termin_monitor.model import Measurement, Status
from mrt_termin_monitor.parse import doctena as parse_doctena
from mrt_termin_monitor.sites import Site

_API_URL = "https://api.doctena.at/agendaSlot"

# Suchfenster ab Lauf-Tag 00:00 lokal. Bei deutlich größeren Fenstern (120 Tage
# geprüft) liefert die API still eine leere Slot-Liste statt eines Fehlers – das
# wäre jede Woche ein falsches „keine Termine“. Folge: „keine Termine“ heißt hier
# nur „kein Termin innerhalb dieses Fensters“; der Hinweis der Zeile sagt das.
_WINDOW_DAYS = 30

# Referer so, wie ihn das Buchungs-Widget im Browser sendet; mehr verlangt die
# API nicht. Der User-Agent kommt aus dem fetch-Layer.
_EXTRA_HEADERS = {"Referer": "https://www.doctena.at/"}

# Empfänger der Roh-Antwort: (Dateiname, Bytes). Die Ablage selbst ist Sache des
# Aufrufers.
Archive = Callable[[str, bytes], None]


def task_count(site: Site) -> int:
    """Zahl der GETs, die ``collect`` für dieses Institut ausführt.

    Die Orchestrierung summiert das zum Request-Budget; die Rechnung muss deshalb
    exakt der Schleife in ``collect`` entsprechen (ein GET je Untersuchung, kein
    Vor- oder Katalog-Request).
    """
    return len(site.exams)


def collect(
    site: Site, run_start: datetime, *, archive: Archive | None = None
) -> list[Measurement]:
    """Erhebt je Untersuchung des Instituts eine Messzeile.

    Args:
        site: validiertes Institut mit ``adapter: doctena``.
        run_start: Lauf-Start (lokal, naiv, minutengenau) für alle Zeilen; sein
            Datum ist der Beginn des Suchfensters.
        archive: erhält je Antwort ``<slug>_<untersuchung>.json`` und die
            Roh-Bytes, bevor geparst wird; ``None`` = nicht archivieren
            (Live-Probe).

    Returns:
        Messzeilen in der Reihenfolge von ``site.exams``; Fehler einer Abfrage
        erscheinen als Zeile mit Fehlerstatus und Grund in ``note``.

    Raises:
        http.BudgetExceededError: bricht den Lauf bewusst ab.
        Exception: was ``archive`` wirft, unverändert – ohne Archiv keine Evidenz.
    """
    timeout = site.timeout_s if site.timeout_s is not None else http.DEFAULT_TIMEOUT

    # Fensterbeginn aus dem Lauf-Start statt aus der aktuellen Uhr: ein Lauf über
    # Mitternacht fragt sonst ab einem Tag, an dem schon ein Termin vor dem
    # Lauf-Tag liegen könnte, und die URL bleibt in Tests deterministisch.
    start = datetime.combine(run_start.date(), time.min).astimezone()
    end = start + timedelta(days=_WINDOW_DAYS)

    rows: list[Measurement] = []
    for exam, values in site.exams.items():
        # Parameter wie beim Buchungs-Widget. doctor und reason sind laut Loader
        # positive Ganzzahlen – nichts zu percent-encoden.
        url = (
            f"{_API_URL}?from={int(start.timestamp())}&to={int(end.timestamp())}"
            "&language=de&weight=front_search_change_date"
            f"&doctor={site.params['doctor']}&reason={values['reason']}"
        )

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
            result = http.get(url, timeout=timeout, extra_headers=_EXTRA_HEADERS)
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

        if result.status_code >= 400:
            # Abgelehnter Zugriff: Alarmzeile, aber keine automatische
            # Abschaltung und kein Ausweichweg – das entscheidet ein Mensch nach
            # Sichtung von Log und Archiv.
            rows.append(
                row(
                    status=Status.ERROR_PARSE,
                    note=(
                        f"HTTP {result.status_code} from api.doctena.at"
                        " - access possibly lost"
                    ),
                )
            )
            continue

        try:
            parsed = parse_doctena.parse(result.content)
            if parsed.status is Status.NO_SLOTS:
                # Fenster in den Hinweis: „keine Termine“ heißt hier nur „nichts
                # innerhalb des Suchfensters“, nicht „gar keine Termine“.
                rows.append(
                    row(
                        status=parsed.status,
                        note=f"no slot within {_WINDOW_DAYS}-day window",
                    )
                )
            else:
                # Im try: Measurement lehnt z. B. ein Datum vor dem Lauf-Tag ab –
                # auch das ist eine unerwartete Antwort und wird eine Fehlerzeile.
                rows.append(row(status=parsed.status, slot_date=parsed.slot_date))
        except Exception as exc:  # noqa: BLE001
            # Bewusst breit: eine unerwartete Antwort kann jede Exception
            # auslösen. Fehlerzeile statt Laufabbruch; die Roh-Antwort liegt schon
            # im Archiv.
            rows.append(row(status=Status.ERROR_PARSE, note=f"parser exception: {exc}"))
    return rows
