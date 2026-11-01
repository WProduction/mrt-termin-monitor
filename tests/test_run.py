# SPDX-License-Identifier: Apache-2.0
"""Lauf-Orchestrierung End-to-End: ``cli.main(["run"])`` mit Fake-Adapter und fester Uhr."""

import builtins
import csv
import io
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from mrt_termin_monitor import cli, csv_output, paths, run
from mrt_termin_monitor.errors import ExitCode
from mrt_termin_monitor.fetch import http, post
from mrt_termin_monitor.model import Measurement, Status
from mrt_termin_monitor.sites import load_sites

SVNR = "1234" + "010180"
START = datetime(2026, 11, 1, 8, 15)
SLOT = date(2099, 1, 15)
# Marker für den Fake-Adapter: dieses Institut überschreitet das Budget.
BUDGET = "budget"


@pytest.fixture
def portal(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Ersetzt jeden Adapter durch einen Fake; Status je Slug über ``status``.

    Ohne Eintrag liefert ein Institut je Untersuchung ``ok`` mit Termin 2099.
    ``calls`` hält die Abfrage-Reihenfolge, ``budgets`` die gesetzten Budgets.
    """
    paths.credentials_file().parent.mkdir(parents=True, exist_ok=True)
    paths.credentials_file().write_text(f"svnr: '{SVNR}'\n", encoding="utf-8")
    state = SimpleNamespace(status={}, calls=[], budgets={})

    def collect(site, run_start: datetime, *, archive) -> list[Measurement]:
        state.calls.append(site.slug)
        archive(f"{site.slug}.html", b"<html></html>")
        status = state.status.get(site.slug, Status.OK)
        if status == BUDGET:
            raise http.BudgetExceededError("request budget exhausted")
        return [
            Measurement(
                run_start=run_start,
                queried_at=run_start.astimezone(),
                site_id=site.slug,
                site_name=site.name,
                exam=exam,
                billing=site.billing,
                status=status,
                slot_date=SLOT if status is Status.OK else None,
            )
            for exam in site.exams
        ]

    adapter = SimpleNamespace(task_count=lambda site: len(site.exams), collect=collect)
    # importlib ist global – nur den Adapter-Import umbiegen, alles andere echt.
    real_import = run.importlib.import_module
    monkeypatch.setattr(
        run.importlib,
        "import_module",
        lambda name, *a: (
            adapter
            if name.startswith("mrt_termin_monitor.adapters.")
            else real_import(name, *a)
        ),
    )
    monkeypatch.setattr(http, "set_budget", lambda n: state.budgets.update(get=n))
    monkeypatch.setattr(post, "set_budget", lambda n: state.budgets.update(post=n))
    # Der Lauf fragt nie nach – jede Eingabe wäre im Aufgabenplaner ein Hänger.
    monkeypatch.setattr(builtins, "input", lambda *_: pytest.fail("input() called"))
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    return state


def main_at(monkeypatch: pytest.MonkeyPatch, start: datetime, *argv: str) -> int:
    """Startet ``cli.main`` mit fester Uhr (benennt Log und CSV)."""

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return start

    monkeypatch.setattr(cli, "datetime", Clock)
    return cli.main(["run", *argv])


def csv_rows(start: datetime = START) -> list[dict[str, str]]:
    path = paths.data_dir() / f"{start:%Y-%m-%d_%H%M}.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=csv_output.CSV_DELIMITER))


def test_full_run_writes_csv_and_archive(monkeypatch, portal, capsys) -> None:
    sites = load_sites()
    assert main_at(monkeypatch, START) == ExitCode.OK
    assert portal.calls == list(sites)
    rows = csv_rows()
    expected = sum(len(site.exams) for site in sites.values())
    assert len(rows) == expected
    assert {row["status"] for row in rows} == {"ok"}
    assert {row["lauf_id"] for row in rows} == {"2026-11-01_0815"}
    # Dasselbe Soll für GET und POST, aus task_count summiert.
    assert portal.budgets == {"get": expected, "post": expected}
    raw = paths.raw_dir() / "2026-11-01_0815"
    assert sorted(p.name for p in raw.iterdir()) == sorted(f"{s}.html" for s in sites)
    assert (paths.log_dir() / "run_2026-11-01_0815.log").is_file()
    err = capsys.readouterr().err
    assert "OK            MR-CT Wien-West / Radiologicum Penzing (knie_rechts)" in err
    assert (
        f"Zusammenfassung: {expected} Abfragen - ok {expected}, keine_termine 0" in err
    )
    assert "Ergebnisdatei:" in err
    assert err.rstrip().endswith("OK: Alle Institute wurden erfasst.")
    assert "HINWEIS" not in err


def test_only_with_failing_site_is_partial(monkeypatch, portal, capsys) -> None:
    portal.status["dz_stadlau"] = Status.ERROR_PARSE
    only = "dz_stadlau,dz_simmering,dz_stadlau"
    assert main_at(monkeypatch, START, "--only", only) == ExitCode.PARTIAL
    assert portal.calls == ["dz_stadlau", "dz_simmering"]
    assert [row["institut_id"] for row in csv_rows()] == ["dz_stadlau", "dz_simmering"]
    err = capsys.readouterr().err
    assert "FEHLER        " in err and ": fehler_parsen" in err
    assert "OK MIT LUECKEN (1):" in err


def test_no_site_reachable_still_writes_csv(monkeypatch, portal, capsys) -> None:
    for slug in ("dz_stadlau", "dz_simmering"):
        portal.status[slug] = Status.NOT_COLLECTED
    argv = ("--only", "dz_stadlau,dz_simmering")
    assert main_at(monkeypatch, START, *argv) == ExitCode.NO_SITE_REACHABLE
    assert {row["status"] for row in csv_rows()} == {"nicht_erhoben"}
    assert "FEHLER: Kein Institut war erreichbar." in capsys.readouterr().err


def test_budget_exceeded_keeps_rows_and_skips_rest(monkeypatch, portal, capsys) -> None:
    portal.status["dz_simmering"] = BUDGET
    argv = ("--only", "dz_stadlau,dz_simmering,dz_urania")
    assert main_at(monkeypatch, START, *argv) == ExitCode.UNEXPECTED
    assert portal.calls == ["dz_stadlau", "dz_simmering"]
    assert [row["institut_id"] for row in csv_rows()] == ["dz_stadlau"]
    err = capsys.readouterr().err
    assert err.count("UEBERSPRUNGEN ") == 2


@pytest.mark.parametrize(
    ("previous", "hint"),
    [(datetime(2026, 11, 1, 6, 15), True), (datetime(2026, 10, 31, 7, 15), False)],
)
def test_second_run_within_24h_is_noted(
    monkeypatch, portal, capsys, previous: datetime, hint: bool
) -> None:
    # Fremde CSVs im Ergebnisordner zählen nicht als Lauf.
    paths.data_dir().mkdir(parents=True)
    (paths.data_dir() / "notizen.csv").write_text("x;y\n", encoding="utf-8")
    assert main_at(monkeypatch, previous, "--only", "dz_stadlau") == ExitCode.OK
    capsys.readouterr()
    assert main_at(monkeypatch, START, "--only", "dz_stadlau") == ExitCode.OK
    err = capsys.readouterr().err
    assert ("HINWEIS: Der letzte Lauf" in err) is hint
    if hint:
        assert "(2026-11-01_0615)" in err


@pytest.mark.parametrize(
    ("before", "warned"), [(Status.OK, True), (Status.NO_SLOTS, False)]
)
def test_no_slots_after_slot_warns(
    monkeypatch, portal, capsys, before: Status, warned: bool
) -> None:
    portal.status["dz_stadlau"] = before
    main_at(monkeypatch, datetime(2026, 10, 25, 8, 15), "--only", "dz_stadlau")
    capsys.readouterr()
    portal.status["dz_stadlau"] = Status.NO_SLOTS
    assert main_at(monkeypatch, START, "--only", "dz_stadlau") == ExitCode.OK
    err = capsys.readouterr().err
    assert ("WARNUNG:" in err) is warned
    if warned:
        assert "(2026-10-25_0815)" in err


def test_run_of_same_minute_stops_before_any_request(monkeypatch, portal) -> None:
    paths.data_dir().mkdir(parents=True)
    (paths.data_dir() / "2026-11-01_0815.csv").write_text("", encoding="utf-8")
    assert main_at(monkeypatch, START) == ExitCode.OUTPUT_ERROR
    assert portal.calls == []


def test_raw_archive_not_writable_exit_4(monkeypatch, portal) -> None:
    # Eine Datei, wo der Archiv-Ordner des Laufs hin soll.
    paths.raw_dir().mkdir(parents=True)
    (paths.raw_dir() / "2026-11-01_0815").write_text("", encoding="utf-8")
    assert main_at(monkeypatch, START, "--only", "dz_stadlau") == ExitCode.OUTPUT_ERROR
    assert "raw archive not writable" in next(paths.log_dir().glob("*.log")).read_text(
        encoding="utf-8"
    )


def test_only_without_slug_is_config_error(monkeypatch, portal) -> None:
    assert main_at(monkeypatch, START, "--only", ",") == ExitCode.CONFIG_ERROR
    assert portal.calls == []
