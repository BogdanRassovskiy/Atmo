from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from asgiref.sync import async_to_sync
from aiogram.types import Update
from .loader import bot, dp
import json


@csrf_exempt
def telegram_webhook(request):
    if request.method == "POST":
        data = json.loads(request.body)
        update = Update.model_validate(data)

        async_to_sync(dp.feed_update)(bot, update)

        return JsonResponse({"ok": True})

    return JsonResponse({"error": "Only POST allowed"}, status=405)