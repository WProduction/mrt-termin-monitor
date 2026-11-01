# SPDX-License-Identifier: Apache-2.0
"""Tests des PatApp-Parsers gegen handgebaute Struktur-Skelette (kein Netz).

Jede Regel schützt vor einem stillen Fehler in den Studiendaten: geratene
Untersuchung bei mehrdeutigem Muster, Server-Fehler als „keine Termine“,
Ticket im Archiv.
"""

from datetime import date
from pathlib import Path

import pytest

from mrt_termin_monitor.parse import patapp as parse

DATA = Path(__file__).parent / "data" / "patapp"


def _skeleton(name: str) -> bytes:
    # Bytes wie im Betrieb: der Parser bekommt die archivierten Roh-Bytes.
    return (DATA / name).read_bytes()


# --- Katalog -------------------------------------------------------------------


def test_catalogue_lists_every_entry_in_order() -> None:
    entries = parse.parse_catalogue(_skeleton("katalog.xml"))
    assert [e.tshort for e in entries] == ["xknr", "xknl", "xckn", "pxkn"]
    assert entries[0] == parse.CatalogEntry("xknr", "MR Knie rechts", "MR", "Gelenke")
    assert entries[3].modality == "MRP"


def test_catalogue_ignores_namespace_prefix() -> None:
    # Der Server mischt soap/soap12 je Operation; der Local-Name zählt.
    payload = (
        _skeleton("katalog.xml")
        .replace(b"soap:", b"env:")
        .replace(b"xmlns:soap=", b"xmlns:env=")
    )
    assert len(parse.parse_catalogue(payload)) == 4


def test_empty_catalogue_is_error() -> None:
    payload = _skeleton("katalog.xml").replace(b"ShortLongTitles", b"Ignored")
    with pytest.raises(ValueError, match="no ShortLongTitles"):
        parse.parse_catalogue(payload)


def test_soap_fault_is_error_with_text() -> None:
    with pytest.raises(ValueError, match="SOAP fault: placeholder fault text"):
        parse.parse_catalogue(_skeleton("fault.xml"))


def test_non_xml_is_error() -> None:
    with pytest.raises(ValueError, match="not well-formed"):
        parse.parse_catalogue(b"<html><body>maintenance</body></html")


# --- Auswahl ------------------------------------------------------------------


@pytest.fixture
def catalogue() -> list[parse.CatalogEntry]:
    return parse.parse_catalogue(_skeleton("katalog.xml"))


def test_select_unique_match(catalogue) -> None:
    assert parse.select_exam(catalogue, "Knie rechts").tshort == "xknr"


def test_select_filters_modality_and_casefolds(catalogue) -> None:
    # „Knie“ trifft MR rechts/links, CT und MRP; nur MR zählt – mit „mr“ genauso.
    with pytest.raises(ValueError) as exc:
        parse.select_exam(catalogue, "Knie", "mr")
    message = str(exc.value)
    assert "xknr" in message and "xknl" in message
    assert "xckn" not in message and "pxkn" not in message


def test_select_ambiguous_names_both_candidates(catalogue) -> None:
    with pytest.raises(ValueError, match="ambiguous") as exc:
        parse.select_exam(catalogue, "Knie")
    assert "xknr=MR Knie rechts" in str(exc.value)
    assert "xknl=MR Knie links" in str(exc.value)


def test_select_no_match_lists_offer_of_modality(catalogue) -> None:
    with pytest.raises(ValueError, match="matches no MR entry") as exc:
        parse.select_exam(catalogue, "Schulter")
    # Nur das MR-Angebot, damit das Muster ohne zweiten Lauf korrigierbar ist.
    assert "xknr=MR Knie rechts; xknl=MR Knie links" in str(exc.value)
    assert "xckn" not in str(exc.value)


def test_select_without_modality_filter_sees_all(catalogue) -> None:
    assert parse.select_exam(catalogue, "^CT", "").tshort == "xckn"


# --- Ticket -------------------------------------------------------------------


def test_ticket_ok() -> None:
    ticket = parse.parse_ticket(_skeleton("ticket.xml"))
    assert ticket == parse.Ticket("TICKET-PLACEHOLDER", "")


def test_ticket_error_is_passed_through() -> None:
    ticket = parse.parse_ticket(_skeleton("ticket_abgelehnt.xml"))
    assert ticket == parse.Ticket("", "placeholder login error")


def test_ticket_empty_is_error() -> None:
    payload = _skeleton("ticket.xml").replace(b"TICKET-PLACEHOLDER||1|0", b"")
    with pytest.raises(ValueError, match="empty"):
        parse.parse_ticket(payload)


def test_ticket_without_result_element_is_error() -> None:
    payload = _skeleton("ticket.xml").replace(b"GetPatientTicketResult", b"Other")
    with pytest.raises(ValueError, match="no GetPatientTicketResult"):
        parse.parse_ticket(payload)


# --- Ticket-Schwärzung --------------------------------------------------------


def test_redact_ticket_removes_value_keeps_rest() -> None:
    redacted = parse.redact_ticket(_skeleton("ticket.xml"))
    assert b"TICKET-PLACEHOLDER" not in redacted
    assert b"<GetPatientTicketResult>ticket-removed||1|0</GetPatientTicketResult>" in (
        redacted
    )
    # Die geschwärzte Datei bleibt lesbares XML.
    assert parse.parse_ticket(redacted).value == "ticket-removed"


def test_redact_ticket_handles_prefixed_element() -> None:
    payload = (
        _skeleton("ticket.xml")
        .replace(
            b"<GetPatientTicketResult>", b'<ns1:GetPatientTicketResult xmlns:ns1="x">'
        )
        .replace(b"</GetPatientTicketResult>", b"</ns1:GetPatientTicketResult>")
    )
    assert b"TICKET-PLACEHOLDER" not in parse.redact_ticket(payload)


def test_redact_ticket_is_noop_without_ticket() -> None:
    rejected = _skeleton("ticket_abgelehnt.xml")
    assert parse.redact_ticket(rejected) == rejected
    assert (
        parse.redact_ticket(b"<html>maintenance</html>") == b"<html>maintenance</html>"
    )


# --- Termine ------------------------------------------------------------------


def test_dates_minimum_over_unsorted_list_with_offset() -> None:
    dates = parse.parse_dates(_skeleton("termine.xml"))
    assert dates == [date(2099, 3, 11), date(2099, 3, 2), date(2099, 3, 20)]
    assert min(dates) == date(2099, 3, 2)


def test_dates_accept_timestamp_without_offset() -> None:
    payload = _skeleton("termine.xml").replace(b"+01:00", b"")
    assert min(parse.parse_dates(payload)) == date(2099, 3, 2)


def test_empty_diffgram_is_empty_list() -> None:
    # Kein Vorschlag = leere Liste; der Adapter macht daraus NO_SLOTS.
    assert parse.parse_dates(_skeleton("termine_leer.xml")) == []


def test_errors_block_is_error_never_empty_list() -> None:
    with pytest.raises(ValueError, match="server reports: placeholder server error"):
        parse.parse_dates(_skeleton("termine_fehler.xml"))


def test_missing_result_element_is_error() -> None:
    payload = _skeleton("termine_leer.xml").replace(b"GetProposedDatesResult", b"X")
    with pytest.raises(ValueError, match="no GetProposedDatesResult"):
        parse.parse_dates(payload)


def test_date_without_start_is_error() -> None:
    payload = _skeleton("termine.xml").replace(
        b"<start>2099-03-02T07:45:00+01:00</start>", b""
    )
    with pytest.raises(ValueError, match="without start"):
        parse.parse_dates(payload)


def test_foreign_date_format_is_error() -> None:
    payload = _skeleton("termine.xml").replace(
        b"2099-03-02T07:45:00+01:00", b"02.03.2099 07:45"
    )
    with pytest.raises(ValueError, match="unreadable start"):
        parse.parse_dates(payload)


def test_accepts_str() -> None:
    text = _skeleton("termine.xml").decode("utf-8")
    assert min(parse.parse_dates(text)) == date(2099, 3, 2)
