@echo off
rem Startet einen Lauf. Ziel der Desktop-Verknuepfung; install.cmd kopiert diese
rem Datei nach %LOCALAPPDATA%\mrt-termin-monitor. Argumente gehen an "run"
rem durch (z. B. --only <slug> fuer eine Probe).
setlocal
set "PYV=%LOCALAPPDATA%\mrt-termin-monitor\venv\Scripts\python.exe"

if not exist "%PYV%" (
    echo FEHLER: Das Programm ist nicht installiert.
    echo Bitte zuerst install.cmd aus dem entpackten Ordner starten.
    pause
    exit /b 2
)

rem Fehlen die Zugangsdaten, erst die Einrichtung; eine kaputte Datei faengt der
rem Lauf selbst ab (Exit 2 mit Erklaerung).
"%PYV%" -X utf8 -c "from mrt_termin_monitor import paths; raise SystemExit(not paths.credentials_file().is_file())"
if errorlevel 1 "%PYV%" -X utf8 -m mrt_termin_monitor setup

"%PYV%" -X utf8 -m mrt_termin_monitor run %*
set "RC=%ERRORLEVEL%"
rem Fenster bleibt offen, Erfolg wie Fehler: die Operatorin liest die Summary.
pause
exit /b %RC%
