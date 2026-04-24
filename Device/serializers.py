from rest_framework import serializers
from .models import Device


class DeviceAuthSerializer(serializers.Serializer):
    device_id = serializers.CharField()
    device_secret = serializers.CharField()


class DeviceChallengeRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField()


class DeviceSignatureSerializer(serializers.Serializer):
    device_id = serializers.CharField()
    signature = serializers.CharField()


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = ('product_model', 'device_id', 'is_active', 'last_active')
