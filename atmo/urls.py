from django.contrib import admin
from django.urls import path
from bot.views import telegram_webhook
from bot.views import *

urlpatterns = [
    path("admin/", admin.site.urls),
    path("webhook/atmo/", telegram_webhook),
    path("api/weblink/", weblink),
]