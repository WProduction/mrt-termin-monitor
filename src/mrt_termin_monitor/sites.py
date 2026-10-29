# SPDX-License-Identifier: Apache-2.0
"""Loader der ``sites.yaml`` – prüft das Schema, bevor je ein Request rausgeht.

Handgeschriebene Prüfung statt Schema-Library: wenige Felder, und die
Fehlermeldung soll Slug und Feld nennen. Die Werte von ``abrechnung`` und den
``untersuchungen``-Schlüsseln sind dieselben deutschen Werte wie in der CSV
(``csv_output``) – ein Vokabular für Config und Auswertung.

Die adapter-spezifischen Pflichtfelder prüft der Loader erst, wenn der jeweilige
Adapter existiert; bis dahin ist nur der iris-Block vollständig festgelegt.
"""

import re
from dataclasses import dataclass
from importlib.resources.abc import Traversable
from typing import Any

import yaml

from mrt_termin_monitor import runinfo
from mrt_termin_monitor.csv_output import BILLING_VALUES, EXAM_VALUES
from mrt_termin_monitor.errors import ConfigError
from mrt_termin_monitor.model import Billing, Exam

ADAPTERS = ("xrweb", "klinix", "miranext", "doctena", "patapp", "iris")

# ASCII-snake_case: landet unverändert in CSV und Dateinamen; ein Bindestrich oder
# Umlaut wäre in Excel-Filtern und Pfaden eine Fehlerquelle.
_SLUG = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")
_BILLING = {csv: Billing(code) for code, csv in BILLING_VALUES.items()}
_EXAMS = {csv: Exam(code) for code, csv in EXAM_VALUES.items()}
_KEYS = {"name", "adapter", "abrechnung", "untersuchungen", "timeout_s"}


@dataclass(frozen=True)
class Site:
    """Ein validiertes Institut.

    Attributes:
        slug: Schlüssel aus ``sites.yaml``, CSV-Spalte ``institut_id``.
        name: lesbarer Name, CSV-Spalte ``institut_name``.
        adapter: einer aus ``ADAPTERS``.
        billing: Abrechnungsweg des gemessenen Pools.
        params: Block, der wie der Adapter heißt (Standort-Parameter).
        exams: je Untersuchung die adapter-spezifischen Werte.
        timeout_s: eigener Timeout; ``None`` = Standard des fetch-Layers.
    """

    slug: str
    name: str
    adapter: str
    billing: Billing
    params: dict[str, Any]
    exams: dict[Exam, dict[str, Any]]
    timeout_s: float | None = None


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader, der doppelte Schlüssel ablehnt.

    PyYAML nimmt sonst still den letzten Wert – ein kopierter Block mit altem Slug
    würde ein Institut ohne Fehlermeldung ersetzen.
    """

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise ConfigError(
                    f"sites.yaml line {key_node.start_mark.line + 1}:"
                    f" duplicate key {key!r}"
                )
            seen.add(key)
        return super().construct_mapping(node, deep)


def load_sites(source: Traversable | None = None) -> dict[str, Site]:
    """Lädt und validiert die Institute.

    Args:
        source: YAML-Datei; ``None`` = Package-Data ``sites.yaml``.

    Returns:
        Slug → Institut, in Dateireihenfolge; leer, wenn die Datei keine
        Blöcke enthält.

    Raises:
        ConfigError: Datei fehlt, ist kein gültiges YAML oder verletzt das Schema;
            die Meldung nennt Slug und Feld.
    """
    source = runinfo.sites_file() if source is None else source
    try:
        # yaml.load ist hier sicher: der Loader ist eine SafeLoader-Unterklasse.
        data = yaml.load(source.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except OSError as exc:
        raise ConfigError(f"sites.yaml not readable: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"sites.yaml is not valid YAML: {exc}") from exc
    if data is None:  # nur Kommentare
        return {}
    if not isinstance(data, dict):
        raise ConfigError("sites.yaml must map slugs to site blocks")
    return {slug: _site(slug, block) for slug, block in data.items()}


def _site(slug: object, block: object) -> Site:
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug):
        raise ConfigError(f"site slug {slug!r} is not ASCII snake_case")
    if not isinstance(block, dict):
        raise ConfigError(f"{slug}: block must be a mapping")

    name = _text(block, "name", slug)
    adapter = block.get("adapter")
    if adapter not in ADAPTERS:
        raise ConfigError(
            f"{slug}: unknown adapter {adapter!r} (allowed: {', '.join(ADAPTERS)})"
        )
    # Ein Tippfehler in einem optionalen Feld (``timeout`` statt ``timeout_s``)
    # würde sonst still ignoriert.
    unknown = set(block) - _KEYS - {adapter}
    if unknown:
        raise ConfigError(f"{slug}: unknown keys {sorted(map(str, unknown))}")

    billing = block.get("abrechnung")
    if billing == "privat":
        # Gemessen werden nur Kassen-Termine; reine Privat-Pools verfälschten die
        # Wartezeit der Studie.
        raise ConfigError(f"{slug}: abrechnung 'privat' is not measured")
    if billing not in _BILLING:
        raise ConfigError(
            f"{slug}: unknown abrechnung {billing!r} (allowed: {', '.join(_BILLING)})"
        )

    params = block.get(adapter)
    if not isinstance(params, dict):
        raise ConfigError(f"{slug}: block {adapter!r} missing or not a mapping")
    if adapter == "iris":
        _check_iris(slug, params)

    exams = block.get("untersuchungen")
    if not isinstance(exams, dict) or not exams:
        raise ConfigError(f"{slug}: 'untersuchungen' must be a non-empty mapping")
    for exam, values in exams.items():
        # Unbekannt ist auch ``knie_links``: die Studie misst nur das rechte Knie.
        if exam not in _EXAMS:
            raise ConfigError(
                f"{slug}: unknown untersuchung {exam!r} (allowed: {', '.join(_EXAMS)})"
            )
        if not isinstance(values, dict):
            raise ConfigError(f"{slug}.untersuchungen.{exam}: must be a mapping")

    # Optional für Portale, die bei erschöpftem Pool erst nach ~30 s antworten;
    # mit dem Standard-Timeout würde daraus „nicht erhoben“ statt der echten Antwort.
    timeout = block.get("timeout_s")
    if timeout is not None and (
        isinstance(timeout, bool)
        or not isinstance(timeout, int | float)
        or timeout <= 0
    ):
        raise ConfigError(f"{slug}: 'timeout_s' must be a number > 0")

    return Site(
        slug=slug,
        name=name,
        adapter=adapter,
        billing=_BILLING[billing],
        params=params,
        exams={_EXAMS[exam]: values for exam, values in exams.items()},
        timeout_s=timeout,
    )


def _check_iris(slug: str, params: dict[str, Any]) -> None:
    # Der Katalog des Portals führt keine Kalender-/Ressourcen-ID – ohne beide gibt
    # es keinen Terminabruf. ``ressource`` darf eine Liste wie ``A,B`` sein (zwei
    # Geräte eines Pools in einem Request, so wie der Portal-Client fragt); der
    # Adapter reicht den String unverändert durch, daher keine Ein-Zeichen-Prüfung.
    for field in ("kalender", "ressource"):
        _text(params, field, f"{slug}.iris")


def _text(block: dict[str, Any], field: str, where: str) -> str:
    value = block.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}: {field!r} must be a non-empty string")
    return value
