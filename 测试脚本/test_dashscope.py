import asyncio
import websockets
import json
import os
import time

API_KEY = "sk-fake" # Will replace with env or django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'E100DictServer.settings')
import django
django.setup()
from django.conf import settings
API_KEY = getattr(settings, "DASHSCOPE_API_KEY", "")

async def test_dashscope():
    url = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=qwen3-omni-flash-realtime"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    
    async with websockets.connect(url, additional_headers=headers) as ws:
        print("Connected.")
        
        # Test my exact payload
        payload = {
            "type": "session.update",
            "event_id": f"event_{int(time.time() * 1000)}",
            "session": {
                "modalities": ["text", "audio"],
                "turn_detection": None,
                "input_audio_format": "pcm",
                "output_audio_format": "pcm",
                "input_audio_transcription": {
                    "model": "gummy-realtime-v1"
                },
                "instructions": "你是个人助理，请你准确且友好地解答用户的问题，始终以乐于助人的态度回应。"
            }
        }
        await ws.send(json.dumps(payload))
        print("Sent session.update")
        
        res = await ws.recv()
        print("Received:", res)
        
        # test event_id
        payload2 = {
            "type": "input_audio_buffer.commit",
            "event_id": f"event_{int(time.time() * 1000)}_c"
        }
        await ws.send(json.dumps(payload2))
        res = await ws.recv()
        print("Received after commit:", res)

        payload3 = {
            "type": "response.create",
            "event_id": f"event_{int(time.time() * 1000)}_r"
        }
        await ws.send(json.dumps(payload3))
        res = await ws.recv()
        print("Received after create:", res)

if __name__ == "__main__":
    asyncio.run(test_dashscope())
