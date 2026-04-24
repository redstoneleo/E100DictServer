# Device API Documentation

This document describes the Device management and authentication APIs.

Table of contents
- Register Device (Admin-only, RESTful)
- Get Token (Challenge-Response)
- Refresh Token
- Other endpoints
- Redis configuration and deployment notes

## Register Device (Admin-only, RESTful)

Endpoint
```
POST /device/devices/
```
Description
- Create a new Device. Admin-only (`IsAdminUser`).
- The response includes the generated `device_secret` only at creation time — store it securely.

Request body (JSON)
```json
{
  "product_class": "LYY",
  "device_id": "LYY-202603-000123"
}
```
Response (201 Created)
```json
{
  "product_class": "LYY",
  "device_id": "LYY-202603-000123",
  "device_secret": "64hexchars...",
  "is_active": true,
  "last_active": null
}
```

Curl example (Basic Auth with admin):
```bash
curl -u admin:password -X POST http://127.0.0.1:8000/device/devices/ \
  -H "Content-Type: application/json" \
  -d '{"product_class":"LYY","device_id":"LYY-202603-000123"}'
```

Python example (requests):
```python
import requests
resp = requests.post(
    "http://127.0.0.1:8000/device/devices/",
    auth=('admin','password'),
    json={"product_class":"LYY","device_id":"LYY-202603-000123"}
)
resp.raise_for_status()
print(resp.json())  # save device_secret
```

Notes
- `device_secret` is a 32-byte random hex string returned only once. Store it safely on the device.

## Get Token (Challenge-Response)

Two-step flow (prevents sending device_secret in plaintext):

### 1) Request nonce (challenge)

Endpoint
```
POST /device/challenge/
```
Request body
```json
{ "device_id": "LYY-202603-000123" }
```
Response
```json
{ "nonce": "<random-string>" }
```

### 2) Sign nonce and request tokens

- On device: compute `signature = HMAC_SHA256(device_secret, nonce)` and encode as hex.
- Submit signature (device_secret is never sent).

Endpoint
```
POST /device/token/
```
Request body
```json
{ "device_id": "LYY-202603-000123", "signature": "<hex-hmac-sha256>" }
```
Response
```json
{ "access": "<access_jwt>", "refresh": "<refresh_jwt>" }
```

Python client example
```python
import requests, hmac, hashlib
BASE = "http://127.0.0.1:8000"
device_id = "LYY-202603-000123"
device_secret = "<device-secret>"

# 1. get nonce
r = requests.post(f"{BASE}/device/challenge/", json={"device_id": device_id})
nonce = r.json()['nonce']

# 2. sign
sig = hmac.new(device_secret.encode('utf-8'), nonce.encode('utf-8'), hashlib.sha256).hexdigest()

# 3. request tokens
r2 = requests.post(f"{BASE}/device/token/", json={"device_id": device_id, "signature": sig})
print(r2.json())
```

Security notes
- Nonce is stored in server cache for a short time (60s) and deleted after use.
- Use HTTPS/WSS in production.

## Refresh Token

Endpoint (standard SimpleJWT)
```
POST /api/token/refresh/
```
Request body
```json
{ "refresh": "<refresh_token>" }
```
Response
```json
{ "access": "<new_access_token>" }
```

Curl example
```bash
curl -X POST http://127.0.0.1:8000/api/token/refresh/ -H "Content-Type: application/json" -d '{"refresh":"<refresh_token>"}'
```

## Other endpoints
- `GET /device/whoami/` — protected endpoint returning token claims (for debugging). Use `Authorization: Bearer <access>` header.
- `GET /device/devices/`, `GET /device/devices/{id}/`, `PUT`, `PATCH`, `DELETE` — standard DeviceViewSet admin endpoints.

## Redis configuration and deployment notes
- This project uses Redis for cache (nonce storage). Configure `REDIS_URL` environment variable or default `redis://127.0.0.1:6379/1`.
- Install dependencies:
  ```bash
  pip install django-redis
  ```
- In production, ensure Redis is secured and accessible only to your app instances.

## Troubleshooting
- If you receive "challenge expired or not found", request a new nonce and ensure device clock is correct and network latency is acceptable.
- If you can't authenticate, verify device_id exists, is_active is true, and device_secret stored on device matches server.

*** End of Document
