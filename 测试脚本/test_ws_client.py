import os
import asyncio
import json
import secrets
import hmac
import hashlib

# Setup Django environment so we can use ORM to create/get a device and generate a token
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'E100DictServer.settings')
import django
django.setup()

from Device.models import Device
from rest_framework_simplejwt.tokens import RefreshToken
from django.core.cache import cache
import websockets

def setup_test_device():
    device, created = Device.objects.get_or_create(
        device_id="test_device_ws_001",
        defaults={
            "product_model": "TEST_MOD",
            "is_active": True
        }
    )
    if created:
        print(f"[*] Created new test device: {device.device_id} (Secret: {device.device_secret})")
    else:
        print(f"[*] Using existing test device: {device.device_id}")

    refresh = RefreshToken()
    refresh['device_id'] = device.device_id
    refresh['product_model'] = device.product_model
    access_token = str(refresh.access_token)
    
    # Generate nonce conceptually via /device/challenge endpoint
    nonce = secrets.token_urlsafe(32)
    cache.set(f"device_challenge_{device.device_id}", nonce, timeout=60)
    
    # Sign it conceptually like the hardware would
    signature = hmac.new(device.device_secret.encode('utf-8'), nonce.encode('utf-8'), hashlib.sha256).hexdigest()
    
    return access_token, nonce, signature

async def test_valid_connection(access_token, nonce, signature):
    print("=== Testing Valid WebSocket Connection ===")
    print(f"[*] Generated Access Token: {access_token[:30]}...\n")

    # 3. Connect to WebSocket endpoint
    ws_url = f"ws://127.0.0.1:8000/ws/chatbot/?token={access_token}&nonce={nonce}&sign={signature}"
    print(f"[*] Connecting to: {ws_url}")
    
    try:
        async with websockets.connect(ws_url) as websocket:
            print("[+] Connection SUCCESSFUL! Handshake completed.")
            
            # Send an optional text message to the server
            test_msg = {"event": "hello", "data": "Testing connection"}
            await websocket.send(json.dumps(test_msg))
            print(f"[>] Sent frame: {test_msg}")
            
            # Keep connection open for a moment to demonstrate it wasn't dropped
            await asyncio.sleep(2)
            print("[+] Connection is stable. Test passed!\n")
            
    except Exception as e:
        print(f"[-] Connection Failed: {e}\n")


async def test_invalid_connection():
    print("=== Testing Invalid/Replayed WebSocket Connection ===")
    print("[*] Attempting connection with an invalid token/nonce...")
    
    ws_url = f"ws://127.0.0.1:8000/ws/chatbot/?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.fake.signature"
    
    try:
        async with websockets.connect(ws_url) as websocket:
            # We shouldn't reach here if the server properly rejects it
            print("[-] Test FAILED: The connection was incorrectly accepted.")
    except websockets.exceptions.ConnectionClosedError as e:
        # The connection was dropped after handshake due to custom logic.
        if e.code == 4001:
            print(f"[+] Connection gracefully rejected with custom code: {e.code}. Test passed!\n")
        else:
            print(f"[*] Connection closed with code: {e.code}\n")
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"[+] Connection HTTP rejected with status: {e.status_code}. Test passed!\n")
    except Exception as e:
        print(f"[*] Result: {e}\n")

async def test_replay_connection(access_token, nonce, signature):
    print("=== Testing Replay WebSocket Connection ===")
    print("[*] Attempting to REUSE the same nonce and signature for a new connection...")
    
    ws_url = f"ws://127.0.0.1:8000/ws/chatbot/?token={access_token}&nonce={nonce}&sign={signature}"
    
    try:
        async with websockets.connect(ws_url) as websocket:
            print("[-] Test FAILED: Replayed connection was incorrectly accepted!")
    except websockets.exceptions.ConnectionClosedError as e:
        if e.code == 4001:
            print(f"[+] Replay attack successfully blocked! Connection dropped with 4001. Test passed!\n")
        else:
            print(f"[*] Connection closed with code: {e.code}")
    except Exception as e:
        print(f"[*] Result: {e}\n")

async def main(access_token, nonce, signature):
    await test_valid_connection(access_token, nonce, signature)
    await test_replay_connection(access_token, nonce, signature)
    await test_invalid_connection()


if __name__ == "__main__":
    access_token, nonce, signature = setup_test_device()
    asyncio.run(main(access_token, nonce, signature))
