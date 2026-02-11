import os
import asyncio
import subprocess

from bot.loader import bot

WEBHOOK_URL = "https://intime-studio.com/webhook/"

async def set_webhook():
    await bot.set_webhook(WEBHOOK_URL)
    print("Webhook установлен")

if __name__ == "__main__":
    asyncio.run(set_webhook())

    print("Запуск сервера на порту 4001...")
    subprocess.run(["python3", "manage.py", "runserver", "0.0.0.0:4001"])