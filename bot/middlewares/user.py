from aiogram import BaseMiddleware
from bot.services.user_service import (
    get_or_create_user,
    update_user_if_needed,
)


class TelegramUserMiddleware(BaseMiddleware):

    async def __call__(self, handler, event, data):
        from_user = data.get("event_from_user")

        if from_user:
            user, created = await get_or_create_user(from_user)

            if not created:
                user = await update_user_if_needed(user, from_user)

            data["db_user"] = user

        return await handler(event, data)