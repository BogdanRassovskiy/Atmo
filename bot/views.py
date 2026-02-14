from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.conf import settings
from asgiref.sync import async_to_sync
from aiogram.types import Update
from .loader import bot, dp
from .models import TelegramUser, Registration
import json
import requests
from datetime import datetime, time


@csrf_exempt
def telegram_webhook(request):
    if request.method == "POST":
        data = json.loads(request.body)
        update = Update.model_validate(data)

        async_to_sync(dp.feed_update)(bot, update)

        return JsonResponse({"ok": True})

    return JsonResponse({"error": "Only POST allowed"}, status=405)
def format_registration_message(registration, user, is_new):
    status = "🆕 Новая регистрация" if is_new else "🔄 Обновление регистрации"
    return f"""
<b>{status}</b>

<b>👤 Имя:</b> {user.first_name or '-'}
<b>📞 Телефон:</b> {user.phone or '-'}
<b>💬 Telegram:</b> @{user.username or '-'}

<b>🎲 Игра:</b> {registration.game}
<b>🎤 Мастер:</b> {registration.master}

<b>📍 Место:</b> {registration.place_number}
<b>📅 День:</b> {registration.day}
<b>📌 Линия:</b> {registration.line}

<b>⏰ Время:</b> {registration.time_start.strftime('%H:%M')} – {registration.time_end.strftime('%H:%M')}

<b>🪪 ID бронирования:</b> {registration.booking_id}
<b>💳 Оплата:</b> {"✅ Оплачено" if registration.is_paid else "❌ Не оплачено"}

<b>🕓 Дата регистрации:</b> {registration.created_at.strftime('%d.%m.%Y %H:%M')}
"""

def send_to_telegram(message: str):
    try:
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": settings.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        res = requests.post(url, json=payload, timeout=5)
        res.raise_for_status()
        return True
    except Exception as e:
        print(f"Failed to send telegram message: {e}")
        return False

@csrf_exempt
def weblink(request):
    try:
        # Получаем параметры из GET запроса
        name = request.GET.get("name")
        phone = request.GET.get("phone")
        telegram_username = request.GET.get("telegram_username")
        game = request.GET.get("game")
        master = request.GET.get("master")
        place = request.GET.get("place")
        day = request.GET.get("day")
        line = request.GET.get("line")
        booking_id = request.GET.get("booking_id")
        time_start_str = request.GET.get("time_start")
        time_end_str = request.GET.get("time_end")
        
        # Валидация обязательных полей
        if not telegram_username:
            return JsonResponse(
                {"error": "telegram_username is required"},
                status=400
            )
        
        if not booking_id:
            return JsonResponse(
                {"error": "booking_id is required"},
                status=400
            )
        
        if not game or not master or not place or not day or not line:
            return JsonResponse(
                {"error": "game, master, place, day, and line are required"},
                status=400
            )
        
        # Создаем или получаем пользователя по telegram_username
        user, user_created = TelegramUser.objects.get_or_create(
            username=telegram_username,
            defaults={
                "first_name": name or "",
                "phone": phone or "",
                "telegram_id": 0,  # будет обновлен при первом контакте с ботом
            }
        )
        
        # Обновляем данные пользователя, если он уже существовал
        if not user_created:
            updated = False
            
            if name and user.first_name != name:
                user.first_name = name
                updated = True
            
            if phone and user.phone != phone:
                user.phone = phone
                updated = True
            
            if updated:
                user.save()
        
        # Парсим время
        time_start = None
        time_end = None
        
        if time_start_str:
            try:
                time_start = datetime.strptime(time_start_str, "%H:%M").time()
            except ValueError:
                return JsonResponse(
                    {"error": "Invalid time_start format. Use HH:MM"},
                    status=400
                )
        
        if time_end_str:
            try:
                time_end = datetime.strptime(time_end_str, "%H:%M").time()
            except ValueError:
                return JsonResponse(
                    {"error": "Invalid time_end format. Use HH:MM"},
                    status=400
                )
        
        # Создаем или обновляем регистрацию
        # Если пользователь уже регистрировался на эту игру - обновляем
        registration, registration_created = Registration.objects.update_or_create(
            user=user,
            game=game,
            defaults={
                "booking_id": booking_id,
                "master": master,
                "place_number": int(place),
                "day": int(day),
                "line": int(line),
                "time_start": time_start or time(0, 0),
                "time_end": time_end or time(0, 0),
                "created_at": timezone.now(),
            }
        )
        
        # Отправляем уведомление в Telegram
        message = format_registration_message(registration, user, registration_created)
        send_to_telegram(message)
        
        # Если пользователь новый - отправляем приветственное сообщение
        if user_created:
            welcome_message = f"""✨ Здравствуйте, {user.first_name} ✨
             Добро пожаловать на фестиваль трансформационных игр 

Благодарим Вас за выбор — выбор расширяться и идти в трансформацию ❤️

Для завершения регистрации необходимо внести 100% оплату участия.

Реквизиты для оплаты: 1234 5678 9012 3456"""
            send_to_telegram(welcome_message)
        
        # Проверяем количество регистраций пользователя
        if registration_created:  # Только если была создана новая регистрация
            total_registrations = Registration.objects.filter(user=user).count()
            if total_registrations == 4:
                four_games_message = f"""✨ Здравствуйте, {user.first_name} ✨
             Вы выбрали 4 трансформационные игр 

Благодарим Вас за выбор — выбор расширяться и идти в трансформацию ❤️

Для завершения регистрации необходимо внести 100% оплату участия.

Реквизиты для оплаты: 1234 5678 9012 3456"""
                send_to_telegram(four_games_message)
        
        return JsonResponse({
            "success": True,
            "user_created": user_created,
            "registration_created": registration_created,
            "registration_updated": not registration_created,
            "user_id": user.id,
            "registration_id": registration.id,
            "booking_id": booking_id
        })
    
    except Exception as e:
        return JsonResponse(
            {"error": str(e)},
            status=500
        )