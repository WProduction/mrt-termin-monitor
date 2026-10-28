# Exit-Codes

Entwickler- und Support-Tabelle. Die Operatorin sieht nie die Zahl, sondern nur
den deutschen Konsolentext aus `src/mrt_termin_monitor/messages.py`. Bei den Codes
2–5 nennt die Konsole zusätzlich den absoluten Pfad der Log-Datei; der Traceback
steht nur im Log.

| Code | Name | Konsole beginnt mit | Bedeutung | Exception |
|---|---|---|---|---|
| 0 | `OK` | `OK:` | Alle Institute erfasst. | – |
| 1 | `PARTIAL` | `OK MIT LUECKEN (n):` | Lauf beendet, aber n Institute ohne Ergebnis. Bewusst ≠ 0, damit Lücken im Scheduler-Verlauf auffallen. | – |
| 2 | `CONFIG_ERROR` | `FEHLER:` | Konfiguration fehlt oder ungültig: Credentials-Datei fehlt/kaputt/SVNR ungültig, unbekannter Slug bei `--only`. Auch argparse-Bedienfehler enden mit 2. | `ConfigError` |
| 3 | `NO_SITE_REACHABLE` | `FEHLER:` | Kein einziges Institut erreichbar (vermutlich kein Netz). | `NoSiteReachableError` |
| 4 | `OUTPUT_ERROR` | `FEHLER:` | CSV oder Log nicht schreibbar. | `OutputError`; `OSError` beim Anlegen des Logs |
| 5 | `UNEXPECTED` | `FEHLER:` | Unerwartete Exception (Programmfehler, Portaländerung). | jede andere `Exception` |
| 10 | `ABORTED` | `ABGEBROCHEN:` | Abbruch durch die Bedienerin (Strg+C, Fenster geschlossen). | `KeyboardInterrupt` |
