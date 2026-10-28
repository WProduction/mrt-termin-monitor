# SPDX-License-Identifier: Apache-2.0
"""Exit-Codes und die Exceptions, die der Top-Level-Handler auf sie abbildet.

Die Zahlen sieht die Operatorin nie; sie sind für Scheduler und Support. Die
Entwickler-Tabelle steht in ``docs/exit-codes.md`` (ein Test hält sie vollständig).
"""

from enum import IntEnum
from typing import ClassVar


class ExitCode(IntEnum):
    """Prozess-Exit-Codes. 1 ≠ 0, damit Lücken im Scheduler-Verlauf sichtbar sind."""

    OK = 0
    PARTIAL = 1
    CONFIG_ERROR = 2
    NO_SITE_REACHABLE = 3
    OUTPUT_ERROR = 4
    UNEXPECTED = 5
    ABORTED = 10


class MonitorError(Exception):
    """Basis aller erwarteten Fehler; ``exit_code`` bestimmt Code und Meldung."""

    exit_code: ClassVar[ExitCode] = ExitCode.UNEXPECTED


class ConfigError(MonitorError):
    """Konfiguration fehlt oder ist ungültig (Credentials, Argumente, Slugs)."""

    exit_code = ExitCode.CONFIG_ERROR


class NoSiteReachableError(MonitorError):
    """Kein einziges Institut war erreichbar (vermutlich kein Netz)."""

    exit_code = ExitCode.NO_SITE_REACHABLE


class OutputError(MonitorError):
    """CSV oder Log nicht schreibbar."""

    exit_code = ExitCode.OUTPUT_ERROR
