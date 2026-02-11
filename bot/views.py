from django.http import JsonResponse
from aiogram.types import Update
from .loader import bot, dp
import json

async def telegram_webhook(request):
    if request.method == "POST":
        data = json.loads(request.body)
        update = Update.model_validate(data)
        await dp.feed_update(bot, update)
        return JsonResponse({"ok": True})