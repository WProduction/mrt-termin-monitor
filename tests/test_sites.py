# SPDX-License-Identifier: Apache-2.0
"""Tests des sites.yaml-Loaders: was er ablehnt, ist Studiendaten-Schutz."""

import textwrap
from pathlib import Path

import pytest

from mrt_termin_monitor.errors import ConfigError
from mrt_termin_monitor.model import Billing, Exam
from mrt_termin_monitor.sites import _SLUG, load_sites

BLOCK = """\
dz_beispiel:
  name: Diagnosezentrum Beispiel
  adapter: xrweb
  abrechnung: kasse
  xrweb:
    host: termine.example.at
  untersuchungen:
    knie_rechts:
      code: MRKNR
"""

IRIS = """\
dok_beispiel:
  name: Kompetenzzentrum Beispiel
  adapter: iris
  abrechnung: kasse
  iris:
    base_url: https://iris.example.at/terminbuchung
    kalender: M
    ressource: {ressource}
  untersuchungen:
    knie_rechts:
      pattern: Knie rechts
"""


def _load(tmp_path: Path, text: str) -> dict:
    path = tmp_path / "sites.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return load_sites(path)


def _reject(tmp_path: Path, text: str, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        _load(tmp_path, text)


def test_packaged_file_loads_and_every_slug_is_snake_case() -> None:
    sites = load_sites()
    assert all(_SLUG.fullmatch(slug) for slug in sites)


def test_valid_block_maps_german_values_to_enums(tmp_path: Path) -> None:
    site = _load(tmp_path, BLOCK)["dz_beispiel"]
    assert site.name == "Diagnosezentrum Beispiel"
    assert site.adapter == "xrweb"
    assert site.billing is Billing.PUBLIC
    assert site.params == {"host": "termine.example.at"}
    assert site.exams == {Exam.KNEE_RIGHT: {"code": "MRKNR"}}
    assert site.timeout_s is None


def test_comment_only_file_has_no_sites(tmp_path: Path) -> None:
    assert _load(tmp_path, "# leer\n") == {}


def test_kombiniert_and_timeout_load(tmp_path: Path) -> None:
    text = BLOCK.replace("kasse", "kombiniert") + "  timeout_s: 45\n"
    site = _load(tmp_path, text)["dz_beispiel"]
    assert site.billing is Billing.COMBINED
    assert site.timeout_s == 45


def test_rejects_privat(tmp_path: Path) -> None:
    _reject(tmp_path, BLOCK.replace("kasse", "privat"), "privat")


def test_rejects_unknown_billing(tmp_path: Path) -> None:
    _reject(tmp_path, BLOCK.replace("kasse", "public"), "abrechnung")


def test_rejects_knie_links(tmp_path: Path) -> None:
    _reject(tmp_path, BLOCK.replace("knie_rechts", "knie_links"), "knie_links")


def test_rejects_unknown_adapter(tmp_path: Path) -> None:
    text = BLOCK.replace("adapter: xrweb", "adapter: selenium")
    _reject(tmp_path, text, "unknown adapter")


def test_rejects_duplicate_slug(tmp_path: Path) -> None:
    _reject(tmp_path, BLOCK + BLOCK, "duplicate key 'dz_beispiel'")


def test_rejects_duplicate_nested_key(tmp_path: Path) -> None:
    text = BLOCK.replace("  name: D", "  name: X\n  name: D")
    _reject(tmp_path, text, "duplicate key 'name'")


@pytest.mark.parametrize(
    "slug", ["dz-beispiel", "DZ_Beispiel", "dz__beispiel", "1dz", "dz_", "dz_büro"]
)
def test_rejects_non_snake_case_slug(tmp_path: Path, slug: str) -> None:
    _reject(tmp_path, BLOCK.replace("dz_beispiel", slug), "snake_case")


@pytest.mark.parametrize(
    ("old", "new", "match"),
    [
        ("  name: Diagnosezentrum Beispiel\n", "", "'name'"),
        ("name: Diagnosezentrum Beispiel", "name: ' '", "'name'"),
        ("  xrweb:\n    host: termine.example.at\n", "", "block 'xrweb'"),
        ("    host: termine.example.at\n", "", "block 'xrweb'"),  # leer = None
        ("    knie_rechts:\n      code: MRKNR\n", "    {}\n", "untersuchungen"),
        ("      code: MRKNR\n", "", "untersuchungen.knie_rechts"),
        ("  abrechnung: kasse\n", "  abrechnung: kasse\n  timeout: 30\n", "timeout"),
    ],
)
def test_rejects_broken_blocks(tmp_path: Path, old: str, new: str, match: str) -> None:
    assert old in BLOCK
    _reject(tmp_path, BLOCK.replace(old, new), match)


@pytest.mark.parametrize("value", ["0", "-1", "true", "'30'"])
def test_rejects_bad_timeout(tmp_path: Path, value: str) -> None:
    _reject(tmp_path, BLOCK + f"  timeout_s: {value}\n", "timeout_s")


def test_rejects_invalid_yaml_and_non_mapping(tmp_path: Path) -> None:
    _reject(tmp_path, "dz: [unclosed\n", "not valid YAML")
    _reject(tmp_path, "- dz_beispiel\n", "must map slugs")


def test_missing_file_is_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not readable"):
        load_sites(tmp_path / "fehlt.yaml")


def test_iris_resource_list_loads(tmp_path: Path) -> None:
    site = _load(tmp_path, IRIS.format(ressource="A,B"))["dok_beispiel"]
    # Unverändert als String – der Adapter reicht ihn als Query-Parameter durch.
    assert site.params["ressource"] == "A,B"
    assert site.params["kalender"] == "M"


@pytest.mark.parametrize("value", ['""', "' '", "1"])
def test_iris_rejects_empty_or_non_string_resource(tmp_path: Path, value: str) -> None:
    _reject(tmp_path, IRIS.format(ressource=value), "'ressource'")


def test_iris_requires_kalender(tmp_path: Path) -> None:
    text = IRIS.format(ressource="A").replace("    kalender: M\n", "")
    _reject(tmp_path, text, "'kalender'")
