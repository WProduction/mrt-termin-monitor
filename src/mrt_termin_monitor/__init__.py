# SPDX-License-Identifier: Apache-2.0
"""mrt-termin-monitor – Erhebung online sichtbarer MRT-Termine für eine Studie."""

from importlib.metadata import version

# Einzige Versionsquelle ist pyproject.toml; hier nur gelesen, damit die Nummer
# nicht an zwei Stellen gepflegt wird.
__version__ = version("mrt-termin-monitor")
