import os
import django
import asyncio

# Инициализация Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "atmo.settings")
django.setup()

# Только после setup можно импортировать Django-зависимые модули
from bot.loader import bot, dp


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())