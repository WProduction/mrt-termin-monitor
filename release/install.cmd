@echo off
rem Installiert mrt-termin-monitor fuer den angemeldeten Benutzer: venv unter
rem %LOCALAPPDATA%, Pakete offline aus wheels\, Desktop-Verknuepfung auf run.cmd.
rem Kein Admin, kein PATH-Eingriff. Erneut ausfuehren = Update (pip --upgrade).
rem Texte in ASCII-Umschrift: die Konsole liest .cmd-Dateien in der OEM-Codepage.
setlocal
set "APPDIR=%LOCALAPPDATA%\mrt-termin-monitor"
set "VENV=%APPDIR%\venv"
set "PYV=%VENV%\Scripts\python.exe"

echo Installation mrt-termin-monitor
echo.

rem Zuerst der py-Launcher (python.org-Standard), dann python im PATH. Der
rem WindowsApps-Platzhalter "python" ohne installiertes Python scheitert hier.
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (python -c "import sys" >nul 2>&1 && set "PY=python")
if not defined PY goto :kein_python
rem Mindestversion = requires-python in pyproject.toml (Test prueft Gleichheit).
%PY% -c "import sys; sys.exit(sys.version_info < (3, 14))" || goto :altes_python

echo Schritt 1 von 3: Programm wird installiert ...
%PY% -m venv "%VENV%" || goto :fehler
"%PYV%" -m pip install --no-index --find-links "%~dp0wheels" --upgrade --disable-pip-version-check --quiet mrt_termin_monitor || goto :fehler
"%PYV%" -X utf8 -m mrt_termin_monitor --version || goto :fehler

echo Schritt 2 von 3: Verknuepfung auf dem Desktop wird angelegt ...
rem run.cmd neben das venv kopieren: der entpackte Ordner darf danach weg.
copy /y "%~dp0run.cmd" "%APPDIR%\run.cmd" >nul || goto :fehler
rem Desktop ueber die Shell-API, nicht %USERPROFILE%\Desktop: der Ordner kann
rem nach OneDrive umgeleitet sein. Pfad per $env, damit Sonderzeichen im
rem Benutzernamen das Quoting nicht brechen.
powershell -NoProfile -Command "$l=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\MRT-Termin-Monitor.lnk'); $l.TargetPath=$env:APPDIR+'\run.cmd'; $l.WorkingDirectory=$env:APPDIR; $l.Save()" || goto :fehler

echo Schritt 3 von 3: Einrichtung ...
rem Bei einem Update sind die Zugangsdaten schon da und werden nicht neu
rem abgefragt. Den Pfad kennt nur paths.py (eine Quelle fuer alle Pfade).
"%PYV%" -X utf8 -c "from mrt_termin_monitor import paths; raise SystemExit(not paths.credentials_file().is_file())"
if errorlevel 1 ("%PYV%" -X utf8 -m mrt_termin_monitor setup || goto :fehler)

echo.
echo OK: Installation abgeschlossen. Gestartet wird ueber die Verknuepfung
echo "MRT-Termin-Monitor" auf dem Desktop.
pause
exit /b 0

:kein_python
echo FEHLER: Python wurde nicht gefunden.
echo Vermutlich ist Python noch nicht installiert.
echo Bitte Python 3.14 oder neuer von https://www.python.org/downloads/windows/
echo installieren und install.cmd erneut starten.
pause
exit /b 2

:altes_python
echo FEHLER: Die installierte Python-Version ist zu alt.
%PY% --version
echo Bitte Python 3.14 oder neuer von https://www.python.org/downloads/windows/
echo installieren und install.cmd erneut starten.
pause
exit /b 2

:fehler
echo.
echo FEHLER: Die Installation ist fehlgeschlagen (siehe Meldung oben).
echo Bitte install.cmd erneut starten; bleibt der Fehler, ein Foto dieses
echo Fensters an die Person schicken, die das Programm betreut.
pause
exit /b 1
