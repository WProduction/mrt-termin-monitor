# SPDX-License-Identifier: Apache-2.0
"""Datei-Orte: Override, Absolutheit, Secrets nie unter Dokumente/OneDrive."""

from pathlib import Path

import pytest

from mrt_termin_monitor import paths

ALL = (
    paths.config_root,
    paths.documents_root,
    paths.credentials_file,
    paths.log_dir,
    paths.data_dir,
    paths.raw_dir,
)


def test_override_sets_both_roots(home: Path) -> None:
    assert paths.config_root() == home / "config"
    assert paths.documents_root() == home / "documents"
    assert paths.credentials_file() == home / "config" / "credentials.yaml"
    assert paths.log_dir() == home / "documents" / "logs"


def test_relative_override_becomes_absolute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(paths.HOME_ENV, "probe")
    assert all(fn().is_absolute() for fn in ALL)
    assert paths.config_root() == tmp_path / "probe" / "config"


def test_platform_paths_without_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(paths.HOME_ENV)
    assert all(fn().is_absolute() for fn in ALL)
    secret = str(paths.credentials_file()).lower()
    # Secrets nie in einem Ordner, den OneDrive synchronisieren kann.
    assert "documents" not in secret
    assert "onedrive" not in secret
    assert paths.config_root().name == paths.APP_NAME
    assert paths.documents_root().name == paths.APP_NAME
