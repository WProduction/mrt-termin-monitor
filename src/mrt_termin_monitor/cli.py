# SPDX-License-Identifier: Apache-2.0
"""Kommandozeile von mrt-termin-monitor."""

import argparse

from mrt_termin_monitor import __version__


def main(argv: list[str] | None = None) -> int:
    """Parst die Argumente und führt das gewählte Kommando aus.

    Args:
        argv: Argumente ohne Programmnamen; ``None`` liest ``sys.argv[1:]``.

    Returns:
        Exit-Code des Prozesses (0 = Erfolg).
    """
    # prog fest, sonst zeigt argparse bei ``python -m`` "__main__.py" an.
    parser = argparse.ArgumentParser(prog="mrt-termin-monitor")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.parse_args(argv)
    return 0
