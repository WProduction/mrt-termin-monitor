# SPDX-License-Identifier: Apache-2.0
"""Jeder Exit-Code hat eine Meldung und eine Zeile in docs/exit-codes.md."""

from pathlib import Path

import pytest

from mrt_termin_monitor import messages
from mrt_termin_monitor.errors import ExitCode

DOC = Path(__file__).parents[1] / "docs" / "exit-codes.md"


@pytest.mark.parametrize("code", list(ExitCode))
def test_code_has_message(code: ExitCode) -> None:
    msg = messages.MESSAGES[code]
    assert msg.was
    if code in messages.ERROR_CODES:
        assert msg.warum and msg.tun


@pytest.mark.parametrize("code", list(ExitCode))
def test_code_documented(code: ExitCode) -> None:
    lines = DOC.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith(f"| {code.value} | `{code.name}` |") for line in lines)


@pytest.mark.parametrize("code", list(ExitCode))
def test_console_text_is_ascii(code: ExitCode) -> None:
    text = messages.render(code, Path("C:/log.log"), Path("C:/c.yaml"), gaps=2)
    assert text.isascii()


def test_error_render_has_three_parts_log_and_contact() -> None:
    log, cred = Path("C:/x/run.log"), Path("C:/y/credentials.yaml")
    lines = messages.render(ExitCode.CONFIG_ERROR, log, cred).splitlines()
    assert lines[0].startswith("FEHLER: ")
    assert str(cred) in lines[2]
    assert str(log) in lines[3]
    assert messages.KONTAKT_MAIL in lines[4]


def test_partial_shows_gap_count() -> None:
    text = messages.render(ExitCode.PARTIAL, Path("l"), Path("c"), gaps=3)
    assert text.startswith("OK MIT LUECKEN (3):")
