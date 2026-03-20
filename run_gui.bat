@echo off
setlocal
set "ROOT=%~dp0"
set "MAAFW_BINARY_PATH=%ROOT%runtime\bin"
cd /d "%ROOT%"
python gui_app.py
endlocal

