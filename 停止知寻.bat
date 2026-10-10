@echo off
echo ============================================
echo   知寻 KnowSeek - 停止服务...
echo ============================================

rem 查找并终止占用 9876 端口的进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9876" ^| findstr "LISTENING"') do (
    echo 正在终止进程 PID: %%a
    taskkill /F /PID %%a >nul 2>&1
)

echo 服务已停止
timeout /t 3 /nobreak >nul
