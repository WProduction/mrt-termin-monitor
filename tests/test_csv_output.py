# SPDX-License-Identifier: Apache-2.0
"""Lauf-CSV: Golden-Datei byte-exakt, Format-Eckdaten, CSV-Injection."""

import csv
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from mrt_termin_monitor import csv_output
from mrt_termin_monitor.model import Billing, Exam, Measurement, Status

GOLDEN = Path(__file__).parent / "data" / "golden_run.csv"
CEST = timezone(timedelta(hours=2))
START = datetime(2026, 10, 25, 8, 15)


def golden_measurements() -> list[Measurement]:
    """Ein Lauf mit jedem Status, jeder Untersuchung und jeder Abrechnung.

    Fiktive Institute; Umlaute, Trenner, Anführungszeichen und Zeilenumbruch im
    Hinweis, damit die Excel-Probe alle Sonderfälle an einer Datei sieht.
    """

    def m(
        minute: int,
        site: str,
        name: str,
        exam: Exam,
        billing: Billing,
        status: Status,
        slot: date | None = None,
        note: str = "",
    ) -> Measurement:
        return Measurement(
            run_start=START,
            queried_at=datetime(2026, 10, 25, 8, minute, 30, tzinfo=CEST),
            site_id=site,
            site_name=name,
            exam=exam,
            billing=billing,
            status=status,
            slot_date=slot,
            note=note,
        )

    gross = ("institut_grossstadt", "Röntgeninstitut Großstadt")
    au = ("diagnosezentrum_au", "Diagnosezentrum Au – Süd")
    return [
        m(16, *gross, Exam.KNEE_RIGHT, Billing.PUBLIC, Status.OK, date(2026, 11, 3)),
        m(17, *gross, Exam.LUMBAR_SPINE, Billing.PUBLIC, Status.NO_SLOTS),
        m(18, *au, Exam.KNEE_RIGHT, Billing.COMBINED, Status.OK, date(2027, 1, 12)),
        m(
            19,
            *au,
            Exam.RENAL_MRA_CONTRAST,
            Billing.COMBINED,
            Status.ERROR_PARSE,
            note='Antwort "abgeschnitten"; 2 Einträge\r\nzweite Zeile',
        ),
        m(
            20,
            "praxis_ost",
            "Praxis Ost",
            Exam.KNEE_RIGHT,
            Billing.PUBLIC,
            Status.ERROR_REDIRECT,
            note='=HYPERLINK("x")',
        ),
        m(
            21,
            "praxis_ost",
            "Praxis Ost",
            Exam.LUMBAR_SPINE,
            Billing.PUBLIC,
            Status.NOT_COLLECTED,
            note="-Zeitüberschreitung",
        ),
    ]


@pytest.fixture
def written(tmp_path: Path) -> bytes:
    path = tmp_path / "data" / "2026-10-25_0815.csv"
    csv_output.write_run(path, golden_measurements())
    return path.read_bytes()


def test_matches_golden_bytes(written: bytes) -> None:
    # Schlägt bei jeder Schema-Änderung fehl (Spalte, Reihenfolge, Wert, Format):
    # dann feat! + SCHEMA_VERSION + docs/datenfelder.md, erst danach Golden erneuern.
    assert written == GOLDEN.read_bytes()


def test_format_bom_crlf_delimiter_header(written: bytes) -> None:
    assert written.startswith(b"\xef\xbb\xbf")
    assert b"sep=" not in written
    header, _, rest = written[3:].partition(b"\r\n")
    assert header.decode("ascii") == ";".join(csv_output.FIELDS)
    # Jeder LF ist Teil eines CRLF – kein nacktes \n außerhalb von Zellen.
    assert written.count(b"\n") == written.count(b"\r\n")
    assert rest.endswith(b"\r\n")


def test_reads_back_with_excel_dialect(written: bytes) -> None:
    rows = list(
        csv.DictReader(
            written.decode("utf-8-sig").splitlines(keepends=True),
            delimiter=csv_output.CSV_DELIMITER,
        )
    )
    assert [r["status"] for r in rows] == [
        "ok",
        "keine_termine",
        "ok",
        "fehler_parsen",
        "fehler_weiterleitung",
        "nicht_erhoben",
    ]
    assert all(len(r) == 14 for r in rows)
    assert rows[0]["wartetage"] == "9" and rows[2]["wartetage"] == "79"
    assert rows[3]["hinweis"] == 'Antwort "abgeschnitten"; 2 Einträge\r\nzweite Zeile'
    # Zeilen ohne Injection-Präfix kommen unverändert zurück.
    for row, m in zip(rows[:4], golden_measurements()[:4], strict=True):
        assert Measurement.from_row(row) == m


def test_never_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_bytes(b"alt")
    with pytest.raises(FileExistsError):
        csv_output.write_run(path, [])
    assert path.read_bytes() == b"alt"


def test_aborted_write_leaves_no_file(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"

    def broken() -> Iterator[Measurement]:
        yield golden_measurements()[0]
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        csv_output.write_run(path, broken())
    assert not path.exists()


@pytest.mark.parametrize("value", ["=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx", "\nx"])
def test_neutralize_formula_prefix(value: str) -> None:
    assert csv_output.neutralize(value) == "'" + value


@pytest.mark.parametrize("value", ["", "ok", "2026-10-25", "Termin = morgen", "'x"])
def test_neutralize_leaves_harmless_values(value: str) -> None:
    assert csv_output.neutralize(value) == value


def test_injection_applied_in_written_cells(written: bytes) -> None:
    text = written.decode("utf-8-sig")
    assert ';"\'=HYPERLINK(""x"")"\r\n' in text
    assert ";'-Zeitüberschreitung\r\n" in text
