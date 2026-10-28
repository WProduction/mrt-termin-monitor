# SPDX-License-Identifier: Apache-2.0
"""Schwärzt Secrets in Log-Einträgen, bevor ein Handler sie schreibt.

Die Log-Datei geht per Mail an den Support; die SVNR ist ein Gesundheitsdatum.
Deshalb zwei Linien:

1. Wertbasiert: jeder Wert aus der Credentials-Datei, zusätzlich in den Formen,
   in denen er in URLs oder Fehlermeldungen auftauchen kann (Leerzeichen nach
   Stelle 4, URL-kodiert). Ein reines Muster verpasst solche Umformatierungen.
2. SVNR-Regex für Werte, die (noch) nicht bekannt sind – etwa wenn das Parsen der
   Credentials-Datei selbst scheitert und der Fehlertext die Zeile zitiert.

Grenze: Secrets, die erst zur Laufzeit entstehen (Session-Token), kennt der Filter
nicht; sie dürfen gar nicht erst geloggt werden.
"""

import logging
import re
from collections.abc import Iterable
from urllib.parse import quote, quote_plus

MASK = "***"

# Gleiches Muster wie der Commit-Hook no-svnr: 10 Ziffern, optional Leerzeichen nach 4.
SVNR_PATTERN = re.compile(r"\b\d{4}\s?\d{6}\b")

# Nur für formatException; das Ausgabeformat legen die Handler fest.
_FORMATTER = logging.Formatter()


def variants(value: str) -> set[str]:
    """Liefert alle Schreibweisen eines Secrets, die geschwärzt werden müssen.

    Args:
        value: Secret im Klartext, z. B. die SVNR (10 Ziffern).

    Returns:
        Menge nicht-leerer Varianten: Original, URL-kodiert (``%20``/``+``) und bei
        10-stelligen Ziffernfolgen die Form mit Leerzeichen nach Stelle 4.
    """
    forms = {value.strip()}
    digits = re.sub(r"\s", "", value)
    if len(digits) == 10 and digits.isascii() and digits.isdigit():
        forms |= {digits, f"{digits[:4]} {digits[4:]}"}
    out = set(forms)
    for form in forms:
        out |= {quote(form, safe=""), quote_plus(form, safe="")}
    return {v for v in out if v}


class RedactionFilter(logging.Filter):
    """Handler-Filter, der Nachricht, Argumente, Exception- und Stack-Text schwärzt.

    Muss an jedem Handler hängen (nicht am Logger), damit auch Einträge aus
    Fremd-Loggern (urllib3 usw.) geschwärzt werden. Der Filter verändert den
    Record in place; die Schwärzung ist idempotent, mehrere Handler sind also
    unproblematisch.
    """

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets: list[str] = []
        self.add_secrets(secrets)

    def add_secrets(self, secrets: Iterable[str]) -> None:
        """Nimmt weitere Secret-Werte auf (z. B. nach dem Laden der Credentials).

        Args:
            secrets: Klartext-Werte; leere Strings werden ignoriert.
        """
        found = set(self._secrets)
        for secret in secrets:
            found |= variants(secret)
        # Längste zuerst: ist ein Wert Teil eines anderen ("Anna" in "Annabell"),
        # bliebe sonst ein Rest des längeren stehen ("***bell").
        self._secrets = sorted(found, key=len, reverse=True)

    def redact(self, text: str) -> str:
        """Ersetzt alle bekannten Secrets und SVNR-förmigen Ziffernfolgen durch ``***``."""
        for secret in self._secrets:
            text = text.replace(secret, MASK)
        return SVNR_PATTERN.sub(MASK, text)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except TypeError, ValueError:
            # Kaputter Log-Aufruf (Platzhalter passen nicht): logging würde Nachricht
            # und Argumente ungeschwärzt nach stderr melden – deshalb hier schon bündeln.
            message = f"{record.msg!s} {record.args!r}"
        record.msg = self.redact(message)
        record.args = None
        if record.exc_info:
            # Formatter.format nutzt exc_text, wenn gesetzt, statt neu zu formatieren.
            record.exc_text = self.redact(_FORMATTER.formatException(record.exc_info))
        elif record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        if record.stack_info:
            record.stack_info = self.redact(record.stack_info)
        return True
