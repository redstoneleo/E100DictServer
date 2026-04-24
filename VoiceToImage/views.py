from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from Device.models import Device
from .models import VoiceTask
from .tasks import process_voice_to_image
import os


def verify_device_token(request):
    """
    验证设备的 JWT token
    返回 (device, error_response) 元组
    """
    # 从 Header 或 POST/GET 参数中获取 token
    auth_header = request.headers.get("Authorization", "")
    token = None

    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.POST.get("token") or request.GET.get("token")

    if not token:
        return None, JsonResponse(
            {"status": "error", "message": "Missing token"}, status=401
        )

    try:
        # 解码 token
        access_token = AccessToken(token)
        device_id = access_token.get("device_id")

        if not device_id:
            return None, JsonResponse(
                {"status": "error", "message": "Invalid token: missing device_id"},
                status=401,
            )

        # 验证设备是否存在且激活
        try:
            device = Device.objects.get(device_id=device_id)
            if not device.is_active:
                return None, JsonResponse(
                    {"status": "error", "message": "Device is not active"}, status=403
                )
        except Device.DoesNotExist:
            return None, JsonResponse(
                {"status": "error", "message": "Device not found"}, status=404
            )

        return device, None

    except (InvalidToken, TokenError) as e:
        return None, JsonResponse(
            {"status": "error", "message": f"Invalid token: {str(e)}"}, status=401
        )


@csrf_exempt
def upload_voice(request):
    if request.method != "POST":
        return JsonResponse(
            {"status": "error", "message": "Invalid request method"}, status=405
        )

    # 验证设备 token
    device, error_response = verify_device_token(request)
    if error_response:
        return error_response

    if not request.FILES.get("audio"):
        return JsonResponse(
            {"status": "error", "message": "No audio file provided"}, status=400
        )

    audio_file = request.FILES["audio"]
    style = request.POST.get("style")
    valid_styles = [choice[0] for choice in VoiceTask.STYLE_CHOICES]
    if style not in valid_styles:
        style = None

    # 创建任务时关联设备
    task = VoiceTask.objects.create(audio_file=audio_file, style=style, device=device)

    # Trigger Celery task
    process_voice_to_image.delay(task.id)

    return JsonResponse(
        {
            "status": "success",
            "task_id": task.id,
            "message": "Voice recording uploaded and processing started.",
        }
    )


def task_status(request, task_id):
    # 验证设备 token
    device, error_response = verify_device_token(request)
    if error_response:
        return error_response

    try:
        task = VoiceTask.objects.get(id=task_id)

        # 确保只能查询自己设备的任务
        if task.device != device:
            return JsonResponse(
                {"status": "error", "message": "Permission denied"}, status=403
            )

        return JsonResponse(
            {
                "id": task.id,
                "status": task.status,
                "style": task.style,
                "recognized_text": task.recognized_text,
                "generated_image_url": task.generated_image_url,
                "error_message": task.error_message,
                "created_at": task.created_at,
            }
        )
    except VoiceTask.DoesNotExist:
        return JsonResponse(
            {"status": "error", "message": "Task not found"}, status=404
        )
