# SPDX-License-Identifier: Apache-2.0
"""XR-WEB-Parser (D.A.T.A.): Terminvorschlags-HTML → frühestes Termin-Datum.

Vier Regeln, in dieser Reihenfolge: Weiterleitungsseite erkennen, Titel prüfen,
Spaltenzahl der Tages-Tabelle prüfen, leere Liste als „keine Termine“. Jede
Abweichung von der erwarteten Struktur wird ein Fehlerstatus, nie ein stilles
„keine Termine“. Reine Funktion – kein Netz, kein Datei-I/O.
"""

import re
from dataclasses import dataclass
from datetime import date

from bs4 import BeautifulSoup

from mrt_termin_monitor.model import Status

# Kennzeichen der „keine Online-Vergabe möglich“-Seite in der finalen URL. Nur der
# Pfad, weil Query und Host je Mandant variieren.
_FORWARD_PAGE_MARKER = "/EKOSAppointmentForward/ForwardPage"

# ID der Tages-Tabelle im gerenderten HTML – auf allen Mandanten gleich, weil
# serverseitig dieselbe ASP.NET-View rendert.
_DAY_TABLE_ID = "tblAppointmentResponse_DayInfos"

# Erste Zelle: „Di., 11.08.2026“ oder „Fr, 14.08.2026“ (ohne Punkt nach dem
# Wochentag, je Mandant verschieden) – deshalb Regex auf dd.mm.yyyy statt
# strptime mit festem Wochentags-Präfix.
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


@dataclass(frozen=True)
class XrWebResult:
    """Parse-Ergebnis: Status und frühestes Datum mit Zähler > 0 (nur bei ``OK``)."""

    status: Status
    slot_date: date | None = None


def parse(
    html: bytes | str,
    expected_title: str,
    day_table_columns: int,
    final_url: str,
) -> XrWebResult:
    """Parst eine XR-WEB-Terminvorschlagsseite.

    Args:
        html: Roh-HTML der finalen Antwort (Bytes wie archiviert oder str).
        expected_title: Untersuchungsname, der im Text stehen muss (Teilstring);
            schützt davor, dass ein umbenannter Code still eine andere
            Untersuchung misst.
        day_table_columns: Zahl der Zählspalten der Tages-Tabelle (z. B. 2 für
            Vormittag/Nachmittag); jede Abweichung ist Layout-Drift.
        final_url: finale URL nach Redirects (Erkennung der Weiterleitungsseite).

    Returns:
        ``XrWebResult``; ``slot_date`` ist das früheste Datum mit Zähler > 0 in
        irgendeiner Spalte, sonst ``None``.
    """
    # Weiterleitung vor der Titelprüfung: die Seite hat weder Titel noch Tabelle,
    # ein ERROR_PARSE würde den spezifischeren Befund verdecken. Nie als
    # „keine Termine“ werten – das Portal hat schlicht nichts angezeigt.
    if _FORWARD_PAGE_MARKER.lower() in final_url.lower():
        return XrWebResult(Status.ERROR_REDIRECT)

    soup = BeautifulSoup(html, "lxml")

    # Titel vor jedem Zugriff auf die Termindaten. get_text() statt Rohstring,
    # damit HTML-Entities keine Rolle spielen.
    if expected_title not in soup.get_text():
        return XrWebResult(Status.ERROR_PARSE)

    table = soup.find(id=_DAY_TABLE_ID)
    if table is None:
        # Titel da, Tabelle weg: Struktur-Drift. Lieber Alarm als ein stilles,
        # falsches „keine Termine“.
        return XrWebResult(Status.ERROR_PARSE)

    earliest: date | None = None
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue  # Kopf- und Leerzeilen

        # Erste Zelle Datum + genau day_table_columns Zählspalten.
        if len(cells) != 1 + day_table_columns:
            return XrWebResult(Status.ERROR_PARSE)

        m = _DATE_RE.search(cells[0].get_text())
        if m is None:
            return XrWebResult(Status.ERROR_PARSE)
        day, month, year = (int(g) for g in m.groups())
        row_date = date(year, month, day)

        for td in cells[1:]:
            counter_text = td.get_text().strip()
            if not counter_text.isdigit():
                return XrWebResult(Status.ERROR_PARSE)
            # Es zählt das früheste Datum mit Zähler > 0 in IRGENDEINER Spalte –
            # Vormittag und Nachmittag sind derselbe Terminpool.
            if int(counter_text) > 0 and (earliest is None or row_date < earliest):
                earliest = row_date

    if earliest is None:
        # Korrekte, aber leere Liste (keine Zeilen oder überall Zähler 0).
        return XrWebResult(Status.NO_SLOTS)
    return XrWebResult(Status.OK, earliest)
