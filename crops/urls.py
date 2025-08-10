"""crops URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .api import api, webhook_api

from django_paddle_billing.urls import urlpatterns as paddle_billing_urls


@csrf_exempt
def health_check(request):
    """Health check endpoint for load balancer"""
    return JsonResponse({"status": "healthy", "service": "crops-backend"})


urlpatterns = [
    path('admin/', admin.site.urls),
    path("api/v1/", api.urls),
    path("webhooks/", webhook_api.urls),
    path("", health_check, name="health_check"),  # Root health check endpoint
]
urlpatterns += paddle_billing_urls