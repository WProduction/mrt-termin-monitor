# SPDX-License-Identifier: Apache-2.0
"""Smoke-Test der Kommandozeile."""

import pytest

from mrt_termin_monitor import __version__
from mrt_termin_monitor.cli import main


def test_version_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    # argparse beendet bei --version per SystemExit(0); geprüft wird die Ausgabe.
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"mrt-termin-monitor {__version__}"
