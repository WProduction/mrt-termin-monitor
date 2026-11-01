@echo off
rem Entfernt Programm, Verknuepfung und geplanten Task. Die Ergebnisse unter
rem Dokumente\mrt-termin-monitor bleiben immer; die Zugangsdaten nur auf Wunsch.
setlocal
set "APPDIR=%LOCALAPPDATA%\mrt-termin-monitor"
set "PYV=%APPDIR%\venv\Scripts\python.exe"

echo Deinstallation mrt-termin-monitor
echo Die Ergebnisse im Ordner Dokumente\mrt-termin-monitor bleiben erhalten.
echo.

rem Vor dem Loeschen des venv fragen: den Pfad der Zugangsdaten kennt nur paths.py.
set "ANTWORT="
set /p "ANTWORT=Gespeicherte Sozialversicherungsnummer ebenfalls loeschen? [j/N] "
if /i "%ANTWORT%"=="j" (
    if exist "%PYV%" (
        "%PYV%" -X utf8 -c "from mrt_termin_monitor import paths; paths.credentials_file().unlink(missing_ok=True)"
    ) else (
        del /q "%APPDIR%\credentials.yaml" 2>nul
    )
    echo Zugangsdaten geloescht.
)

rem Fehlt der Task, meldet schtasks einen Fehler - hier kein Problem.
schtasks /delete /tn MRT-Termin-Monitor /f >nul 2>&1
powershell -NoProfile -Command "Remove-Item -LiteralPath ([Environment]::GetFolderPath('Desktop')+'\MRT-Termin-Monitor.lnk') -ErrorAction SilentlyContinue"
if exist "%APPDIR%\venv" rd /s /q "%APPDIR%\venv"
del /q "%APPDIR%\run.cmd" 2>nul
rem Nur wenn leer (ohne /s): verbliebene Zugangsdaten bleiben unangetastet.
rd "%APPDIR%" 2>nul

echo.
echo OK: Deinstallation abgeschlossen.
pause
exit /b 0
