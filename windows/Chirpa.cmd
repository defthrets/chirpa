@echo off
REM ── Chirpa launcher ─────────────────────────────────────────────────
REM Starts the Chirpa dashboard using the bundled, private Python runtime.
REM No system Python, pip, or PATH changes are required.

setlocal
set "CHIRPA_HOME=%~dp0"
cd /d "%CHIRPA_HOME%"

REM Use the windowed interpreter so no console window lingers.
start "" "%CHIRPA_HOME%python\pythonw.exe" "%CHIRPA_HOME%birdnet_gui.py"
endlocal
