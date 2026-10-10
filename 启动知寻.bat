@echo off
echo ============================================
echo   知寻 KnowSeek - 启动中...
echo ============================================
cd /d "%~dp0"

rem 无窗口后台启动：优先 pythonw（无控制台窗口），输出写入 logs\knowseek.log
set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "logs" mkdir logs
set "LOG=%~dp0logs\knowseek.log"

rem 已在运行：直接打开浏览器后退出
netstat -ano | findstr ":9876" | findstr "LISTENING" >nul
if not errorlevel 1 (
  echo 服务已在运行，正在打开浏览器...
  start "" http://127.0.0.1:9876
  timeout /t 3 /nobreak >nul
  exit /b 0
)

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
echo 启动成功: http://127.0.0.1:9876
start "" http://127.0.0.1:9876
echo 停止服务请双击 停止知寻.bat
timeout /t 3 /nobreak >nul
exit /b 0

:fail
echo 启动超时，请查看日志: logs\knowseek.log
timeout /t 8 /nobreak >nul
exit /b 1
