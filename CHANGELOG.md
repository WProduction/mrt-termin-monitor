# Changelog

Alle nennenswerten Änderungen an diesem Projekt stehen in dieser Datei.
Format: [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung: [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

## [1.0.0] – 2026-11-02

Erster Messlauf über alle Untersuchungen: 50 Abfragen bei 24 Instituten, 48 davon mit
Termin; die zwei Lücken stehen unter „Bekannte Lücken“.

### Added

- Zwei neue Untersuchungen: MRT der Lendenwirbelsäule (`lws`) bei 22 Instituten und
  MR-Angiographie der Nierengefäße (`mr_angio_nieren_km`) bei 4 Instituten (MR DZ Baden,
  Diagnostikum Linz, Diagnostikum Graz Süd-West, Radiologisches Zentrum Kapfenberg). Jede
  neue Zelle hat in einer Live-Probe einen Termin geliefert. Kein Portal bietet für diese
  Fälle eine Kontrastmittel-Wahl; gemessen wird der neutrale Eintrag. Bei Instituten ohne eigenen
  LWS-Eintrag zählt der Sammeleintrag „Wirbelsäule“.

### Changed

- Radiologie Waidhofen: Die Titelprüfung des Knie-Falls verlangt jetzt „MRT Knie rechts“.
- Benutzerhandbuch: Die Einrichtung fragt nach der Platzhalter-Nummer (zehnmal die
  Ziffer 1), die alle drei PatApp-Portale für die reine Terminabfrage akzeptieren, statt
  nach der eigenen Sozialversicherungsnummer.
- Die Kontaktadresse ist überall entfernt, weil das Projekt keinen Support bietet:
  Fehlermeldungen und das Benutzerhandbuch nennen als Empfänger der Log-Datei die Person,
  die das Programm betreut; der User-Agent nennt nur noch Version und Projekt-URL;
  `SECURITY.md` sagt, dass Meldungen nicht bearbeitet werden.
- Benutzerhandbuch: Ein Lauf dauert jetzt etwa zehn Minuten; Beispiel und Status-Tabelle
  zeigen die neuen Untersuchungen.

### Bekannte Lücken

- CT/MR Institut Südost (Feldbach): Das Zertifikat der Webseite ist abgelaufen; gemessen
  wird weiter nur das Knie (`nicht_erhoben`). LWS und Nieren-Angiographie kommen dazu,
  sobald das Portal wieder erreichbar ist.
- Ambulatorium Döbling: Das Buchungssystem antwortet mit einem Serverfehler
  (`fehler_parsen`); weitere Untersuchungen erst, wenn es wieder antwortet.
- MR-Angiographie der Nierengefäße bei DZ Meidling und Röntgen Wien Nord: Das Portal führt
  den Eintrag, zeigte in den bisherigen Probe-Läufen aber keinen freien Termin. Aufnahme,
  sobald eine Probe einen Termin liefert.

## [0.1.3] – 2026-11-02

### Fixed

- MR DZ Baden: Die Abfrage nutzte einen falschen Untersuchungscode und endete deshalb bei
  jedem Lauf auf der Weiterleitungsseite (`fehler_weiterleitung`). Mit Code und Titel des
  Portals liefert Baden wieder den nächsten Termin.
- MiraNext (Radiologie Doringer): Leistungen, die das Portal nicht online anbietet oder nur
  aus seinem Standardkatalog mitführt, hätten ein Datum mit Status `ok` bekommen. Sie
  werden jetzt übersprungen; die Knie-Messung ist davon nicht betroffen.

### Changed

- Benutzerhandbuch: derzeit zwei dauerhafte Lücken (Feldbach, Döbling) statt drei.
- `docs/robots-and-terms.md` hält die Befunde zu Doctena, Feldbach, der XR-WEB-Katalogroute
  und dem patapp-Platzhalter-Ticket fest.

## [0.1.2] – 2026-11-01

### Fixed

- Mit Python 3.15 (seit Oktober 2026 Standard auf python.org) brach die Installation mit
  „No matching distribution found for lxml“ ab. Das ZIP enthält jetzt Pakete für
  Python 3.14 und 3.15; PyYAML liegt ohne C-Beschleunigung bei, weil es dafür noch kein
  fertiges Paket für 3.15 gibt.
- `install.cmd` legt die Programmumgebung bei jeder Installation neu an. Nach einem
  Python-Wechsel blieben sonst Pakete der alten Version liegen; die Zugangsdaten bleiben.

### Changed

- `install.cmd` sucht gezielt Python 3.15, dann 3.14, und meldet jede andere Version
  verständlich, statt sie an pip scheitern zu lassen.
- Benutzerhandbuch und README: Voraussetzung ist Python 3.14 oder 3.15.

## [0.1.1] – 2026-11-01

### Fixed

- `install.cmd` erkennt das GitHub-Quellcode-Archiv („Source code“) am fehlenden Ordner
  `wheels` und sagt, welche Datei die richtige ist, statt mit einer pip-Meldung abzubrechen.
- XR-WEB: Wenn das Portal auf seine „keine Online-Vergabe“-Seite umleitet, erklärt das
  jetzt die Spalte `hinweis` der CSV, statt leer zu bleiben.

### Changed

- Benutzerhandbuch nennt die richtige Download-Datei und die neue Meldung.

## [0.1.0] – 2026-11-01

Erste Version für den Studienbetrieb.

### Added

- Lauf über 24 Institute (Portale XR-WEB, klinix, MiraNext, Doctena, iris, patapp):
  nächster online sichtbarer Termin für MRT Knie rechts, Kassen- bzw. kombinierter Pool.
- Je Lauf eine CSV (Schema v1, Codebook `docs/datenfelder.md`), Roh-Archiv jeder Antwort
  und eine Log-Datei; Logs rotieren auf 30, Roh-Archiv und CSV bleiben.
- Deutsche Konsolenmeldungen mit Ursache und Handlungsanweisung, Exit-Codes
  (`docs/exit-codes.md`), Tracebacks nur im Log, Zugangsdaten im Log geschwärzt.
- `setup` für die Zugangsdaten unter `%LOCALAPPDATA%`, `run --only` für Proben.
- Responsible Scraping: 10 s Mindestabstand je Host, gesperrte Hosts, Request-Budget.
- Release-ZIP mit `install.cmd`/`run.cmd`/`uninstall.cmd`, Offline-Wheels, optionalem
  Wochen-Task (Montag 09:00) und `docs/benutzerhandbuch.html`.
- Projektgerüst: Lizenz, Commit-Hooks, CI.

[Unreleased]: https://github.com/WProduction/mrt-termin-monitor/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/WProduction/mrt-termin-monitor/compare/v0.1.3...v1.0.0
[0.1.3]: https://github.com/WProduction/mrt-termin-monitor/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/WProduction/mrt-termin-monitor/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/WProduction/mrt-termin-monitor/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/WProduction/mrt-termin-monitor/releases/tag/v0.1.0
