from asgiref.sync import sync_to_async
from bot.models import TelegramUser


@sync_to_async
def get_or_create_user(from_user):
    return TelegramUser.objects.get_or_create(
        telegram_id=from_user.id,
        defaults={
            "username": from_user.username,
            "first_name": from_user.first_name or "",
            "last_name": from_user.last_name or "",
        }
    )


@sync_to_async
def update_user_if_needed(user, from_user):
    updated = False

    if user.username != from_user.username:
        user.username = from_user.username
        updated = True

    if user.first_name != (from_user.first_name or ""):
        user.first_name = from_user.first_name or ""
        updated = True

    if user.last_name != (from_user.last_name or ""):
        user.last_name = from_user.last_name or ""
        updated = True

    if updated:
        user.save()

    return user