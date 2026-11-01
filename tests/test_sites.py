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
    day_table_columns: 2
  untersuchungen:
    knie_rechts:
      code: MRKNR
      expected_title: MR Knie
"""

# Inhalt des xrweb-Blocks und der Untersuchung in BLOCK, für Ersetzungen.
XRWEB = "    host: termine.example.at\n    day_table_columns: 2\n"
KNIE = "      code: MRKNR\n      expected_title: MR Knie\n"

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
    assert site.params == {"host": "termine.example.at", "day_table_columns": 2}
    assert site.exams == {
        Exam.KNEE_RIGHT: {"code": "MRKNR", "expected_title": "MR Knie"}
    }
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
        (f"  xrweb:\n{XRWEB}", "", "block 'xrweb'"),
        (XRWEB, "", "block 'xrweb'"),  # leer = None
        (f"    knie_rechts:\n{KNIE}", "    {}\n", "untersuchungen"),
        (KNIE, "", "untersuchungen.knie_rechts"),
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


def test_xrweb_site_param_loads(tmp_path: Path) -> None:
    text = BLOCK.replace(XRWEB, XRWEB + "    site_param: p\n")
    assert _load(tmp_path, text)["dz_beispiel"].params["site_param"] == "p"


@pytest.mark.parametrize(
    ("old", "new", "match"),
    [
        ("    host: termine.example.at\n", "", "'host'"),
        ("host: termine.example.at", "host: https://termine.example.at", "bare"),
        ("host: termine.example.at", "host: termine.example.at/x", "bare"),
        ("    day_table_columns: 2\n", "", "day_table_columns"),
        ("day_table_columns: 2", "day_table_columns: 0", "day_table_columns"),
        ("day_table_columns: 2", "day_table_columns: true", "day_table_columns"),
        ("day_table_columns: 2", "day_table_columns: '2'", "day_table_columns"),
        (XRWEB, XRWEB + "    site_param: ''\n", "'site_param'"),
        # Vertippter Schlüssel: der Site-Parameter fiele sonst still weg.
        (XRWEB, XRWEB + "    site_parm: p\n", "site_parm"),
        (KNIE, KNIE + "      exas: MRKNR\n", "exas"),
        ("      code: MRKNR\n", "", "'code'"),
        # Ungequoteter Zahlencode wird int – muss als String gequotet werden.
        ("code: MRKNR", "code: 2244", "'code'"),
        ("      expected_title: MR Knie\n", "", "'expected_title'"),
        ("expected_title: MR Knie", "expected_title: ' '", "'expected_title'"),
    ],
)
def test_xrweb_rejects(tmp_path: Path, old: str, new: str, match: str) -> None:
    assert old in BLOCK
    _reject(tmp_path, BLOCK.replace(old, new), match)


def test_xrweb_quoted_numeric_code_loads(tmp_path: Path) -> None:
    text = BLOCK.replace("code: MRKNR", "code: '2244'")
    site = _load(tmp_path, text)["dz_beispiel"]
    assert site.exams[Exam.KNEE_RIGHT]["code"] == "2244"


KLINIX = """\
dz_beispiel:
  name: Diagnosezentrum Beispiel
  adapter: klinix
  abrechnung: kombiniert
  klinix:
    host: termine.example.at
  untersuchungen:
    knie_rechts:
      code: mknr
"""


def test_klinix_block_loads(tmp_path: Path) -> None:
    site = _load(tmp_path, KLINIX)["dz_beispiel"]
    assert site.adapter == "klinix"
    assert site.billing is Billing.COMBINED
    assert site.params == {"host": "termine.example.at"}
    assert site.exams == {Exam.KNEE_RIGHT: {"code": "mknr"}}


MIRANEXT = """\
mn_beispiel:
  name: Radiologie Beispiel
  adapter: miranext
  abrechnung: kasse
  miranext:
    portal_id: 3
    device: MR
  untersuchungen:
    knie_rechts:
      search: Kniegelenk
      service_name: MR Kniegelenk rechts
      expected_id: 00000000-0000-4000-8000-aaaaaaaaaa01
"""


def test_miranext_block_loads(tmp_path: Path) -> None:
    site = _load(tmp_path, MIRANEXT)["mn_beispiel"]
    assert site.params == {"portal_id": 3, "device": "MR"}
    assert site.billing is Billing.PUBLIC
    assert site.exams[Exam.KNEE_RIGHT] == {
        "search": "Kniegelenk",
        "service_name": "MR Kniegelenk rechts",
        "expected_id": "00000000-0000-4000-8000-aaaaaaaaaa01",
    }


@pytest.mark.parametrize(
    ("old", "new", "match"),
    [
        ("    host: termine.example.at\n", "", "block 'klinix'"),  # leer = None
        ("host: termine.example.at", "host: ' '", "'host'"),
        ("host: termine.example.at", "host: https://termine.example.at", "bare"),
        ("host: termine.example.at", "host: termine.example.at/x", "bare"),
        ("host: termine.example.at", "host: termine.example.at:443", "bare"),
        # Mitkopierter Schlüssel aus einer anderen Config-Form fiele sonst still weg.
        (
            "    host: termine.example.at\n",
            "    host: termine.example.at\n    exam_codes: x\n",
            "exam_codes",
        ),
        ("      code: mknr\n", "      {}\n", "'code'"),
        ("      code: mknr\n", "      exas: mknr\n", "exas"),
        # Ungequoteter Zahlencode wird int – muss als String gequotet werden.
        ("code: mknr", "code: 2244", "'code'"),
        ("code: mknr", "code: ' '", "'code'"),
        # Kein Titel-Schutz bei klinix: das Feld darf nicht so tun, als gäbe es ihn.
        (
            "      code: mknr\n",
            "      code: mknr\n      expected_title: MR Knie\n",
            "expected_title",
        ),
    ],
)
def test_klinix_rejects(tmp_path: Path, old: str, new: str, match: str) -> None:
    assert old in KLINIX
    _reject(tmp_path, KLINIX.replace(old, new), match)


def test_klinix_requires_host(tmp_path: Path) -> None:
    text = KLINIX.replace("    host: termine.example.at\n", "    other: x\n")
    _reject(tmp_path, text, "other")
    text = KLINIX.replace("    host: termine.example.at\n", "    {}\n")
    _reject(tmp_path, text, "'host'")


def test_klinix_quoted_numeric_code_loads(tmp_path: Path) -> None:
    text = KLINIX.replace("code: mknr", "code: '2244'")
    site = _load(tmp_path, text)["dz_beispiel"]
    assert site.exams[Exam.KNEE_RIGHT]["code"] == "2244"


@pytest.mark.parametrize(
    ("old", "new", "match"),
    [
        # Vertippte Schlüssel fielen sonst still weg.
        ("    device: MR\n", "    device: MR\n    portal: 3\n", "portal"),
        ("      search: Kniegelenk\n", "      suche: Kniegelenk\n", "suche"),
        # Der Mandant geht ungequotet in die URL: nur echte Ganzzahlen > 0.
        ("    portal_id: 3\n", "", "'portal_id'"),
        ("portal_id: 3", "portal_id: true", "'portal_id'"),
        ("portal_id: 3", "portal_id: '3'", "'portal_id'"),
        ("portal_id: 3", "portal_id: 0", "'portal_id'"),
        ("    device: MR\n", "", "'device'"),
        ("device: MR", "device: ' '", "'device'"),
        ("      search: Kniegelenk\n", "", "'search'"),
        ("search: Kniegelenk", "search: ''", "'search'"),
        ("      service_name: MR Kniegelenk rechts\n", "", "'service_name'"),
        ("service_name: MR Kniegelenk rechts", "service_name: ' '", "'service_name'"),
        (
            "      expected_id: 00000000-0000-4000-8000-aaaaaaaaaa01\n",
            "",
            "expected_id",
        ),
        (
            "expected_id: 00000000-0000-4000-8000-aaaaaaaaaa01",
            "expected_id: 3",
            "expected_id",
        ),
        # Die Studie misst nur das rechte Knie; der Katalog nennt die Seite im Namen.
        ("Kniegelenk rechts", "Kniegelenk links", "left side"),
        ("Kniegelenk rechts", "Kniegelenk LINKS", "left side"),
    ],
)
def test_miranext_rejects(tmp_path: Path, old: str, new: str, match: str) -> None:
    assert old in MIRANEXT
    _reject(tmp_path, MIRANEXT.replace(old, new), match)
