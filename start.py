import os
import django
import asyncio
import subprocess

# Инициализация Django ПЕРЕД любыми импортами из bot
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "atmo.settings")
django.setup()

# Только ПОСЛЕ django.setup() импортируем bot
from bot.loader import bot

WEBHOOK_URL = "https://intime-studio.com/webhook/atmo/"

async def set_webhook():
    await bot.set_webhook(WEBHOOK_URL)
    print("Webhook установлен")

if __name__ == "__main__":
    asyncio.run(set_webhook())

    print("Запуск сервера на порту 4001...")
    subprocess.run([
    "python3",
    "-m",
    "uvicorn",
    "atmo.asgi:application",
    "--host",
    "0.0.0.0",
    "--port",
    "4001"
])
    