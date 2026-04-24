import asyncio
import json
import websockets
import ssl
import requests
import hmac
import hashlib

# E600 服务器配置
HOST = "e600.feing.com.cn"
BASE_HTTP = f"https://{HOST}"
BASE_WS = f"wss://{HOST}"

# 设备信息（需要替换为实际的设备信息）
DEVICE_ID = "FA1-202603-000123"  # 替换为实际的 device_id
DEVICE_SECRET = "381570a6a34e98ea6183687f0932ed938436323be216bab360f9ac2376c2edbe"  # 替换为实际的 device_secret


def hmac_hex(secret: str, nonce: str) -> str:
    """计算 HMAC-SHA256 签名"""
    return hmac.new(
        secret.encode("utf-8"),
        nonce.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def test_http_endpoints():
    """测试 HTTP 端点是否可访问"""
    print("=== 测试 HTTP 端点 ===")
    
    endpoints = [
        "/",
        "/device/challenge/",
        "/device/token/",
        "/api/token/refresh/"
    ]
    
    for endpoint in endpoints:
        url = f"{BASE_HTTP}{endpoint}"
        try:
            response = requests.get(url, timeout=5)
            print(f"[{response.status_code}] {url}")
        except requests.exceptions.SSLError as e:
            print(f"[SSL错误] {url}: {e}")
        except requests.exceptions.ConnectionError as e:
            print(f"[连接错误] {url}: {e}")
        except Exception as e:
            print(f"[错误] {url}: {type(e).__name__}: {e}")
    
    print()


def get_nonce(device_id: str) -> str:
    """获取 nonce"""
    print(f"[*] 请求 nonce for device: {device_id}")
    try:
        r = requests.post(
            f"{BASE_HTTP}/device/challenge/",
            json={"device_id": device_id},
            timeout=10
        )
        print(f"[*] 响应状态码: {r.status_code}")
        print(f"[*] 响应内容: {r.text}")
        r.raise_for_status()
        return r.json()["nonce"]
    except Exception as e:
        print(f"[-] 获取 nonce 失败: {e}")
        raise


def get_tokens(device_id: str, device_secret: str):
    """获取 access 和 refresh token"""
    print(f"[*] 获取 token for device: {device_id}")
    try:
        nonce = get_nonce(device_id)
        print(f"[+] 获得 nonce: {nonce[:20]}...")
        
        sig = hmac_hex(device_secret, nonce)
        print(f"[*] 计算签名: {sig[:20]}...")
        
        r = requests.post(
            f"{BASE_HTTP}/device/token/",
            json={"device_id": device_id, "signature": sig},
            timeout=10
        )
        print(f"[*] 响应状态码: {r.status_code}")
        print(f"[*] 响应内容: {r.text}")
        r.raise_for_status()
        
        data = r.json()
        return data["access"], data["refresh"]
    except Exception as e:
        print(f"[-] 获取 token 失败: {e}")
        raise


async def test_websocket_with_auth(device_id: str, device_secret: str):
    """测试带完整认证的 WebSocket 连接"""
    print("=== 测试 WebSocket 连接（带认证）===")
    
    try:
        # 1. 获取 access token
        access, refresh = get_tokens(device_id, device_secret)
        print(f"[+] 获得 access token: {access[:30]}...")
        print(f"[+] 获得 refresh token: {refresh[:30]}...")
        print()
        
        # 2. 获取 WebSocket 连接用的 nonce 和签名
        print("[*] 获取 WebSocket 连接用的 nonce")
        nonce_ws = get_nonce(device_id)
        sign_ws = hmac_hex(device_secret, nonce_ws)
        print(f"[+] WS nonce: {nonce_ws[:20]}...")
        print(f"[+] WS sign: {sign_ws[:20]}...")
        print()
        
        # 3. 建立 WebSocket 连接
        ws_url = f"{BASE_WS}/ws/chatbot/?token={access}&nonce={nonce_ws}&sign={sign_ws}"
        print(f"[*] 连接到: {ws_url[:80]}...")
        
        ssl_context = ssl.create_default_context()
        
        async with websockets.connect(ws_url, ssl=ssl_context, ping_interval=None) as websocket:
            print("[+] WebSocket 连接成功！")
            
            # 4. 发送测试消息（模拟停止说话）
            test_msg = {"action": "stop_speaking"}
            await websocket.send(json.dumps(test_msg))
            print(f"[>] 已发送: {test_msg}")
            
            # 5. 接收消息
            print("[*] 等待服务器响应...")
            try:
                for i in range(5):
                    msg = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                    if isinstance(msg, bytes):
                        print(f"[<] 收到二进制数据: {len(msg)} 字节")
                    else:
                        print(f"[<] 收到文本: {msg}")
            except asyncio.TimeoutError:
                print("[!] 3秒内无响应")
            
            print("[+] 测试完成\n")
            
    except websockets.exceptions.InvalidStatus as e:
        print(f"[-] WebSocket 连接被拒绝")
        print(f"    状态码: {e.response.status_code if hasattr(e, 'response') else 'N/A'}")
        print(f"    详情: {e}\n")
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"[-] 连接被关闭")
        print(f"    代码: {e.code}")
        print(f"    原因: {e.reason}\n")
    except Exception as e:
        print(f"[-] 测试失败: {type(e).__name__}")
        print(f"    详情: {e}\n")


async def test_websocket_without_auth():
    """测试不带认证的 WebSocket 连接（应该失败）"""
    print("=== 测试 WebSocket 连接（无认证）===")
    
    ws_url = f"{BASE_WS}/ws/chatbot/"
    print(f"[*] 连接到: {ws_url}")
    
    try:
        ssl_context = ssl.create_default_context()
        async with websockets.connect(ws_url, ssl=ssl_context) as websocket:
            print("[-] 连接成功（不应该成功！）")
    except websockets.exceptions.InvalidStatus as e:
        print(f"[+] 连接被正确拒绝")
        print(f"    状态码: {e.response.status_code if hasattr(e, 'response') else 'N/A'}")
        print(f"    详情: {e}\n")
    except Exception as e:
        print(f"[*] 结果: {type(e).__name__}: {e}\n")


async def main():
    """主测试函数"""
    print("=" * 60)
    print("E600 服务端测试工具")
    print("=" * 60)
    print()
    
    # 测试 1: HTTP 端点可达性
    test_http_endpoints()
    
    # 测试 2: 无认证连接（应该失败）
    await test_websocket_without_auth()
    
    # 测试 3: 完整认证流程
    print("=" * 60)
    print("注意：以下测试需要有效的设备凭证")
    print(f"当前配置: DEVICE_ID={DEVICE_ID}")
    print("=" * 60)
    print()
    
    if DEVICE_SECRET == "your_device_secret_here":
        print("[!] 请在脚本中配置实际的 DEVICE_ID 和 DEVICE_SECRET")
        print("[!] 跳过认证测试")
    else:
        await test_websocket_with_auth(DEVICE_ID, DEVICE_SECRET)
    
    print("=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
