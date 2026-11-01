# SPDX-License-Identifier: Apache-2.0
"""PatApp-Adapter (HGS PatApp/PatWeb): drei SOAP-POSTs je Institut → Messzeilen.

Der Lesepfad besteht aus genau drei Aufrufen an denselben ASMX-Dienst::

    1. GetShortLongTitles          → Untersuchungskatalog (ohne Anmeldung)
    2. GetPatientTicket(sin, …)    → Sitzungsticket (Anmeldung mit der SVNR)
    3. GetProposedDates(ticket, …) → Terminvorschläge je Untersuchungscode

Der Katalog wird bei jedem Lauf neu geholt, weil die Untersuchungscodes hausintern
vergeben sind und in keiner öffentlichen Datei stehen; die Auswahl läuft über ein
Muster auf dem Klartext und ist bei 0 oder >1 Treffern eine Fehlerzeile mit
Kandidatenliste, nie eine stille Wahl.

Umgang mit den Secrets:

* Die Credentials (SVNR, Name, Mobilnummer) liest der Adapter selbst aus der
  Credentials-Datei – einmal je ``collect`` und vor dem ersten Request. So
  bleibt die Signatur wie bei jedem anderen Adapter, es gibt keinen globalen
  Zustand, und ohne Datei geht kein einziger Request raus.
* Die SVNR geht nur in den Rumpf von ``GetPatientTicket``, nie in eine URL.
  Die Log-Redaction kennt sie bereits (der Aufrufer lädt dieselbe Datei);
  Server-Texte, die in einen CSV-Hinweis gehen, schwärzt der Adapter zusätzlich
  selbst, denn die CSV läuft nicht durch den Log-Filter.
* Das Sitzungsticket entsteht erst zur Laufzeit, der Log-Filter kennt es nicht.
  Es wird deshalb nie geloggt (höchstens seine Länge). Nach dem Empfang nimmt
  der Adapter es in seine eigene Schwärzung auf – ein Server-Fehlertext (etwa
  „Ticket abgelaufen“) könnte es zitieren – und entfernt es vor dem Archivieren
  aus jeder Antwort, die es enthalten kann.

Nur lesende Operationen: buchende oder sperrende Aufrufe stehen nicht auf der
Whitelist des fetch-Layers und sind damit nicht sendbar. Die Roh-Antwort geht
immer vor dem Parse-Versuch an ``archive``. Fehler einer Abfrage brechen nie den
Lauf ab; Ausnahmen sind das Request-Budget und Archivfehler.
"""

import logging
import re
from collections.abc import Callable
from datetime import datetime
from functools import partial
from urllib.parse import quote

from mrt_termin_monitor import paths, setup
from mrt_termin_monitor.errors import ConfigError
from mrt_termin_monitor.fetch import http, post
from mrt_termin_monitor.model import Exam, Measurement, Status
from mrt_termin_monitor.parse import patapp as parse_patapp
from mrt_termin_monitor.redaction import RedactionFilter, variants
from mrt_termin_monitor.sites import Site

log = logging.getLogger(__name__)

# Die Studie misst nur MRT; andere Modalitäten (CT, MRP = MR privat) fallen bei
# der Auswahl durch. Bewusst Konstante statt Config-Feld.
_MODALITY = "MR"

# Laufzeit-Guard: der Code entsteht erst aus dem Katalog, der Loader kann einen
# Links-Treffer nicht ausschließen. Ein Klartext mit „links“, aber ohne „rechts“
# (also nicht „links/rechts“ = seitenneutral) wird nie abgefragt.
_LEFT = re.compile(r"\blinks\b", re.IGNORECASE)
_RIGHT = re.compile(r"\brechts\b", re.IGNORECASE)

# Empfänger der Roh-Antwort: (Dateiname, Bytes). Die Ablage selbst ist Sache des
# Aufrufers.
Archive = Callable[[str, bytes], None]

# Platzhalter für ein aus einer Archivdatei entferntes Ticket; ohne spitze
# Klammern, damit die Datei gültiges XML bleibt.
_TICKET_REMOVED = b"ticket-removed"


def _enc(value: str) -> str:
    """Kodiert einen Parameterwert wie der Portal-Client (``encodeURIComponent``).

    Der Dienst erwartet die Werte URL-kodiert *innerhalb* der XML-Elemente –
    ungewöhnlich, aber so sendet der ausgelieferte Client, und der Server
    dekodiert entsprechend. Nebeneffekt: ``<`` und ``&`` können den Envelope nicht
    zerlegen.
    """
    # encodeURIComponent lässt A-Za-z0-9 - _ . ! ~ * ' ( ) stehen; quote() lässt
    # -_.~ ohnehin stehen, der Rest kommt über safe dazu.
    return quote(value, safe="!*'()")


def _without_ticket(content: bytes, ticket: str) -> bytes:
    """Entfernt das Sitzungsticket aus einer Roh-Antwort vor dem Archivieren.

    Die Terminantwort enthält das Ticket im Normalfall nicht, ein Fehlertext des
    Servers kann es aber zitieren – und die Datei liegt unverschlüsselt auf der
    Platte. Byteweise und ohne XML-Parse, damit auch eine Antwort bereinigt
    wird, die der Parser gleich ablehnt; neben dem Rohwert auch die
    URL-kodierten Formen, weil der Dienst Parameter so entgegennimmt.
    """
    for form in sorted(variants(ticket), key=len, reverse=True):
        content = content.replace(form.encode(), _TICKET_REMOVED)
    return content


def task_count(site: Site) -> int:
    """Zahl der POSTs, die ``collect`` für dieses Institut höchstens ausführt.

    Katalog + Ticket + ein ``GetProposedDates`` je Untersuchung. Frühabbrüche
    (fehlende Credentials, abgelehnte Anmeldung, mehrdeutiges Muster) bleiben
    darunter, nie darüber. Es sind POSTs, keine GETs.
    """
    return 2 + len(site.exams)


def collect(
    site: Site, run_start: datetime, *, archive: Archive | None = None
) -> list[Measurement]:
    """Erhebt je Untersuchung des Instituts eine Messzeile.

    Args:
        site: validiertes Institut mit ``adapter: patapp``.
        run_start: Lauf-Start (lokal, naiv, minutengenau) für alle Zeilen.
        archive: erhält ``<slug>_catalog.xml``, ``<slug>_ticket.xml`` und je
            Untersuchung ``<slug>_<untersuchung>.xml`` mit den Roh-Bytes, bevor
            geparst wird – das Ticket ist überall entfernt; ``None`` = nicht
            archivieren.

    Returns:
        Messzeilen in der Reihenfolge von ``site.exams``. Scheitern Credentials,
        Katalog oder Anmeldung, bekommt jede Untersuchung dieselbe Fehlerzeile.

    Raises:
        http.BudgetExceededError: bricht den Lauf bewusst ab.
        Exception: was ``archive`` wirft, unverändert – ohne Archiv keine Evidenz.
    """
    url: str = site.params["service_url"]
    timeout = site.timeout_s if site.timeout_s is not None else http.DEFAULT_TIMEOUT

    def row_for(exam: Exam) -> partial[Measurement]:
        # Alles außer Status, Termin und Hinweis steht vor dem Request fest.
        return partial(
            Measurement,
            run_start=run_start,
            queried_at=datetime.now().astimezone(),
            site_id=site.slug,
            site_name=site.name,
            exam=exam,
            billing=site.billing,
        )

    def rows_all(status: Status, note: str) -> list[Measurement]:
        # Dieselbe Fehlerzeile für jede Untersuchung (Stufe vor der Schleife).
        return [row_for(exam)(status=status, note=note) for exam in site.exams]

    # --- Credentials, vor dem ersten Request -----------------------------------
    try:
        creds = setup.load_credentials(paths.credentials_file())
    except ConfigError as exc:
        # Der Fehlertext nennt nur den Pfad, nie Werte.
        return rows_all(Status.NOT_COLLECTED, f"credentials unavailable: {exc}")
    # Für Fremdtexte, die in die CSV gehen: der Log-Filter sieht die CSV nicht.
    # Eigene Instanz, weil später das Ticket dazukommt.
    redactor = RedactionFilter(creds.values())
    redact = redactor.redact

    # --- 1. Katalog (ohne Anmeldung) -------------------------------------------
    try:
        result = post.soap(url, "GetShortLongTitles", timeout=timeout)
    except post.BudgetExceededError:
        raise
    except post.FetchError as exc:
        return rows_all(Status.NOT_COLLECTED, redact(f"GetShortLongTitles: {exc}"))
    if archive is not None:
        archive(f"{site.slug}_catalog.xml", result.content)
    if result.status_code >= 400:
        return rows_all(
            Status.ERROR_PARSE, f"GetShortLongTitles: HTTP {result.status_code}"
        )
    try:
        catalogue = parse_patapp.parse_catalogue(result.content)
    except Exception as exc:  # noqa: BLE001
        # Bewusst breit: unbekannte Antwortform kann jede Exception auslösen.
        return rows_all(
            Status.ERROR_PARSE, redact(f"GetShortLongTitles: parser exception: {exc}")
        )
    log.debug("%s: catalogue with %d entries", site.slug, len(catalogue))

    # --- 2. Ticket (Anmeldung mit SVNR) ----------------------------------------
    params = (
        f"<sin>{_enc(creds[setup.SVNR])}</sin>"
        f"<name>{_enc(creds[setup.NAME])}</name>"
        f"<mobilenumber>{_enc(creds[setup.MOBILE])}</mobilenumber>"
    )
    try:
        result = post.soap(url, "GetPatientTicket", params, timeout=timeout)
    except post.BudgetExceededError:
        raise
    except post.FetchError as exc:
        return rows_all(Status.NOT_COLLECTED, redact(f"GetPatientTicket: {exc}"))
    if archive is not None:
        # Vor dem Parsen, aber ohne das Ticket: das Fehlerfeld ist die wichtigste
        # Diagnosequelle, das Ticket ein Zugangsmittel zum fremden Terminbuch.
        archive(f"{site.slug}_ticket.xml", parse_patapp.redact_ticket(result.content))
    if result.status_code >= 400:
        return rows_all(
            Status.ERROR_PARSE, f"GetPatientTicket: HTTP {result.status_code}"
        )
    try:
        ticket = parse_patapp.parse_ticket(result.content)
    except Exception as exc:  # noqa: BLE001
        return rows_all(
            Status.ERROR_PARSE, redact(f"GetPatientTicket: parser exception: {exc}")
        )
    if ticket.error:
        # Typisch: SVNR im Haus unbekannt. Betriebsbefund, kein Parserfehler –
        # aber sicher kein „kein Termin“. Der Server könnte die Eingabe zitieren.
        return rows_all(Status.NOT_COLLECTED, redact(f"login rejected: {ticket.error}"))
    # Nur die Länge – der Wert selbst darf nirgends hin.
    log.debug("%s: ticket received (%d chars)", site.slug, len(ticket.value))
    # Ab hier kennt die Schwärzung auch das Ticket: ein Server-Fehlertext könnte
    # es zitieren, und der ginge sonst ungefiltert in den CSV-Hinweis.
    redactor.add_secrets([ticket.value])

    # --- 3. Termine je Untersuchung --------------------------------------------
    rows: list[Measurement] = []
    for exam, values in site.exams.items():
        row = row_for(exam)

        try:
            entry = parse_patapp.select_exam(catalogue, values["pattern"], _MODALITY)
        except ValueError as exc:
            # Kandidatenliste im Hinweis: das Muster ist ohne zweiten Lauf
            # korrigierbar. Kein Request für eine geratene Untersuchung.
            rows.append(row(status=Status.ERROR_PARSE, note=redact(str(exc))))
            continue
        if _LEFT.search(entry.tlong) and not _RIGHT.search(entry.tlong):
            rows.append(
                row(
                    status=Status.ERROR_PARSE,
                    note=f"left-side exam selected: {entry.tshort}: {entry.tlong}",
                )
            )
            continue
        log.debug("%s %s: %s (%s)", site.slug, exam, entry.tshort, entry.tlong)

        # Leeres <from>: der Client startet die Liste ebenfalls ohne Datum und
        # bekommt sie ab „jetzt“ – genau der gesuchte nächste freie Termin.
        params = (
            f"<ticket>{_enc(ticket.value)}</ticket>"
            f"<tshort>{_enc(entry.tshort)}</tshort>"
            "<from></from>"
        )
        try:
            result = post.soap(url, "GetProposedDates", params, timeout=timeout)
        except post.BudgetExceededError:
            raise
        except post.FetchError as exc:
            rows.append(
                row(
                    status=Status.NOT_COLLECTED, note=redact(f"GetProposedDates: {exc}")
                )
            )
            continue

        if archive is not None:
            archive(
                f"{site.slug}_{exam}.xml", _without_ticket(result.content, ticket.value)
            )
        if result.status_code >= 400:
            rows.append(
                row(
                    status=Status.ERROR_PARSE,
                    note=f"GetProposedDates: HTTP {result.status_code}",
                )
            )
            continue

        try:
            dates = parse_patapp.parse_dates(result.content)
            # Code und Klartext in den Hinweis: der Code wird je Lauf gewählt, so
            # bleibt Katalog-Drift in der CSV sichtbar.
            note = f"{entry.tshort}: {entry.tlong}"
            if dates:
                # min() statt erstem Eintrag: die Server-Reihenfolge ist nirgends
                # zugesichert. Im try: Measurement lehnt ein Datum vor dem Lauf-Tag
                # ab – auch das ist eine unerwartete Antwort.
                rows.append(row(status=Status.OK, slot_date=min(dates), note=note))
            else:
                rows.append(row(status=Status.NO_SLOTS, note=note))
        except Exception as exc:  # noqa: BLE001
            # Fehlerzeile statt Laufabbruch; die Roh-Antwort liegt schon im Archiv.
            rows.append(
                row(status=Status.ERROR_PARSE, note=redact(f"parser exception: {exc}"))
            )
    return rows
