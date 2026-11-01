# robots.txt und Nutzungsbedingungen je Institut

Einmaliges Review vor der Studie: Für jedes abgefragte Institut wurden
`robots.txt` und Nutzungsbedingungen geprüft, sowohl auf dem Host, den das Tool
anfragt, als auch auf der Website des Instituts. Wo keine Nutzungsbedingungen
existieren, wurden Impressum und
Datenschutzerklärung auf Klauseln zu automatisierten Abfragen, zu Scraping oder
zur privaten bzw. nicht-kommerziellen Nutzung durchgesehen.

Was das Tool daraus macht, steht im README unter „Responsible use“: Es sendet nur
lesende Requests mit mindestens 10 Sekunden Abstand je Host und einem
User-Agent mit Kontaktadresse. Hosts mit Sperre fragt es nie an, und
Schutzmaßnahmen umgeht es nicht.

„404“ heißt: Der Host liefert keine `robots.txt`. Damit gibt es dort keine
Crawl-Regel; nach RFC 9309 darf ein Client dann zugreifen.

## Befunde

| Institut | abgefragter Host | `robots.txt` | Nutzungsbedingungen / Impressum | geprüft |
|---|---|---|---|---|
| MR-CT Wien-West / Radiologicum Penzing | `www.radiologicum.radiologie.at` | 404; Institutsseite ohne gültige Datei | keine AGB auf dem Buchungshost; Impressum nur Haftungsausschluss für externe Links | 2026-07-27 |
| DZ Stadlau | `www.dzstadlau.radiologie.at` | 404; die Terminseite des Instituts sperrt nur technische Pfade und KI-Crawler (GPTBot u. a.), nicht die Buchung | keine Klausel zu automatisierten Abfragen; Impressum nur berufsrechtliche Angaben | 2026-07-27 |
| DZ Simmering | `www.dh11.radiologie.at` | 404; Gruppenseite `Allow: /` | keine Klausel gefunden | 2026-07-27 |
| Ambulatorium Döbling | `api.doctena.at` | API-Host ohne lesbare Datei (2026-07-27 keine, 2026-11-01 HTTP 522); `www.doctena.at/robots.txt` sperrt u. a. `/login`, `/account/`, `/booking-form/`, `/search`, die frühere Sperre `*slots*` ist entfallen (siehe Anmerkung) | Patienten-AGB (Stand 14.02.2024) klauselweise geprüft: kein Verbot automatisierter Abfragen, nur ein Missbrauchsverbot (betrügerische Buchungen, Falschinformationen) | 2026-11-01 |
| DZ Urania | `webportal.urania.imaging.at` | 404; `imaging.at` sperrt nur technische Pfade, die Buchungsseite trägt `meta robots="all"` | keine Nutzungsbedingungen; Impressum und Datenschutz ohne Klausel | 2026-07-27 |
| imagin Floridsdorf | `webportal.floridsdorf.imaging.at` | 404; `imaging.at` wie oben | wie DZ Urania | 2026-07-27 |
| Diagnosehaus 3 | `www.dh3.radiologie.at` | 404; Gruppenseite `Allow: /` | keine Klausel gefunden | 2026-07-27 |
| Röntgen Wien Nord | `termin.roentgen-wien-nord.at` | 404; Institutsseite sperrt nur `/wp-admin/` | AGB im Buchungsportal regeln den Behandlungsvertrag, keine Klausel zu automatisierten Abfragen; Impressum allgemeiner Urheberrechtsvorbehalt | 2026-09-18 |
| Hansson Diagnostik | `www.hansson-diagnostik.radiologie.at` | 404; Institutsseite sperrt nur `/wp-admin/` | keine Nutzungsbedingungen; Datenschutz ohne Klausel | 2026-09-18 |
| DZ Meidling | `portal-dzm.diagnostikum.at` | sperrt nur `/api/account*`, `/api/logs/`, `/api/users/`, `/management/`, `/v3/api-docs/`; die Terminabfrage unter `/api/public/` ist erlaubt; `diagnostikum.at` `Allow: /`, sperrt `/api/`, `/admin/`, `/_next/`, `/private/` | keine AGB; Impressum und Datenschutz ohne Klausel | 2026-11-01 |
| Radiologie Waidhofen/Ybbs | `www.waidhofen.radiologie.at` | 404; Institutsseite erlaubt alles | Impressum mit Haftungs- und Urheberrechtshinweis, keine Klausel zu automatisierten Abfragen | 2026-07-27 |
| MR DZ Baden | `webportal.dzbaden.at` | 404; Institutsseite erlaubt alles | Portal ohne eigene Bedingungen; Impressum und Datenschutz ohne Klausel | 2026-09-18 |
| Dr. Rainer Diagnostik, Zwettl | `www.rainer.radiologie.at` | 404 (erneut 2026-11-01); Institutsseite `www.diagnose-zentrum-rainer.at` liefert eine leere Datei (keine Regel) | Impressum: Vervielfältigung der Inhalte nur mit Zustimmung; keine Klausel zu automatisierten Abfragen | 2026-11-01 |
| Dr. Rachinger, Linz | `onlinekalender.institut-rachinger.at` | 404; Institutsseite sperrt nur `/wp-admin/` | keine AGB für das Portal (der verlinkte AGB-Pfad ist ein ungenutzter Vorlagen-Rest, 404); Datenschutzerklärung ohne Klausel | 2026-09-18 |
| MR-CT DZ Horn | `termin.diagnose.team` | 404; Institutsseite sperrt nur `/wp-admin/` | keine Nutzungsbedingungen; Datenschutz ohne Klausel | 2026-09-18 |
| Diagnostikum Linz | `portal-dl.diagnostikum.at` | wie DZ Meidling (Portal mit identischer Datei, und `diagnostikum.at`) | keine Nutzungsbedingungen; Impressum nur Firmendaten | 2026-11-01 |
| Diagnostikum Graz Süd-West | `portal-dg.diagnostikum.at` | wie DZ Meidling (Portal mit identischer Datei, und `diagnostikum.at`) | wie Diagnostikum Linz | 2026-11-01 |
| Radiologisches Zentrum Kapfenberg | `exchange.radiolog.at` | 404; Institutsseite sperrt nur den Admin-Pfad | keine Nutzungsbedingungen; Impressum mit strengem Urheberrechtsvorbehalt (siehe Anmerkung) | 2026-09-18 |
| CT/MR Institut Südost, Feldbach | `www.suedost.radiologie.at` | 404; Institutsseite mit leerem `Disallow:` (erlaubt alles) | keine AGB auf dem Buchungshost; Datenschutz ohne Klausel | 2026-09-18 |
| MR-CT Diagnose Institut Klagenfurt | `www.mr-ct-klagenfurt.radiologie.at` | 404; Institutsseite sperrt nur `/wp-admin/` | Impressum nur Firmendaten, keine Klausel | 2026-07-27 |
| Radiologie Doringer, Salzburg | `patient-portal.miranext.ai` | keine Datei (die App liefert ihre Startseite); Institutsseite `www.doringer.at` `Allow: /` (Content-Signal `ai-train=no`) | Portal ohne Nutzungsbedingungen; Impressum (nach ECG/UGB/MedienG) und Instituts-AGB (Behandlungsvertrag) ohne Klausel zu automatisierten Abfragen | 2026-11-01 |
| MR Institut Bregenz | `xrweb.mr-vorarlberg.at` | 404; Institutsseiten sperren nur `/wp-admin/` | keine Nutzungsbedingungen; Datenschutz ohne Klausel | 2026-09-18 |
| MR Institut Feldkirch | `www.feldkirch.radiologie.at` | 404; Institutsseite `Allow: /` | Buchungsseiten verlinken keine Bedingungen | 2026-09-18 |
| Kompetenzzentrum DOK Schwaz | `smart.mein-dok.at` | 404 | Buchungsseite und ausgelieferte Skripte ohne Nutzungsbedingungen; `www.mein-dok.at/impressum/` und `/datenschutz/` ohne Klausel zu automatisierten Abfragen | 2026-10-28 |

## Anmerkungen

- **Ambulatorium Döbling (Doctena):** Der API-Host hat keine lesbare
  `robots.txt`. Bis 2026-07-27 sperrte `www.doctena.at` die Muster `*slots*` und
  `*/patient*`; der Pfad `/agendaSlot` fiel schon damals nicht wörtlich darunter,
  und 2026-11-01 sind beide Sperren entfallen. Die frühere Sperre zeigte aber,
  dass Doctena das Crawlen von Verfügbarkeiten erschweren wollte. Das Tool
  sendet je Lauf nur einen
  Request an diesen Host. Wird der Zugriff abgelehnt, gibt es keinen
  Ausweichweg: Das Institut wird dann nicht gemessen.
- **Radiologisches Zentrum Kapfenberg:** Das Impressum untersagt, Texte, Fotos
  und Grafiken der Website zu vervielfältigen oder in Datenbanken zu speichern.
  Das Tool speichert davon nichts, sondern nur das Datum des nächsten freien
  Termins.
- **Radiologie Doringer (MiraNext):** Die API verlangt einen `Referer` der
  Portalseite. Das ist keine Zugangskontrolle, drückt aber die Erwartung aus,
  dass die Seite des Betreibers die API aufruft. Das Tool sendet den Header so,
  wie es der Browser tut, und bleibt bei wenigen Requests je Lauf.
- **Diagnostikum-Gruppe:** Die `robots.txt` von `diagnostikum.at` wirkt wie eine
  unveränderte Framework-Vorlage, denn die Sitemap-Zeile zeigt auf einen
  Platzhalter-Host. Ihr `Allow: /` ist daher keine bewusste Erlaubnis.

## Gesperrte Hosts

`BLOCKED_HOSTS` in `src/mrt_termin_monitor/fetch/http.py` sperrt diese Hosts
samt Subdomains, unabhängig von jeder Konfiguration:

| Host | Befund | geprüft |
|---|---|---|
| `ctmr.expert` | `robots.txt`: `User-agent: *` / `Disallow: /`. Das Institut schließt automatisierte Abrufe seiner Website ausdrücklich aus. | 2026-07-27 |
| `azs.at` | Buchungsportal desselben Instituts (`termin.azs.at`, ohne eigene `robots.txt`) | 2026-09-18 |
| `vera.care` | Plattform mit einer Instanz desselben Instituts | 2026-09-18 |

Die Portale `azs.at` und `vera.care` haben selbst keine Sperre. Formal reicht das
`Disallow` von `ctmr.expert` nach RFC 9309 nicht auf andere Hosts. Das Tool
behandelt den erklärten Wunsch des Instituts trotzdem als Absage für alle seine
Hosts.
