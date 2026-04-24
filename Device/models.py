import secrets
from django.db import models
from django.utils import timezone


def generate_secret():
    return secrets.token_hex(32)  # 64 hex chars -> 32 bytes


class Device(models.Model):
    product_model = models.CharField(max_length=10)
    device_id = models.CharField(max_length=128, unique=True)
    device_secret = models.CharField(max_length=64, default=generate_secret)
    is_active = models.BooleanField(default=True)
    last_active = models.DateTimeField(null=True, blank=True)

    def touch(self):
        self.last_active = timezone.now()
        self.save(update_fields=['last_active'])

    def __str__(self):
        return f"{self.device_id} ({'active' if self.is_active else 'inactive'})"
