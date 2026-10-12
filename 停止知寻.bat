@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title KnowSeek-Stopper
cd /d "%~dp0"

echo ============================================
echo   KnowSeek - stopping service
echo ============================================
echo.

netstat -ano | findstr ":9876" | findstr "LISTENING" >nul
if errorlevel 1 goto nope

echo   Killing the process listening on port 9876...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9876" ^| findstr "LISTENING"') do (echo   - PID: %%a & taskkill /F /PID %%a >nul 2>&1)
echo   Stopped.
echo.
timeout /t 2 /nobreak >nul
exit /b 0

:nope
echo   Service is not running.
echo.
timeout /t 2 /nobreak >nul
exit /b 0
