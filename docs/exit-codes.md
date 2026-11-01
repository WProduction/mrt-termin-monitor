# Exit-Codes

Entwickler- und Support-Tabelle. Die Operatorin sieht nie die Zahl, sondern nur
den deutschen Konsolentext aus `src/mrt_termin_monitor/messages.py`. Bei den Codes
2–5 nennt die Konsole zusätzlich den absoluten Pfad der Log-Datei; der Traceback
steht nur im Log.

| Code | Name | Konsole beginnt mit | Bedeutung | Exception |
|---|---|---|---|---|
| 0 | `OK` | `OK:` | Alle Institute erfasst. | – |
| 1 | `PARTIAL` | `OK MIT LUECKEN (n):` | Lauf beendet, aber n Institute mit mindestens einer Fehlerzeile (`fehler_weiterleitung`, `fehler_parsen`, `nicht_erhoben`). Bewusst ≠ 0, damit Lücken im Scheduler-Verlauf auffallen. | – |
| 2 | `CONFIG_ERROR` | `FEHLER:` | Konfiguration fehlt oder ungültig: Credentials-Datei fehlt/kaputt/SVNR ungültig, unbekannter Slug bei `--only`. Auch argparse-Bedienfehler enden mit 2. | `ConfigError` |
| 3 | `NO_SITE_REACHABLE` | `FEHLER:` | Kein einziges Institut erreichbar (alle Zeilen `nicht_erhoben`, vermutlich kein Netz). Die CSV ist trotzdem geschrieben. | `NoSiteReachableError` |
| 4 | `OUTPUT_ERROR` | `FEHLER:` | CSV, Roh-Archiv oder Log nicht schreibbar; oder die CSV derselben Minute existiert schon (Doppelstart, erkannt vor dem ersten Request). | `OutputError`; `OSError` beim Anlegen des Logs |
| 5 | `UNEXPECTED` | `FEHLER:` | Unerwartete Exception (Programmfehler, Portaländerung). Auch Überschreiten des Request-Budgets (Schutz gegen Schleifen): bis dahin erhobene Zeilen stehen in der CSV, der Rest fehlt. | jede andere `Exception` |
| 10 | `ABORTED` | `ABGEBROCHEN:` | Abbruch durch die Bedienerin (Strg+C, Fenster geschlossen). | `KeyboardInterrupt` |
