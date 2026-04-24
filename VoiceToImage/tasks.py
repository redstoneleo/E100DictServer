from celery import shared_task
from celery.exceptions import Retry
from django.conf import settings
from .models import VoiceTask
from . import BaiduSpeechToText as baidu_stt
import dashscope
from dashscope import ImageSynthesis, MultiModalConversation
from http import HTTPStatus

# DashScope API Key
dashscope.api_key = getattr(settings, 'DASHSCOPE_API_KEY', 'your_dashscope_api_key_here')

@shared_task(bind=True, max_retries=20)
def poll_baidu_stt(self, task_id):
    try:
        task = VoiceTask.objects.get(id=task_id)
        
        # 使用 dicts.BaiduSpeechToText 中的查询函数
        result = baidu_stt.query_lst_task([task.baidu_task_id])
        
        if result.get("tasks_info"):
            task_info = result["tasks_info"][0]
            status = task_info.get("task_status")
            
            if status == "Success":
                task.recognized_text = task_info.get("task_result", {}).get("result", "")
                task.status = 'PROCESSING_IMAGE'
                task.save()
                # 识别成功，进入生图环节
                generate_image_task.delay(task.id)
            elif status == "Failure":
                error_msg = task_info.get('task_result', {}).get('err_msg', 'Unknown Baidu error')
                raise Exception(f"Baidu STT failed: {error_msg}")
            else:
                # 还在处理中，10秒后重试
                raise self.retry(countdown=10)
        else:
            raise Exception("No task info returned from Baidu")
            
    except Retry:
        raise
    except Exception as e:
        task = VoiceTask.objects.get(id=task_id)
        task.status = 'FAILED'
        task.error_message = str(e)
        task.save()

@shared_task
def generate_image_task(task_id):
    try:
        task = VoiceTask.objects.get(id=task_id)
        style = task.style or '简笔画'
        base_prompt = task.recognized_text or ''
        prompt = f"{style}风格，{base_prompt}" if base_prompt else f"{style}风格"
        
        # Qwen-Image 系列模型通常使用 MultiModalConversation 接口（类似 Qwen-VL）
        # 文档参考：https://help.aliyun.com/zh/model-studio/qwen-image-api
        messages = [{
            "role": "user",
            "content": [{"text": prompt}]
        }]
        
        rsp = MultiModalConversation.call(
            model='qwen-image-max',  # 用户指定的模型，如需更稳定可用 qwen-image-plus
            messages=messages,
            # parameters={'size': '1024*1024'} # 如果模型支持分辨率参数可在此添加
        )
        
        if rsp.status_code == HTTPStatus.OK:
            # 尝试解析返回结果，Qwen-Image 返回格式可能在 choices[0].message.content 中包含图片信息
            if rsp.output and rsp.output.choices:
                content = rsp.output.choices[0].message.content
                # content 通常是 list，包含 {'image': 'url'}
                if isinstance(content, list) and len(content) > 0 and 'image' in content[0]:
                    task.generated_image_url = content[0]['image']
                    task.status = 'COMPLETED'
                else:
                     task.status = 'FAILED'
                     task.error_message = f"Unexpected content format in Qwen-Image response: {content}"
            # 兼容可能的 ImageSynthesis 风格返回（如果 SDK 做了封装）
            elif rsp.output and hasattr(rsp.output, 'results') and rsp.output.results:
                task.generated_image_url = rsp.output.results[0].url
                task.status = 'COMPLETED'
            else:
                task.status = 'FAILED'
                task.error_message = "No image results found in response"
        else:
            task.status = 'FAILED'
            task.error_message = f"Qwen-Image API failed: {rsp.message}"
            
        task.save()
        
    except Exception as e:
        task = VoiceTask.objects.get(id=task_id)
        task.status = 'FAILED'
        task.error_message = f"Image generation failed: {str(e)}"
        task.save()

@shared_task
def process_voice_to_image(task_id):
    try:
        task = VoiceTask.objects.get(id=task_id)
        task.status = 'PROCESSING_STT'
        task.save()

        task.audio_file.open('rb')
        file_bytes = task.audio_file.read()
        task.audio_file.close()

        result = baidu_stt.speechToText(file_bytes, rate=16000)
        if result.get("err_msg") == "success.":
            recognized_text = ""
            if result.get("result"):
                recognized_text = result["result"][0]
            task.recognized_text = recognized_text
            task.status = 'PROCESSING_IMAGE'
            task.save()
            generate_image_task.delay(task.id)
        else:
            error_msg = result.get("err_msg", "Unknown Baidu error")
            raise Exception(f"Baidu STT failed: {error_msg}")

    except Exception as e:
        task = VoiceTask.objects.get(id=task_id)
        task.status = 'FAILED'
        task.error_message = str(e)
        task.save()
        print(f"Error starting process for task {task_id}: {e}")
