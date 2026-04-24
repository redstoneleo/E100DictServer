@echo off
echo ========================================
echo E100DictServer 启动脚本
echo ========================================
echo.
echo 选择启动方式:
echo 1. Daphne (推荐，支持 WebSocket)
echo 2. Uvicorn (支持 WebSocket)
echo 3. Django runserver (仅 HTTP，不支持 WebSocket)
echo.
set /p choice="请输入选项 (1/2/3): "

if "%choice%"=="1" (
    echo.
    echo 正在使用 Daphne 启动服务器...
    echo 访问地址: http://0.0.0.0:8000
    echo WebSocket: ws://0.0.0.0:8000/ws/chatbot/
    echo.
    daphne -b 0.0.0.0 -p 8000 E100DictServer.asgi:application
) else if "%choice%"=="2" (
    echo.
    echo 正在使用 Uvicorn 启动服务器...
    echo 访问地址: http://0.0.0.0:8000
    echo WebSocket: ws://0.0.0.0:8000/ws/chatbot/
    echo.
    uvicorn E100DictServer.asgi:application --host 0.0.0.0 --port 8000
) else if "%choice%"=="3" (
    echo.
    echo 正在使用 Django runserver 启动服务器...
    echo 警告: 此模式不支持 WebSocket!
    echo 访问地址: http://0.0.0.0:8000
    echo.
    python manage.py runserver 0.0.0.0:8000
) else (
    echo 无效的选项!
    pause
    exit /b 1
)
