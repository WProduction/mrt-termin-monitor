# Changelog

Alle nennenswerten Änderungen an diesem Projekt stehen in dieser Datei.
Format: [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung: [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

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

[Unreleased]: https://github.com/WProduction/mrt-termin-monitor/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/WProduction/mrt-termin-monitor/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/WProduction/mrt-termin-monitor/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/WProduction/mrt-termin-monitor/releases/tag/v0.1.0
