# SPDX-License-Identifier: Apache-2.0
"""Release-Dateien: was beim Ändern still brechen würde, ohne dass ein Lauf es zeigt."""

import importlib.util
import tomllib
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "release"
TASK_XML = RELEASE / "tasks" / "mrt-termin-monitor-weekly.xml"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def test_release_dir_holds_exactly_the_zip_root() -> None:
    files = {
        p.relative_to(RELEASE).as_posix() for p in RELEASE.rglob("*") if p.is_file()
    }
    assert files == {
        "install.cmd",
        "run.cmd",
        "uninstall.cmd",
        "LIESMICH.txt",
        "tasks/mrt-termin-monitor-weekly.xml",
        "tasks/register-task.cmd",
        "tasks/unregister-task.cmd",
    }
    assert len((RELEASE / "LIESMICH.txt").read_text(encoding="ascii").splitlines()) == 5


def test_cmd_files_are_ascii() -> None:
    # cmd liest die Datei in der OEM-Codepage; Umlaute würden verstümmelt.
    for path in RELEASE.rglob("*.cmd"):
        path.read_bytes().decode("ascii")


def test_install_accepts_exactly_the_built_pythons() -> None:
    # wheels\ hat Binärpakete nur für PYTHONS; jede andere Version scheitert erst
    # in pip mit einer unverständlichen Meldung.
    pythons = _build_release().PYTHONS
    requires = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["requires-python"]
    assert requires == f">={pythons[0]}"
    install = (RELEASE / "install.cmd").read_text(encoding="ascii")
    versions = ", ".join(f"({v.replace('.', ', ')})" for v in pythons)
    assert f"sys.version_info[:2] not in ({versions})" in install
    assert f"Python {' oder '.join(pythons)} von" in install
    for v in pythons:
        assert f'set "PY=py -{v}"' in install
    assert "py -3 " not in install


def test_install_recreates_venv() -> None:
    # Nach einem Python-Wechsel blieben sonst Binärpakete der alten Version im venv.
    install = (RELEASE / "install.cmd").read_text(encoding="ascii")
    remove = install.index('rmdir /s /q "%VENV%"')
    assert remove < install.index("-m venv")


def test_install_refuses_source_archive_before_touching_anything() -> None:
    # Im GitHub-Quellcode-Archiv liegt install.cmd unter release\ ohne wheels\; die
    # Prüfung muss vor Python-Suche und venv stehen, sonst kommt nur die pip-Meldung.
    install = (RELEASE / "install.cmd").read_text(encoding="ascii")
    check = install.index('if not exist "%~dp0wheels\\" goto :falsches_zip')
    assert check < install.index('py -3.15 -c "import sys"')
    assert check < install.index("-m venv")
    assert "\n:falsches_zip\n" in install


def test_task_xml_settings() -> None:
    raw = TASK_XML.read_bytes()
    # schtasks /xml lehnt encoding="UTF-8" ab („Codierung kann nicht geändert werden“).
    raw.decode("ascii")
    assert b"encoding=" not in raw.split(b"?>")[0]
    task = ET.fromstring(raw)

    def text(path: str) -> str:
        return task.find(path, NS).text

    assert text("t:Settings/t:MultipleInstancesPolicy") == "IgnoreNew"
    assert text("t:Settings/t:ExecutionTimeLimit") == "PT1H"
    assert text("t:Settings/t:DisallowStartIfOnBatteries") == "false"
    assert text("t:Settings/t:StopIfGoingOnBatteries") == "false"
    assert text("t:Settings/t:StartWhenAvailable") == "true"
    assert text("t:Principals/t:Principal/t:LogonType") == "InteractiveToken"
    trigger = "t:Triggers/t:CalendarTrigger"
    assert text(f"{trigger}/t:StartBoundary").endswith("T09:00:00")
    assert (
        task.find(f"{trigger}/t:ScheduleByWeek/t:DaysOfWeek/t:Monday", NS) is not None
    )
    assert text("t:Actions/t:Exec/t:Command") == (
        r"%LOCALAPPDATA%\mrt-termin-monitor\venv\Scripts\pythonw.exe"
    )
    assert text("t:Actions/t:Exec/t:Arguments") == "-X utf8 -m mrt_termin_monitor run"


def test_task_name_matches_in_all_scripts() -> None:
    for name in (
        "tasks/register-task.cmd",
        "tasks/unregister-task.cmd",
        "uninstall.cmd",
    ):
        assert "/tn MRT-Termin-Monitor " in (RELEASE / name).read_text(encoding="ascii")


def _build_release():
    # tools/ ist kein Paket; das Skript direkt per Pfad laden.
    path = ROOT / "tools" / "build_release.py"
    spec = importlib.util.spec_from_file_location("build_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_zip_layout_and_crlf(tmp_path: Path) -> None:
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "demo-1.0-py3-none-any.whl").write_bytes(b"x")
    (wheels / ".gitignore").write_bytes(b"*")
    target = tmp_path / "dist" / "out.zip"
    names = _build_release().build_zip(wheels, target)
    assert "wheels/demo-1.0-py3-none-any.whl" in names
    assert "wheels/.gitignore" not in names
    assert "tasks/register-task.cmd" in names
    with zipfile.ZipFile(target) as zf:
        assert sorted(zf.namelist()) == sorted(names)
        for name in (n for n in names if n.endswith(".cmd")):
            data = zf.read(name)
            # Jede Zeile genau CRLF – auch wenn die Quelle schon CRLF hatte.
            assert b"\r\r" not in data
            assert data.count(b"\n") == data.count(b"\r\n") > 0
