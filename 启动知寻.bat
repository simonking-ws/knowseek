@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title KnowSeek-Launcher
cd /d "%~dp0"

set "ROOT=%~dp0"
set "VENV=%ROOT%.venv\Scripts\python.exe"
set "VENVW=%ROOT%.venv\Scripts\pythonw.exe"
set "LOG=%ROOT%logs\knowseek.log"

echo ============================================
echo   KnowSeek - starting
echo ============================================
echo.

if not exist "logs" mkdir logs

netstat -ano | findstr ":9876" | findstr "LISTENING" >nul
if not errorlevel 1 goto already

echo [1/3] choose python runtime
if not exist "%VENV%" goto syspy

"%VENV%" -c "import sys" >nul 2>&1
if not errorlevel 1 goto venvoke

echo   - bundled venv not usable on this machine, repairing...
where py >nul 2>&1
if not errorlevel 1 goto repairpy
where python >nul 2>&1
if not errorlevel 1 goto repairpython
echo   - no system python available for repair
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
echo   - using bundled runtime: .venv
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
echo     first run takes about 1-3 minutes, please wait...
%SYS% -m venv "%ROOT%.venv"
if not exist "%VENV%" goto mkvfail
set PY="%VENV%"
set PYW="%VENVW%"
if not exist "%VENVW%" set PYW="%VENV%"
goto installdeps

:sysuse
set "PY=%SYS%"
set "PYW=%SYS%"
echo   - using system python
goto deps

:deps
%PY% -c "import flask, jieba, yaml, docx, pdfplumber, openpyxl" >nul 2>&1
if errorlevel 1 goto installdeps
goto launch

:installdeps
echo   - installing dependencies, please wait...
%PY% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 goto pipfail
goto launch

:launch
echo.
echo [2/3] starting server in background, log: logs\knowseek.log
start "" /b %PYW% run.py > "%LOG%" 2>&1
echo [3/3] waiting for the service to become ready...
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
echo   URL    : http://127.0.0.1:9876
echo   Stop   : run  停止知寻.bat
echo   Restart: run  重启知寻.bat
echo.
echo Opening browser...
start "" http://127.0.0.1:9876
timeout /t 5 /nobreak >nul
exit /b 0

:already
echo Service is already running, opening browser...
start "" http://127.0.0.1:9876
echo.
echo   To restart, run 重启知寻.bat
echo.
timeout /t 5 /nobreak >nul
exit /b 0

:nopython
echo.
echo [ERROR] No usable python runtime found.
echo.
echo   The bundled .venv is missing or broken. Common causes:
echo     1) .venv was not extracted  - unzip to a SHORT path like C:\knowseek\
echo     2) python.exe was quarantined by antivirus - restore it, then run 修复环境.bat
echo     3) the unzip tool skipped deep paths - retry with Windows Explorer or 7-Zip
echo.
echo   Or install Python 3.9-3.12 manually (check "Add to PATH"):
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
echo [ERROR] Service did not become ready within 25 seconds.
echo Last lines of the log:
echo -------------------------------------------
powershell -NoProfile -Command "if (Test-Path -LiteralPath '%LOG%') { Get-Content -LiteralPath '%LOG%' -Tail 25 } else { Write-Host '(no log file produced)' }"
echo -------------------------------------------
echo.
echo   What to try:
echo     1) run 修复环境.bat first, then start again
echo     2) read the full log: logs\knowseek.log
echo     3) if port 9876 is occupied: run 停止知寻.bat or change port in config.yaml
echo.
pause
exit /b 1
