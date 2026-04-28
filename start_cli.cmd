@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON312=%LocalAppData%\Programs\Python\Python312\python.exe"

if not exist "%PYTHON312%" (
    echo Python 3.12 not found at:
    echo   %PYTHON312%
    echo Install Python 3.12 first, then rerun this script.
    exit /b 1
)

if not exist "%ROOT%mykey.py" (
    echo mykey.py is missing. Copy mykey_template.py to mykey.py and add your API config.
    exit /b 1
)

if defined PYTHONPATH (
    set "PYTHONPATH=%ROOT%.deps;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%ROOT%.deps"
)

"%PYTHON312%" "%ROOT%agentmain.py" %*

