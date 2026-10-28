# SPDX-License-Identifier: Apache-2.0
"""Das Codebook docs/datenfelder.md deckt jede Spalte und jeden CSV-Wert ab."""

from pathlib import Path

import pytest

from mrt_termin_monitor import csv_output

DOC = Path(__file__).parents[1] / "docs" / "datenfelder.md"


@pytest.fixture(scope="module")
def lines() -> list[str]:
    return DOC.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(("nr", "name"), list(enumerate(csv_output.FIELDS, start=1)))
def test_every_field_documented_in_order(lines: list[str], nr: int, name: str) -> None:
    assert any(line.startswith(f"| {nr} | `{name}` |") for line in lines)


def test_no_extra_fields_documented(lines: list[str]) -> None:
    # Zeilen der Spalten-Tabelle beginnen mit "| <Nr> |".
    numbered = [line for line in lines if line.split(" | ")[0][2:].isdigit()]
    assert len(numbered) == len(csv_output.FIELDS)


@pytest.mark.parametrize(
    "value",
    [
        *csv_output.EXAM_VALUES.values(),
        *csv_output.BILLING_VALUES.values(),
        *csv_output.STATUS_VALUES.values(),
    ],
)
def test_every_csv_value_documented(lines: list[str], value: str) -> None:
    # Neuer Enum-Wert ist eine Schema-Änderung – die Leserin braucht seine Bedeutung.
    assert any(line.startswith(f"| `{value}` |") for line in lines)
