# SPDX-License-Identifier: Apache-2.0
"""Benutzerhandbuch gegen den Code: Texte, Pfade und Institute dürfen nicht driften.

Die Operatorin vergleicht die Meldung im Fenster mit dem Handbuch; ein Satz, der
nur fast gleich ist, wird dort nicht gefunden.
"""

import re
import tomllib
from html.parser import HTMLParser
from pathlib import Path

from mrt_termin_monitor import csv_output, messages, sites

ROOT = Path(__file__).resolve().parent.parent
HANDBUCH = ROOT / "docs" / "benutzerhandbuch.html"


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.headings: list[str] = []
        self._in_h2 = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        # Nur einschalten: ein Inline-Tag in der Überschrift darf sie nicht abschneiden.
        if tag == "h2":
            self._in_h2 = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2":
            self._in_h2 = False

    def handle_data(self, data: str) -> None:
        self.parts.append(data)
        if self._in_h2:
            self.headings.append(data)


def _parsed() -> _Text:
    parser = _Text()
    parser.feed(HANDBUCH.read_text(encoding="utf-8"))
    return parser


def _norm(text: str) -> str:
    return " ".join(text.split())


TEXT = _norm("".join(_parsed().parts))


def _pattern(template: str) -> re.Pattern:
    """Konsolentext als Regex: feste Teile wörtlich, ``{platzhalter}`` beliebig.

    Die ganze Zeile muss passen, nicht nur Bruchstücke: bei „FEHLER {name}
    ({untersuchung}): {status}“ blieben sonst nur „FEHLER“, „(“ und „):“ übrig.
    """
    parts = re.split(r"\{\w+\}", _norm(template))
    # Begrenzt, weil TEXT eine einzige Zeile ist: ein freies „.+?“ spränge sonst
    # über halbe Abschnitte. 120 Zeichen reichen für Pfade und Institutsnamen.
    return re.compile(".{1,120}?".join(re.escape(p) for p in parts))


def test_sections_present() -> None:
    headings = [_norm(h) for h in _parsed().headings]
    for title in (
        "Installieren",
        "Starten",
        "Wenn etwas schiefgeht",
        "Log-Datei schicken",
        "Automatisch starten (optional)",
        "Deinstallieren",
        "Referenz",
    ):
        assert any(h.endswith(title) for h in headings), title


def test_every_console_text_from_messages_is_quoted_verbatim() -> None:
    templates = [
        value
        for name, value in vars(messages).items()
        if name.isupper() and isinstance(value, str)
    ]
    # render() statt der rohen MESSAGES-Felder: so sind auch „FEHLER: “ und die
    # angehängten Log-/Kontakt-Zeilen dabei. Die Platzhalter bleiben stehen.
    for code in messages.MESSAGES:
        text = messages.render(code, Path("{log}"), Path("{credentials}"), "{gaps}")
        templates += text.splitlines()
    missing = [t for t in templates if not _pattern(t).search(TEXT)]
    assert missing == []


def test_paths_from_spec_verbatim() -> None:
    for path in (
        r"%LOCALAPPDATA%\mrt-termin-monitor\venv",
        r"%LOCALAPPDATA%\mrt-termin-monitor\credentials.yaml",
        r"Dokumente\mrt-termin-monitor\data\<lauf_id>.csv",
        r"Dokumente\mrt-termin-monitor\logs\run_<lauf_id>.log",
        r"Dokumente\mrt-termin-monitor\raw\<lauf_id>",
    ):
        assert path in TEXT, path


def test_all_sites_and_status_values_listed() -> None:
    for site in sites.load_sites().values():
        assert site.name in TEXT, site.name
        assert site.slug in TEXT, site.slug
    for value in csv_output.STATUS_VALUES.values():
        assert value in TEXT, value


def test_version_matches_project() -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    found = set(re.findall(r"mrt-termin-monitor[- ](\d+\.\d+\.\d+)", TEXT))
    assert found == {version}
