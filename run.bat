@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\tucknote.exe" (
    ".venv\Scripts\tucknote.exe" %*
    goto :eof
)

if exist "%USERPROFILE%\.local\bin\uv.exe" (
    "%USERPROFILE%\.local\bin\uv.exe" run tucknote %*
    goto :eof
)

py -3.12 -m tucknote %*
