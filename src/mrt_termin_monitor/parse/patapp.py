# SPDX-License-Identifier: Apache-2.0
"""PatApp-Parser (HGS PatApp/PatWeb): SOAP-Antworten → Katalog, Ticket, Termine.

Der ASMX-Dienst liefert keine WSDL (``?WSDL`` → HTTP 500); die Antwortformen
stammen aus dem ausgelieferten Portal-Client und sind live bestätigt:

* ``GetShortLongTitlesResult`` – ADO.NET-Diffgram, je Untersuchung ein Element
  ``ShortLongTitles`` mit ``tshort`` (Code), ``tlong`` (Klartext), ``duration``,
  ``modality``, ``category``.
* ``GetPatientTicketResult`` – **kein** XML-Baum, sondern ein pipe-getrennter
  String ``ticket|fehler|hasName|isPatWeb`` (der Client macht ``split('|')``).
  Ein nicht leeres zweites Feld ist der Fehler, auch wenn HTTP 200 kam.
* ``GetProposedDatesResult`` – Diffgram (mit eingebettetem ``xs:schema``) und
  darin ``GetProposedDates``; dort entweder ``Errors/Description`` oder N-mal
  ``Dates`` mit ``start``/``startDate``/``startTime``/``id``.

Alle Funktionen sind rein (kein Netz, kein Datei-I/O, kein Logging) und parsen
**namensraum-agnostisch** über den Local-Name: der Server mischt
soap/soap12/diffgr/msdata-Präfixe je nach Operation, und ein Präfixwechsel bei
einem Produkt-Update darf die Messung nicht still auf „keine Termine“ kippen.
Format-Drift wirft ``ValueError`` – der Adapter macht daraus eine
Fehlerzeile, nie ein ``NO_SLOTS``.

``xml.etree`` genügt: expat löst keine externen Entities auf, und der
Entity-Expansions-Schutz ist in der eingesetzten Python-Version eingebaut.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from xml.etree import ElementTree

# Das erste Pipe-Feld der Ticket-Antwort ist das Sitzungsticket. Präfix des
# Elements beliebig (``GetPatientTicketResult`` oder ``ns:GetPatientTicketResult``),
# ``<`` und ``|`` begrenzen das Feld; leer (Fehlerfall) bleibt leer.
_TICKET_FIELD = re.compile(rb"(<(?:[\w.-]+:)?GetPatientTicketResult\b[^>]*>)([^|<]+)")
_TICKET_PLACEHOLDER = b"ticket-removed"


@dataclass(frozen=True)
class CatalogEntry:
    """Ein Katalogeintrag aus ``GetShortLongTitles``.

    Attributes:
        tshort: Untersuchungscode, geht als ``<tshort>`` in ``GetProposedDates``.
        tlong: Klartext, z. B. „MR Kniegelenk rechts“ – darauf wirkt das Muster.
        modality: „MR“, „CT“, „MRP“ …; der Vergleich ist case-insensitiv.
        category: hausinterne Gruppierung (nur zur Diagnose).
    """

    tshort: str
    tlong: str
    modality: str
    category: str


@dataclass(frozen=True)
class Ticket:
    """Ergebnis von ``GetPatientTicket`` (Anmeldung mit SVNR).

    Attributes:
        value: das Sitzungsticket; leer, wenn ``error`` gesetzt ist. Darf nie in
            Log, Hinweis, Exception oder Archiv landen.
        error: Fehlertext des Servers (z. B. unbekannte SVNR) oder ``""``.
    """

    value: str
    error: str


def _local(tag: str) -> str:
    """Local-Name eines ElementTree-Tags (``{ns}name`` → ``name``)."""
    return tag.rpartition("}")[2]


def _find_all(root: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    """Alle Elemente mit diesem Local-Name, Namensraum egal."""
    return [el for el in root.iter() if _local(el.tag) == name]


def _find_one(root: ElementTree.Element, name: str) -> ElementTree.Element | None:
    """Erstes Element mit diesem Local-Name oder ``None``."""
    for el in root.iter():
        if _local(el.tag) == name:
            return el
    return None


def _fields(el: ElementTree.Element) -> dict[str, str]:
    """Direkte Kindelemente eines Diffgram-Datensatzes als {local-name: Text}."""
    return {_local(c.tag): (c.text or "").strip() for c in el}


def _fault(root: ElementTree.Element) -> str | None:
    """SOAP-Fault-Text, falls der Envelope einen Fault transportiert."""
    fault = _find_one(root, "Fault")
    if fault is None:
        return None
    # ``Reason`` trägt bei eingerücktem XML nur Whitespace; leere Teile raus.
    texts = (
        (el.text or "").strip()
        for el in fault.iter()
        if _local(el.tag) in ("Text", "faultstring", "Reason")
    )
    return " / ".join(t for t in texts if t) or "SOAP fault without text"


def _root(payload: bytes | str) -> ElementTree.Element:
    """Parst das XML und meldet einen SOAP-Fault sofort als ``ValueError``."""
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise ValueError(f"response is not well-formed XML: {exc}") from exc
    fault = _fault(root)
    if fault:
        raise ValueError(f"SOAP fault: {fault}")
    return root


def parse_catalogue(payload: bytes | str) -> list[CatalogEntry]:
    """Liest den Untersuchungskatalog aus einer ``GetShortLongTitles``-Antwort.

    Args:
        payload: Roh-Antwort (Bytes wie archiviert oder str).

    Returns:
        Alle Katalogeinträge mit Code, in Server-Reihenfolge.

    Raises:
        ValueError: kein XML, SOAP-Fault oder kein einziger Eintrag. Ein leerer
            Katalog ist immer ein Fehler (der Portal-Client bricht dort ebenfalls
            ab), nie „keine Untersuchung im Angebot“.
    """
    root = _root(payload)
    entries = []
    for el in _find_all(root, "ShortLongTitles"):
        f = _fields(el)
        if not f.get("tshort"):
            continue
        entries.append(
            CatalogEntry(
                tshort=f["tshort"],
                tlong=f.get("tlong", ""),
                modality=f.get("modality", ""),
                category=f.get("category", ""),
            )
        )
    if not entries:
        raise ValueError("GetShortLongTitles returned no ShortLongTitles entry")
    return entries


def select_exam(
    entries: list[CatalogEntry], pattern: str, modality: str = "MR"
) -> CatalogEntry:
    """Wählt genau eine Untersuchung über ein Regex auf ``tlong``.

    Regex statt fester Codes, weil die Codes je Haus vergeben und in keiner
    öffentlichen Datei hinterlegt sind – sie sind erst zur Laufzeit bekannt.
    Mehrdeutigkeit ist ein Fehler und kein Anlass zu raten: „irgendeine passende“
    Untersuchung wäre über die Studiendauer nicht vergleichbar.

    Args:
        entries: Katalog aus ``parse_catalogue``.
        pattern: Regex (case-insensitiv) auf ``tlong``.
        modality: zusätzlich geforderte Modalität (case-insensitiv); ``""``
            schaltet den Filter ab.

    Returns:
        Der eindeutige Treffer.

    Raises:
        ValueError: 0 oder >1 Treffer; die Meldung listet die Kandidaten bzw. das
            ganze Angebot der Modalität, damit das Muster ohne zweiten Lauf
            korrigiert werden kann.
    """
    rx = re.compile(pattern, re.IGNORECASE)
    # Modalität case-insensitiv: die Mandanten schreiben sie unterschiedlich, und
    # ein Groß-/Kleinschreibungs-Unterschied darf keine leere Auswahl ergeben.
    mod = modality.casefold()
    offered = [e for e in entries if not mod or e.modality.casefold() == mod]
    hits = [e for e in offered if rx.search(e.tlong)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        candidates = "; ".join(f"{e.tshort}={e.tlong}" for e in offered) or "(none)"
        raise ValueError(
            f"pattern {pattern!r} matches no {modality or 'catalog'} entry;"
            f" offered: {candidates}"
        )
    matched = "; ".join(f"{e.tshort}={e.tlong}" for e in hits)
    raise ValueError(
        f"pattern {pattern!r} is ambiguous ({len(hits)} entries): {matched}"
    )


def parse_ticket(payload: bytes | str) -> Ticket:
    """Liest das Sitzungsticket aus einer ``GetPatientTicket``-Antwort.

    Args:
        payload: Roh-Antwort.

    Returns:
        ``Ticket``; bei Server-Fehler ist ``error`` gesetzt und ``value`` leer.

    Raises:
        ValueError: kein XML, SOAP-Fault, fehlendes Ergebniselement oder weder
            Ticket noch Fehlertext (kein verwertbarer Zustand).
    """
    root = _root(payload)
    el = _find_one(root, "GetPatientTicketResult")
    if el is None:
        raise ValueError("response has no GetPatientTicketResult")
    # Die Felder nach dem Fehlertext (hasName, isPatWeb) steuern nur die
    # Buchungsmaske des Clients.
    parts = (el.text or "").split("|")
    value = parts[0].strip()
    error = parts[1].strip() if len(parts) > 1 else ""
    if not value and not error:
        raise ValueError("GetPatientTicketResult is empty (no ticket, no error)")
    return Ticket(value=value, error=error)


def redact_ticket(payload: bytes) -> bytes:
    """Ersetzt das Sitzungsticket in einer Ticket-Antwort durch einen Platzhalter.

    Für das Archiv: die Antwort wird vor dem Parsen abgelegt, weil ihr Fehlerfeld
    die wichtigste Diagnosequelle ist – das Ticket selbst ist ein Zugangsmittel
    zum fremden Terminbuch und darf nicht auf der Platte landen. Arbeitet auf den
    Bytes und ohne XML-Parse, damit auch eine Antwort bereinigt wird, die der
    Parser gleich ablehnen wird. Der Platzhalter enthält keine spitzen Klammern,
    die Datei bleibt gültiges XML.

    Args:
        payload: Roh-Antwort.

    Returns:
        Die Antwort mit ersetztem ersten Pipe-Feld; unverändert, wenn es kein
        Ergebniselement gibt oder das Feld leer ist (Fehlerfall).
    """
    return _TICKET_FIELD.sub(rb"\1" + _TICKET_PLACEHOLDER, payload, count=1)


def parse_dates(payload: bytes | str) -> list[date]:
    """Liest die Terminvorschläge aus einer ``GetProposedDates``-Antwort.

    Args:
        payload: Roh-Antwort.

    Returns:
        Termindaten in Server-Reihenfolge (nicht zugesichert sortiert); leere
        Liste, wenn der Server keine Vorschläge hat.

    Raises:
        ValueError: kein XML, SOAP-Fault, fehlendes Ergebniselement,
            ``Errors/Description`` im Diffgram (z. B. abgelaufenes Ticket), ein
            Termin ohne ``start`` oder ein unlesbares Datum. Ein Server-Fehler
            darf nie als „kein Termin“ gezählt werden.
    """
    root = _root(payload)
    if _find_one(root, "GetProposedDatesResult") is None:
        raise ValueError("response has no GetProposedDatesResult")

    # Local-Name „Errors“ trifft nur den Datenblock; die Deklaration im
    # eingebetteten Schema heißt ``xs:element`` und bleibt unsichtbar.
    errors = _find_one(root, "Errors")
    if errors is not None:
        desc = _fields(errors).get("Description", "")
        raise ValueError(f"server reports: {desc or '(Errors without Description)'}")

    dates: list[date] = []
    for el in _find_all(root, "Dates"):
        raw = _fields(el).get("start", "")
        if not raw:
            raise ValueError(f"Dates entry without start field: {_fields(el)}")
        dates.append(_parse_start(raw))
    return dates


def _parse_start(raw: str) -> date:
    """Wandelt das ``start``-Feld eines Termins in ein Datum.

    Live kommt ein ISO-Zeitstempel mit Offset (``2026-11-01T16:20:00+01:00``).
    Bewusst ohne String-Schnitt geparst, damit ein geändertes Format als
    Ausnahme auffällt statt falsch geschnitten zu werden.
    """
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError as exc:
        raise ValueError(f"unreadable start {raw!r}: {exc}") from exc
