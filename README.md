# mrt-termin-monitor

![No Maintenance Intended](docs/no-maintenance-intended.svg)

Erhebt für eine Studie zur Terminverfügbarkeit den nächsten online sichtbaren
MRT-Termin österreichischer Radiologie-Institute. Jeder Programmstart ist ein
Messlauf und schreibt eine CSV-Datei.

**Für wen:** die Person, die die Messläufe der Studie auf einem Windows-Laptop
startet. Einzweck-Werkzeug: kein Support, keine Weiterentwicklung über die
Studie hinaus.

## Starten

Noch kein Release. Ab Version 0.1.0: ZIP aus den GitHub-Releases entpacken,
`install.cmd` doppelklicken und danach über die Desktop-Verknüpfung starten.
Die Bedienanleitung liegt dem ZIP bei.

## Responsible use

Das Tool liest öffentlich sichtbare Buchungskalender, so wie ein Patient sie im
Browser sieht. Die folgenden Regeln stehen im Code (`src/mrt_termin_monitor/fetch/`)
und werden nicht per Config gelockert:

- **Abrufrate:** ein Lauf fragt die Institute nacheinander ab, nie parallel. Zwischen
  zwei Requests an denselben Host liegen mindestens 10 Sekunden
  (`REQUEST_DELAY_SECONDS`, gilt auch für Redirects und Wiederholungen). Je URL gibt
  es höchstens zwei Versuche; ein Request-Budget je Lauf bricht bei Schleifen-Fehlern
  ab. Ein Lauf erzeugt je Institut und Untersuchung nur wenige Requests.
- **Nur lesen:** Abrufe sind GET. Die einzige Ausnahme sind die lesenden Aufrufe
  zweier Portal-Produkte, die nur per POST antworten: drei SOAP-Leseoperationen der
  HGS-PatApp (Katalog, Anmeldung, Terminvorschläge) und die anonyme Session des
  IRIS-Portals. Diese Operationen stehen auf einer festen Whitelist; buchende,
  sperrende oder stornierende Operationen sind im Code nicht aufrufbar. Es wird nie
  ein Termin gebucht oder reserviert.
- **Erkennbar:** jeder Request trägt den User-Agent
  `mrt-termin-monitor/<version> (+<repo-url>; …; contact: <mail>)` mit Kontaktadresse.
- **Sperren respektiert:** Untersagt ein Institut in seiner `robots.txt`
  automatisierte Abrufe, stehen alle seine Hosts in `BLOCKED_HOSTS` und werden nie
  angefragt. Es gibt keine Umgehung von
  Captchas, Rate-Limits oder sonstigen Schutzmaßnahmen. Das einmalige Review von
  `robots.txt` und Nutzungsbedingungen je Institut steht in
  [docs/robots-and-terms.md](docs/robots-and-terms.md).
- **Datenminimierung:** erhoben wird je Institut und Untersuchung nur der nächste
  freie Termin. Die Sozialversicherungsnummer, die ein Portal-Produkt für die
  Anmeldung verlangt, liegt nur lokal beim Benutzer und erscheint in keiner Log-Datei.
  Portal-Antworten werden nur lokal archiviert und nie veröffentlicht.
- **Einzweck-Werkzeug:** gebaut für eine Studie, ohne Wartung danach. Für andere Zwecke
  bitte nicht ohne Rücksprache mit den Instituten einsetzen.

## Entwicklung

Arbeitsregeln, Einrichtung und Prüfbefehle: [AGENTS.md](AGENTS.md).

## Lizenz

[Apache-2.0](LICENSE), © 2026 Markus Radike.

This tool was written with an AI coding agent under human review.
