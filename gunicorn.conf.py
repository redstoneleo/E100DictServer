# Gunicorn configuration file for E100DictServer
import multiprocessing

# Server socket
bind = "127.0.0.1:8000"

# Worker processes
workers = 4  # 推荐: CPU核心数 * 2 + 1
worker_class = "uvicorn.workers.UvicornWorker"

# Logging
accesslog = "/home/ubuntu/E100DictServer/gunicorn_access.log"
errorlog = "/home/ubuntu/E100DictServer/gunicorn_error.log"
loglevel = "info"

# Process naming
proc_name = "e100dictserver"

# Worker timeout (秒)
timeout = 120
keepalive = 5

# Graceful timeout
graceful_timeout = 30

# Max requests per worker (防止内存泄漏)
max_requests = 1000
max_requests_jitter = 50

# Daemon mode
daemon = False  # systemd 会管理进程，不需要 daemon

# PID file
pidfile = "/home/ubuntu/E100DictServer/gunicorn.pid"
