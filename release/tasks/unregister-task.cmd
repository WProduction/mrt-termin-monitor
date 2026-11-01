@echo off
rem Entfernt den woechentlichen Lauf wieder; das Programm selbst bleibt.
schtasks /delete /tn MRT-Termin-Monitor /f
if errorlevel 1 (
    echo HINWEIS: Es war kein automatischer Start eingerichtet.
) else (
    echo OK: Der automatische Start ist entfernt.
)
pause
