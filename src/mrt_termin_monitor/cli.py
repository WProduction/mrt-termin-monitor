# SPDX-License-Identifier: Apache-2.0
"""Kommandozeile von mrt-termin-monitor und Top-Level-Fehlerbehandlung.

Vertrag: ``run [--only <slug>[,<slug>…]] [--no-color]``, ``setup``, globales
``--version``. Bewusst kein ``--config`` (Pfade nur aus ``paths``) und kein ``-y``
(der Lauf fragt nie nach).

Jede Exception endet hier: Konsole bekommt nur den deutschen Drei-Teile-Text aus
``messages``, der Traceback landet ausschließlich in der Log-Datei.
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from mrt_termin_monitor import (
    __version__,
    logging_setup,
    messages,
    paths,
    retention,
    runinfo,
    setup,
)
from mrt_termin_monitor.errors import ExitCode, MonitorError
from mrt_termin_monitor.redaction import RedactionFilter
from mrt_termin_monitor.run import execute

log = logging.getLogger(__name__)


def _slugs(value: str) -> list[str]:
    return [s.strip() for s in value.split(",") if s.strip()]


def _parser() -> argparse.ArgumentParser:
    # prog fest, sonst zeigt argparse bei ``python -m`` "__main__.py" an.
    # color=False: Konsole ist durchgehend farblos (siehe logging_setup).
    parser = argparse.ArgumentParser(prog="mrt-termin-monitor", color=False)
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Termine erheben", color=False)
    run.add_argument(
        "--only",
        type=_slugs,
        metavar="SLUG[,SLUG...]",
        help="nur diese Institute abfragen (Live-Probe)",
    )
    # Ohne Wirkung, weil die Konsole nie Farben ausgibt; Teil des CLI-Vertrags.
    run.add_argument("--no-color", action="store_true", help="keine Farben")
    run.set_defaults(handler=_run)
    sub.add_parser("setup", help="Zugangsdaten einrichten", color=False).set_defaults(
        handler=_setup
    )
    return parser


def _run(
    args: argparse.Namespace,
    credentials: Path,
    redaction: RedactionFilter,
    log_file: Path,
    started: datetime,
) -> ExitCode:
    creds = setup.load_credentials(credentials)
    redaction.add_secrets(creds.values())
    gaps = execute(args.only, started)
    code = ExitCode.PARTIAL if gaps else ExitCode.OK
    log.info(messages.render(code, log_file, credentials, gaps))
    # Auch im Erfolgsfall: „schick mir die Log-Datei“ braucht den Pfad. Direkt nach
    # stderr wie der Pfad der Ergebnisdatei, damit die Redaction ihn nicht verstümmelt.
    text = messages.LOG_DATEI.format(path=log_file)
    log.debug("console: %s", text)
    print(text, file=sys.stderr)
    return code


def _setup(
    args: argparse.Namespace,
    credentials: Path,
    redaction: RedactionFilter,
    log_file: Path,
    started: datetime,
) -> ExitCode:
    redaction.add_secrets(setup.run_dialog(credentials).values())
    return ExitCode.OK


def _exit_code(exc: BaseException) -> ExitCode:
    if isinstance(exc, KeyboardInterrupt):
        return ExitCode.ABORTED
    if isinstance(exc, MonitorError):
        return exc.exit_code
    return ExitCode.UNEXPECTED


def main(argv: list[str] | None = None) -> int:
    """Parst die Argumente, richtet Logging ein und führt das Kommando aus.

    Args:
        argv: Argumente ohne Programmnamen; ``None`` liest ``sys.argv[1:]``.

    Returns:
        Exit-Code des Prozesses (siehe ``errors.ExitCode``). Bedienfehler der
        Argumente beendet argparse selbst mit 2.
    """
    argv = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(argv)
    # Einmal bestimmt: dieselbe Minute benennt Log-Datei und Lauf-CSV.
    started = datetime.now().replace(second=0, microsecond=0)
    log_file = paths.log_dir() / f"run_{runinfo.lauf_id(started)}.log"
    credentials = paths.credentials_file()
    redaction = RedactionFilter()
    try:
        logging_setup.configure(log_file, redaction)
    except OSError:
        # Ohne Log gibt es keinen anderen Kanal als stderr.
        code = ExitCode.OUTPUT_ERROR
        print(messages.render(code, log_file, credentials), file=sys.stderr)
        return int(code)
    try:
        for line in runinfo.header_lines(argv, credentials):
            log.debug(line)
        retention.prune_logs(log_file.parent)
        return int(args.handler(args, credentials, redaction, log_file, started))
    except (Exception, KeyboardInterrupt) as exc:
        code = _exit_code(exc)
        # DEBUG geht nur in die Datei: Traceback nie auf die Konsole.
        log.debug("exit %s (%d)", code.name, code, exc_info=exc)
        text = messages.render(code, log_file, credentials)
        log.debug("console: %s", text)
        # Direkt nach stderr statt über den Konsolen-Handler: der Text besteht nur aus
        # Konstanten und Pfaden, und die Redaction würde z. B. einen Patientennamen
        # auch im Benutzerordner des Log-Pfads schwärzen – Pfad dann unbrauchbar.
        print(text, file=sys.stderr)
        return int(code)
