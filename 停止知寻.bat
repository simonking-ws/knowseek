:: KnowSeek batch script - first line is a comment on purpose: if the file was saved with a UTF-8 BOM, that prefix lands here instead of breaking @echo off below
@echo off
setlocal EnableExtensions
title KnowSeek - Stopper
cd /d "%~dp0"

rem ASCII-only output on purpose - see the header comment in the start script.

echo ============================================
echo   KnowSeek - stopping service
echo ============================================
echo.

netstat -ano | findstr ":9876" | findstr "LISTENING" >nul
if errorlevel 1 goto nope

echo   Killing the process listening on port 9876 ...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9876" ^| findstr "LISTENING"') do (echo   - PID: %%a & taskkill /F /PID %%a >nul 2>&1)
echo   Stopped.
echo.
timeout /t 2 /nobreak >nul
exit /b 0

:nope
echo   The service is not running.
echo.
timeout /t 2 /nobreak >nul
exit /b 0
