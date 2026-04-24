@echo off
REM 测试远程服务器 e600.feing.com.cn (HTTPS)

REM 设置 WebSocket 地址（使用 wss:// 因为服务器配置了 HTTPS）
set E100_WS_BASE=wss://e600.feing.com.cn

REM 设置认证模式为 http（远程服务器必须用 http 模式）
set E100_AUTH_MODE=http

REM 设置设备 ID 和密钥（需要替换为实际值）
set E100_DEVICE_ID=FA1-202603-000123
set E100_DEVICE_SECRET=your_device_secret_here

REM 启动模拟器
python simulator.py
