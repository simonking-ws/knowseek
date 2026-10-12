:: KnowSeek batch script - first line is a comment on purpose: if the file was saved with a UTF-8 BOM, that prefix lands here instead of breaking @echo off below
@echo off
setlocal EnableExtensions
title KnowSeek - Launcher
cd /d "%~dp0"

rem ---------------------------------------------------------------------------
rem This file is intentionally ASCII-only (English messages).
rem Batch files cannot reliably display CJK text: cmd.exe decodes the .bat bytes
rem with the current console code page, which differs across Windows language /
region / font settings. ASCII output is guaranteed to render correctly everywhere.
rem The file MAY still contain Chinese script names in comments only.
rem
rem To keep generated artifacts readable, we force UTF-8 inside the child Python
rem process regardless of the machine locale:
rem   PYTHONUTF8        -> Python UTF-8 mode (open() / stdio defaults to utf-8)
rem   PYTHONIOENCODING  -> stdout+stderr are utf-8, so logs\knowseek.log stays UTF-8
rem   PYTHONUNBUFFERED  -> flush immediately, useful when the process is killed
rem ---------------------------------------------------------------------------
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

set "ROOT=%~dp0"
set "VENV=%ROOT%.venv\Scripts\python.exe"
set "VENVW=%ROOT%.venv\Scripts\pythonw.exe"
set "LOG=%ROOT%logs\knowseek.log"

echo ============================================
echo   KnowSeek - starting up
echo ============================================
echo.

if not exist "logs" mkdir logs

netstat -ano | findstr ":9876" | findstr "LISTENING" >nul
if not errorlevel 1 goto already

echo [1/3] Locating a python runtime ...
if not exist "%VENV%" goto syspy

"%VENV%" -c "import sys" >nul 2>&1
if not errorlevel 1 goto venvoke

echo   - bundled venv is not usable on this machine, trying to repair it ...
where py >nul 2>&1
if not errorlevel 1 goto repairpy
where python >nul 2>&1
if not errorlevel 1 goto repairpython
echo   - no system python available to repair with
goto syspy

:repairpy
py -3 -m venv "%ROOT%.venv"
goto repairdone

:repairpython
python -m venv "%ROOT%.venv"
goto repairdone

:repairdone
"%VENV%" -c "import sys" >nul 2>&1
if not errorlevel 1 goto venvoke
echo   - repair failed, falling back to system python
goto syspy

:venvoke
set PY="%VENV%"
set PYW="%VENVW%"
if not exist "%VENVW%" set PYW="%VENV%"
echo   - using the bundled runtime in .venv
goto deps

:syspy
where py >nul 2>&1
if not errorlevel 1 goto syspy1
where python >nul 2>&1
if not errorlevel 1 goto syspy2
goto nopython

:syspy1
set "SYS=py -3"
goto sysgot

:syspy2
set "SYS=python"
goto sysgot

:sysgot
if exist "%VENV%" goto sysuse
echo   - no bundled venv found, creating one and installing dependencies
echo     first run takes about 1-3 minutes, please wait ...
%SYS% -m venv "%ROOT%.venv"
if not exist "%VENV%" goto mkvfail
set PY="%VENV%"
set PYW="%VENVW%"
if not exist "%VENVW%" set PYW="%VENV%"
goto installdeps

:sysuse
set "PY=%SYS%"
set "PYW=%SYS%"
echo   - using the system python installation
goto deps

:deps
%PY% -c "import flask, jieba, yaml, docx, pdfplumber, openpyxl" >nul 2>&1
if errorlevel 1 goto installdeps
goto launch

:installdeps
echo   - installing dependencies, please wait ...
%PY% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 goto pipfail
goto launch

:launch
echo.
echo [2/3] Starting the server in the background ...
echo       log file: logs\knowseek.log  (UTF-8)
start "" /b %PYW% run.py > "%LOG%" 2>&1
echo [3/3] Waiting for the service to become ready ...
set waited=0

:wait
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":9876" | findstr "LISTENING" >nul
if not errorlevel 1 goto ready
set /a waited+=1
if %waited% GEQ 25 goto fail
goto wait

:ready
echo.
echo Started successfully.
echo.
echo   URL     : http://127.0.0.1:9876
echo   Stop    : run the STOP script in this folder
echo   Restart : run the RESTART script in this folder
echo   Logs    : logs\knowseek.log
echo.
echo Opening the browser ...
start "" http://127.0.0.1:9876
timeout /t 5 /nobreak >nul
exit /b 0

:already
echo The service is already running, opening the browser ...
start "" http://127.0.0.1:9876
echo.
echo   URL     : http://127.0.0.1:9876
echo   Restart : run the RESTART script in this folder
echo.
timeout /t 5 /nobreak >nul
exit /b 0

:nopython
echo.
echo [ERROR] No usable python runtime found.
echo.
echo   The bundled .venv is missing or broken. Common causes:
echo     1) .venv was not extracted
echo        -> unzip to a SHORT path such as C:\knowseek\ (Windows limits paths to 260 chars)
echo     2) python.exe was quarantined by antivirus
echo        -> restore it, then run the REPAIR script in this folder
echo     3) the unzip tool silently skipped deep directories
echo        -> retry with Windows Explorer or 7-Zip
echo.
echo   Alternatively install Python 3.9-3.12 manually (check "Add to PATH"):
echo   https://www.python.org/downloads/
echo.
pause
exit /b 1

:mkvfail
echo.
echo [ERROR] Failed to create the virtual environment.
echo.
echo   Run this manually to see the reason:
echo   %SYS% -m venv "%ROOT%.venv"
echo.
pause
exit /b 1

:pipfail
echo.
echo [ERROR] Failed to install dependencies, please check the network.
echo.
echo   Retry manually with:
echo   %PY% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.
pause
exit /b 1

:fail
echo.
echo [ERROR] The service did not become ready within 25 seconds.
echo Last lines of the log file:
echo -------------------------------------------
powershell -NoProfile -Command "if (Test-Path -LiteralPath '%LOG%') { Get-Content -LiteralPath '%LOG%' -Tail 25 -Encoding UTF8 } else { Write-Host '(no log file was produced)' }"
echo -------------------------------------------
echo.
echo   What to try:
echo     1) run the REPAIR script in this folder, then start again
echo     2) open the full log: logs\knowseek.log (UTF-8 encoded)
echo     3) if port 9876 is occupied: run the STOP script, or change "port" in config.yaml
echo.
pause
exit /b 1
