@echo off
setlocal
set "ROOT=%~dp0"
set "MAAFW_BINARY_PATH=%ROOT%runtime\bin"
cd /d "%ROOT%"
python -m autoreverse.main --controller win32 --bundle "%ROOT%resource\autoreverse_bundle" --config "%ROOT%autoreverse\config.default.json"
endlocal

