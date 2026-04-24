from django.contrib import admin
from .models import Device


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ('device_id', 'product_model', 'is_active', 'last_active')
    search_fields = ('device_id', 'product_model')
    readonly_fields = ('last_active',)
