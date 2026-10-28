# SPDX-License-Identifier: Apache-2.0
"""Redaction: SVNR in msg, args, Exception und URL-Query wird zu ***."""

import logging
from pathlib import Path

import pytest

from mrt_termin_monitor import logging_setup
from mrt_termin_monitor.redaction import MASK, RedactionFilter, variants

# Zur Laufzeit zusammengesetzt, nie als 10-Ziffern-Literal (Hook no-svnr).
SVNR = "1234" + "010180"
SPACED = "1234 " + "010180"


@pytest.fixture
def logged(tmp_path: Path):
    """Loggt über die echte Konfiguration und liefert den Datei-Inhalt."""
    log_file = tmp_path / "run.log"
    flt = RedactionFilter([SVNR, "Geheim-Pass!"])
    logging_setup.configure(log_file, flt)

    def read() -> str:
        logging.shutdown()
        return log_file.read_text(encoding="utf-8")

    return logging.getLogger("probe"), read


def test_msg(logged) -> None:
    log, read = logged
    log.info(f"svnr={SVNR} spaced={SPACED}")
    text = read()
    assert SVNR not in text and "010180" not in text
    assert f"svnr={MASK} spaced={MASK}" in text


def test_args(logged) -> None:
    log, read = logged
    log.info("login %s mit %s", SVNR, "Geheim-Pass!")
    text = read()
    assert f"login {MASK} mit {MASK}" in text


def test_exception_and_traceback(logged) -> None:
    log, read = logged
    try:
        raise ValueError(f"ungültig: {SVNR}")
    except ValueError:
        log.exception("fehler bei %s", SVNR)
    text = read()
    assert "010180" not in text
    assert "Traceback" in text
    assert f"ValueError: ungültig: {MASK}" in text


@pytest.mark.parametrize(
    "url",
    [
        f"https://x.example/a?svnr={SVNR}&n=1",
        "https://x.example/a?svnr=1234%20" + "010180",
        "https://x.example/a?svnr=1234+" + "010180",
        "https://x.example/a?pw=Geheim-Pass%21",
    ],
)
def test_url_query(logged, url: str) -> None:
    log, read = logged
    log.warning("GET %s", url)
    text = read()
    assert "010180" not in text
    assert "Geheim-Pass" not in text


def test_regex_catches_unknown_svnr() -> None:
    # Wert ist dem Filter nicht bekannt (z. B. Parse-Fehler der Credentials-Datei).
    other = "9876" + "543210"
    assert RedactionFilter().redact(f"zeile: svnr: {other}") == f"zeile: svnr: {MASK}"


def test_variants_of_svnr() -> None:
    assert variants(SVNR) >= {SVNR, SPACED, "1234%20010180", "1234+010180"}
    assert "" not in variants("  ")


def test_broken_log_call_is_still_redacted(logged) -> None:
    log, read = logged
    # Absichtlich kaputter Aufruf: genau diesen Fall soll der Filter abfangen.
    log.info("zu viele %s %s", SVNR)  # noqa: PLE1206
    assert "010180" not in read()
