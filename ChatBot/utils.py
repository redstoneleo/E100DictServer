import time
import datetime
from django.core.cache import cache

DAILY_LIMIT_SECONDS = 5 * 60 * 60 # 5 hours

def get_daily_usage_key(device_id):
    today = datetime.date.today().isoformat()
    return f"device_usage:{device_id}:{today}"

def get_daily_usage(device_id):
    key = get_daily_usage_key(device_id)
    usage = cache.get(key)
    return int(usage) if usage else 0

def add_usage(device_id, seconds):
    key = get_daily_usage_key(device_id)
    try:
        if cache.get(key) is None:
            cache.set(key, int(seconds), timeout=86400 * 2) # keep for 2 days
        else:
            cache.incr(key, int(seconds))
    except Exception as e:
        print(f"[RateLimit] Failed to update usage in Redis: {e}")

def check_limit_exceeded(device_id):
    return get_daily_usage(device_id) >= DAILY_LIMIT_SECONDS
