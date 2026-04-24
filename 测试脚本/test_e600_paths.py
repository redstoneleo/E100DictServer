import asyncio
import websockets
import ssl
import requests

HOST = "e600.feing.com.cn"
BASE_HTTP = f"https://{HOST}"
BASE_WS = f"wss://{HOST}"

# 可能的 WebSocket 路径
WS_PATHS = [
    "/ws/chatbot/",
    "/ws/chat/",
    "/ws/",
    "/websocket/",
    "/chatbot/",
    "/api/ws/chatbot/",
    "/api/websocket/",
]


async def test_ws_path(path: str):
    """测试单个 WebSocket 路径"""
    url = f"{BASE_WS}{path}"
    try:
        ssl_context = ssl.create_default_context()
        async with websockets.connect(url, ssl=ssl_context, open_timeout=3) as ws:
            return f"[✓] {path} - 连接成功"
    except websockets.exceptions.InvalidStatus as e:
        status = e.response.status_code if hasattr(e, 'response') else 'N/A'
        if status == 404:
            return f"[✗] {path} - 404 Not Found"
        elif status == 403:
            return f"[!] {path} - 403 Forbidden (路径存在但需要认证)"
        elif status == 401:
            return f"[!] {path} - 401 Unauthorized (路径存在但需要认证)"
        else:
            return f"[?] {path} - HTTP {status}"
    except asyncio.TimeoutError:
        return f"[✗] {path} - 超时"
    except Exception as e:
        return f"[✗] {path} - {type(e).__name__}"


def test_http_paths():
    """测试 HTTP 路径"""
    print("=== 测试 HTTP 路径 ===")
    
    paths = [
        "/",
        "/admin/",
        "/api/",
        "/device/",
        "/chatbot/",
        "/ws/",
    ]
    
    for path in paths:
        url = f"{BASE_HTTP}{path}"
        try:
            r = requests.get(url, timeout=3, allow_redirects=False)
            status = r.status_code
            if status == 200:
                print(f"[✓] {path} - 200 OK")
            elif status == 301 or status == 302:
                print(f"[→] {path} - {status} 重定向")
            elif status == 403:
                print(f"[!] {path} - 403 Forbidden")
            elif status == 404:
                print(f"[✗] {path} - 404 Not Found")
            else:
                print(f"[?] {path} - {status}")
        except Exception as e:
            print(f"[✗] {path} - {type(e).__name__}")
    
    print()


async def test_all_ws_paths():
    """测试所有可能的 WebSocket 路径"""
    print("=== 测试 WebSocket 路径 ===")
    
    tasks = [test_ws_path(path) for path in WS_PATHS]
    results = await asyncio.gather(*tasks)
    
    for result in results:
        print(result)
    
    print()


def check_server_info():
    """检查服务器信息"""
    print("=== 服务器信息 ===")
    
    try:
        r = requests.get(BASE_HTTP, timeout=5)
        print(f"服务器响应头:")
        for key, value in r.headers.items():
            if key.lower() in ['server', 'x-powered-by', 'x-frame-options']:
                print(f"  {key}: {value}")
    except Exception as e:
        print(f"无法获取服务器信息: {e}")
    
    print()


async def main():
    print("=" * 60)
    print("E600 服务器路径探测工具")
    print("=" * 60)
    print()
    
    check_server_info()
    test_http_paths()
    await test_all_ws_paths()
    
    print("=" * 60)
    print("建议:")
    print("1. 检查服务器是否已部署 WebSocket 路由")
    print("2. 检查 Nginx/Apache 配置是否正确代理 WebSocket")
    print("3. 检查 Django Channels 是否正确配置")
    print("4. 查看服务器日志获取更多信息")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
