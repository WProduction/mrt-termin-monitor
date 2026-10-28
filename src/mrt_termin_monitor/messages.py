# SPDX-License-Identifier: Apache-2.0
"""Alle deutschen Konsolentexte für die Operatorin – nur hier, als Python-Konstanten.

Bewusst keine Textdatei: eine kaputte Datei könnte sonst genau die Fehlermeldung
verhindern, die sie erklären soll. Texte in ASCII-Umschrift (``pruefen``), damit
sie in jeder Windows-Konsole lesbar bleiben; Statuswörter in Großbuchstaben.
Muster bei Fehlern: was passiert ist / warum vermutlich / was tun.
"""

from dataclasses import dataclass
from pathlib import Path

from mrt_termin_monitor.errors import ExitCode

# ponytail: Platzhalter (empfängt keine Mails) – vor Release 0.1.0 durch eine echte
# Support-Adresse ersetzen.
KONTAKT_MAIL = "72034176+WProduction@users.noreply.github.com"


@dataclass(frozen=True)
class Message:
    """Drei-Teile-Meldung. Platzhalter: ``{credentials}``, ``{gaps}``.

    Attributes:
        was: Was passiert ist (bei Erfolg/Abbruch inkl. Statuswort).
        warum: Vermutliche Ursache; leer, wenn es nichts zu erklären gibt.
        tun: Was die Operatorin tun soll; leer, wenn nichts zu tun ist.
    """

    was: str
    warum: str
    tun: str


MESSAGES: dict[ExitCode, Message] = {
    ExitCode.OK: Message("OK: Alle Institute wurden erfasst.", "", ""),
    ExitCode.PARTIAL: Message(
        "OK MIT LUECKEN ({gaps}): Nicht alle Institute konnten erfasst werden.",
        "Vermutlich war ein Institut kurz nicht erreichbar"
        " oder hat seine Webseite geaendert.",
        "Nichts zu tun; beim naechsten Lauf wird es erneut versucht.",
    ),
    ExitCode.CONFIG_ERROR: Message(
        "Die Konfiguration konnte nicht gelesen werden.",
        "Vermutlich fehlt die Datei credentials.yaml, oder die"
        " Sozialversicherungsnummer darin fehlt oder hat einen Tippfehler.",
        "Bitte die Einrichtung erneut starten oder die Datei {credentials} pruefen",
    ),
    ExitCode.NO_SITE_REACHABLE: Message(
        "Kein Institut war erreichbar.",
        "Vermutlich besteht gerade keine Internetverbindung.",
        "Bitte die Internetverbindung pruefen und das Programm erneut starten",
    ),
    ExitCode.OUTPUT_ERROR: Message(
        "Die Ergebnis- oder Log-Datei konnte nicht geschrieben werden.",
        "Vermutlich ist die Datei gerade in Excel geoeffnet oder der Ordner"
        " Dokumente ist nicht beschreibbar.",
        "Bitte Excel schliessen und das Programm erneut starten",
    ),
    ExitCode.UNEXPECTED: Message(
        "Im Programm ist ein unerwarteter Fehler aufgetreten.",
        "Vermutlich hat sich eine Instituts-Webseite geaendert"
        " oder das Programm hat einen Fehler.",
        "Bitte das Programm spaeter erneut starten",
    ),
    ExitCode.ABORTED: Message(
        "ABGEBROCHEN: Der Lauf wurde vorzeitig beendet.",
        "Das Programm wurde mit Strg+C oder durch Schliessen des Fensters gestoppt.",
        "Das Programm kann jederzeit neu gestartet werden.",
    ),
}

# Dialog des Subcommands ``setup`` (einzige Stelle mit Eingaben).
SETUP_TITEL = "Einrichtung mrt-termin-monitor"
SETUP_SVNR = "Sozialversicherungsnummer (10 Ziffern): "
SETUP_SVNR_UNGUELTIG = (
    "Die Nummer muss genau 10 Ziffern haben (Leerzeichen sind erlaubt)."
    " Bitte erneut eingeben."
)
SETUP_NAME = "Name (optional, Enter = leer lassen): "
SETUP_MOBIL = "Mobilnummer (optional, Enter = leer lassen): "
SETUP_GESPEICHERT = "OK: Gespeichert in {path}"

# Bei diesen Codes folgt der Hinweis auf die Log-Datei (Konsolen-Vertrag).
ERROR_CODES = frozenset(
    {
        ExitCode.CONFIG_ERROR,
        ExitCode.NO_SITE_REACHABLE,
        ExitCode.OUTPUT_ERROR,
        ExitCode.UNEXPECTED,
    }
)


def render(code: ExitCode, log_file: Path, credentials: Path, gaps: int = 0) -> str:
    """Baut den Konsolentext zu einem Exit-Code.

    Args:
        code: Exit-Code des Laufs.
        log_file: Absoluter Pfad der Log-Datei dieses Laufs.
        credentials: Absoluter Pfad der Credentials-Datei.
        gaps: Zahl der nicht erfassten Institute (nur für ``PARTIAL``).

    Returns:
        Mehrzeiliger Text ohne abschließenden Zeilenumbruch. Bei Fehlern:
        ``FEHLER: was`` / warum / tun / Log-Pfad / Kontakt-Mail.
    """
    msg = MESSAGES[code]
    lines = [msg.was, msg.warum, msg.tun]
    if code in ERROR_CODES:
        lines[0] = f"FEHLER: {lines[0]}"
        lines += ["oder die Log-Datei {log}", "an {kontakt} schicken."]
    fields = {
        "credentials": credentials,
        "gaps": gaps,
        "log": log_file,
        "kontakt": KONTAKT_MAIL,
    }
    return "\n".join(line.format(**fields) for line in lines if line)
