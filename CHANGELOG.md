# Changelog

Alle nennenswerten Änderungen an diesem Projekt stehen in dieser Datei.
Format: [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung: [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

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

[Unreleased]: https://github.com/WProduction/mrt-termin-monitor/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/WProduction/mrt-termin-monitor/releases/tag/v0.1.0
