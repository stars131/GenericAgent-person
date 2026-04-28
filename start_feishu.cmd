@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON312=%LocalAppData%\Programs\Python\Python312\python.exe"

if not exist "%PYTHON312%" (
    echo Python 3.12 not found at:
    echo   %PYTHON312%
    exit /b 1
)

if defined PYTHONPATH (
    set "PYTHONPATH=%ROOT%.deps;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%ROOT%.deps"
)

"%PYTHON312%" -u "%ROOT%frontends\fsapp.py" %*
