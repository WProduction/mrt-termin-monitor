@echo off
rem Richtet den optionalen woechentlichen Lauf ein (Montag 09:00, ohne Fenster).
rem /f: erneutes Registrieren ersetzt den Task statt zu scheitern.
schtasks /create /tn MRT-Termin-Monitor /xml "%~dp0mrt-termin-monitor-weekly.xml" /f
if errorlevel 1 (
    echo FEHLER: Der automatische Start konnte nicht eingerichtet werden.
) else (
    echo OK: Das Programm laeuft jetzt jeden Montag um 09:00 Uhr automatisch.
)
pause
