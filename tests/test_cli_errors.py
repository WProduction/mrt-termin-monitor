# SPDX-License-Identifier: Apache-2.0
"""Top-Level-Handler: Exception → Exit-Code → deutsche Meldung, Traceback nur im Log."""

import io
from pathlib import Path

import pytest

from mrt_termin_monitor import cli, messages, paths
from mrt_termin_monitor.errors import ExitCode, NoSiteReachableError, OutputError

SVNR = "1234" + "010180"


def only_log() -> str:
    (log_file,) = paths.log_dir().glob("run_*.log")
    return log_file.read_text(encoding="utf-8")


def write_credentials(text: str) -> None:
    paths.credentials_file().parent.mkdir(parents=True, exist_ok=True)
    paths.credentials_file().write_text(text, encoding="utf-8")


def test_broken_credentials_exit_2_without_console_traceback(capsys) -> None:
    write_credentials(f"svnr: [{SVNR}\n")
    assert cli.main(["run"]) == ExitCode.CONFIG_ERROR
    err = capsys.readouterr().err
    assert err.startswith("FEHLER: Die Konfiguration konnte nicht gelesen werden.")
    assert str(paths.credentials_file()) in err
    assert str(paths.log_dir()) in err
    assert messages.KONTAKT_MAIL in err
    assert "Traceback" not in err
    text = only_log()
    assert "Traceback" in text and "ConfigError" in text
    # YAML-Fehlertext zitiert die Zeile – die SVNR muss trotzdem geschwärzt sein.
    assert "010180" not in text


def test_missing_credentials_exit_2(capsys) -> None:
    assert cli.main(["run"]) == ExitCode.CONFIG_ERROR
    assert "FEHLER:" in capsys.readouterr().err


def test_unknown_slug_exit_2_and_svnr_redacted(capsys) -> None:
    write_credentials(f"svnr: '{SVNR}'\npatient_name: Anna Muster\n")
    assert cli.main(["run", "--only", "nirgendwo,auch_nicht"]) == 2
    text = only_log()
    assert "nirgendwo" in text
    assert "Anna Muster" not in capsys.readouterr().err


def test_run_without_only_is_unexpected_until_orchestration(capsys) -> None:
    write_credentials(f"svnr: '{SVNR}'\n")
    assert cli.main(["run"]) == ExitCode.UNEXPECTED
    assert "Traceback" not in capsys.readouterr().err
    assert "NotImplementedError" in only_log()


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (NoSiteReachableError("offline"), ExitCode.NO_SITE_REACHABLE),
        (OutputError("csv locked"), ExitCode.OUTPUT_ERROR),
        (RuntimeError(f"boom {SVNR}"), ExitCode.UNEXPECTED),
        (KeyboardInterrupt(), ExitCode.ABORTED),
    ],
)
def test_exception_mapping(
    monkeypatch: pytest.MonkeyPatch, capsys, exc: BaseException, code: ExitCode
) -> None:
    def boom(*_args: object) -> ExitCode:
        raise exc

    monkeypatch.setattr(cli, "_run", boom)
    assert cli.main(["run"]) == code
    err = capsys.readouterr().err
    assert "Traceback" not in err
    expected = "ABGEBROCHEN:" if code == ExitCode.ABORTED else "FEHLER:"
    assert err.startswith(expected)
    assert "010180" not in only_log()


def test_log_not_writable_exit_4(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def fail(*_args: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(cli.logging_setup, "configure", fail)
    assert cli.main(["run"]) == ExitCode.OUTPUT_ERROR
    assert capsys.readouterr().err.startswith("FEHLER: Die Ergebnis- oder Log-Datei")


def test_start_prunes_logs_to_30() -> None:
    log_dir: Path = paths.log_dir()
    log_dir.mkdir(parents=True)
    for i in range(35):
        (log_dir / f"run_2026-01-{i + 1:02d}_0800.log").write_text("alt")
    cli.main(["run"])  # endet mit Exit 2 (keine Credentials), Retention lief vorher
    logs = sorted(log_dir.glob("run_*.log"))
    assert len(logs) == 30
    assert logs[-1].read_text(encoding="utf-8") != "alt"  # aktueller Lauf blieb


def test_header_is_first_in_log() -> None:
    cli.main(["run", "--no-color"])
    first = only_log().splitlines()[0]
    assert "mrt-termin-monitor" in first


def test_setup_subcommand(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    # input() liest aus sys.stdin, wenn das keine Konsole ist – wie bei Umleitung.
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{SVNR}\n\n\n"))
    assert cli.main(["setup"]) == ExitCode.OK
    assert str(paths.credentials_file()) in capsys.readouterr().out
    assert paths.credentials_file().is_file()
