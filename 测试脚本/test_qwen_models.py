import os
import base64
import time
import json
import pyaudio
from dashscope.audio.qwen_omni import MultiModality, AudioFormat, OmniRealtimeCallback, OmniRealtimeConversation
import dashscope
import json
import websocket
import os
dashscope.api_key = "sk-73223fb139e147b690aa95d43b73d400"



API_KEY="sk-73223fb139e147b690aa95d43b73d400"
API_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=qwen3.5-omni-plus-realtime"

headers = [
    "Authorization: Bearer " + API_KEY
]

def on_open(ws):
    print(f"Connected to server: {API_URL}")
def on_message(ws, message):
    data = json.loads(message)
    print("Received event:", json.dumps(data, indent=2))
def on_error(ws, error):
    print("Error:", error)

ws = websocket.WebSocketApp(
    API_URL,
    header=headers,
    on_open=on_open,
    on_message=on_message,
    on_error=on_error
)

ws.run_forever()