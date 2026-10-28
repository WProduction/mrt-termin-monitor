# Datenfelder der Lauf-CSV (Schema v1)

Codebook für die Auswertung. Jeder Lauf schreibt eine Datei
`Dokumente\mrt-termin-monitor\data\<lauf_id>.csv`. Eine Zeile ist eine Messung:
**Institut × Untersuchung × Abrechnung × Lauf**.

## Format

- Trennzeichen Semikolon, Zeichensatz UTF-8 mit BOM, Zeilenende CRLF – Excel mit
  deutscher oder österreichischer Windows-Region öffnet die Datei per Doppelklick
  richtig.
- Erste Zeile ist der Kopf mit den Spaltennamen unten.
- Datum immer `JJJJ-MM-TT`, Uhrzeit `HH:MM`; nur Ganzzahlen, keine Dezimalzahlen.
- Leere Zelle = kein Wert (siehe Spalte „Leer wenn“).
- Zellen, die mit `=`, `+`, `-`, `@`, Tabulator oder Zeilenumbruch beginnen würden,
  beginnen mit einem Apostroph `'` – Schutz davor, dass Excel Fremdtext als Formel
  ausführt. Das Apostroph ist kein Teil des Inhalts.
- `schema_version` ändert sich mit jeder Änderung an Spalten oder Werten. Dateien
  mit unterschiedlicher Version vor dem Zusammenführen prüfen.

## Spalten

| Nr | Spalte | Typ / Einheit | Leer wenn | Quelle | Bedeutung |
|---|---|---|---|---|---|
| 1 | `schema_version` | Ganzzahl | nie | Konstante (`1`) | Version dieses Schemas. |
| 2 | `lauf_id` | Text `JJJJ-MM-TT_HHMM` | nie | Lauf-Start, lokale Zeit | Kennung des Laufs; benennt CSV- und Log-Datei. |
| 3 | `lauf_datum` | Datum `JJJJ-MM-TT` | nie | Lauf-Start, lokale Zeit | Tag des Laufs; Basis für `wartetage`. |
| 4 | `lauf_zeit` | Uhrzeit `HH:MM` | nie | Lauf-Start, lokale Zeit | Startzeit des Laufs. |
| 5 | `abfrage_zeitpunkt` | Text, ISO-8601 mit UTC-Offset (`2026-10-25T08:16:30+02:00`) | nie | Zeitpunkt der Abfrage | Exakter Zeitpunkt der einzelnen Abfrage; eindeutig auch bei Sommerzeit-Umstellung. Excel liest ihn als Text. |
| 6 | `institut_id` | Text (Kürzel, Kleinbuchstaben und `_`) | nie | `sites.yaml` | Stabiler Schlüssel des Instituts über alle Läufe; ändert sich nie, auch wenn sich der Name ändert. |
| 7 | `institut_name` | Text | nie | `sites.yaml` | Lesbarer Name des Instituts. |
| 8 | `untersuchung` | Wert aus Liste [Untersuchung](#untersuchung) | nie | `sites.yaml` | Gemessener Testfall. |
| 9 | `abrechnung` | Wert aus Liste [Abrechnung](#abrechnung) | nie | `sites.yaml` | Welcher Termin-Pool gemessen wurde. |
| 10 | `quelle` | Wert `online_abfrage` | nie | Konstante | Herkunft der Zeile. Telefonisch oder anders erhobene Werte stammen nicht aus diesem Tool. |
| 11 | `naechster_termin` | Datum `JJJJ-MM-TT` | `status` ist nicht `ok` | Online-Portal des Instituts | Frühester online sichtbarer Termin. |
| 12 | `wartetage` | Ganzzahl, Tage, ≥ 0 | `naechster_termin` leer | berechnet | `naechster_termin` − `lauf_datum` in Kalendertagen; 0 = Termin am Lauf-Tag. |
| 13 | `status` | Wert aus Liste [Status](#status) | nie | Abfrage | Ergebnis der Abfrage. |
| 14 | `hinweis` | Text, auch mehrzeilig | meistens leer | Abfrage | Zusatzinformation, z. B. Fehlergrund. Kann Text aus der Antwort des Portals enthalten. |

## Werte

### untersuchung

| Wert | Bedeutung |
|---|---|
| `knie_rechts` | MRT rechtes Knie, ÖGK, ohne Kontrastmittel. Ist rechts nicht wählbar, die seitenneutrale Knie-Untersuchung. |
| `lws` | MRT Lendenwirbelsäule, ÖGK, ohne Kontrastmittel. |
| `mr_angio_nieren_km` | MR-Angiographie der Nierengefäße, ÖGK, mit Kontrastmittel. |

### abrechnung

Gemessen werden nur Termine für ÖGK-Versicherte; reine Privat-Termine nie.

| Wert | Bedeutung |
|---|---|
| `kasse` | Das Institut führt einen eigenen Termin-Pool für Kassenpatienten; dieser wurde gemessen. |
| `kombiniert` | Das Institut vergibt Kassen- und Privattermine aus einem gemeinsamen Pool; der Kassen-Termin ist darin enthalten. |

### status

| Wert | Bedeutung | `naechster_termin` |
|---|---|---|
| `ok` | Termin gefunden. | gesetzt |
| `keine_termine` | Portal hat geantwortet, im abgefragten Zeitraum aber keinen Termin angeboten. | leer |
| `fehler_weiterleitung` | Portal hat auf eine Fehler- oder fremde Seite umgeleitet. Nicht als „keine Termine“ werten. | leer |
| `fehler_parsen` | Antwort kam, war aber nicht auswertbar (z. B. Portal geändert, Terminliste unvollständig). | leer |
| `nicht_erhoben` | Abfrage fand nicht statt oder bekam keine Antwort (z. B. Portal nicht erreichbar). | leer |
