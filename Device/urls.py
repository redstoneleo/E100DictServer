from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'devices', views.DeviceViewSet, basename='device')

urlpatterns = [
    path('', include(router.urls)),
    path('token/', views.device_token, name='device-token'),
    path('challenge/', views.device_challenge, name='device-challenge'),
    path('whoami/', views.whoami, name='device-whoami'),
]
