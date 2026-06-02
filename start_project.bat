@echo off
:: 强制控制台使用 UTF-8 编码，防止中文日志乱码
chcp 65001 >nul
title QX Agent 项目全模块一键全自动启动器
cd /d %~dp0

echo ============================================================
echo  🚀 QX Product Research Agent 项目全模块全自动拉起工具
echo ============================================================
echo.

:: 1. 自动化探测并拦截守护 Redis
echo [1/4] 🔍 正在精密检测本地 Redis 服务 (端口: 6379)...
netstat -ano | findstr "6379" >nul
if %errorlevel% equ 0 (
    echo    ✅ 检测到本地 Redis 哨兵服务已处于就绪运行状态。
) else (
    echo    ⚠️ 未检测到常驻 Redis 端口！正在尝试静默拉起 Windows 本地 Redis 服务...
    net start redis >nul 2>&1

    :: 再次硬校验
    netstat -ano | findstr "6379" >nul
    if %errorlevel% neq 0 (
        echo    ❌ [致命错误] 无法全自动唤醒 Redis 服务！
        echo    请检查本地是否安装 Redis 并常驻 6379 端口。
        echo.
        pause
        exit /b
    )
    echo    ✅ Redis 服务已成功唤醒并就绪。
)
echo.

:: 2. 独立窗口启动 FastAPI 异步 Web 服务
echo [2/4] 🌐 正在独立进程窗口中拉起 FastAPI Web 服务 (端口: 8000)...
if not exist venv\Scripts\activate (
    echo    ❌ [致命错误] 未在当前根目录下找到 venv 虚拟环境！
    pause
    exit /b
)
start "1. FastAPI Web Server (Port 8000)" cmd /k "call venv\Scripts\activate && cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

:: 3. 独立窗口启动符合 Windows/Python3.14 架构对齐的 Celery 线程池 Worker
echo [3/4] ⚙️  正在独立进程窗口中拉起 Celery 异步队列 Worker (Pool: threads)...
start "2. Celery Worker (Async Queue)" cmd /k "call venv\Scripts\activate && cd backend && celery -A app.core.celery_app.celery_app worker --loglevel=info --concurrency=4 --pool=threads"

:: 4. 独立窗口启动 React 前端开发服务器 (Vite)
echo [4/4] 📦 正在独立进程窗口中拉起 React 前端开发服务器 (Vite Dev)...
if not exist frontend\package.json (
    echo    ❌ [致命错误] 未在当前根目录下找到 frontend 文件夹！
    pause
    exit /b
)
start "3. React Frontend (Vite Dev)" cmd /k "cd frontend && npm run dev"

echo.
echo ============================================================
echo  🎉 恭喜！整个全栈 Agent 项目架构组件指令已全部下发就绪！
echo  💡 核心技术对齐: Celery 已强制切换为线程池模式，免除解包崩溃隐患。
echo  ⚠️  提示: 请保持弹出的 3 个控制台窗口处于开启状态。祝开发愉快！
echo ============================================================
echo.
pause
