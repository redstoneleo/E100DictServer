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
import os
import logging
from django.conf import settings
from channels.generic.websocket import AsyncWebsocketConsumer
from .utils import check_limit_exceeded, add_usage
from urllib.parse import parse_qs

logger = logging.getLogger('chatbot')

_brtc_session = None

# Token 缓存：key=(device_id, lang, asr_mode) → {"inst_id": ..., "token": ..., "expire_at": float}
# 每个 token 缓存 4 分钟（百度 token 有效期通常 5 分钟，留 1 分钟余量）
_brtc_token_cache: dict = {}
_BRTC_TOKEN_TTL = 240  # seconds

# 设备连接代次：key=device_id → int，每次新 WebSocket 连接递增
# 用于使旧消费者的 connect_to_brtc 重连循环和预取任务自动退出
_device_generation: dict = {}

async def _get_brtc_session():
    global _brtc_session
    if _brtc_session is None or _brtc_session.closed:
        connector = aiohttp.TCPConnector(limit=100, keepalive_timeout=3600)
        _brtc_session = aiohttp.ClientSession(connector=connector)
    return _brtc_session

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
        logger.info(f"[{self.device.device_id}] WebSocket connected. backend={getattr(settings, 'CHATBOT_BACKEND', 'QWEN')}, lang={self.lang}, asr_mode={self.asr_mode}")
        
        # Establish Connection
        self.qwen_ws = None
        self.brtc_ws = None
        self._interrupted = False  # 打断标志：过滤旧回答的残余音频
        self._response_active = False  # 是否有 AI 回答正在进行
        self._queue = asyncio.Queue()  # 流控发送队列
        self.sender_task = asyncio.create_task(self.sender_loop())  # 启动流控发送任务
        self._current_voice_buf = bytearray()
        
        self.backend = getattr(settings, "CHATBOT_BACKEND", "QWEN")
        
        # 立即下发 audio_config，准许客户端立即发送语音
        sample_rate = 16000 if self.backend == "BRTC" else 24000
        await self.send(text_data=json.dumps({
            "action": "audio_config",
            "sample_rate": sample_rate
        }))
        
        self.upstream_audio_buffer = bytearray()
        self.pending_stop_speaking = False

        if self.backend == "BRTC":
            self.is_brtc_recording = False
            self.brtc_tts_ready = False
            # 递增设备代次，使旧消费者的 connect_to_brtc 重连循环自动退出
            dev_id = self.device.device_id
            _device_generation[dev_id] = _device_generation.get(dev_id, 0) + 1
            self._connect_gen = _device_generation[dev_id]
            logger.info(f"[{dev_id}] connect() gen={self._connect_gen}, lang={self.lang}")
            self.backend_task = asyncio.create_task(self.connect_to_brtc())
        else:
            self.backend_task = asyncio.create_task(self.connect_to_qwen())
            
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
                    logger.info(f"[{self.device.device_id}] Connected to Qwen Omni API")

                    # Configure session for Manual mode
                    await ws.send(json.dumps({
                        "type": "session.update",
                        "event_id": f"event_{int(time.time() * 1000)}",
                        "session": {
                            "modalities": ["text", "audio"],
                            "turn_detection": None,
                            "input_audio_format": "pcm16",
                            "output_audio_format": "pcm24",
                            "voice": "Cherry",
                            "input_audio_transcription": {
                                "model": "gummy-realtime-v1"
                            },
                            "instructions": "你是个人助理，请用和用户语言相同的语种极其极其简短地回答用户的问题。"
                        }
                    }))
                    
                    # 检查是否有未发送的积压录音
                    if hasattr(self, 'upstream_audio_buffer') and self.upstream_audio_buffer:
                        audio_b64 = base64.b64encode(self.upstream_audio_buffer).decode('ascii')
                        await ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "event_id": f"event_{int(time.time() * 1000)}_flush",
                            "audio": audio_b64
                        }))
                        self.upstream_audio_buffer = bytearray()
                        
                        if getattr(self, "pending_stop_speaking", False):
                            await ws.send(json.dumps({
                                "type": "input_audio_buffer.commit",
                                "event_id": f"event_{int(time.time() * 1000)}_c"
                            }))
                            await ws.send(json.dumps({
                                "type": "response.create",
                                "event_id": f"event_{int(time.time() * 1000)}_r"
                            }))
                            self.pending_stop_speaking = False

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
            # 记录从 stop_speaking 到 AI 开始响应的延迟
            if hasattr(self, '_stop_speaking_time') and self._stop_speaking_time:
                latency = time.time() - self._stop_speaking_time
                logger.info(f"[{self.device.device_id}] [LATENCY] stop_speaking → response.created: {latency:.3f}s")
                self._stop_speaking_time = None
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
            
            # 记录首包音频到达时间
            if not getattr(self, '_first_audio_logged', False):
                self._first_audio_logged = True
                if hasattr(self, '_response_created_time') and self._response_created_time:
                    latency = time.time() - self._response_created_time
                    logger.info(f"[{self.device.device_id}] [LATENCY] response.created → first audio delta: {latency:.3f}s")
                if hasattr(self, '_stop_speaking_time_ref') and self._stop_speaking_time_ref:
                    total = time.time() - self._stop_speaking_time_ref
                    logger.info(f"[{self.device.device_id}] [LATENCY] stop_speaking → first audio: {total:.3f}s (total TTFA)")
            
            # 使用较小的 chunk 放入队列，方便细粒度限速和打断响应
            CHUNK_SIZE = 2400  # 约 50ms (2400 bytes)
            for i in range(0, len(audio_bytes), CHUNK_SIZE):
                chunk = audio_bytes[i:i+CHUNK_SIZE]
                self._queue.put_nowait({"type": "audio", "data": chunk})

        elif event_type == "response.audio_transcript.delta":
            if self._interrupted:
                return  # 同样丢弃残余文字
            self._queue.put_nowait({"type": "text", "data": data["delta"]})

        elif event_type == "conversation.item.input_audio_transcription.completed":
            # 用户语音识别结果
            transcript = data.get("transcript", "")
            if transcript:
                logger.info(f"[{self.device.device_id}] [ASR] User said: {transcript!r}")

        elif event_type in ("response.done", "response.cancelled"):
            self._response_active = False
            self._first_audio_logged = False
            self._response_created_time = None
            self._stop_speaking_time_ref = None

        elif event_type == "error":
            logger.error(f"[{self.device.device_id}] [Qwen] Error returned: {data}")

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

    def _brtc_cache_key(self):
        return (
            self.device.device_id,
            getattr(self, 'lang', ''),
            getattr(self, 'asr_mode', '')
        )

    async def _generate_brtc_token(self, app_id, ak, sk):
        """调用 generateAIAgentCall 动态传入 lang 和 asr_mode，获取实例 ID 和 token。
        
        优先使用缓存（TTL 内），避免每次重连都发起 REST 请求。
        """
        cache_key = self._brtc_cache_key()
        cached = _brtc_token_cache.get(cache_key)
        if cached and time.time() < cached["expire_at"]:
            print(f"[{self.device.device_id}] Using cached BRTC token (expires in "
                  f"{cached['expire_at'] - time.time():.0f}s)")
            return cached["inst_id"], cached["token"]

        return await self._fetch_brtc_token(app_id, ak, sk)

    @staticmethod
    def _fix_brtc_overflow(data: bytes, device_id: str = "") -> bytes:
        """修复 BRTC 韩语 TTS 引擎的 int16 溢出 bug。

        根因：百度 BRTC 韩语 TTS 的 float→int16 转换不钳位，
        当 float > 1.0 时直接 cast 导致正溢出回绕为负值（符号位翻转），
        例如 float 1.5 → uint16 49152 → int16 -16384。
        回绕的样本与相邻样本产生巨大跳变（>30000），听起来就是滋滋声。

        修复策略（两遍处理）：
        1. 检测相邻样本间异常大的跳变（>JUMP_THRESHOLD），
           尝试翻转符号解释（正溢出→还原为正值，负溢出→还原为负值），
           选择跳变更小的那个，然后钳位到 [-32768, 32767]。
        2. 平滑处理钳位区域：当溢出样本被钳位到极值（±32767）时，
           用前后正常样本的加权平均值替代，避免与相邻样本产生假跳跃。
        """
        n = len(data) // 2
        if n == 0:
            return data

        JUMP_THRESHOLD = 25000  # 降低阈值以捕获更多溢出样本
        SMOOTH_WINDOW = 5       # 平滑窗口大小

        # 第一遍：溢出修复
        samples = [0] * n
        fix_count = 0
        prev = 0

        for i in range(n):
            offset = i * 2
            # 小端序读取为无符号
            uv = data[offset] | (data[offset + 1] << 8)
            # 当前有符号解释
            sv = (uv - 0x10000) if uv >= 0x8000 else uv

            # 检测与前一个样本的跳变
            jump = abs(sv - prev)
            if jump > JUMP_THRESHOLD:
                # 尝试翻转符号：如果 uv >= 0x8000（当前解释为负），
                # 翻转为正（uv 本身）；否则翻转为负（uv - 0x10000）
                alt = uv if uv >= 0x8000 else (uv - 0x10000)
                # 钳位备选值
                if alt > 32767:
                    alt = 32767
                elif alt < -32768:
                    alt = -32768
                alt_jump = abs(alt - prev)
                if alt_jump < jump:
                    sv = alt
                    fix_count += 1

            # 最终钳位（安全网）
            if sv > 32767:
                sv = 32767
            elif sv < -32768:
                sv = -32768
            samples[i] = sv
            prev = sv

        # 第二遍：平滑处理钳位区域（被钳位到极值的样本用邻域平均值替代）
        smoothed = 0
        for i in range(n):
            if abs(samples[i]) >= 32700:  # 被钳位到极值附近
                left_vals = []
                right_vals = []
                # 向左找非钳位样本
                for j in range(i - 1, max(i - SMOOTH_WINDOW - 1, -1), -1):
                    if abs(samples[j]) < 30000:
                        left_vals.append(samples[j])
                        if len(left_vals) >= 3:
                            break
                # 向右找非钳位样本
                for j in range(i + 1, min(i + SMOOTH_WINDOW + 1, n)):
                    if abs(samples[j]) < 30000:
                        right_vals.append(samples[j])
                        if len(right_vals) >= 3:
                            break

                if left_vals and right_vals:
                    # 用左右非钳位样本的加权平均值替代
                    left_avg = sum(left_vals) / len(left_vals)
                    right_avg = sum(right_vals) / len(right_vals)
                    left_w = 1.0 / (len(left_vals) + 1)
                    right_w = 1.0 / (len(right_vals) + 1)
                    samples[i] = int((left_avg * left_w + right_avg * right_w) / (left_w + right_w))
                    smoothed += 1

        # 写回小端序
        out = bytearray(len(data))
        for i in range(n):
            offset = i * 2
            sv = samples[i]
            uo = (sv + 0x10000) if sv < 0 else sv
            out[offset] = uo & 0xFF
            out[offset + 1] = (uo >> 8) & 0xFF

        # 奇数长度防御
        if len(data) % 2:
            out[-1] = data[-1]

        logger.info(f"[{device_id}] _fix_brtc_overflow: fixed {fix_count}/{n} samples, smoothed {smoothed}")
        return bytes(out)

    def _get_brtc_config(self):
        """构造大模型互动实例配置对象"""
        config_dict = {
            "audiocodec": "raw16k",
            "dfda": True,  # 启用 Digital Full-Duplex Audio
            "asr_vad_level": getattr(settings, "BRTC_ASR_VAD_LEVEL", 45)  # 人声检测灵敏度，默认 45
        }

        # TTS参数：vol 必须放在 tts_url 子参数中（文档：tts_url中支持的参数配置）
        # 顶层 config 不支持 vol，需嵌套在 "DEFAULT{...}" 格式的 tts_url 内
        vol = 0.3 if getattr(self, 'lang', '') == 'ko' else 1.0  # 韩语降低音量以避免溢出
        tts_url_params = {"vol": vol, "spd": 1.0}
        config_dict["tts"] = "DEFAULT"
        config_dict["tts_url"] = "DEFAULT" + json.dumps(tts_url_params)
            
        config_dict["cloud_3A_url"] = {
            "ANS": {
                "enable": True,
                "preMode": "VH",
                "midGainDb": 0,
                "dfLimitDb": 10
            },
            "AGC": {
                "enable": False,  # 关闭 AGC，避免与 TTS vol 叠加导致削波
                "maxVolume": 60,
                "extraGain": 0
            }
        }
        if getattr(self, 'lang', None):
            config_dict["lang"] = self.lang
        if getattr(self, 'asr_mode', None):
            config_dict["asr_mode"] = self.asr_mode
        config_dict["user_id"] = self.device.device_id
        logger.info(f"[{self.device.device_id}] BRTC config: lang={self.lang}, asr_mode={self.asr_mode}")
            
        return config_dict

    async def _fetch_brtc_token(self, app_id, ak, sk):
        """实际发起 REST 请求获取新 token，并写入缓存。"""
        start_time = time.time()
        host = "rtc-aiagent.baidubce.com"
        path = "/api/v1/aiagent/generateAIAgentCall"
        
        config_dict = self._get_brtc_config()
        print(f"[{self.device.device_id}] BRTC REST API config: {json.dumps(config_dict, ensure_ascii=False)}")
        
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
        session = await _get_brtc_session()
        try:
            async with session.post(url, headers=headers, data=payload_bytes) as resp:
                resp_text = await resp.text()
                duration = time.time() - start_time
                if resp.status == 200:
                    data = json.loads(resp_text)
                    inst_id = data.get("ai_agent_instance_id")
                    token = data.get("context", {}).get("token")
                    # 写入缓存
                    _brtc_token_cache[self._brtc_cache_key()] = {
                        "inst_id": inst_id,
                        "token": token,
                        "expire_at": time.time() + _BRTC_TOKEN_TTL
                    }
                    logger.info(f"[{self.device.device_id}] [LATENCY] Fetched new BRTC token in {duration:.3f}s")
                    return inst_id, token
                else:
                    logger.warning(f"[{self.device.device_id}] BCE request failed ({resp.status}) in {duration:.3f}s")
                    raise Exception(f"BCE request failed via code {resp.status}: {resp_text}")
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[{self.device.device_id}] BCE request error in {duration:.3f}s: {e}")
            raise

    async def _prefetch_brtc_token(self, app_id, ak, sk):
        """在后台静默预取下一个 token，不抛异常（失败时下次连接再重试）。"""
        try:
            # 强制绕过缓存，提前刷新
            await self._fetch_brtc_token(app_id, ak, sk)
            print(f"[{self.device.device_id}] BRTC token prefetched successfully")
        except Exception as e:
            print(f"[{self.device.device_id}] BRTC token prefetch failed (non-fatal): {e}")

    async def connect_to_brtc(self):
        """与 Baidu RTC 建立连接。支持两种方式：
        1. 方式一：服务端 API 获取 Token (安全性高，lang 参数通过 REST API 传递)
        2. 方式二：AK/SK 直接建连 (建连速度快，但 WebSocket 网关可能不解析 config 中的 lang)
        """
        app_id = getattr(settings, "BRTC_APP_ID", "")
        ak = getattr(settings, "BRTC_AK", "")
        sk = getattr(settings, "BRTC_SK", "")
        method = getattr(settings, "BRTC_CONNECTION_METHOD", 1)
        my_gen = getattr(self, '_connect_gen', 0)

        while True:
            # 代次检查：若已有更新的消费者接管，立即退出
            current_gen = _device_generation.get(self.device.device_id, 0)
            if my_gen != current_gen:
                print(f"[{self.device.device_id}] connect_to_brtc gen={my_gen} stale (current={current_gen}), exiting")
                return

            try:
                ws_start = time.time()
                token_duration = 0
                if method == 2:
                    # 每次重连都重新计算 URL，确保 lang 变更生效
                    config_json = json.dumps(self._get_brtc_config())
                    config_b64 = base64.b64encode(config_json.encode('utf-8')).decode('ascii')
                    url = f"wss://rtc-aiotgw.exp.bcelive.com/v1/realtime?a={app_id}&ak={ak}&sk={sk}&ac=raw16k&c={config_b64}"
                    print(f"[{self.device.device_id}] Connecting via Method 2 (AK/SK), lang={self.lang}, gen={my_gen}...")
                else:
                    print(f"[{self.device.device_id}] Fetching BRTC token via Method 1 (lang={self.lang}, gen={my_gen})...")
                    token_start = time.time()
                    inst_id, token = await self._generate_brtc_token(app_id, ak, sk)
                    token_duration = time.time() - token_start
                    url = f"wss://rtc-aiotgw.exp.bcelive.com/v1/realtime?a={app_id}&id={inst_id}&t={token}&ac=raw16k"
                    print(f"[{self.device.device_id}] Token setup: {token_duration:.2f}s")

                async with websockets.connect(
                    url,
                    ping_interval=10,
                    ping_timeout=10,
                    compression=None # 原始 PCM 不需要压缩，禁用以减少延迟和 CPU
                ) as ws:
                    ws_duration = time.time() - ws_start
                    self.brtc_ws = ws
                    print(f"[{self.device.device_id}] Connected to BRTC Omni API (gen={my_gen}). Total: {ws_duration:.2f}s (Token: {token_duration:.2f}s)")

                    # 连接成功后，在后台提前刷新 token，为下次断线重连做准备
                    # 使用 TTL 的一半时间后触发，确保重连时缓存仍有效
                    # 捕获当前代次，确保预取不会在旧连接上执行
                    async def _delayed_prefetch(gen=my_gen):
                        await asyncio.sleep(_BRTC_TOKEN_TTL / 2)
                        if _device_generation.get(self.device.device_id, 0) != gen:
                            print(f"[{self.device.device_id}] Prefetch skipped: gen={gen} stale")
                            return
                        await self._prefetch_brtc_token(app_id, ak, sk)
                    asyncio.create_task(_delayed_prefetch())

                    async for message in ws:
                        await self.handle_brtc_message(message)

            except Exception as e:
                print(f"[{self.device.device_id}] BRTC disconnected (gen={my_gen}): {e}, reconnecting in 2s...")
                self.brtc_ws = None
                self._interrupted = True
                # 连接断开时使缓存失效，下次重连强制获取新 token
                _brtc_token_cache.pop(self._brtc_cache_key(), None)

            # 代次检查（重连前）
            if _device_generation.get(self.device.device_id, 0) != my_gen:
                print(f"[{self.device.device_id}] connect_to_brtc gen={my_gen} stale after disconnect, exiting")
                return

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
                dev_id = self.device.device_id if hasattr(self, 'device') and self.device else "unknown"
                active_msg = f'[E]:[LIC]:[ACTIVE]:{{"devId":"{dev_id}","uId":"{dev_id}","licKey":"{lic}"}}'
                await self.brtc_ws.send(active_msg)
                await self.brtc_ws.send('[E]:[CMD]:[ASR_DISABLE_REALTIME]')
                
                if hasattr(self, 'upstream_audio_buffer') and self.upstream_audio_buffer:
                    if not getattr(self, "is_brtc_recording", False):
                        await self.brtc_ws.send('[E]:[CMD]:[ASR_START_LONGTEXT_REC]')
                        self.is_brtc_recording = True
                        
                    await self.brtc_ws.send(self.upstream_audio_buffer)
                    self.upstream_audio_buffer = bytearray()
                    
                    if getattr(self, "pending_stop_speaking", False):
                        await self.brtc_ws.send('[E]:[CMD]:[ASR_STOP_LONGTEXT_REC]')
                        self.is_brtc_recording = False
                        self.pending_stop_speaking = False
            
            elif message.startswith("[Q]:") and not message.startswith("[Q]:[M]:"):
                text = message[4:]
                logger.info(f"[{self.device.device_id}] [ASR] User said: {text!r}")
                self._queue.put_nowait({"type": "text", "data": text})
            
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
            
            # DEBUG: 保存 BRTC 原始音频字节，用于排查韩语滋滋声问题
            if not hasattr(self, '_brtc_raw_fh'):
                import datetime as _dt
                ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
                fname = os.path.join(settings.BASE_DIR, f"debug_brtc_raw_{self.lang or 'default'}_{self.device.device_id}_{ts}.pcm")
                self._brtc_raw_fh = open(fname, "wb")
                self._brtc_raw_count = 0
                self._brtc_raw_bytes = 0
                logger.info(f"[{self.device.device_id}] Saving BRTC raw audio to: {fname}")
            self._brtc_raw_fh.write(message)
            self._brtc_raw_count += 1
            self._brtc_raw_bytes += len(message)
            if self._brtc_raw_count <= 5 or self._brtc_raw_count % 50 == 0:
                logger.info(f"[{self.device.device_id}] BRTC raw msg #{self._brtc_raw_count}: {len(message)}B, "
                           f"total {self._brtc_raw_bytes}B ({self._brtc_raw_bytes/32000:.1f}s)")
            
            # WORKAROUND: 百度 BRTC 韩语 TTS 引擎 bug — float→int16 转换溢出，
            # 正溢出回绕为负值导致滋滋声。此处检测并修复溢出样本。
            if getattr(self, 'lang', '') == 'ko':
                message = self._fix_brtc_overflow(message, self.device.device_id)
            
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
                            "role": item.get("role", "ai"),
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
        
        # 主动清除 BRTC token 缓存，防止新消费者复用旧 BRTC 实例的 token
        if hasattr(self, 'device') and self.device:
            _brtc_token_cache.pop(self._brtc_cache_key(), None)
        
        # 关闭 BRTC 原始音频调试文件
        if hasattr(self, '_brtc_raw_fh') and self._brtc_raw_fh:
            self._brtc_raw_fh.close()
            logger.info(f"[{self.device.device_id}] BRTC raw audio saved: "
                       f"{self._brtc_raw_count} msgs, {self._brtc_raw_bytes}B")
        
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

    def _save_voice_log(self, voice_data):
        if not voice_data:
            return
        log_dir = os.path.join(settings.BASE_DIR, 'logs', 'voices')
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.datetime.now()
        timestamp_str = timestamp.strftime('%Y%m%d_%H%M%S_%f')
        device_id = self.device.device_id if hasattr(self, 'device') and self.device else "unknown"
        filename = f"{timestamp_str}_{device_id}.pcm"
        filepath = os.path.join(log_dir, filename)
        
        try:
            with open(filepath, 'wb') as f:
                f.write(voice_data)
            
            log_file = os.path.join(log_dir, 'voice_metadata.txt')
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] Device: {device_id}, Audio Length: {len(voice_data)} bytes\n")
                
            files = [os.path.join(log_dir, f) for f in os.listdir(log_dir) if f.endswith('.pcm')]
            files.sort(key=os.path.getmtime)
            while len(files) > 20:
                oldest = files.pop(0)
                try:
                    os.remove(oldest)
                except Exception:
                    pass
        except Exception as e:
            print(f"Failed to record voice log: {e}")

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            try:
                data = json.loads(text_data)
                action = data.get("action")
                
                if action == "stop_speaking":
                    if hasattr(self, '_current_voice_buf') and self._current_voice_buf:
                        self._save_voice_log(self._current_voice_buf)
                        self._current_voice_buf = bytearray()

                    if getattr(self, "backend", "QWEN") == "QWEN":
                        if getattr(self, "qwen_ws", None):
                            # Once button is released, flush buffer and generate response in manual mode
                            await self.qwen_ws.send(json.dumps({
                                "type": "input_audio_buffer.commit",
                                "event_id": f"event_{int(time.time() * 1000)}_c"
                            }))
                            await self.qwen_ws.send(json.dumps({
                                "type": "response.create",
                                "event_id": f"event_{int(time.time() * 1000)}_r"
                            }))
                        else:
                            self.pending_stop_speaking = True
                            
                    elif getattr(self, "backend", "QWEN") == "BRTC":
                        if getattr(self, "brtc_ws", None):
                            await self.brtc_ws.send('[E]:[CMD]:[ASR_STOP_LONGTEXT_REC]')
                            self.is_brtc_recording = False
                        else:
                            self.pending_stop_speaking = True
                
                elif action == "interrupt":
                    if hasattr(self, '_current_voice_buf') and self._current_voice_buf:
                        self._save_voice_log(self._current_voice_buf)
                        self._current_voice_buf = bytearray()

                    # 处于连接中断期间直接清空离线缓存
                    if not getattr(self, "qwen_ws" if getattr(self, "backend", "QWEN") == "QWEN" else "brtc_ws", None):
                        self.upstream_audio_buffer = bytearray()
                        self.pending_stop_speaking = False

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
                    elif getattr(self, "backend", "QWEN") == "BRTC" and getattr(self, "brtc_ws", None):
                        if getattr(self, "is_brtc_recording", False):
                            await self.brtc_ws.send('[E]:[CMD]:[ASR_STOP_LONGTEXT_REC]')
                        self.is_brtc_recording = False
            except json.JSONDecodeError:
                pass
                
        if bytes_data:
            if hasattr(self, '_current_voice_buf'):
                self._current_voice_buf.extend(bytes_data)

            # Append audio buffers block-by-block while device button is held
            if getattr(self, "backend", "QWEN") == "QWEN":
                ws = getattr(self, "qwen_ws", None)
                if ws:
                    audio_b64 = base64.b64encode(bytes_data).decode('ascii')
                    try:
                        await ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "event_id": f"event_{int(time.time() * 1000)}_a",
                            "audio": audio_b64
                        }))
                    except websockets.exceptions.ConnectionClosed:
                        pass
                else:
                    if not hasattr(self, 'upstream_audio_buffer'):
                        self.upstream_audio_buffer = bytearray()
                    self.upstream_audio_buffer.extend(bytes_data)
                    
            elif getattr(self, "backend", "QWEN") == "BRTC":
                ws = getattr(self, "brtc_ws", None)
                if ws:
                    try:
                        if getattr(self, "is_brtc_recording", False) == False:
                            await ws.send('[E]:[CMD]:[ASR_START_LONGTEXT_REC]')
                            self.is_brtc_recording = True
                        await ws.send(bytes_data)
                    except websockets.exceptions.ConnectionClosed:
                        pass
                else:
                    if not hasattr(self, 'upstream_audio_buffer'):
                        self.upstream_audio_buffer = bytearray()
                    self.upstream_audio_buffer.extend(bytes_data)
