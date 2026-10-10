@echo off
echo ============================================
echo   知寻 KnowSeek - 重启服务...
echo ============================================
cd /d "%~dp0"

rem ---------- 1) 停止：终止占用 9876 端口的进程 ----------
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9876" ^| findstr "LISTENING"') do (
    echo 正在终止进程 PID: %%a
    taskkill /F /PID %%a >nul 2>&1
)

rem ---------- 2) 等待端口释放，最多 10 秒 ----------
set freed=0
:waitfree
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":9876" | findstr "LISTENING" >nul
if errorlevel 1 goto start
set /a freed+=1
if %freed% GEQ 10 (
  echo 端口 9876 仍未释放，请手动结束占用进程后重试
  timeout /t 5 /nobreak >nul
  exit /b 1
)
goto waitfree

rem ---------- 3) 后台启动 ----------
:start
set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "logs" mkdir logs
set "LOG=%~dp0logs\knowseek.log"

echo 正在后台启动（无窗口），日志: logs\knowseek.log
start "" /b "%PY%" run.py > "%LOG%" 2>&1

rem 等待端口就绪，最多 20 秒
set waited=0
:wait
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":9876" | findstr "LISTENING" >nul
if not errorlevel 1 goto ready
set /a waited+=1
if %waited% GEQ 20 goto fail
goto wait

:ready
echo 重启完成: http://127.0.0.1:9876
start "" http://127.0.0.1:9876
echo 其它操作: 停止知寻.bat / 启动知寻.bat
timeout /t 3 /nobreak >nul
exit /b 0

:fail
echo 启动超时，请查看日志: logs\knowseek.log
timeout /t 8 /nobreak >nul
exit /b 1
