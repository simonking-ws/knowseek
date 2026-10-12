:: KnowSeek batch script - first line is a comment on purpose: if the file was saved with a UTF-8 BOM, that prefix lands here instead of breaking @echo off below
@echo off
setlocal EnableExtensions
title KnowSeek - Repair
cd /d "%~dp0"

rem ---------------------------------------------------------------------------
rem ASCII-only output on purpose - see the header comment in the start script.
rem
rem IMPORTANT structural rule for this file:
rem   The CRLF rewriting step MUST stay on the very LAST line.
rem   cmd.exe reads a batch file by byte offset, so if this file modified itself
rem   mid-run, every following statement would be read from a corrupted offset.
rem   Keeping it last (and doing the "press any key" wait inside PowerShell)
rem   means there is nothing left for cmd.exe to misread.
rem ---------------------------------------------------------------------------

echo ============================================
echo   KnowSeek - repair downloaded copy
echo ============================================
echo.
echo This fixes the classic "downloaded the zip, double-click does nothing" case:
echo   [1] remove Windows file blocks  (antivirus / SmartScreen may quarantine python.exe)
echo   [2] print an environment report
echo   [3] convert .bat line endings to CRLF  (LF breaks cmd.exe parsing)
echo.
pause

echo.
echo [1/3] Removing file blocks ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%~dp0' -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.Extension -in '.exe','.dll','.pyd','.bat','.cmd','.ps1' } | Unblock-File -ErrorAction SilentlyContinue"
echo   done.
echo.

echo [2/3] Environment report:
echo.
if exist "%~dp0.venv" echo   [OK]   bundled runtime directory found: .venv
if not exist "%~dp0.venv" echo   [WARN] no .venv - it will be created automatically on first start
if exist "%~dp0.venv\Scripts\python.exe" echo   [OK]   found .venv\Scripts\python.exe
if not exist "%~dp0.venv\Scripts\python.exe" echo   [WARN] missing .venv\Scripts\python.exe
if exist "%~dp0.venv\Lib\os.py" (echo   [OK]   bundled stdlib found: .venv\Lib ^(portable^)) else echo   [WARN] missing .venv\Lib\os.py - bundled runtime is not self-contained
if exist "%~dp0.venv\Scripts\python310.dll" (echo   [OK]   found .venv\Scripts\python310.dll) else echo   [WARN] missing .venv\Scripts\python310.dll - bundled runtime needs a system Python 3.10
if exist "%~dp0.venv\DLLs\_sqlite3.pyd" (echo   [OK]   found .venv\DLLs\_sqlite3.pyd) else echo   [WARN] missing .venv\DLLs extensions
if exist "%~dp0.venv\Scripts\python.exe" "%~dp0.venv\Scripts\python.exe" -c "import sys; print('         bundled python version: ' + sys.version.split()[0])"
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
echo   Existing log file - leading bytes (UTF-8 files must NOT start with EF,187,191):
powershell -NoProfile -Command "if (Test-Path -LiteralPath '%~dp0logs\knowseek.log') { $b = [IO.File]::ReadAllBytes('%~dp0logs\knowseek.log')[0..3]; Write-Host ('         bytes: ' + ($b -join ',')) } else { Write-Host '         (no log yet)' }"
echo.
echo   .bat health check  (asciiOnly must be True, CRLF should equal LF, BOM must be False):
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%~dp0' -Filter *.bat -File -ErrorAction SilentlyContinue | ForEach-Object { $b = [IO.File]::ReadAllBytes($_.FullName); $lf = 0; $crlf = 0; $hi = 0; for ($i = 0; $i -lt $b.Length; $i++) { if ($b[$i] -eq 10) { $lf++ }; if ($i -gt 0 -and $b[$i] -eq 10 -and $b[$i-1] -eq 13) { $crlf++ }; if ($b[$i] -gt 127) { $hi++ } }; $bom = ($b.Length -gt 2 -and $b[0] -eq 239 -and $b[1] -eq 187 -and $b[2] -eq 191); Write-Host ('         bat: ' + $_.Length + ' bytes   LF=' + $lf + ' CRLF=' + $crlf + ' nonAscii=' + $hi + ' BOM=' + $bom + ' asciiOnly=' + ($hi -eq 0)) }"
echo.
echo Review the report above, then continue to the last step.
echo.
pause

echo.
echo [3/3] Converting .bat line endings to CRLF ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$e = New-Object System.Text.UTF8Encoding($false); $n = 0; Get-ChildItem -LiteralPath '%~dp0' -Filter *.bat -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notmatch '\\.venv\\' } | ForEach-Object { $t = [IO.File]::ReadAllText($_.FullName) -replace '(?<!\r)\n', ([string][char]13 + [string][char]10); [IO.File]::WriteAllText($_.FullName, $t, $e); $n = $n + 1 }; Write-Host ('         normalized ' + $n + ' .bat file(s) to CRLF'); Write-Host ''; Write-Host 'Repair finished - now double-click the START script in this folder.'; Write-Host 'Press any key to close...'; try { [void][Console]::ReadKey($true) } catch { Start-Sleep -Seconds 5 }"
