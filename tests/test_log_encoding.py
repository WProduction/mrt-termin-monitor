# SPDX-License-Identifier: Apache-2.0
"""Log-Datei verliert keine Zeichen – auch nicht bei Emoji oder lone surrogates."""

import logging
from pathlib import Path

from mrt_termin_monitor import logging_setup
from mrt_termin_monitor.redaction import RedactionFilter


def test_unicode_and_lone_surrogate_survive(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "run_test.log"
    logging_setup.configure(log_file, RedactionFilter())
    log = logging.getLogger("probe")
    log.debug("umlaut ä€😀")
    # Lone surrogate (z. B. aus kaputtem Dateinamen): utf-8 strict würde scheitern.
    log.debug("surrogate \ud800 ende")
    log.info("danach geht es weiter")
    logging.shutdown()

    # strict lesen: die Datei muss gültiges UTF-8 sein.
    text = log_file.read_text(encoding="utf-8")
    assert "umlaut ä€😀" in text
    assert "surrogate \\ud800 ende" in text
    assert "danach geht es weiter" in text


def test_console_gets_info_but_not_debug(tmp_path: Path, capsys) -> None:
    logging_setup.configure(tmp_path / "run.log", RedactionFilter())
    logging.getLogger("probe").debug("nur datei")
    logging.getLogger("probe").info("auch konsole")
    err = capsys.readouterr().err
    assert "auch konsole" in err
    assert "nur datei" not in err


def test_urllib3_below_warning_is_dropped(tmp_path: Path) -> None:
    log_file = tmp_path / "run.log"
    logging_setup.configure(log_file, RedactionFilter())
    logging.getLogger("urllib3.connectionpool").debug("GET /?q=geheim")
    logging.getLogger("urllib3.connectionpool").warning("retry")
    logging.shutdown()
    text = log_file.read_text(encoding="utf-8")
    assert "geheim" not in text
    assert "retry" in text
