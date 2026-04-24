from django.db import models

class VoiceTask(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING_STT', 'Processing STT'),
        ('PROCESSING_IMAGE', 'Processing Image'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]
    
    STYLE_CHOICES = [
        ('简笔画', '简笔画'),
        ('线稿', '线稿'),
        ('素描', '素描'),
        ('动漫', '动漫'),
        ('卡通', '卡通'),
        ('水墨', '水墨'),
    ]

    device = models.ForeignKey('Device.Device', on_delete=models.CASCADE, related_name='voice_tasks', null=True, blank=True)
    audio_file = models.FileField(upload_to='voice_recordings/')
    style = models.CharField(max_length=20, choices=STYLE_CHOICES, blank=True, null=True, default='卡通')
    baidu_task_id = models.CharField(max_length=100, blank=True, null=True)
    recognized_text = models.TextField(blank=True, null=True)
    generated_image_url = models.URLField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Task {self.id} - {self.status}"
