import json
import base64
import asyncio
import time
import websockets
from django.conf import settings
from channels.generic.websocket import AsyncWebsocketConsumer
from .utils import check_limit_exceeded, add_usage

class ChatBotConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.device = self.scope.get("device")
        
        # Verify device token and handshake existed
        if not self.device:
            await self.accept()
            await self.close(code=4001)  # 4001 is a custom code indicating unauthorized
            return
            
        # Check Daily limit
        try:
            if check_limit_exceeded(self.device.device_id):
                await self.accept()
                await self.close(code=4002) # Daily limit exceeded
                return
        except Exception as e:
            print(f"Redis check failed, allowing connection bypass: {e}")

        # Accept the connection
        await self.accept()
        
        # Track usage
        self.session_start_time = time.time()
        
        # Establish Qwen connection
        self.qwen_ws = None
        self._interrupted = False  # 打断标志：过滤旧回答的残余音频
        self._queue = asyncio.Queue()  # 流控发送队列
        self.sender_task = asyncio.create_task(self.sender_loop())  # 启动流控发送任务
        self.qwen_task = asyncio.create_task(self.connect_to_qwen())
        
        # 启动心跳保活任务
        self._keepalive_task = asyncio.create_task(self.keepalive_loop())

    async def connect_to_qwen(self):
        """与 Qwen 建立连接，断开后自动重连，不关闭 Django WebSocket"""
        api_key = getattr(settings, "DASHSCOPE_API_KEY", "")
        url = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=qwen3.5-omni-realtime"
        headers = {"Authorization": f"Bearer {api_key}"}

        while True:  # 断线自动重连循环
            try:
                async with websockets.connect(
                    url,
                    additional_headers=headers,
                    ping_interval=10,   # 每 10 秒 ping 一次，减少空闲断连
                    ping_timeout=10     # 10 秒内收不到 pong 则主动断开重连
                ) as ws:
                    self.qwen_ws = ws
                    print(f"[{self.device.device_id}] Connected to Qwen Omni API")

                    # Configure session for Manual mode
                    await ws.send(json.dumps({
                        "type": "session.update",
                        "event_id": f"event_{int(time.time() * 1000)}",
                        "session": {
                            "modalities": ["text", "audio"],
                            "turn_detection": None,
                            "input_audio_format": "pcm16",#输入音频的格式，固定为pcm16。
                            "output_audio_format": "pcm24",#输出音频的格式，固定为pcm24。
                            "voice": "Cherry",
                            "input_audio_transcription": {
                                "model": "gummy-realtime-v1"
                            },
                            "instructions": "你是个人助理，请简明扼要地解答用户的问题。"
                        }
                    }))

                    # Listen endlessly for Aliyun chunks
                    async for message in ws:
                        await self.handle_qwen_message(message)

            except Exception as e:
                print(f"[{self.device.device_id}] Qwen disconnected: {e}, reconnecting in 2s...")
                self.qwen_ws = None
                self._interrupted = True  # 重连期间过滤残余事件

            # 检查 Django WebSocket 是否还活着，若已关闭则退出重连循环
            try:
                if self.channel_layer is None and not hasattr(self, 'channel_name'):
                    break
            except Exception:
                break

            await asyncio.sleep(2)  # 等待 2 秒后重连

    async def handle_qwen_message(self, message):
        data = json.loads(message)
        event_type = data.get("type")

        if event_type == "response.created":
            # 新回答开始，解除打断过滤
            self._interrupted = False
            # 清空之前可能的滞留消息
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

        elif event_type == "response.audio.delta":
            if self._interrupted:
                return  # 丢弃打断后 Qwen 推来的残余音频
            audio_bytes = base64.b64decode(data["delta"])
            
            # 使用较小的 chunk 放入队列，方便细粒度限速和打断响应
            CHUNK_SIZE = 2400  # 约 50ms (2400 bytes)
            for i in range(0, len(audio_bytes), CHUNK_SIZE):
                chunk = audio_bytes[i:i+CHUNK_SIZE]
                self._queue.put_nowait({"type": "audio", "data": chunk})

        elif event_type == "response.audio_transcript.delta":
            if self._interrupted:
                return  # 同样丢弃残余文字
            self._queue.put_nowait({"type": "text", "data": data["delta"]})

        elif event_type == "error":
            print(f"[Qwen] Error returned: {data}")

    async def keepalive_loop(self):
        """每30秒发送一次心跳，保持连接活跃"""
        try:
            while True:
                await asyncio.sleep(30)
                try:
                    # 发送一个心跳消息
                    await self.send(text_data=json.dumps({
                        "action": "ping",
                        "timestamp": int(time.time())
                    }))
                except Exception as e:
                    print(f"[{self.device.device_id}] Keepalive failed: {e}")
                    break
        except asyncio.CancelledError:
            pass

    async def sender_loop(self):
        """流控循环：控制发送给 ESP32 的速率，防止客户端 OOM"""
        try:
            while True:
                item = await self._queue.get()
                if self._interrupted:
                    continue
                
                if item["type"] == "audio":
                    chunk = item["data"]
                    try:
                        await self.send(bytes_data=chunk)
                    except Exception:
                        break # 连接断开，退出循环
                    
                    # 流控计算: 服务端发送 24kHz, 16-bit 单声道 = 48000 bytes/sec
                    # 使用 0.95 倍真实播放时长，稍微提前发以构建安全 buffer 但不撑爆 ESP32 内存
                    sleep_time = (len(chunk) / 48000.0) * 0.95
                    await asyncio.sleep(sleep_time)

                elif item["type"] == "text":
                    try:
                        await self.send(text_data=json.dumps({
                            "action": "transcript",
                            "text": item["data"]
                        }))
                    except Exception:
                        break
        except asyncio.CancelledError:
            pass

    async def disconnect(self, close_code):
        if hasattr(self, 'session_start_time'):
            duration = time.time() - self.session_start_time
            add_usage(self.device.device_id, duration)
            print(f"[{self.device.device_id}] Disconnected. Duration: {duration}s added.")
        
        # 取消心跳任务
        if hasattr(self, '_keepalive_task'):
            self._keepalive_task.cancel()
            
        # 取消发送流控任务
        if hasattr(self, 'sender_task'):
            self.sender_task.cancel()
            
        if hasattr(self, 'qwen_task'):
            self.qwen_task.cancel()
        if hasattr(self, 'qwen_ws') and self.qwen_ws:
            await self.qwen_ws.close()

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            try:
                data = json.loads(text_data)
                action = data.get("action")
                
                if action == "stop_speaking":
                    if self.qwen_ws:
                        # Once button is released, flush buffer and generate response in manual mode
                        await self.qwen_ws.send(json.dumps({
                            "type": "input_audio_buffer.commit",
                            "event_id": f"event_{int(time.time() * 1000)}_c"
                        }))
                        await self.qwen_ws.send(json.dumps({
                            "type": "response.create",
                            "event_id": f"event_{int(time.time() * 1000)}_r"
                        }))
                
                elif action == "interrupt":
                    if self.qwen_ws:
                        # 标记打断，后续残余音频将被丢弃
                        self._interrupted = True
                        # 清空下发队列
                        while not self._queue.empty():
                            try:
                                self._queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                        # 取消当前回答生成
                        await self.qwen_ws.send(json.dumps({
                            "type": "response.cancel",
                            "event_id": f"event_{int(time.time() * 1000)}_cancel"
                        }))
                        # 同时清空输入缓冲区，避免旧音频污染新回答
                        await self.qwen_ws.send(json.dumps({
                            "type": "input_audio_buffer.clear",
                            "event_id": f"event_{int(time.time() * 1000)}_clr"
                        }))
            except json.JSONDecodeError:
                pass
                
        if bytes_data:
            # Append audio buffers block-by-block while device button is held
            if self.qwen_ws:
                audio_b64 = base64.b64encode(bytes_data).decode('ascii')
                try:
                    await self.qwen_ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "event_id": f"event_{int(time.time() * 1000)}_a",
                        "audio": audio_b64
                    }))
                except websockets.exceptions.ConnectionClosed:
                    pass
