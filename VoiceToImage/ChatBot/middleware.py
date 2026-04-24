from urllib.parse import parse_qs
from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
import hmac
import hashlib
from django.core.cache import cache

@database_sync_to_async
def get_device(device_id):
    from Device.models import Device
    try:
        device = Device.objects.get(device_id=device_id)
        if device.is_active:
            return device
    except Device.DoesNotExist:
        pass
    return None

@database_sync_to_async
def verify_nonce_and_sign(device, nonce, signature):
    cache_key = f"device_challenge_{device.device_id}"
    cached_nonce = cache.get(cache_key)
    if not cached_nonce or cached_nonce != nonce:
        return False
    
    expected = hmac.new(device.device_secret.encode('utf-8'), nonce.encode('utf-8'), hashlib.sha256).hexdigest()
    if hmac.compare_digest(expected, signature):
        cache.delete(cache_key) # one-time use to prevent replay
        return True
    return False

class JWTAuthMiddleware(BaseMiddleware):
    """
    Custom Middleware to handle SimpleJWT token + HMAC Signature for WebSocket connections.
    """
    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode()
        query_params = parse_qs(query_string)
        token = query_params.get("token", [None])[0]
        nonce = query_params.get("nonce", [None])[0]
        signature = query_params.get("sign", [None])[0]

        scope["device"] = None
        
        if token and nonce and signature:
            try:
                # Decode token
                access_token = AccessToken(token)
                device_id = access_token.get("device_id")
                if device_id:
                    # Verify device in DB
                    device = await get_device(device_id)
                    if device:
                        is_valid = await verify_nonce_and_sign(device, nonce, signature)
                        if is_valid:
                            scope["device"] = device
            except (InvalidToken, TokenError):
                pass
        
        return await super().__call__(scope, receive, send)
