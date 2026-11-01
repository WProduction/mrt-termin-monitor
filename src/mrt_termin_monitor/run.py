# SPDX-License-Identifier: Apache-2.0
"""Orchestrierung eines Messlaufs.

Fragt alle Institute (oder die per ``--only`` gewählten) sequenziell ab, legt jede
Roh-Antwort im Archiv ab, schreibt die Lauf-CSV und zeigt eine Zusammenfassung.
Der Lauf fragt nie nach – Verknüpfung und Aufgabenplanung nutzen denselben Pfad;
ein zweiter Lauf binnen 24 h wird nur vermerkt. Fehler eines Instituts brechen den
Lauf nie ab; einzige Ausnahme ist das Request-Budget als Schutz gegen Schleifen-Bugs.
"""

import csv
import importlib
import logging
import sys
from collections import Counter
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

from mrt_termin_monitor import csv_output, messages, paths, runinfo
from mrt_termin_monitor.errors import ConfigError, NoSiteReachableError, OutputError
from mrt_termin_monitor.fetch import http, post
from mrt_termin_monitor.model import Measurement, Status
from mrt_termin_monitor.sites import Site, load_sites

log = logging.getLogger(__name__)

# Zeilen mit diesem Status machen ein Institut zur Lücke (Exit 1).
FAILURE_STATUS = frozenset(
    {Status.ERROR_REDIRECT, Status.ERROR_PARSE, Status.NOT_COLLECTED}
)

# CSV-Wert von Status.OK, für den Vergleich mit Zeilen früherer Läufe.
_OK = csv_output.STATUS_VALUES[Status.OK]


def execute(only: list[str] | None, run_start: datetime) -> int:
    """Führt einen Messlauf aus und schreibt ``data/<lauf_id>.csv``.

    Args:
        only: Slugs, die abgefragt werden (Reihenfolge wie angegeben, doppelte
            einmal); ``None`` = alle Institute aus ``sites.yaml``.
        run_start: Lauf-Start, lokal, naiv, minutengenau – dieselbe Zeit, die
            auch die Log-Datei benennt.

    Returns:
        Zahl der Institute mit mindestens einer Fehlerzeile (0 = alle erfasst).

    Raises:
        ConfigError: unbekannter oder leerer Slug – vor dem ersten Request.
        OutputError: CSV dieses Laufs existiert schon (vor dem ersten Request),
            Archiv oder CSV nicht schreibbar.
        NoSiteReachableError: keine einzige Antwort; die CSV ist dann geschrieben.
        http.BudgetExceededError: Schleifen-Schutz; die bis dahin erhobenen
            Zeilen sind geschrieben.
    """
    sites = _select(load_sites(), only)
    run_id = runinfo.lauf_id(run_start)
    csv_file = paths.data_dir() / f"{run_id}.csv"
    # Vor dem ersten Request: ein zweiter Start in derselben Minute hätte dieselbe
    # Kennung, und die CSV scheiterte sonst erst nach allen Abfragen.
    # ponytail: erkennt nur einen schon beendeten Lauf dieser Minute; ein noch
    # laufender Doppelstart fragt doppelt ab und endet beim Schreiben mit Exit 4.
    # Lock-Datei, falls Doppelstarts in der Praxis vorkommen.
    if csv_file.exists():
        raise OutputError(f"run {run_id} already exists: {csv_file}")

    latest, previous = _history(paths.data_dir())
    if latest is not None and run_start - latest < timedelta(hours=24):
        log.info(messages.LAUF_24H.format(letzter=runinfo.lauf_id(latest)))

    adapters = {
        site.slug: importlib.import_module(
            f"mrt_termin_monitor.adapters.{site.adapter}"
        )
        for site in sites
    }
    # Dasselbe Soll für GET und POST: task_count zählt je Adapter beide Arten
    # zusammen (iris, patapp), die Aufteilung kennt nur der Adapter. Als Decke gegen
    # Schleifen-Bugs reicht das; eine exakte Aufteilung brächte keinen Schutz mehr.
    budget = sum(adapters[site.slug].task_count(site) for site in sites)
    http.set_budget(budget)
    post.set_budget(budget)
    log.info(messages.LAUF_START.format(lauf_id=run_id, anzahl=len(sites)))
    log.debug("request budget %d (GET and POST each)", budget)

    archive = partial(_archive, paths.raw_dir() / run_id)
    rows: list[Measurement] = []
    for index, site in enumerate(sites):
        before = http.request_count() + post.request_count()
        try:
            site_rows = adapters[site.slug].collect(site, run_start, archive=archive)
        except http.BudgetExceededError:
            # Nur ins Log: die Konsole zeigt den Abbruch über UEBERSPRUNGEN und die
            # deutsche Fehlermeldung; ein englischer Satz dort verwirrte nur.
            log.debug("request budget exceeded at %s - run stopped", site.slug)
            for skipped in sites[index:]:
                log.info(messages.ZEILE_UEBERSPRUNGEN.format(name=skipped.name))
            # Was schon erhoben ist, sind gültige Messungen – nicht verwerfen.
            if rows:
                _write(csv_file, rows)
            raise
        requests = http.request_count() + post.request_count() - before
        log.debug("%s: %d requests", site.slug, requests)
        for m in site_rows:
            _report(m)
        rows.extend(site_rows)

    _write(csv_file, rows)
    _summary(rows, previous, csv_file)
    if all(m.status is Status.NOT_COLLECTED for m in rows):
        raise NoSiteReachableError("no site answered")
    return len({m.site_id for m in rows if m.status in FAILURE_STATUS})


def _select(sites: dict[str, Site], only: list[str] | None) -> list[Site]:
    """Wählt die Institute des Laufs; prüft alle Slugs vor dem ersten Request."""
    if only is None:
        return list(sites.values())
    # Doppelte nur einmal: jede Wiederholung wäre Portal-Last ohne Messwert.
    only = list(dict.fromkeys(only))
    if not only:
        raise ConfigError("--only without any site slug")
    unknown = [slug for slug in only if slug not in sites]
    if unknown:
        raise ConfigError(f"unknown site slug: {', '.join(unknown)}")
    return [sites[slug] for slug in only]


def _history(
    data_dir: Path,
) -> tuple[datetime | None, dict[tuple[str, str], tuple[str, str]]]:
    """Liest die früheren Lauf-CSVs.

    Returns:
        Start des jüngsten Laufs (``None`` ohne frühere CSV) und je
        ``(institut_id, untersuchung)`` den Status der jüngsten Zeile samt
        Lauf-Kennung. ``--only``-Läufe zählen mit.

    Dateien, deren Name keine Lauf-Kennung ist oder die sich nicht lesen lassen,
    werden übersprungen: der Verlauf liefert nur Hinweise und darf den Lauf nie
    verhindern.
    """
    latest = None
    previous: dict[tuple[str, str], tuple[str, str]] = {}
    # Dateiname = Lauf-Kennung, sortiert also chronologisch; Jüngeres überschreibt.
    for path in sorted(data_dir.glob("*.csv")):
        rows = {}
        try:
            started = datetime.strptime(path.stem, runinfo.LAUF_ID_FORMAT)
            with path.open(encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f, delimiter=csv_output.CSV_DELIMITER):
                    rows[(row["institut_id"], row["untersuchung"])] = (
                        row["status"],
                        path.stem,
                    )
        except (ValueError, OSError, KeyError, csv.Error) as exc:
            log.debug("history: skipping %s (%s)", path.name, exc)
            continue
        latest = started
        previous.update(rows)
    return latest, previous


def _archive(directory: Path, name: str, content: bytes) -> None:
    """Legt eine Roh-Antwort unter ``raw/<lauf_id>/<name>`` ab."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_bytes(content)
    except OSError as exc:
        # Exit 4 statt 5: eine volle oder gesperrte Platte ist kein Programmfehler.
        raise OutputError(f"raw archive not writable: {exc}") from exc


def _write(csv_file: Path, rows: list[Measurement]) -> None:
    try:
        csv_output.write_run(csv_file, rows)
    except OSError as exc:  # auch FileExistsError
        raise OutputError(f"run CSV not writable: {exc}") from exc


def _report(m: Measurement) -> None:
    """Eine Konsolenzeile je Messung; Details (Hinweis) nur ins Log."""
    row = m.to_row()
    fields = {"name": m.site_name, "untersuchung": row["untersuchung"]}
    if m.status is Status.OK:
        line = messages.ZEILE_TERMIN.format(termin=row["naechster_termin"], **fields)
    elif m.status is Status.NO_SLOTS:
        line = messages.ZEILE_KEINE.format(**fields)
    else:
        line = messages.ZEILE_FEHLER.format(status=row["status"], **fields)
    log.info(line)
    log.debug(
        "%s %s: %s %s %s",
        m.site_id,
        row["untersuchung"],
        row["status"],
        row["naechster_termin"] or "-",
        row["hinweis"],
    )


def _summary(
    rows: list[Measurement],
    previous: dict[tuple[str, str], tuple[str, str]],
    csv_file: Path,
) -> None:
    # keine_termine nach einem Termin im letzten Lauf: typisches Symptom eines
    # still geänderten Portals (umbenannter Code, verschobener Kalender), das
    # sonst wie ein echtes „ausgebucht“ aussähe.
    for m in rows:
        row = m.to_row()
        status, last_run = previous.get((m.site_id, row["untersuchung"]), ("", ""))
        if m.status is Status.NO_SLOTS and status == _OK:
            log.warning(
                messages.WARNUNG_KEINE_TERMINE.format(
                    name=m.site_name,
                    untersuchung=row["untersuchung"],
                    letzter=last_run,
                    kontakt=messages.KONTAKT_MAIL,
                )
            )
    counts = Counter(m.to_row()["status"] for m in rows)
    # Alle Status immer nennen, damit „0 Fehler“ ausdrücklich lesbar ist.
    counted = ", ".join(
        f"{value} {counts[value]}" for value in csv_output.STATUS_VALUES.values()
    )
    log.info(messages.ZUSAMMENFASSUNG.format(zeilen=len(rows), zaehlung=counted))
    text = messages.ERGEBNIS_DATEI.format(path=csv_file)
    # Pfad direkt nach stderr statt über den Konsolen-Handler: die Redaction würde
    # z. B. einen Namen im Benutzerordner schwärzen und den Pfad unbrauchbar machen.
    log.debug("console: %s", text)
    print(text, file=sys.stderr)
