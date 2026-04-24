# 从 uWSGI + Daphne 迁移到 Gunicorn + Uvicorn

## 迁移步骤

### 1. 安装新依赖

```bash
cd /home/ubuntu/E100DictServer/
source SiteEnv/bin/activate
uv pip install gunicorn uvicorn[standard]
```

### 2. 配置 systemd 服务

```bash
# 复制 systemd 服务文件
sudo cp /home/ubuntu/E100DictServer/gunicorn.service /etc/systemd/system/

# 重新加载 systemd
sudo systemctl daemon-reload

# 启用开机自启
sudo systemctl enable gunicorn
```

### 3. 更新 Nginx 配置

```bash
# 备份旧配置
sudo cp /etc/nginx/conf.d/E100DictServer_nginx_http.conf /etc/nginx/conf.d/E100DictServer_nginx_http.conf.bak

# 使用新配置
sudo cp /home/ubuntu/E100DictServer/E100DictServer_nginx_gunicorn.conf /etc/nginx/conf.d/E100DictServer_nginx_http.conf

# 测试 Nginx 配置
sudo nginx -t
```

### 4. 停止旧服务并启动新服务

```bash
# 停止旧服务
pkill -f uwsgi -9
pkill -f daphne -9

# 启动新服务
sudo systemctl start gunicorn

# 重启 Nginx
sudo systemctl restart nginx
```

### 5. 验证服务状态

```bash
# 查看 Gunicorn 状态
sudo systemctl status gunicorn

# 查看日志
sudo journalctl -u gunicorn -f

# 或查看日志文件
tail -f /home/ubuntu/E100DictServer/gunicorn_access.log
tail -f /home/ubuntu/E100DictServer/gunicorn_error.log
```

### 6. 测试功能

- 测试普通 HTTP 请求: `curl http://e600.feing.com.cn/`
- 测试 WebSocket 连接: 使用 `test_ws_client.py`

## 常用管理命令

```bash
# 启动服务
sudo systemctl start gunicorn

# 停止服务
sudo systemctl stop gunicorn

# 重启服务
sudo systemctl restart gunicorn

# 重新加载配置（不中断连接）
sudo systemctl reload gunicorn

# 查看状态
sudo systemctl status gunicorn

# 查看日志
sudo journalctl -u gunicorn -f
```

## 性能调优

编辑 `gunicorn.conf.py`:

```python
# 根据服务器 CPU 核心数调整
workers = 4  # 推荐: CPU核心数 * 2 + 1

# 调整超时时间
timeout = 120

# 调整最大请求数（防止内存泄漏）
max_requests = 1000
```

修改后重启服务:
```bash
sudo systemctl restart gunicorn
```

## 回滚方案

如果遇到问题需要回滚:

```bash
# 停止新服务
sudo systemctl stop gunicorn
sudo systemctl disable gunicorn

# 恢复旧的 Nginx 配置
sudo cp /etc/nginx/conf.d/E100DictServer_nginx_http.conf.bak /etc/nginx/conf.d/E100DictServer_nginx_http.conf

# 启动旧服务
cd /home/ubuntu/E100DictServer/
source SiteEnv/bin/activate
uwsgi --ini uwsgi.ini
daphne -b 127.0.0.1 -p 8001 E100DictServer.asgi:application

# 重启 Nginx
sudo systemctl restart nginx
```

## 优势对比

### 旧方案 (uWSGI + Daphne)
- 需要维护两个服务器进程
- 配置复杂，两个端口
- Daphne 性能一般

### 新方案 (Gunicorn + Uvicorn)
- 单一服务器进程
- 配置简单，一个端口
- Uvicorn 性能更好（基于 uvloop）
- 更好的进程管理和优雅重启
- 社区更活跃

## 注意事项

1. 确保 Redis 服务正常运行（Channels 依赖）
2. 确保 Celery 服务正常运行
3. 迁移后测试所有 WebSocket 功能
4. 监控日志确保没有错误
