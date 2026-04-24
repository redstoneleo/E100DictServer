#!/usr/bin/env python3
"""
E600 服务器测试客户端
基于 simulator.py 的简化版本，专门用于测试 e600.feing.com.cn 服务器
"""
import asyncio
import json
import ssl
import hmac
import hashlib
import secrets
import urllib.request
from urllib.parse import urlencode, urlparse
import websockets
import time

# ============================================
# 配置区域 - 根据实际情况修改
# ============================================
SERVER_HOST = "e600.feing.com.cn"
DEVICE_ID = "FA1-202603-000123"  # 替换为实际的设备 ID
DEVICE_SECRET = "381570a6a34e98ea6183687f0932ed938436323be216bab360f9ac2376c2edbe"  # 替换为实际的密钥

# 自动推导的 URL
HTTP_BASE = f"https://{SERVER_HOST}"
WS_BASE = f"wss://{SERVER_HOST}"


class E600TestClient:
    """E600 服务器测试客户端"""
    
    def __init__(self, device_id: str, device_secret: str):
        self.device_id = device_id
        self.device_secret = device_secret
        self.ws = None
        self.ws_url = None
        
    def _post_json(self, url: str, payload: dict, timeout: int = 10) -> dict:
        """发送 JSON POST 请求"""
        print(f"[POST] {url}")
        print(f"[DATA] {json.dumps(payload, indent=2)}")
        
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url=url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        
        # 创建 SSL 上下文
        ctx = ssl.create_default_context()
        
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body) if body else {}
                print(f"[RESP] {resp.status} - {json.dumps(result, indent=2)}")
                return result
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            print(f"[ERROR] HTTP {e.code}: {error_body}")
            raise RuntimeError(f"POST {url} failed: HTTP {e.code}") from e
        except Exception as e:
            print(f"[ERROR] {type(e).__name__}: {e}")
            raise RuntimeError(f"POST {url} failed: {type(e).__name__}: {e}") from e
    
    def _hmac_sign(self, nonce: str) -> str:
        """计算 HMAC-SHA256 签名"""
        return hmac.new(
            self.device_secret.encode("utf-8"),
            nonce.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    
    def get_auth_credentials(self):
        """
        获取 WebSocket 连接所需的认证凭证
        流程：
        1. 请求 /device/challenge/ 获取 nonce_token
        2. 用 device_secret 签名 nonce_token
        3. 请求 /device/token/ 获取 access_token
        4. 再次请求 /device/challenge/ 获取 nonce_ws
        5. 用 device_secret 签名 nonce_ws
        6. 构造 WebSocket URL
        """
        print("\n" + "="*60)
        print("开始认证流程")
        print("="*60)
        
        try:
            # 步骤 1: 获取 nonce_token
            print("\n[步骤 1] 获取 nonce_token...")
            nonce_token = self._post_json(
                f"{HTTP_BASE}/device/challenge/",
                {"device_id": self.device_id}
            ).get("nonce")
            
            if not nonce_token:
                raise RuntimeError("device/challenge 未返回 nonce")
            print(f"[成功] nonce_token: {nonce_token[:20]}...")
            
            # 步骤 2: 签名 nonce_token
            print("\n[步骤 2] 签名 nonce_token...")
            sig_token = self._hmac_sign(nonce_token)
            print(f"[成功] signature: {sig_token[:20]}...")
            
            # 步骤 3: 获取 access_token
            print("\n[步骤 3] 获取 access_token...")
            token_resp = self._post_json(
                f"{HTTP_BASE}/device/token/",
                {"device_id": self.device_id, "signature": sig_token}
            )
            access_token = token_resp.get("access")
            
            if not access_token:
                raise RuntimeError("device/token 未返回 access token")
            print(f"[成功] access_token: {access_token[:30]}...")
            
            # 步骤 4: 获取 nonce_ws
            print("\n[步骤 4] 获取 nonce_ws...")
            nonce_ws = self._post_json(
                f"{HTTP_BASE}/device/challenge/",
                {"device_id": self.device_id}
            ).get("nonce")
            
            if not nonce_ws:
                raise RuntimeError("device/challenge 未返回 nonce for ws")
            print(f"[成功] nonce_ws: {nonce_ws[:20]}...")
            
            # 步骤 5: 签名 nonce_ws
            print("\n[步骤 5] 签名 nonce_ws...")
            sign_ws = self._hmac_sign(nonce_ws)
            print(f"[成功] sign_ws: {sign_ws[:20]}...")
            
            # 步骤 6: 构造 WebSocket URL
            print("\n[步骤 6] 构造 WebSocket URL...")
            qs = urlencode({
                "token": access_token,
                "nonce": nonce_ws,
                "sign": sign_ws
            })
            self.ws_url = f"{WS_BASE}/ws/chatbot/?{qs}"
            print(f"[成功] ws_url: {self.ws_url[:80]}...")
            
            print("\n" + "="*60)
            print("认证流程完成")
            print("="*60 + "\n")
            
        except Exception as e:
            self.ws_url = None
            print(f"\n[失败] 认证失败: {type(e).__name__}: {e}")
            raise
    
    async def connect_websocket(self):
        """连接到 WebSocket 服务器"""
        if not self.ws_url:
            raise RuntimeError("ws_url 未配置，请先调用 get_auth_credentials()")
        
        print("\n" + "="*60)
        print("连接 WebSocket")
        print("="*60)
        print(f"[连接] {self.ws_url[:80]}...")
        
        try:
            ssl_ctx = ssl.create_default_context()
            self.ws = await websockets.connect(
                self.ws_url,
                ssl=ssl_ctx,
                open_timeout=10,
                ping_interval=20,
                ping_timeout=10
            )
            print("[成功] WebSocket 连接成功！")
            return True
        except Exception as e:
            self.ws = None
            print(f"[失败] 连接失败: {type(e).__name__}: {e}")
            return False
    
    async def send_text_message(self, action: str, **kwargs):
        """发送文本消息"""
        if not self.ws:
            print("[错误] WebSocket 未连接")
            return False
        
        try:
            msg = {"action": action, **kwargs}
            await self.ws.send(json.dumps(msg))
            print(f"[发送] {msg}")
            return True
        except Exception as e:
            print(f"[错误] 发送失败: {type(e).__name__}: {e}")
            return False
    
    async def send_audio_chunk(self, audio_data: bytes):
        """发送音频数据"""
        if not self.ws:
            print("[错误] WebSocket 未连接")
            return False
        
        try:
            await self.ws.send(audio_data)
            return True
        except Exception as e:
            print(f"[错误] 发送音频失败: {type(e).__name__}: {e}")
            return False
    
    async def receive_messages(self, duration: float = 5.0):
        """接收消息（指定时长）"""
        if not self.ws:
            print("[错误] WebSocket 未连接")
            return
        
        print(f"\n[接收] 监听消息 {duration} 秒...")
        start_time = time.time()
        message_count = 0
        audio_count = 0
        
        try:
            while time.time() - start_time < duration:
                try:
                    msg = await asyncio.wait_for(self.ws.recv(), timeout=1.0)
                    message_count += 1
                    
                    if isinstance(msg, bytes):
                        audio_count += 1
                        print(f"[音频] 收到音频数据: {len(msg)} 字节")
                    else:
                        try:
                            data = json.loads(msg)
                            print(f"[文本] {json.dumps(data, ensure_ascii=False)}")
                        except json.JSONDecodeError:
                            print(f"[文本] {msg}")
                            
                except asyncio.TimeoutError:
                    continue
                    
        except websockets.exceptions.ConnectionClosed as e:
            print(f"[断开] 连接已关闭: code={e.code}, reason={e.reason}")
        except Exception as e:
            print(f"[错误] {type(e).__name__}: {e}")
        
        print(f"\n[统计] 共收到 {message_count} 条消息 (文本: {message_count - audio_count}, 音频: {audio_count})")
    
    async def close(self):
        """关闭连接"""
        if self.ws:
            await self.ws.close()
            print("[关闭] WebSocket 连接已关闭")


async def test_basic_connection():
    """测试 1: 基本连接测试"""
    print("\n" + "="*60)
    print("测试 1: 基本连接测试")
    print("="*60)
    
    client = E600TestClient(DEVICE_ID, DEVICE_SECRET)
    
    try:
        # 获取认证凭证
        client.get_auth_credentials()
        
        # 连接 WebSocket
        if await client.connect_websocket():
            # 发送测试消息
            await client.send_text_message("interrupt")
            
            # 接收响应
            await client.receive_messages(duration=3.0)
            
    except Exception as e:
        print(f"\n[测试失败] {type(e).__name__}: {e}")
    finally:
        await client.close()


async def test_audio_simulation():
    """测试 2: 模拟音频交互"""
    print("\n" + "="*60)
    print("测试 2: 模拟音频交互")
    print("="*60)
    
    client = E600TestClient(DEVICE_ID, DEVICE_SECRET)
    
    try:
        # 获取认证凭证并连接
        client.get_auth_credentials()
        if not await client.connect_websocket():
            return
        
        # 模拟发送音频数据（静音数据）
        print("\n[模拟] 发送 10 个音频块...")
        chunk_size = 800  # 50ms @ 16kHz
        silent_audio = b'\x00' * (chunk_size * 2)  # 16-bit PCM
        
        for i in range(10):
            await client.send_audio_chunk(silent_audio)
            await asyncio.sleep(0.05)  # 50ms
            if (i + 1) % 5 == 0:
                print(f"[进度] 已发送 {i + 1}/10 个音频块")
        
        # 发送停止说话信号
        print("\n[信号] 发送 stop_speaking...")
        await client.send_text_message("stop_speaking")
        
        # 等待 AI 响应
        print("\n[等待] 等待 AI 响应...")
        await client.receive_messages(duration=10.0)
        
    except Exception as e:
        print(f"\n[测试失败] {type(e).__name__}: {e}")
    finally:
        await client.close()


async def test_interrupt():
    """测试 3: 中断测试"""
    print("\n" + "="*60)
    print("测试 3: 中断测试")
    print("="*60)
    
    client = E600TestClient(DEVICE_ID, DEVICE_SECRET)
    
    try:
        client.get_auth_credentials()
        if not await client.connect_websocket():
            return
        
        # 发送中断信号
        print("\n[测试] 发送 interrupt 信号...")
        await client.send_text_message("interrupt")
        
        # 接收响应
        await client.receive_messages(duration=2.0)
        
    except Exception as e:
        print(f"\n[测试失败] {type(e).__name__}: {e}")
    finally:
        await client.close()


async def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("E600 服务器测试客户端")
    print("="*60)
    print(f"服务器: {SERVER_HOST}")
    print(f"设备 ID: {DEVICE_ID}")
    print(f"HTTP Base: {HTTP_BASE}")
    print(f"WS Base: {WS_BASE}")
    print("="*60)
    
    # 检查配置
    if DEVICE_SECRET == "your_device_secret_here":
        print("\n[错误] 请在脚本中配置实际的 DEVICE_ID 和 DEVICE_SECRET")
        return
    
    # 运行测试
    tests = [
        ("基本连接测试", test_basic_connection),
        ("音频交互测试", test_audio_simulation),
        ("中断测试", test_interrupt),
    ]
    
    for i, (name, test_func) in enumerate(tests, 1):
        try:
            await test_func()
        except KeyboardInterrupt:
            print("\n\n[中断] 用户取消测试")
            break
        except Exception as e:
            print(f"\n[异常] 测试 {name} 出现未捕获异常: {e}")
        
        # 测试间隔
        if i < len(tests):
            print("\n" + "-"*60)
            await asyncio.sleep(2)
    
    print("\n" + "="*60)
    print("所有测试完成")
    print("="*60 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n程序已退出")
