import json
import base64
import asyncio
import time
import websockets
import hmac
import hashlib
import urllib.parse
import datetime
import aiohttp
from django.conf import settings
from channels.generic.websocket import AsyncWebsocketConsumer
from .utils import check_limit_exceeded, add_usage
from urllib.parse import parse_qs

class ChatBotConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.device = self.scope.get("device")
        
        # 解析 lang 参数
        query_string = self.scope.get("query_string", b"").decode("utf-8")
        qs = parse_qs(query_string)
        self.lang = qs.get("lang", [""])[0]
        self.asr_mode = qs.get("asr_mode", [""])[0]
        
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
        
        # Establish Connection
        self.qwen_ws = None
        self.brtc_ws = None
        self._interrupted = False  # 打断标志：过滤旧回答的残余音频
        self._response_active = False  # 是否有 AI 回答正在进行
        self._queue = asyncio.Queue()  # 流控发送队列
        self.sender_task = asyncio.create_task(self.sender_loop())  # 启动流控发送任务
        
        self.backend = getattr(settings, "CHATBOT_BACKEND", "QWEN")
        if self.backend == "BRTC":
            self.is_brtc_recording = False
            self.brtc_tts_ready = False  # BRTC连接建立后会先发送 8-byte心跳包，达到 TTS_BEGIN_SPEAKING 调度才找到周期内的更大 chunks
            self.backend_task = asyncio.create_task(self.connect_to_brtc())
        else:
            self.backend_task = asyncio.create_task(self.connect_to_qwen())
            
        # 注意：audio_config 会在后端（Qwen/BRTC）真正连接成功后发送，不在这里发送
        
        # 启动心跳保活任务
        self._keepalive_task = asyncio.create_task(self.keepalive_loop())

    async def connect_to_qwen(self):
        """与 Qwen 建立连接，断开后自动重连，不关闭 Django WebSocket"""
        api_key = getattr(settings, "DASHSCOPE_API_KEY", "")
        url = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=qwen3-omni-flash-realtime"
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
                            "instructions": "你是个人助理，请用和用户语言相同的语种极其极其简短地回答用户的问题。"
                        }
                    }))
                    
                    # Qwen 后端已就绪，通知客户端
                    await self.send(text_data=json.dumps({
                        "action": "audio_config",
                        "sample_rate": 24000
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
            self._response_active = True
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

        elif event_type in ("response.done", "response.cancelled"):
            self._response_active = False

        elif event_type == "error":
            print(f"[Qwen] Error returned: {data}")

    def _get_bce_auth(self, ak, sk, method, path, headers):
        timestamp = datetime.datetime.now(datetime.UTC)
        date_str = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        headers["x-bce-date"] = date_str
        auth_string_prefix = f"bce-auth-v1/{ak}/{date_str}/1800"
        
        signing_key = hmac.new(
            sk.encode('utf-8'),
            auth_string_prefix.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        canonical_uri = urllib.parse.quote(path.encode('utf-8'), safe='~-_./')
        
        signed_headers = []
        canonical_headers = []
        for k in sorted(headers.keys()):
            k_lower = k.lower()
            if k_lower in ('host', 'content-type', 'content-md5', 'content-length') or k_lower.startswith('x-bce-'):
                signed_headers.append(k_lower)
                val_encoded = urllib.parse.quote(headers[k].encode('utf-8'), safe='~-_.')
                k_encoded = urllib.parse.quote(k_lower.encode('utf-8'), safe='~-_.')
                canonical_headers.append(f"{k_encoded}:{val_encoded}")
                
        canonical_request = f"{method}\n{canonical_uri}\n\n{chr(10).join(canonical_headers)}"
        
        signature = hmac.new(
            signing_key.encode('utf-8'),
            canonical_request.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return f"{auth_string_prefix}/{';'.join(signed_headers)}/{signature}"

    async def _generate_brtc_token(self, app_id, ak, sk):
        """调用 generateAIAgentCall 动态传入 lang 和 asr_mode，获取实例 ID 和 token"""
        host = "rtc-aiagent.baidubce.com"
        path = "/api/v1/aiagent/generateAIAgentCall"
        
        config_dict = {
            "audiocodec": "raw16k"
        }
        if getattr(self, 'lang', None):
            config_dict["lang"] = self.lang
        if getattr(self, 'asr_mode', None):
            config_dict["asr_mode"] = self.asr_mode
        config_dict["user_id"] = self.device.device_id
            
        payload = {
            "app_id": app_id,
            "config": json.dumps(config_dict)
        }
        payload_bytes = json.dumps(payload).encode('utf-8')
        
        headers = {
            "host": host,
            "content-type": "application/json"
        }
        
        auth_header = self._get_bce_auth(ak, sk, "POST", path, headers)
        headers["Authorization"] = auth_header
        
        url = f"https://{host}{path}"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=payload_bytes) as resp:
                resp_text = await resp.text()
                if resp.status == 200:
                    data = json.loads(resp_text)
                    inst_id = data.get("ai_agent_instance_id")
                    token = data.get("context", {}).get("token")
                    return inst_id, token
                else:
                    raise Exception(f"BCE request failed via code {resp.status}: {resp_text}")

    async def connect_to_brtc(self):
        """与 Baidu RTC 建立连接，先生成实例获取 Token，再连 WebSocket 断开后重连"""
        app_id = getattr(settings, "BRTC_APP_ID", "")
        ak = getattr(settings, "BRTC_AK", "")
        sk = getattr(settings, "BRTC_SK", "")

        while True:
            try:
                print(f"[{self.device.device_id}] Fetching BRTC token mapping config (lang={getattr(self, 'lang', 'N/A')})...")
                inst_id, token = await self._generate_brtc_token(app_id, ak, sk)
                url = f"wss://rtc-aiotgw.exp.bcelive.com/v1/realtime?a={app_id}&id={inst_id}&t={token}&ac=raw16k"
                
                async with websockets.connect(
                    url,
                    ping_interval=10,
                    ping_timeout=10
                ) as ws:
                    self.brtc_ws = ws
                    print(f"[{self.device.device_id}] Connected to BRTC Omni API")
                    
                    # BRTC 后端已就绪，通知客户端
                    await self.send(text_data=json.dumps({
                        "action": "audio_config",
                        "sample_rate": 16000
                    }))

                    async for message in ws:
                        await self.handle_brtc_message(message)

            except Exception as e:
                print(f"[{self.device.device_id}] BRTC disconnected: {e}, reconnecting in 2s...")
                self.brtc_ws = None
                self._interrupted = True

            try:
                if self.channel_layer is None and not hasattr(self, 'channel_name'):
                    break
            except Exception:
                break
            await asyncio.sleep(2)

    async def handle_brtc_message(self, message):
        if isinstance(message, str):
            if message.startswith("[E]:[LIC]:[MUST]"):
                lic = getattr(settings, "BRTC_LIC_KEY", "")
                dev_id = self.device.device_id
                active_msg = f'[E]:[LIC]:[ACTIVE]:{{"devId":"{dev_id}","uId":"{dev_id}","licKey":"{lic}"}}'
                await self.brtc_ws.send(active_msg)
                await self.brtc_ws.send('[E]:[CMD]:[ASR_DISABLE_REALTIME]')
            
            elif message.startswith("[Q]:") and not message.startswith("[Q]:[M]:"):
                self._queue.put_nowait({"type": "text", "data": message[4:]})
            
            elif message.startswith('[E]:[TTS_BEGIN_SPEAKING]'):
                self.brtc_tts_ready = True
                self._interrupted = False
                self._response_active = True
                while not self._queue.empty():
                    try:
                        self._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                        
            elif message.startswith('[E]:[TTS_END_SPEAKING]') or message.startswith('[E]:[AGENTID]'):
                self.brtc_tts_ready = False
                self._response_active = False
                        
        elif isinstance(message, bytes):
            # 心跳包过滤：BRTC 的保活心跳仅为 8 字节，真实 TTS 音频包通常 ≥ 320 字节
            # 按大小过滤比按状态机过滤更可靠，也能覆盖没有 TTS_BEGIN_SPEAKING 的边界场景
            if len(message) < 64:
                return  # 八字节心跳/保活包，直接丢弃
            if self._interrupted:
                return
            CHUNK_SIZE = 1600 # 32000 bytes/sec * 0.05 sec
            for i in range(0, len(message), CHUNK_SIZE):
                chunk = message[i:i+CHUNK_SIZE]
                self._queue.put_nowait({"type": "audio", "data": chunk})

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
                    
                    # 流控计算: Qwen发送 24kHz = 48000 bytes/sec, BRTC发送 16kHz = 32000 bytes/sec (16-bit单声道)
                    # 使用 0.95 倍真实播放时长，稍微提前发以构建安全 buffer 但不撑爆 ESP32 内存
                    bytes_per_sec = 48000.0 if getattr(self, "backend", "QWEN") == "QWEN" else 32000.0
                    sleep_time = (len(chunk) / bytes_per_sec) * 0.95
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
            
        if hasattr(self, 'backend_task'):
            self.backend_task.cancel()
        elif hasattr(self, 'qwen_task'): # fallback
            self.qwen_task.cancel()
            
        if hasattr(self, 'qwen_ws') and self.qwen_ws:
            await self.qwen_ws.close()
        if hasattr(self, 'brtc_ws') and self.brtc_ws:
            await self.brtc_ws.close()

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            try:
                data = json.loads(text_data)
                action = data.get("action")
                
                if action == "stop_speaking":
                    if getattr(self, "backend", "QWEN") == "QWEN" and getattr(self, "qwen_ws", None):
                        # Once button is released, flush buffer and generate response in manual mode
                        await self.qwen_ws.send(json.dumps({
                            "type": "input_audio_buffer.commit",
                            "event_id": f"event_{int(time.time() * 1000)}_c"
                        }))
                        await self.qwen_ws.send(json.dumps({
                            "type": "response.create",
                            "event_id": f"event_{int(time.time() * 1000)}_r"
                        }))
                    elif getattr(self, "backend", "QWEN") == "BRTC" and getattr(self, "brtc_ws", None):
                        await self.brtc_ws.send('[E]:[CMD]:[ASR_STOP_LONGTEXT_REC]')
                        self.is_brtc_recording = False
                
                elif action == "interrupt":
                    # 只在有 AI 回答正在进行时才打断，避免误设 _interrupted 导致后续回复被丢弃
                    if not self._response_active:
                        # 没有正在进行的回答，只清空输入缓冲区即可
                        if getattr(self, "backend", "QWEN") == "QWEN" and getattr(self, "qwen_ws", None):
                            await self.qwen_ws.send(json.dumps({
                                "type": "input_audio_buffer.clear",
                                "event_id": f"event_{int(time.time() * 1000)}_clr"
                            }))
                        return

                    # 有回答正在进行：标记打断，清空队列，取消生成
                    self._interrupted = True
                    self._response_active = False
                    while not self._queue.empty():
                        try:
                            self._queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                            
                    if getattr(self, "backend", "QWEN") == "QWEN" and getattr(self, "qwen_ws", None):
                        await self.qwen_ws.send(json.dumps({
                            "type": "response.cancel",
                            "event_id": f"event_{int(time.time() * 1000)}_cancel"
                        }))
                        await self.qwen_ws.send(json.dumps({
                            "type": "input_audio_buffer.clear",
                            "event_id": f"event_{int(time.time() * 1000)}_clr"
                        }))
                    elif getattr(self, "backend", "QWEN") == "BRTC":
                        self.is_brtc_recording = False
            except json.JSONDecodeError:
                pass
                
        if bytes_data:
            # Append audio buffers block-by-block while device button is held
            if getattr(self, "backend", "QWEN") == "QWEN" and getattr(self, "qwen_ws", None):
                audio_b64 = base64.b64encode(bytes_data).decode('ascii')
                try:
                    await self.qwen_ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "event_id": f"event_{int(time.time() * 1000)}_a",
                        "audio": audio_b64
                    }))
                except websockets.exceptions.ConnectionClosed:
                    pass
            elif getattr(self, "backend", "QWEN") == "BRTC" and getattr(self, "brtc_ws", None):
                try:
                    if getattr(self, "is_brtc_recording", False) == False:
                        await self.brtc_ws.send('[E]:[CMD]:[ASR_START_LONGTEXT_REC]')
                        self.is_brtc_recording = True
                    await self.brtc_ws.send(bytes_data)
                except websockets.exceptions.ConnectionClosed:
                    pass
