from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from bot.views import telegram_webhook
from bot.views import *

urlpatterns = [
    path("admin/", admin.site.urls),
    path("webhook/atmo/", telegram_webhook),
    path("api/weblink/", weblink),
]

# Раздача статики в продакшене
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
else:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)