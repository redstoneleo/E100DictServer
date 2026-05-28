import sys
import os
import asyncio
import json
import base64
import time
import secrets
import hmac
import hashlib
import ssl
import urllib.request
from urllib.parse import urlencode, urlparse
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout,
                              QHBoxLayout, QWidget, QTextEdit, QLabel, QComboBox)
from PyQt6.QtCore import QThread, pyqtSignal, QObject, Qt
from PyQt6.QtGui import QFont, QTextCursor, QColor
import threading
import queue
import pyaudio
import websockets

#####################################
# AUDIO GLOBALS
#####################################
CHUNK = 800   # 50ms at 16kHz
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000        # 录音/上行采样率（16kHz）
OUT_RATE = 16000    # 播放/下行采样率（BRTC 输出为 16kHz，Qwen 为 24kHz 由 audio_config 动态切换）

#####################################
# 服务器配置
#####################################
SERVER_CONFIGS = {
    "local": {
        "name": "本地服务器",
        "host": "127.0.0.1:8000",
        "http_scheme": "http",
        "ws_scheme": "ws",
        "device_id": "FA1-202603-000123",
        "device_secret": "381570a6a34e98ea6183687f0932ed938436323be216bab360f9ac2376c2edbe"
    },
    "e600": {
        "name": "E600 服务器",
        "host": "e600.feing.com.cn",
        "http_scheme": "https",
        "ws_scheme": "wss",
        "device_id": "FA1-202603-000123",
        "device_secret": "381570a6a34e98ea6183687f0932ed938436323be216bab360f9ac2376c2edbe"
    }
}


# ---------------------------------------------------------------------------
# 语言选项（在主界面下拉框中显示）
# 格式：(显示名称, lang_param)，lang_param 对应 Query String 里的 lang 及额外参数
# ---------------------------------------------------------------------------
LANG_OPTIONS = [
    # ── 中英混合（默认） ──────────────────────────────────────────────────────
    ("── 中英混合场景 ──",       None),          # 分组标题，不可选
    ("默认（不传 lang，偏中文）", ""),
    ("中文  lang=zh（偏中文）",   "zh"),
    ("英语  lang=en（偏英文）",   "en"),
    # ── 方言 ─────────────────────────────────────────────────────────────────
    ("── 方言场景 ──",            None),
    ("广东话  lang=zh_yue",       "zh_yue"),
    ("四川话  lang=zh_sc",        "zh_sc"),
    ("苏州话  lang=zh_su",        "zh_su"),
    # ── 纯外语 ───────────────────────────────────────────────────────────────
    ("── 纯外语场景 ──",          None),
    ("日语    lang=ja",            "ja"),
    ("西班牙语 lang=es",           "es"),
    ("俄语    lang=ru",            "ru"),
    ("韩语    lang=ko",            "ko"),
    ("越南语  lang=vi",            "vi"),
    ("德语    lang=de",            "de"),
    ("阿拉伯语 lang=ar",           "ar"),
    ("印尼语  lang=id",            "id"),
    ("泰语    lang=th",            "th"),
    ("马来语  lang=ms",            "ms"),
    ("葡萄牙语 lang=pt",           "pt"),
    ("乌兹别克语 lang=uz",         "uz"),
    ("波兰语  lang=pl",            "pl"),
    ("波斯语  lang=fa",            "fa"),
]


class AudioController(QObject):
    transcript_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    user_text_signal = pyqtSignal(str)  # 用户说的话
    ai_text_signal = pyqtSignal(str)    # AI说的话

    def __init__(self, server_type="local", lang_type=""):
        super().__init__()
        self.server_type = server_type
        self.lang_type = lang_type   # 可在运行时通过 update_lang() 修改
        self.server_config = SERVER_CONFIGS[server_type]
        
        self.p = pyaudio.PyAudio()
        self.ws = None
        self.is_recording = False
        self.ws_url = None
        self._init_error = None
        self._current_user_text = ""
        self._current_ai_text = ""
        self._backend_ready = threading.Event()  # 收到 audio_config 时置位，表示后端已就绪

        # Guard: 防止重复启动录音协程
        self._recording_guard = False
        # 后台重连中标志：防止并发重连
        self._reconnecting = False
        self._pending_reconnect = False
        # 主动关闭标志：语言切换时主动关闭连接，listen_for_messages 不应自动重连
        self._intentional_close = False
        self._switch_pending = False
        self._desired_connection_seq = 0
        self._ws_url_seq = 0
        self._active_connection_seq = 0
        self._ptt_pressed = False

        # 流只创建一次，不在 PTT 期间关闭
        self.in_stream = None   # 录音流（懒加载）
        self.out_stream = None  # 播放流（懒加载）
        self.out_rate_current = OUT_RATE # 默认播放采样率

        # 播放专用队列 + 线程
        self._audio_queue = queue.Queue()
        self._playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self._playback_thread.start()

        self._cache_file = os.path.join(os.path.dirname(__file__), ".simulator_cache.json")
        self.get_auth_credentials()

    def _post_json(self, url: str, payload: dict, timeout: int = 10) -> dict:
        """发送 JSON POST 请求 (优化：禁用系统代理探测以加速本地连接)"""
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url=url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        parsed = urlparse(url)
        # 核心优化：显式指定不使用代理，避免 Windows 下 urllib 的代理搜索延迟
        proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_handler)

        try:
            with opener.open(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except Exception as e:
            raise RuntimeError(f"POST {url} failed: {type(e).__name__}: {e}") from e

    def _ensure_out_stream(self):
        if not self.out_stream:
            try:
                self.out_stream = self.p.open(
                    format=FORMAT, channels=CHANNELS,
                    rate=self.out_rate_current, output=True
                )
            except Exception as e:
                print(f"Failed to open output stream: {e}")
        return self.out_stream

    def _ensure_in_stream(self):
        if not self.in_stream:
            try:
                self.in_stream = self.p.open(
                    format=FORMAT, channels=CHANNELS,
                    rate=RATE, input=True, frames_per_buffer=CHUNK
                )
            except Exception as e:
                print(f"Failed to open mic: {e}")
        return self.in_stream

    def _close_all_streams(self):
        """仅在程序退出时调用"""
        if self.in_stream:
            try:
                self.in_stream.stop_stream()
                self.in_stream.close()
            except Exception:
                pass
            self.in_stream = None
        if self.out_stream:
            try:
                self.out_stream.stop_stream()
                self.out_stream.close()
            except Exception:
                pass
            self.out_stream = None

    def _set_out_rate(self, rate):
        """动态修改回放采样率（如果发生变化则重建流）"""
        if self.out_rate_current != rate:
            self.out_rate_current = rate
            if self.out_stream:
                try:
                    self.out_stream.stop_stream()
                    self.out_stream.close()
                except Exception:
                    pass
                self.out_stream = None

    def _playback_worker(self):
        """独立线程：持续从队列取音频块并播放"""
        while True:
            try:
                audio_bytes = self._audio_queue.get(timeout=0.05)
                if audio_bytes is None:   # 哨兵值，退出线程
                    break
                if self.is_recording:     # 录音期间丢弃残余音频
                    continue
                stream = self._ensure_out_stream()
                if stream:
                    try:
                        stream.write(audio_bytes)
                    except OSError as e:
                        print(f"Audio playback error: {e}")
            except queue.Empty:
                pass

    def update_lang(self, new_lang_type: str):
        """在主界面切换语言时调用：立即在后台重认证并重连，
        确保用户按下 PTT 时新连接已就绪，避免第一次 PTT 无响应。"""
        self.lang_type = new_lang_type
        self._mark_connection_dirty()
        self._schedule_reconnect()    # 后台立即触发重连

    def update_server(self, new_server_type: str):
        """在主界面切换服务器时调用：更新服务器配置并立即后台重连"""
        self.server_type = new_server_type
        self.server_config = SERVER_CONFIGS[new_server_type]
        self._mark_connection_dirty()
        self._schedule_reconnect()    # 后台立即触发重连

    def _mark_connection_dirty(self):
        self._desired_connection_seq += 1
        self._switch_pending = True
        self._backend_ready.clear()

    def _schedule_reconnect(self):
        """在 AsyncWorker 的事件循环中调度后台重连任务（非阻塞）"""
        if self._reconnecting:
            self._pending_reconnect = True
            return
        loop = self._get_loop()
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(self._background_reconnect(), loop)

    async def _background_reconnect(self):
        """后台任务：重新认证、关闭旧连接、建立新连接并等待后端就绪。
        在 update_lang / update_server 后立即执行，与 PTT 无关。"""
        # 防止并发重连
        if getattr(self, '_reconnecting', False):
            self._pending_reconnect = True
            return
        self._reconnecting = True
        try:
            self.status_signal.emit("🔄 正在切换，重新连接中...")

            # 1. 后台重新认证（5 次 HTTP，耗时 1-3s，不阻塞事件循环）
            await asyncio.to_thread(self.get_auth_credentials)
            if self._init_error:
                self.status_signal.emit(f"❌ 认证失败: {self._init_error}")
                return

            # 2. 关闭旧连接（如果有）
            if self.ws:
                try:
                    self._intentional_close = True
                    await self.ws.close()
                except Exception:
                    self._intentional_close = False
                self.ws = None

            # 3. 建立新连接
            await self.connect_websocket()
            if not self.ws:
                self.status_signal.emit("❌ 重连失败，请重试")
                return

            # 4. 等待后端就绪（audio_config），超时后继续（允许录音）
            is_local = (self.server_config.get("ws_scheme", "ws") == "ws")
            backend_timeout = 10.0 if is_local else 15.0
            if not self._backend_ready.is_set():
                if await self._wait_for_backend_ready(backend_timeout):
                    self.status_signal.emit("✅ 已就绪，可以说话")
                else:
                    self.status_signal.emit("⚠️ 后端就绪超时，仍可尝试说话")
            else:
                self.status_signal.emit("✅ 已就绪，可以说话")
        finally:
            self._reconnecting = False
            if self._active_connection_seq == self._desired_connection_seq:
                self._switch_pending = False
            if self._pending_reconnect:
                self._pending_reconnect = False
                self._schedule_reconnect()

    def _get_loop(self):
        """获取异步事件循环（由 AsyncWorker 持有）"""
        return getattr(self, '_loop', None)

    def _needs_fresh_connection(self):
        return (
            self._switch_pending
            or self._active_connection_seq != self._desired_connection_seq
        )

    async def _wait_for_fresh_connection(self, timeout: float = 20.0, cancel_on_release: bool = True) -> bool:
        elapsed = 0.0
        reconnect_requested = False
        while self._needs_fresh_connection():
            if cancel_on_release and not self._ptt_pressed:
                self.status_signal.emit("ℹ️ 已取消本次说话")
                return False
            if self._reconnecting:
                reconnect_requested = False
            elif not reconnect_requested:
                self._schedule_reconnect()
                reconnect_requested = True
            await asyncio.sleep(0.1)
            elapsed += 0.1
            if elapsed >= timeout:
                self.status_signal.emit("⚠️ 等待切换完成超时，请重试")
                return False
        return True

    async def _wait_for_backend_ready(self, timeout: float, cancel_on_release: bool = False) -> bool:
        elapsed = 0.0
        while not self._backend_ready.is_set():
            if cancel_on_release and not self._ptt_pressed:
                self.status_signal.emit("ℹ️ 已取消本次说话")
                return False
            await asyncio.sleep(0.1)
            elapsed += 0.1
            if elapsed >= timeout:
                return False
        return True

    async def _interrupt_if_possible(self):
        if not self.ws:
            return
        try:
            await self.ws.send(json.dumps({"action": "interrupt"}))
        except websockets.exceptions.ConnectionClosed:
            self.ws = None

    async def _ensure_connection_ready_for_upload(self) -> bool:
        if self._needs_fresh_connection() or self._reconnecting:
            self.status_signal.emit("⏳ 等待切换完成，准备发送录音...")
            if not await self._wait_for_fresh_connection(cancel_on_release=False):
                return False

        if not self.ws:
            self.status_signal.emit("🔄 正在连接服务器，准备发送录音...")
            await self.connect_websocket()
            if not self.ws:
                self.status_signal.emit("❌ 无法连接到服务器，本次录音未发送")
                return False

        is_local = (self.server_config.get("ws_scheme", "ws") == "ws")
        backend_timeout = 10.0 if is_local else 15.0
        if not self._backend_ready.is_set():
            self.status_signal.emit("⏳ 等待后端就绪，准备发送录音...")
            if not await self._wait_for_backend_ready(backend_timeout):
                self.status_signal.emit("❌ 后端未就绪，本次录音未发送")
                return False

        await self._interrupt_if_possible()
        return self.ws is not None

    def _load_cache(self):
        """尝试从本地文件加载有效的认证缓存"""
        if not os.path.exists(self._cache_file):
            return None
        try:
            with open(self._cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                # 检查缓存是否属于当前服务器且未过期 (缓存效期 1 小时)
                if (cache_data.get("server_host") == self.server_config["host"] and
                    cache_data.get("server_type") == self.server_type and
                    time.time() - cache_data.get("timestamp", 0) < 3600):
                    return cache_data
        except Exception:
            pass
        return None

    def _save_cache(self, access_token):
        """仅保存 access_token 到本地"""
        try:
            cache_data = {
                "access_token": access_token,
                "server_host": self.server_config["host"],
                "server_type": self.server_type,
                "timestamp": time.time()
            }
            with open(self._cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f)
        except Exception as e:
            print(f"[缓存] 保存失败: {e}")

    def get_auth_credentials(self):
        """获取认证凭证 (Token 尝试使用缓存，Nonce 始终获取最新的)"""
        start_time = time.time()
        self._init_error = None
        access_token = None

        # 1. 尝试从缓存读取 access_token
        cached = self._load_cache()
        if cached:
            access_token = cached.get("access_token")
            print(f"[认证] 发现本地有效 Token，跳过 Token 申请步骤。")

        try:
            config = self.server_config
            device_id = config["device_id"]
            device_secret = config["device_secret"]
            http_base = f"{config['http_scheme']}://{config['host']}"
            ws_base = f"{config['ws_scheme']}://{config['host']}"

            # 2. 如果没有缓存 Token，则执行步骤 1-3 获取它
            if not access_token:
                print(f"[配置] 服务器: {config['name']} ({config['host']})")
                print(f"[配置] 设备 ID: {device_id}")

                # 1) 获取 nonce_token
                t1 = time.time()
                print("[认证] 步骤 1/5: 获取 nonce_token...")
                nonce_token = self._post_json(f"{http_base}/device/challenge/", {"device_id": device_id}).get("nonce")
                if not nonce_token: raise RuntimeError("device/challenge 未返回 nonce")
                t2 = time.time()
                print(f"[认证] 获得 nonce_token (耗时: {t2-t1:.2f}s)")

                # 2) 签名 nonce_token
                sig_token = hmac.new(device_secret.encode("utf-8"), nonce_token.encode("utf-8"), hashlib.sha256).hexdigest()

                # 3) 获取 access_token
                t3 = time.time()
                print("[认证] 步骤 3/5: 获取 access_token...")
                token_resp = self._post_json(f"{http_base}/device/token/", {"device_id": device_id, "signature": sig_token})
                access_token = token_resp.get("access")
                if not access_token: raise RuntimeError("device/token 未返回 access token")
                t4 = time.time()
                print(f"[认证] 获得 access_token (耗时: {t4-t3:.2f}s)")
                
                # 存入缓存
                self._save_cache(access_token)

            # 3. 始终执行步骤 4-5 获取新鲜的 WebSocket Nonce
            t5 = time.time()
            print("[认证] 步骤 4/5: 获取新鲜 WebSokect nonce_ws...")
            nonce_ws = self._post_json(f"{http_base}/device/challenge/", {"device_id": device_id}).get("nonce")
            if not nonce_ws: raise RuntimeError("device/challenge 未返回 nonce for ws")
            t6 = time.time()
            print(f"[认证] 获得 nonce_ws (耗时: {t6-t5:.2f}s)")

            print("[认证] 步骤 5/5: 签名 nonce_ws...")
            sign_ws = hmac.new(device_secret.encode("utf-8"), nonce_ws.encode("utf-8"), hashlib.sha256).hexdigest()

            # 4. 构造 WebSocket URL
            params = {"token": access_token, "nonce": nonce_ws, "sign": sign_ws}
            if self.lang_type:
                params["lang"] = self.lang_type
            qs = urlencode(params)
            self.ws_url = f"{ws_base}/ws/chatbot/?{qs}"
            self._ws_url_seq = self._desired_connection_seq
            print(f"[认证] 全流程成功！总耗时: {time.time()-start_time:.2f}s")
            
        except Exception as e:
            self.ws_url = None
            self._ws_url_seq = 0
            self._init_error = f"{type(e).__name__}: {e}"
            print(f"[错误] 认证失败: {self._init_error} (总耗时: {time.time()-start_time:.2f}s)")
            # 如果认证失败（可能是 Token 过期），尝试删除缓存
            if os.path.exists(self._cache_file):
                os.remove(self._cache_file)
            
        except Exception as e:
            self.ws_url = None
            self._ws_url_seq = 0
            self._init_error = f"{type(e).__name__}: {e}"
            print(f"[错误] 认证失败: {self._init_error} (总耗时: {time.time()-start_time:.2f}s)")

    async def connect_websocket(self):
        if self._init_error:
            self.status_signal.emit(f"❌ 认证失败: {self._init_error}")
            return
        if not self.ws_url:
            self.status_signal.emit("❌ 未配置 ws_url")
            return

        start_time = time.time()
        server_name = self.server_config["name"]
        status_text = f"正在连接到 {server_name}..."
        self.status_signal.emit(status_text)
        try:
            # 根据服务器类型决定是否使用 SSL
            ssl_ctx = ssl.create_default_context() if self.server_config["ws_scheme"] == "wss" else None
            self._backend_ready.clear()  # 新连接，后端尚未就绪（即便 update_lang 已 clear，此处再 clear 一次保险）
            print(f"[网络] 正在建立 WebSocket 连接: {self.ws_url[:60]}...")
            
            # 核心优化：强制使用 IPv4 (family=2)，避免某些环境下 IPv6 优先探测导致的数秒延迟
            # 同时适当调小 open_timeout
            import socket
            self.ws = await websockets.connect(
                self.ws_url,
                ssl=ssl_ctx,
                open_timeout=5,
                ping_interval=30,    # 每30秒发送心跳
                ping_timeout=10,     # 10秒内没收到pong则断开
                close_timeout=10,
                family=socket.AF_INET
            )
            self._active_connection_seq = self._ws_url_seq
            duration = time.time() - start_time
            print(f"[网络] WebSocket 已连接，耗时: {duration:.2f}s")
            self.status_signal.emit(f"✅ 已连接到 {server_name} (握手: {duration:.2f}s)")
            asyncio.create_task(self.listen_for_messages())
        except Exception as e:
            self.ws = None
            self.status_signal.emit(f"❌ 连接失败: {type(e).__name__}: {e}")
            print(f"[错误] WebSocket 连接失败: {e}")

    async def listen_for_messages(self):
        """监听服务器消息，断线后自动重连"""
        try:
            async for message in self.ws:
                if isinstance(message, bytes):
                    self.play_audio(message)
                else:
                    try:
                        data = json.loads(message)
                        action = data.get("action")
                        
                        # 忽略心跳消息
                        if action == "ping":
                            continue
                            
                        if action == "audio_config":
                            rate = data.get("sample_rate", 24000)
                            self._set_out_rate(rate)
                            self._backend_ready.set()  # 后端已就绪
                            print(f"[业务] 收到 audio_config，后端已就绪 (sample_rate: {rate})")
                            
                        if action == "transcript":
                            text = data.get("text", "")
                            # 判断是用户的文本还是AI的文本
                            if data.get("role") == "user":
                                self._current_user_text += text
                                self.user_text_signal.emit(text)
                            else:
                                # 默认是AI的文本
                                self._current_ai_text += text
                                self.ai_text_signal.emit(text)
                    except Exception:
                        pass
        except websockets.exceptions.ConnectionClosed as e:
            self.ws = None
            print(f"WebSocket 连接断开: {e}")
            # 主动关闭（语言切换）时不自动重连，由 start_recording 负责重连
            if self._intentional_close:
                self._intentional_close = False
                return
            self.status_signal.emit("🔄 连接断开，等待重连...")
            # 自动重连（延迟3秒）
            await asyncio.sleep(3)
            await self.connect_websocket()
        except Exception as e:
            self.ws = None
            err_msg = f"{type(e).__name__}: {e}"
            self.status_signal.emit(f"❌ 连接错误: {err_msg}")
            print(f"[错误] 监听消息时出错: {err_msg}")
            
            # 如果收到 4001 错误，说明 Token 或 Nonce 失效，清除缓存
            if "4001" in str(e):
                print("[系统] 检测到授权失效(4001)，准备重新获取认证...")
                if os.path.exists(self._cache_file):
                    os.remove(self._cache_file)
                self.get_auth_credentials()

    def play_audio(self, audio_bytes):
        """将音频块放入队列"""
        if not self.is_recording:
            self._audio_queue.put(audio_bytes)

    def stop_playing_audio(self):
        """立即丢弃队列中所有待播放音频"""
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

    async def start_recording(self):
        # 防止重入
        if self._recording_guard:
            return
        self._recording_guard = True

        try:
            self._ptt_pressed = True
            self.is_recording = True
            self.stop_playing_audio()
            has_sent_audio = False
            buffered_audio = []
            buffer_only_mode = self._needs_fresh_connection() or self._reconnecting
            
            # 重置用户文本累积
            self._current_user_text = ""

            # 确保录音流已就绪
            if not self._ensure_in_stream():
                self.status_signal.emit("❌ 麦克风错误")
                return

            if buffer_only_mode:
                self.status_signal.emit("🎤 正在录音，后台切换连接中...")
                if not self._reconnecting:
                    self._schedule_reconnect()
            else:
                # 正常路径仍尽量保持实时流式发送
                if not self.ws:
                    await self.connect_websocket()
                    if not self.ws:
                        self.status_signal.emit("❌ 无法连接到服务器")
                        return
                    is_local = (self.server_config.get("ws_scheme", "ws") == "ws")
                    backend_timeout = 10.0 if is_local else 15.0
                    if not self._backend_ready.is_set():
                        self.status_signal.emit("⏳ 等待后端就绪...")
                        if await self._wait_for_backend_ready(backend_timeout, cancel_on_release=True):
                            self.status_signal.emit("✅ 后端已就绪，开始录音")
                        else:
                            if not self._ptt_pressed:
                                return
                            self.status_signal.emit("⚠️ 后端就绪超时，尝试继续录音...")
                else:
                    await self._interrupt_if_possible()
                    if not self.ws:
                        buffer_only_mode = True
                        self.status_signal.emit("🎤 正在录音，等待重新连接后发送...")
                        self._schedule_reconnect()

                if not buffer_only_mode and not self._ptt_pressed:
                    self.status_signal.emit("ℹ️ 已取消本次说话")
                    return

                if not buffer_only_mode:
                    self.status_signal.emit("🎤 正在录音...")

            while self.is_recording:
                try:
                    data = await asyncio.to_thread(
                        self.in_stream.read, CHUNK, exception_on_overflow=False
                    )
                    if not self.is_recording:
                        break
                    if buffer_only_mode:
                        buffered_audio.append(data)
                        continue

                    if self.ws:
                        try:
                            await self.ws.send(data)
                            has_sent_audio = True
                        except websockets.exceptions.ConnectionClosed:
                            self.ws = None
                            buffered_audio.append(data)
                            buffer_only_mode = True
                            self.status_signal.emit("🎤 录音已缓存，等待重新连接后发送...")
                            self._schedule_reconnect()
                    else:
                        buffered_audio.append(data)
                        buffer_only_mode = True
                        self.status_signal.emit("🎤 录音已缓存，等待连接后发送...")
                        self._schedule_reconnect()
                except websockets.exceptions.ConnectionClosed:
                    self.ws = None
                    self.status_signal.emit("❌ 服务器断开连接")
                    break
                except Exception as e:
                    print("Audio read error", e)
                    break

            if buffered_audio:
                if not await self._ensure_connection_ready_for_upload():
                    return
                self.status_signal.emit("⏳ 正在发送录音...")
                try:
                    for chunk in buffered_audio:
                        await self.ws.send(chunk)
                    has_sent_audio = True
                except websockets.exceptions.ConnectionClosed:
                    self.ws = None
                    self.status_signal.emit("❌ 发送录音时连接断开")
                    return

            if not has_sent_audio:
                self.status_signal.emit("ℹ️ 本次未采集到语音，已取消发送")
                return

            # 录音结束后，执行原来的 stop_recording 逻辑
            if not self.ws:
                self.status_signal.emit("🔄 重新连接到服务器...")
                await self.connect_websocket()
                if not self.ws:
                    self.status_signal.emit("❌ 无法重连 - AI 不会响应")
                    return

            try:
                await self.ws.send(json.dumps({"action": "stop_speaking"}))
                self.status_signal.emit("✅ 已连接 - 等待 AI 响应")
            except websockets.exceptions.ConnectionClosed:
                self.ws = None
                self.status_signal.emit("❌ 服务器断开连接")

        finally:
            self.is_recording = False
            self._recording_guard = False

    async def stop_recording(self):
        self._ptt_pressed = False
        self.is_recording = False
        
        # 重置AI文本累积
        self._current_ai_text = ""


class AsyncWorker(QThread):
    def __init__(self, audio_controller):
        super().__init__()
        self.audio_controller = audio_controller
        self.loop = asyncio.new_event_loop()

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.audio_controller.connect_websocket())
        self.loop.run_forever()

    def run_task(self, coro):
        asyncio.run_coroutine_threadsafe(coro, self.loop)


class SimulatorWindow(QMainWindow):
    def __init__(self, server_type="local"):
        super().__init__()
        self.server_type = server_type
        server_name = SERVER_CONFIGS[server_type]["name"]
        self.setWindowTitle(f"硬件模拟器 - {server_name}")
        self.resize(520, 640)

        # 默认不传 lang（中英混合偏中文）
        self.audio_controller = AudioController(server_type, "")
        self._is_new_user_message = True
        self._is_new_ai_message = True

        # Start Asyncio worker thread
        self.async_worker = AsyncWorker(self.audio_controller)
        # 把 loop 引用告诉 AudioController，以便 update_lang 关闭旧连接
        self.audio_controller._loop = self.async_worker.loop
        self.async_worker.start()

        self.setup_ui()
        self.bind_signals()

    def setup_ui(self):
        main_widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # ── 状态栏 ──────────────────────────────────────────────
        self.status_label = QLabel("初始化中...")
        self.status_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        layout.addWidget(self.status_label)

        # ── 服务器选择行 ────────────────────────────────────────
        server_row = QHBoxLayout()
        server_label = QLabel("🖥️ 服务器：")
        server_label.setFont(QFont("Microsoft YaHei", 11))
        server_row.addWidget(server_label)

        self.server_combo = QComboBox()
        self.server_combo.setFont(QFont("Microsoft YaHei", 11))
        self.server_combo.setMinimumWidth(280)
        self.server_combo.addItem("🏠 本地服务器 (127.0.0.1:8000)", "local")
        self.server_combo.addItem("🌐 E600 服务器 (e600.feing.com.cn)", "e600")
        # 设置当前选中项
        current_index = 0 if self.server_type == "local" else 1
        self.server_combo.setCurrentIndex(current_index)

        server_row.addWidget(self.server_combo)
        server_row.addStretch()
        layout.addLayout(server_row)

        # ── 语言选择行 ──────────────────────────────────────────
        lang_row = QHBoxLayout()
        lang_label = QLabel("🌐 语言场景：")
        lang_label.setFont(QFont("Microsoft YaHei", 11))
        lang_row.addWidget(lang_label)

        self.lang_combo = QComboBox()
        self.lang_combo.setFont(QFont("Microsoft YaHei", 11))
        self.lang_combo.setMinimumWidth(280)

        # 填充下拉项；分组标题设为不可选
        for display, param in LANG_OPTIONS:
            self.lang_combo.addItem(display)
            idx = self.lang_combo.count() - 1
            if param is None:           # 分组标题：置灰、禁用
                item = self.lang_combo.model().item(idx)
                item.setEnabled(False)
                item.setForeground(QColor("#888888"))
        self.lang_combo.setCurrentIndex(1)  # 默认「默认（不传 lang）」

        lang_row.addWidget(self.lang_combo)
        lang_row.addStretch()
        layout.addLayout(lang_row)

        # ── 对话记录区 ──────────────────────────────────────────
        self.transcript_area = QTextEdit()
        self.transcript_area.setReadOnly(True)
        self.transcript_area.setFont(QFont("Microsoft YaHei", 11))
        self.transcript_area.setStyleSheet("QTextEdit { background-color: #f5f5f5; }")
        layout.addWidget(self.transcript_area)

        # ── PTT 按钮 ────────────────────────────────────────────
        self.ptt_button = QPushButton("👆 按住说话 (Push to Talk)")
        self.ptt_button.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.ptt_button.setMinimumHeight(100)
        self.ptt_button.setStyleSheet("background-color: #4CAF50; color: white; border-radius: 10px;")
        layout.addWidget(self.ptt_button)

        main_widget.setLayout(layout)
        self.setCentralWidget(main_widget)

    def bind_signals(self):
        self.ptt_button.pressed.connect(self.on_ptt_pressed)
        self.ptt_button.released.connect(self.on_ptt_released)
        self.server_combo.currentIndexChanged.connect(self.on_server_changed)
        self.lang_combo.currentIndexChanged.connect(self.on_lang_changed)
        self.audio_controller.status_signal.connect(self.update_status)
        self.audio_controller.user_text_signal.connect(self.append_user_text)
        self.audio_controller.ai_text_signal.connect(self.append_ai_text)

    def on_ptt_pressed(self):
        self.ptt_button.setStyleSheet("background-color: #f44336; color: white; border-radius: 10px;")
        self.ptt_button.setText("🎙️ 正在录音...")
        self._is_new_user_message = True
        self.async_worker.run_task(self.audio_controller.start_recording())

    def on_ptt_released(self):
        self.ptt_button.setStyleSheet("background-color: #4CAF50; color: white; border-radius: 10px;")
        self.ptt_button.setText("👆 按住说话 (Push to Talk)")
        self._is_new_ai_message = True
        self.async_worker.run_task(self.audio_controller.stop_recording())

    def on_server_changed(self, index):
        """下拉框切换服务器时触发"""
        server_type = self.server_combo.itemData(index)
        if server_type == self.audio_controller.server_type:
            return  # 没有实际变化，跳过
        self.audio_controller.update_server(server_type)
        server_name = SERVER_CONFIGS[server_type]["name"]
        self.status_signal_proxy(f"🖥️ 服务器已切换：{server_name}，下次说话时生效")
        # 更新窗口标题
        self.setWindowTitle(f"硬件模拟器 - {server_name}")

    def on_lang_changed(self, index):
        """下拉框切换语言时触发"""
        _, param = LANG_OPTIONS[index]
        if param is None:
            return  # 分组标题，跳过
        # 更新 AudioController 的语言并重建 ws_url
        self.audio_controller.update_lang(param)
        display, _ = LANG_OPTIONS[index]
        self.status_signal_proxy(f"🌐 语言已切换：{display}，下次说话时生效")

    def status_signal_proxy(self, text):
        self.status_label.setText(text)

    def update_status(self, text):
        self.status_label.setText(text)

    def append_user_text(self, text):
        """显示用户说的话（蓝色）"""
        cursor = self.transcript_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        if self._is_new_user_message:
            if not self.transcript_area.toPlainText().endswith("\n") and self.transcript_area.toPlainText():
                cursor.insertText("\n\n")
            cursor.insertHtml('<p style="color: #2196F3; font-weight: bold; margin: 0;">👤 用户：</p>')
            self._is_new_user_message = False
        
        cursor.insertHtml(f'<span style="color: #1976D2;">{text}</span>')
        
        self.transcript_area.setTextCursor(cursor)
        self.transcript_area.ensureCursorVisible()

    def append_ai_text(self, text):
        """显示AI说的话（绿色）"""
        cursor = self.transcript_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        if self._is_new_ai_message:
            if not self.transcript_area.toPlainText().endswith("\n") and self.transcript_area.toPlainText():
                cursor.insertText("\n\n")
            cursor.insertHtml('<p style="color: #4CAF50; font-weight: bold; margin: 0;">🤖 AI：</p>')
            self._is_new_ai_message = False
        
        cursor.insertHtml(f'<span style="color: #2E7D32;">{text}</span>')
        
        self.transcript_area.setTextCursor(cursor)
        self.transcript_area.ensureCursorVisible()

    def closeEvent(self, event):
        self.audio_controller._close_all_streams()
        self.audio_controller._audio_queue.put(None)
        self.async_worker.loop.call_soon_threadsafe(self.async_worker.loop.stop)
        self.async_worker.wait()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 默认连接本地服务器
    window = SimulatorWindow(server_type="local")
    window.show()
    sys.exit(app.exec())
