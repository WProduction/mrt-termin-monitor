# SPDX-License-Identifier: Apache-2.0
"""Gemeinsame pytest-Fixtures. Testdaten liegen byte-exakt unter tests/data/."""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from mrt_termin_monitor import paths


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Lenkt alle Programm-Pfade nach tmp_path und räumt das Logging danach ab.

    Kein Test soll je in die echten Ordner *Dokumente* oder ``%LOCALAPPDATA%``
    schreiben. Die Handler müssen geschlossen werden, weil Windows offene
    Log-Dateien sperrt und pytest tmp_path sonst nicht löschen kann.
    """
    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path / "home"))
    yield tmp_path / "home"
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()
