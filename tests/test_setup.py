# SPDX-License-Identifier: Apache-2.0
"""Einrichtungs-Dialog und Laden der Credentials-Datei."""

from pathlib import Path

import pytest

from mrt_termin_monitor import setup
from mrt_termin_monitor.errors import ConfigError

SVNR = "1234" + "010180"


def dialog(target: Path, answers: list[str]) -> tuple[dict[str, str], list[str]]:
    said: list[str] = []
    asked = iter(answers)
    data = setup.run_dialog(target, ask=lambda _prompt: next(asked), say=said.append)
    return data, said


def test_nine_digits_asks_again_then_writes(tmp_path: Path) -> None:
    target = tmp_path / "cfg" / "credentials.yaml"
    data, said = dialog(target, ["123401018", "1234 " + "010180", "Anna Muster", ""])
    assert said.count(setup.messages.SETUP_SVNR_UNGUELTIG) == 1
    assert data == {"svnr": SVNR, "patient_name": "Anna Muster", "patient_mobile": ""}
    assert str(target) in said[-1]
    assert setup.load_credentials(target) == data


def test_svnr_written_as_string(tmp_path: Path) -> None:
    target = tmp_path / "credentials.yaml"
    dialog(target, ["0" + "123010180", "", ""])
    # Führende Null bleibt erhalten: Wert ist in der Datei gequotet.
    assert setup.load_credentials(target)["svnr"] == "0" + "123010180"


def test_unquoted_svnr_with_leading_zero(tmp_path: Path) -> None:
    # Von Hand eingetragen, ohne Quotes; nur Ziffern 0–7 = YAML-1.1-Oktalform.
    svnr = "0123" + "456701"
    target = tmp_path / "credentials.yaml"
    target.write_text(f"svnr: {svnr}\npatient_name:\n", encoding="utf-8")
    assert setup.load_credentials(target) == {
        "svnr": svnr,
        "patient_name": "",
        "patient_mobile": "",
    }


@pytest.mark.parametrize(
    "content",
    [
        None,  # Datei fehlt
        "svnr: [kaputt\n",  # kein gültiges YAML
        "- liste\n",  # kein Mapping
        "patient_name: x\n",  # SVNR fehlt
        "svnr: '123'\n",  # SVNR zu kurz
    ],
)
def test_broken_file_is_config_error(tmp_path: Path, content: str | None) -> None:
    target = tmp_path / "credentials.yaml"
    if content is not None:
        target.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError):
        setup.load_credentials(target)


def test_non_ascii_digits_rejected() -> None:
    # Arabisch-indische Ziffern; zusammengesetzt, weil auch sie den Hook no-svnr träfen.
    assert setup.normalize_svnr("١" * 10) is None
