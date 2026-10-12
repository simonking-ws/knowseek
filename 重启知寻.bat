:: KnowSeek batch script - first line is a comment on purpose: if the file was saved with a UTF-8 BOM, that prefix lands here instead of breaking @echo off below
@echo off
setlocal EnableExtensions
title KnowSeek - Restarter
cd /d "%~dp0"

rem ---------------------------------------------------------------------------
rem This script is deliberately SELF-CONTAINED: it never calls another .bat.
rem
rem Reason: cmd.exe decodes a .bat's bytes using the current console code page.
rem The names 启动 / 停止 / 重启 are stored as UTF-8 bytes, so on a machine whose
rem console code page is GBK those bytes decode into a DIFFERENT string and any
rem `call "%~dp0<name>.bat"` referencing them fails to resolve. That is why the
rem start and stop scripts work fine while this one did not - only this one
rem needs to invoke its siblings.
rem
rem Inlining both phases removes the only fragile dependency. The rest of the
rem logic is identical to the start script.
rem ---------------------------------------------------------------------------

rem Keep generated artifacts readable regardless of the machine locale:
rem   PYTHONUTF8        -> Python UTF-8 mode (open() / stdio defaults to utf-8)
rem   PYTHONIOENCODING  -> stdout+stderr are utf-8, so logs\knowseek.log stays UTF-8
rem   PYTHONUNBUFFERED  -> flush immediately, useful when the process is killed
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

set "ROOT=%~dp0"
set "VENV=%ROOT%.venv\Scripts\python.exe"
set "VENVW=%ROOT%.venv\Scripts\pythonw.exe"
set "LOG=%ROOT%logs\knowseek.log"

if not exist "logs" mkdir logs

echo ============================================
echo   KnowSeek - restarting service
echo ============================================
echo.

rem ================= phase 1: stop =================
echo [1/4] Stopping the running service ...
netstat -ano | findstr ":9876" | findstr "LISTENING" >nul
if errorlevel 1 goto nothingtokill

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9876" ^| findstr "LISTENING"') do (echo   - terminating PID: %%a & taskkill /F /PID %%a >nul 2>&1)
echo   Stopped.
echo.
echo [2/4] Waiting for port 9876 to be released ...
set freed=0

:waitfree
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":9876" | findstr "LISTENING" >nul
if errorlevel 1 goto pickpy
set /a freed+=1
if %freed% GEQ 10 goto portfail
goto waitfree

:nothingtokill
echo   No service is currently running.
echo.

rem ================= phase 2: pick a python runtime =================
:pickpy
echo [3/4] Locating a python runtime ...
if not exist "%VENV%" goto rsyspy

"%VENV%" -c "import sys" >nul 2>&1
if not errorlevel 1 goto rvenvoke

echo   - bundled venv is not usable on this machine, trying to repair it ...
where py >nul 2>&1
if not errorlevel 1 goto rrepairpy
where python >nul 2>&1
if not errorlevel 1 goto rrepairpython
echo   - no system python available to repair with
goto rsyspy

:rrepairpy
py -3 -m venv "%ROOT%.venv"
goto rrepairdone

:rrepairpython
python -m venv "%ROOT%.venv"
goto rrepairdone

:rrepairdone
"%VENV%" -c "import sys" >nul 2>&1
if not errorlevel 1 goto rvenvoke
echo   - repair failed, falling back to system python
goto rsyspy

:rvenvoke
set PY="%VENV%"
set PYW="%VENVW%"
if not exist "%VENVW%" set PYW="%VENV%"
echo   - using the bundled runtime in .venv
goto rdeps

:rsyspy
where py >nul 2>&1
if not errorlevel 1 goto rsyspy1
where python >nul 2>&1
if not errorlevel 1 goto rsyspy2
goto rnopython

:rsyspy1
set "SYS=py -3"
goto rsysgot

:rsyspy2
set "SYS=python"
goto rsysgot

:rsysgot
if exist "%VENV%" goto rsysuse
echo   - no bundled venv found, creating one and installing dependencies
echo     first run takes about 1-3 minutes, please wait ...
%SYS% -m venv "%ROOT%.venv"
if not exist "%VENV%" goto rmkvfail
set PY="%VENV%"
set PYW="%VENVW%"
if not exist "%VENVW%" set PYW="%VENV%"
goto rinstalldeps

:rsysuse
set "PY=%SYS%"
set "PYW=%SYS%"
echo   - using the system python installation
goto rdeps

:rdeps
%PY% -c "import flask, jieba, yaml, docx, pdfplumber, openpyxl" >nul 2>&1
if errorlevel 1 goto rinstalldeps
goto rlaunch

:rinstalldeps
echo   - installing dependencies, please wait ...
%PY% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 goto rpipfail
goto rlaunch

rem ================= phase 3: start =================
:rlaunch
echo.
echo [4/4] Starting the server in the background ...
echo       log file: logs\knowseek.log  (UTF-8)
start "" /b %PYW% run.py > "%LOG%" 2>&1
echo       Waiting for the service to become ready ...
set waited=0

:rwait
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":9876" | findstr "LISTENING" >nul
if not errorlevel 1 goto rready
set /a waited+=1
if %waited% GEQ 25 goto rfail
goto rwait

:rready
echo.
echo Restarted successfully.
echo.
echo   URL     : http://127.0.0.1:9876
echo   Stop    : run the STOP script in this folder
echo   Logs    : logs\knowseek.log
echo.
echo Opening the browser ...
start "" http://127.0.0.1:9876
timeout /t 5 /nobreak >nul
exit /b 0

:portfail
echo.
echo [ERROR] Port 9876 was not released within 10 seconds.
echo         Please terminate the process holding it manually and retry.
echo.
pause
exit /b 1

:rnopython
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

:rmkvfail
echo.
echo [ERROR] Failed to create the virtual environment.
echo.
echo   Run this manually to see the reason:
echo   %SYS% -m venv "%ROOT%.venv"
echo.
pause
exit /b 1

:rpipfail
echo.
echo [ERROR] Failed to install dependencies, please check the network.
echo.
echo   Retry manually with:
echo   %PY% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.
pause
exit /b 1

:rfail
echo.
echo [ERROR] The service did not become ready within 25 seconds.
echo Last lines of the log file:
echo -------------------------------------------
powershell -NoProfile -Command "if (Test-Path -LiteralPath '%LOG%') { Get-Content -LiteralPath '%LOG%' -Tail 25 -Encoding UTF8 } else { Write-Host '(no log file was produced)' }"
echo -------------------------------------------
echo.
echo   What to try:
echo     1) run the REPAIR script in this folder, then restart again
echo     2) open the full log: logs\knowseek.log (UTF-8 encoded)
echo     3) if port 9876 is occupied by another program, change "port" in config.yaml
echo.
pause
exit /b 1
