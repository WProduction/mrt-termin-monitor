# AGENTS.md

Arbeitsregeln für Coding-Agenten und Menschen in diesem Repository.

## Projekt

Python ≥ 3.14, src-Layout `src/mrt_termin_monitor/`, Build-Backend hatchling,
Abhängigkeiten über uv mit committetem `uv.lock`. `requirements.txt` wird aus dem
Lock generiert und nie von Hand editiert – die Bediener-Laptops installieren mit
pip, nicht mit uv. Lock einfrieren: keine Tool-Upgrades während der Studie.

## Einrichtung nach dem Klonen

```
uv sync --locked
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
git config commit.template .gitmessage.txt
```

## Verifikation (identisch zur CI)

```
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Lock-Drift-Check (ebenfalls in der CI):

```
uv export --no-dev --format requirements-txt -o requirements.txt && git diff --exit-code requirements.txt
```

Nach jeder Abhängigkeitsänderung (`uv add`, `uv lock`) den Export neu erzeugen und
im selben Commit mitcommitten.

## Code

- Jede `.py`-Datei beginnt mit `# SPDX-License-Identifier: Apache-2.0`.
- Kommentare und Docstrings auf Deutsch; sie erklären das Warum.
- ruff mit Defaults; pytest mit `--import-mode=importlib`, kein `__init__.py` in
  `tests/`, Testdaten byte-exakt unter `tests/data/`.
- Testdaten für Adapter und Parser sind handgebaute Struktur-Skelette mit
  Platzhaltern, nie Mitschnitte oder bereinigte Kopien echter Portal-Antworten
  (Begründung: `tests/data/README.md`). Der Hook `no-portal-captures` lehnt
  Portal-Hostnamen unter `tests/data/` ab; schlägt er an, wird der Inhalt ersetzt,
  nicht das Muster gelockert.

## CSV-Schema (einzige öffentliche Schnittstelle)

Schema = `FIELDS` und die CSV-Werte der Mappings in
`src/mrt_termin_monitor/csv_output.py`. **Änderung an `FIELDS` → `feat!` +
`schema_version` + Codebook** – im selben Commit:

- Commit-Typ `feat!` mit `BREAKING CHANGE:`-Footer (Major-Version).
- `SCHEMA_VERSION` um 1 erhöhen.
- `docs/datenfelder.md` nachziehen (Spalte bzw. Wert mit Bedeutung).
- `tests/data/golden_run.csv` erst danach neu erzeugen – der Golden-Test schlägt
  bei jeder Schema-Änderung absichtlich fehl.

Dasselbe gilt für einen neuen, geänderten oder entfernten CSV-Wert (z. B. eine
neue Untersuchung).

## Commits

- Conventional Commits 1.0, Englisch, Betreff max. 50 Zeichen, Body-Zeilen max. 72.
- Erlaubte Typen: `feat fix docs test refactor chore build`.
- Scopes optional, frei wählbar, klein geschrieben.
- `!` bzw. `BREAKING CHANGE` ausschließlich für Änderungen am CSV-Schema (die
  einzige öffentliche Schnittstelle).
- Eine logische Änderung je Commit.
- Trunk-based auf `main`, keine Feature-Branches. Tags `vX.Y.Z` annotiert, von
  Hand, mit CHANGELOG-Eintrag und nur nach grünem CI-Run.
- Hooks nie umgehen (`--no-verify`, `-n`), kein Force-Push.

Durchsetzung: commitizen (`cz check`) als commit-msg-Hook über pre-commit; Typen
und Längen stehen in `pyproject.toml` unter `[tool.commitizen]`.

### Regex-Fallback (dokumentiert, nicht aktiv)

Nur falls commitizen ausfällt: als `.githooks/commit-msg` anlegen und
`git config core.hooksPath .githooks` setzen.

```sh
#!/bin/sh
# Fallback-Prüfung der Commit-Message: Typ, Betreff <= 50, Zeilen <= 72.
msg=$(grep -v '^#' "$1")
head=$(printf '%s\n' "$msg" | head -n 1)
types='feat|fix|docs|test|refactor|chore|build'
printf '%s\n' "$head" | grep -Eq "^($types)(\([a-z0-9-]+\))?!?: .+" ||
  { echo "commit-msg: kein Conventional Commit: $head" >&2; exit 1; }
[ "${#head}" -le 50 ] || { echo "commit-msg: Betreff > 50 Zeichen" >&2; exit 1; }
printf '%s\n' "$msg" | awk 'length > 72 { bad = 1 } END { exit bad }' ||
  { echo "commit-msg: Zeile > 72 Zeichen" >&2; exit 1; }
```

## Veröffentlichungsgrenze

Dieses Repository ist öffentlich.

- **Public referenziert nie intern:** keine Pfade, Namen oder Inhalte aus dem
  Sibling-Ordner neben diesem Repo, keine Arbeitsdateien mit tmp-Suffix, keine
  lokalen Claude-Dateien, keine Recherche- oder Planungsdokumente. Der Hook
  `no-internal-refs` erzwingt das; seine Muster stehen nur in `.gitignore` und
  `.pre-commit-config.yaml`.
- Nie Credentials, nie Portal-Mitschnitte stagen.
- SVNR-förmige Testwerte zur Laufzeit zusammensetzen (`"1234" + "010180"`), nie als
  10-Ziffern-Literal – der Hook `no-svnr` hat keine Ausnahme für `tests/`.

## Session-Ende

Jede Agenten-Session endet mit `git log --oneline` im Session-Protokoll. Der Linter
prüft nur die Form; der Mensch liest die History.
