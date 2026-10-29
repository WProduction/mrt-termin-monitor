# Testdaten

Hier liegen nur Dateien, die für dieses Repo gebaut wurden:

- `golden_run.csv`: Soll-Bytes des CSV-Writers.
- `<adapter>/*.html|json`: handgebaute **Struktur-Skelette** der Portal-Antworten.
  Sie enthalten nur die Elemente, die der Parser liest, und Platzhalter-Texte,
  dazu Hosts wie `example.at`.

**Keine Mitschnitte echter Portal-Antworten**, auch keine bereinigten Kopien.
Die Seiten sind Fremdinhalt der Institute und ihrer Software-Anbieter. Eine
Kopie für die eigene Arbeit aufzubewahren ist zulässig, sie zu veröffentlichen
nicht (§ 42h UrhG). Ein öffentliches Repo veröffentlicht alles, was hier liegt.
Eine Bereinigung müsste außerdem jede Version jedes Portals zuverlässig
erfassen; ein Skelett braucht das nicht.

Der pre-commit-Hook `no-portal-captures` lehnt jede Datei unter `tests/data/`
ab, die einen Portal-Hostnamen enthält. Schlägt er an, gehört der Inhalt durch
Platzhalter ersetzt. Das Muster wird nicht gelockert.
