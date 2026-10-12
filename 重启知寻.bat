@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title KnowSeek-Restarter
cd /d "%~dp0"

echo ============================================
echo   KnowSeek - restarting service
echo ============================================
echo.

call "%~dp0Í£Ö¹ÖªÑ°.bat"

echo.
echo Waiting for port 9876 to be released...
set freed=0

:waitfree
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":9876" | findstr "LISTENING" >nul
if errorlevel 1 goto start
set /a freed+=1
if %freed% GEQ 10 goto portfail
goto waitfree

:start
echo.
call "%~dp0Æô¶¯ÖªÑ°.bat"
exit /b 0

:portfail
echo   Port 9876 is still occupied, please kill the process manually.
echo.
pause
exit /b 1
