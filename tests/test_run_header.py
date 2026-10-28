# SPDX-License-Identifier: Apache-2.0
"""Run-Header und Log-Retention."""

from datetime import datetime
from pathlib import Path

from mrt_termin_monitor import __version__, retention, runinfo


def test_lauf_id_format() -> None:
    assert runinfo.lauf_id(datetime(2026, 10, 25, 8, 15)) == "2026-10-25_0815"


def test_header_has_provenance_but_no_secret_content(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    creds.write_text("svnr: geheimwert\n", encoding="utf-8")
    sites = tmp_path / "sites.yaml"
    sites.write_bytes(b"x")
    text = "\n".join(runinfo.header_lines(["run", "--only", "a"], creds, sites))
    assert __version__ in text
    assert "Python " in text and "Platform " in text and "utf8_mode=" in text
    # SHA-256 von b"x"
    assert "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881" in text
    assert "credentials.yaml vorhanden" in text
    assert "geheimwert" not in text
    assert "['run', '--only', 'a']" in text


def test_header_reports_missing_files(tmp_path: Path) -> None:
    text = "\n".join(
        runinfo.header_lines([], tmp_path / "nope.yaml", tmp_path / "nope2.yaml")
    )
    assert "credentials.yaml fehlt" in text
    assert "sha256=fehlt" in text


def test_prune_keeps_30_newest(tmp_path: Path) -> None:
    for i in range(35):
        (tmp_path / f"run_2026-01-{i + 1:02d}_0800.log").write_text("x")
    (tmp_path / "anderes.txt").write_text("bleibt")
    removed = retention.prune_logs(tmp_path)
    left = sorted(p.name for p in tmp_path.glob("run_*.log"))
    assert len(left) == 30 and len(removed) == 5
    assert left[0] == "run_2026-01-06_0800.log"
    assert (tmp_path / "anderes.txt").exists()
