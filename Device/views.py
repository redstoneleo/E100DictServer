from django.utils import timezone
from django.core.cache import cache
import hmac
import hashlib
import secrets
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import viewsets
from rest_framework.response import Response as DRFResponse
from rest_framework import status as drf_status
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Device
from .serializers import DeviceSerializer, DeviceChallengeRequestSerializer, DeviceSignatureSerializer


class DeviceViewSet(viewsets.ModelViewSet):
    """RESTful device management. Admin-only for create/update/delete/list."""
    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
    permission_classes = [IsAdminUser]

    def create(self, request, *args, **kwargs):
        # support legacy clients that send 'product_class' by normalizing payload
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        if 'product_class' in data and 'product_model' not in data:
            data['product_model'] = data.pop('product_class')

        serializer = self.get_serializer(data=data)
        if not serializer.is_valid():
            # Return explicit validation errors and log for easier debugging
            print('DeviceSerializer validation errors:', serializer.errors)
            return DRFResponse(serializer.errors, status=drf_status.HTTP_400_BAD_REQUEST)
        device = Device.objects.create(product_model=serializer.validated_data.get('product_model'), device_id=serializer.validated_data.get('device_id'))
        out = {
            'product_model': device.product_model,
            'device_id': device.device_id,
            'device_secret': device.device_secret,
            'is_active': device.is_active,
            'last_active': device.last_active,
        }
        return DRFResponse(out, status=drf_status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAdminUser])
def device_register(request):
    """Admin-only: register a new device and return its generated secret."""
    # accept legacy 'product_class' key
    data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
    if 'product_class' in data and 'product_model' not in data:
        data['product_model'] = data.pop('product_class')

    serializer = DeviceSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    product_model = serializer.validated_data.get('product_model')
    device_id = serializer.validated_data.get('device_id')

    if Device.objects.filter(device_id=device_id).exists():
        return Response({'detail': 'device_id already exists'}, status=status.HTTP_400_BAD_REQUEST)

    device = Device.objects.create(product_model=product_model, device_id=device_id)

    out = {
        'product_model': device.product_model,
        'device_id': device.device_id,
        'device_secret': device.device_secret,
        'is_active': device.is_active,
        'last_active': device.last_active,
    }
    return Response(out, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
def device_token(request):
    """Authenticate device using a signature over a server nonce (challenge-response).

    Expected body: {"device_id": "...", "signature": "hex-hmac-sha256"}
    The server previously issued a nonce via /device/challenge/. Signature is HMAC-SHA256(nonce, device_secret).
    """
    serializer = DeviceSignatureSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    device_id = serializer.validated_data['device_id']
    signature = serializer.validated_data['signature']

    try:
        device = Device.objects.get(device_id=device_id)
    except Device.DoesNotExist:
        return Response({'detail': 'invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

    if not device.is_active:
        return Response({'detail': 'device inactive'}, status=status.HTTP_401_UNAUTHORIZED)

    # fetch nonce from cache
    cache_key = f"device_challenge_{device_id}"
    nonce = cache.get(cache_key)
    if not nonce:
        return Response({'detail': 'challenge expired or not found'}, status=status.HTTP_400_BAD_REQUEST)

    # compute expected signature
    expected = hmac.new(device.device_secret.encode('utf-8'), nonce.encode('utf-8'), hashlib.sha256).hexdigest()
    # constant-time compare
    if not hmac.compare_digest(expected, signature):
        return Response({'detail': 'invalid signature'}, status=status.HTTP_401_UNAUTHORIZED)

    # authentication success
    device.last_active = timezone.now()
    device.save(update_fields=['last_active'])

    # remove nonce to prevent reuse
    cache.delete(cache_key)

    refresh = RefreshToken()
    refresh['device_id'] = device.device_id
    refresh['product_model'] = device.product_model
    access = refresh.access_token

    return Response({'access': str(access), 'refresh': str(refresh)})


@api_view(['POST'])
@permission_classes([AllowAny])
def device_challenge(request):
    """Issue a short random nonce for a device to sign. Body: {"device_id": "..."} -> {"nonce": "..."}
    Nonce is stored in cache for a short time (e.g., 60s).
    """
    serializer = DeviceChallengeRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    device_id = serializer.validated_data['device_id']

    if not Device.objects.filter(device_id=device_id).exists():
        return Response({'detail': 'unknown device'}, status=status.HTTP_404_NOT_FOUND)

    # generate random nonce
    nonce = secrets.token_urlsafe(32)
    cache_key = f"device_challenge_{device_id}"
    # store for 60 seconds
    cache.set(cache_key, nonce, timeout=60)
    return Response({'nonce': nonce})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def whoami(request):
    # token-based access; return token claims
    return Response({'claims': request.auth})
