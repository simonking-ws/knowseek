@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title KnowSeek-Repair
cd /d "%~dp0"

echo ============================================
echo   KnowSeek - repair downloaded copy
echo ============================================
echo.
echo This fixes the classic "downloaded zip, double-click does nothing":
echo   [1] remove Windows file blocks (antivirus / SmartScreen may quarantine python.exe)
echo   [2] convert .bat line endings to CRLF (LF breaks cmd.exe parsing)
echo   [3] print an environment report
echo.
pause

echo.
echo [1/3] Removing file blocks ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%~dp0' -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.Extension -in '.exe','.dll','.pyd','.bat','.cmd','.ps1' } | Unblock-File -ErrorAction SilentlyContinue"
echo   done.
echo.

rem 注意：必须排除自身，cmd 按文件偏移逐行读取，边跑边改自己会导致后续命令错位
echo [2/3] Converting .bat line endings to CRLF ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$self = Split-Path -Leaf $MyInvocation.MyCommand.Path; $e = New-Object System.Text.UTF8Encoding($false); Get-ChildItem -LiteralPath '%~dp0' -Filter *.bat -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notmatch '\\.venv\\' -and $_.Name -ne $self -and $_.Name -ne '修复环境.bat' } | ForEach-Object { $t = [IO.File]::ReadAllText($_.FullName) -replace '(?<!\r)\n', ([string][char]13 + [string][char]10); [IO.File]::WriteAllText($_.FullName, $t, $e); Write-Host ('       ' + $_.Name) }"
echo   done.
echo.

echo [3/3] Environment report:
echo.
if exist "%~dp0.venv" echo   [OK]   bundled runtime directory found: .venv
if not exist "%~dp0.venv" echo   [WARN] no .venv - it will be created automatically on first start
if exist "%~dp0.venv\Scripts\python.exe" echo   [OK]   found .venv\Scripts\python.exe
if not exist "%~dp0.venv\Scripts\python.exe" echo   [WARN] missing .venv\Scripts\python.exe
if exist "%~dp0.venv\Scripts\python.exe" "%~dp0.venv\Scripts\python.exe" -c "import sys; print('         venv python version: ' + sys.version.split()[0])"
if exist "%~dp0.config.yaml" echo   [OK]   found config.yaml
if not exist "%~dp0.config.yaml" echo   [WARN] missing config.yaml
if exist "%~dp0.run.py" echo   [OK]   found run.py
if not exist "%~dp0.run.py" echo   [WARN] missing run.py
where py >nul 2>&1
if not errorlevel 1 echo   [OK]   system python launcher available: py
where python >nul 2>&1
if not errorlevel 1 echo   [OK]   system python available: python
echo.
echo   Port 9876 status:
netstat -ano | findstr ":9876" | findstr "LISTENING"
if errorlevel 1 echo   (not occupied, ok to start)
echo.
echo   .bat line endings in this folder:
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%~dp0' -Filter *.bat -File -ErrorAction SilentlyContinue | ForEach-Object { $b = [IO.File]::ReadAllBytes($_.FullName); $lf = 0; $crlf = 0; for ($i = 0; $i -lt $b.Length; $i++) { if ($b[$i] -eq 10) { $lf++ }; if ($i -gt 0 -and $b[$i] -eq 10 -and $b[$i-1] -eq 13) { $crlf++ } }; Write-Host ('       ' + $_.Name + ' : LF=' + $lf + ' CRLF=' + $crlf) }"
echo.
echo repair finished, now double-click 启动知寻.bat
echo.
pause
exit /b 0
