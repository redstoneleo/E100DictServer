from django.urls import path
from . import views

urlpatterns = [
    path('upload/', views.upload_voice, name='upload_voice'),
    path('status/<int:task_id>/', views.task_status, name='task_status'),
]
