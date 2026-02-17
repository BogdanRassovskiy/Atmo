from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.conf import settings
from asgiref.sync import async_to_sync
from aiogram.types import Update
from .loader import bot, dp
from .models import TelegramUser, Registration
import json
import requests
import uuid
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
<b>💬 Telegram ID:</b> {user.telegram_id or '-'}

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

def send_to_telegram(message: str, registration_ref: str = None):
    try:
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": settings.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        
        # Добавляем inline кнопки если передан идентификатор регистрации
        if registration_ref:
            payload["reply_markup"] = {
                "inline_keyboard": [[
                    {
                        "text": "✅ Оплачено",
                        "callback_data": f"pay_{registration_ref}"
                    },
                    {
                        "text": "❌ Отменить",
                        "callback_data": f"cancel_{registration_ref}"
                    }
                ]]
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
        telegram_id_str = request.GET.get("telegram_id")
        game = request.GET.get("game")
        master = request.GET.get("master")
        place = request.GET.get("place")
        day = request.GET.get("day")
        line = request.GET.get("line")
        booking_id = request.GET.get("booking_id")
        time_start_str = request.GET.get("time_start")
        time_end_str = request.GET.get("time_end")
        
        # Валидация обязательных полей
        if not telegram_id_str and not telegram_username:
            return JsonResponse(
                {"error": "telegram_id or telegram_username is required"},
                status=400
            )

        telegram_id = None
        if telegram_id_str:
            try:
                telegram_id = int(telegram_id_str)
            except ValueError:
                return JsonResponse(
                    {"error": "Invalid telegram_id format"},
                    status=400
                )
        elif telegram_username and telegram_username.isdigit():
            telegram_id = int(telegram_username)
        
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
        
        # Создаем или получаем пользователя по telegram_id, иначе по username
        if telegram_id:
            user, user_created = TelegramUser.objects.get_or_create(
                telegram_id=telegram_id,
                defaults={
                    "username": telegram_username,
                    "first_name": name or "",
                    "phone": phone or "",
                }
            )
        else:
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
            
            if telegram_id and user.telegram_id != telegram_id:
                user.telegram_id = telegram_id
                updated = True

            if telegram_username and user.username != telegram_username:
                user.username = telegram_username
                updated = True

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
        send_to_telegram(message, registration.booking_id)
        
        # Если пользователь новый - отправляем приветственное сообщение
        if user_created:
            welcome_message = f"""✨ {user.first_name}, Добро пожаловать на фестиваль трансформационных игр ✨

Благодарим Вас за выбор — выбор расширяться и идти в трансформацию ❤️

Для завершения регистрации необходимо внести 100% оплату участия.

Реквизиты для оплаты: 1234 5678 9012 3456"""
            send_to_telegram(welcome_message)
        
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


def atmafest_app(request):
    return render(request, "atmafest.html")


def _normalize_phone(phone):
    if not phone:
        return ""
    return "".join(ch for ch in str(phone) if ch.isdigit())


def _normalize_telegram_id(telegram_id):
    if telegram_id is None:
        return None
    normalized = "".join(ch for ch in str(telegram_id).strip() if ch.isdigit() or ch == "-")
    if not normalized:
        return None
    try:
        return int(normalized)
    except ValueError:
        return None


def _generate_booking_id():
    return f"ATMA-{int(timezone.now().timestamp() * 1000)}-{uuid.uuid4().hex[:8].upper()}"


def _generate_temp_telegram_id():
    while True:
        candidate = -int(uuid.uuid4().int % 9_000_000_000_000_000_000) - 1
        if not TelegramUser.objects.filter(telegram_id=candidate).exists():
            return candidate


def _get_or_create_user(name, phone, telegram_id):
    normalized_telegram_id = _normalize_telegram_id(telegram_id)

    user = None
    if normalized_telegram_id is not None:
        user = TelegramUser.objects.filter(telegram_id=normalized_telegram_id).first()

    if not user and phone:
        user = TelegramUser.objects.filter(phone=phone).first()

    if user:
        updated = False
        if name and user.first_name != name:
            user.first_name = name
            updated = True
        if phone and user.phone != phone:
            user.phone = phone
            updated = True
        if normalized_telegram_id is not None and user.telegram_id != normalized_telegram_id:
            user.telegram_id = normalized_telegram_id
            updated = True
        if updated:
            user.save(update_fields=["first_name", "phone", "telegram_id", "updated_at"])
        return user

    return TelegramUser.objects.create(
        telegram_id=normalized_telegram_id if normalized_telegram_id is not None else _generate_temp_telegram_id(),
        username=None,
        first_name=name or "Гость",
        phone=phone or "",
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def bookings_collection(request):
    if request.method == "GET":
        registrations = (
            Registration.objects.select_related("user")
            .order_by("-created_at")
        )
        bookings = [
            {
                "bookingId": item.booking_id,
                "timestamp": item.created_at.isoformat(),
                "name": item.user.first_name,
                "phone": item.user.phone,
                "telegramId": item.user.telegram_id,
                "gameTitle": item.game,
                "masterName": item.master,
                "day": item.day,
                "line": item.line,
                "seatNumber": item.place_number,
            }
            for item in registrations
        ]
        return JsonResponse({"success": True, "bookings": bookings})

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    form_data = payload.get("formData") or {}
    master_name = payload.get("masterName")
    game_title = payload.get("gameTitle")
    seat_number = payload.get("seatNumber")
    day = payload.get("day")
    line = payload.get("line")

    name = form_data.get("name")
    phone = form_data.get("phone")
    telegram_id = form_data.get("telegramId") or form_data.get("telegram")
    slot_id = form_data.get("slotId")
    seat_id = form_data.get("seatId")

    if not all([master_name, game_title, seat_number, day, line, slot_id, seat_id]):
        return JsonResponse({"success": False, "error": "Missing required fields"}, status=400)

    try:
        seat_number = int(seat_number)
        day = int(day)
        line = int(line)
        seat_id = int(seat_id)
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "error": "Invalid numeric fields"}, status=400)

    if Registration.objects.filter(slot_id=slot_id, seat_id=seat_id).exists():
        return JsonResponse({"success": False, "error": "Seat is already booked"}, status=400)

    by_phone = 0
    if _normalize_phone(phone):
        by_phone = Registration.objects.filter(day=day, user__phone=phone).count()

    by_telegram_id = 0
    normalized_telegram_id = _normalize_telegram_id(telegram_id)
    if normalized_telegram_id is not None:
        by_telegram_id = Registration.objects.filter(day=day, user__telegram_id=normalized_telegram_id).count()

    if max(by_phone, by_telegram_id) >= 2:
        return JsonResponse({"success": False, "error": "MAX_PER_DAY"}, status=400)

    user = _get_or_create_user(name=name, phone=phone, telegram_id=telegram_id)
    booking_id = _generate_booking_id()

    registration = Registration.objects.create(
        user=user,
        booking_id=booking_id,
        slot_id=slot_id,
        seat_id=seat_id,
        game=game_title,
        master=master_name,
        place_number=seat_number,
        day=day,
        line=line,
        time_start=time(0, 0),
        time_end=time(0, 0),
        created_at=timezone.now(),
    )

    message = format_registration_message(registration, user, True)
    send_to_telegram(message, registration.booking_id)

    return JsonResponse({"success": True, "bookingId": booking_id}, status=201)


@require_http_methods(["GET"])
def bookings_seats(request, slot_id):
    seat_ids = list(
        Registration.objects.filter(slot_id=slot_id)
        .exclude(seat_id__isnull=True)
        .values_list("seat_id", flat=True)
    )
    return JsonResponse({"success": True, "bookedSeats": seat_ids})


@csrf_exempt
@require_http_methods(["DELETE"])
def booking_detail(request, booking_id):
    registration = Registration.objects.filter(booking_id=booking_id).first()
    if not registration:
        return JsonResponse({"success": False, "error": "Booking not found"}, status=404)

    registration.delete()
    return JsonResponse({"success": True})