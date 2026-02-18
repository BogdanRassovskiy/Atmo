from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.conf import settings
from django.db import transaction
from django.db.models import Max
from asgiref.sync import async_to_sync
from aiogram.types import Update
from .loader import bot, dp
from .models import TelegramUser, Registration
import json
import requests
import uuid
from datetime import datetime, time


REGISTRATION_NUMBER_START = 1104000
WEB_USER_COOKIE_NAME = "atmo_web_user_id"
WEB_USER_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def _set_web_user_cookie(response, user):
    if user and user.web_user_id:
        response.set_cookie(
            WEB_USER_COOKIE_NAME,
            str(user.web_user_id),
            max_age=WEB_USER_COOKIE_MAX_AGE,
            secure=not settings.DEBUG,
            httponly=True,
            samesite="Lax",
        )
    return response


def _paid_mode_label(user):
    if user.paid_participation_days == 2:
        return "✅ Оплачен режим: 2 дня (600 000 сум)"
    if user.paid_participation_days == 1:
        return "✅ Оплачен режим: 1 день (450 000 сум)"
    return "❌ Режим участия не оплачен"


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
<b>💼 Режим:</b> {_paid_mode_label(user)}

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
        auto_paid = user.paid_participation_days in (1, 2)
        defaults = {
            "booking_id": booking_id,
            "master": master,
            "place_number": int(place),
            "day": int(day),
            "line": int(line),
            "time_start": time_start or time(0, 0),
            "time_end": time_end or time(0, 0),
            "created_at": timezone.now(),
        }
        if auto_paid:
            defaults["is_paid"] = True

        registration, registration_created = Registration.objects.update_or_create(
            user=user,
            game=game,
            defaults=defaults,
        )
        
        # Отправляем уведомление в Telegram
        message = format_registration_message(registration, user, registration_created)
        send_to_telegram(message, None if auto_paid else registration.booking_id)
        if registration_created:
            _send_completion_message_if_reached(user)
        
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


def _assign_next_registration_number(user_id):
    with transaction.atomic():
        user = TelegramUser.objects.select_for_update().get(id=user_id)
        if user.registration_number is not None:
            return user.registration_number
        max_number = TelegramUser.objects.exclude(registration_number__isnull=True).aggregate(
            max_num=Max("registration_number")
        )["max_num"]
        next_number = (max_number + 1) if max_number is not None else REGISTRATION_NUMBER_START
        user.registration_number = next_number
        user.save(update_fields=["registration_number", "updated_at"])
        return next_number


def _build_completion_message(registration_number, participation_days, games_map):
    day1_line1 = games_map.get((1, 1), "-")
    day1_line2 = games_map.get((1, 2), "-")

    parts = [
        "✨ Регистрация завершена ✨",
        "",
        "Благодарим за оплату, Ваше участие подтверждено.",
        "",
        f"Ваш регистрационный номер: {registration_number}",
        "",
        "Игры:",
        "1 день (11:00 - 13:00)",
        f"1 линия: {day1_line1}",
        f"2 линия: {day1_line2}",
        "",
        "Обед: 13:00 - 14:30",
        "",
    ]

    if participation_days == 2:
        day2_line1 = games_map.get((2, 1), "-")
        day2_line2 = games_map.get((2, 2), "-")
        parts.extend([
            "2 день (14:30 - 16:30)",
            f"1 линия: {day2_line1}",
            f"2: линия: {day2_line2}",
            "",
        ])

    parts.extend([
        "❗️Необходимо придти к 10:30 ",
        "",
        "Адрес: fakestreet 742",
        "",
        "Рады, что Вы с нами в этом пространстве трансформации.",
        "",
        "До скорой встречи на фестивале ✨",
    ])

    return "\n".join(parts)


def _send_user_telegram_message(telegram_id, message):
    if not telegram_id or telegram_id < 0:
        return False
    try:
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": telegram_id,
            "text": message,
            "parse_mode": "HTML",
        }
        res = requests.post(url, json=payload, timeout=5)
        res.raise_for_status()
        return True
    except Exception as e:
        print(f"Failed to send user telegram message: {e}")
        return False


def _send_completion_message_if_reached(user):
    if user.paid_participation_days not in (1, 2):
        return False

    required_games = _get_allowed_games_by_paid_mode(user)
    total_registrations = Registration.objects.filter(user=user).count()
    if total_registrations != required_games:
        return False

    registration_number = _assign_next_registration_number(user.id)
    regs = Registration.objects.filter(user=user).order_by("day", "line", "created_at")
    games_map = {}
    for reg in regs:
        key = (reg.day, reg.line)
        if key not in games_map:
            games_map[key] = reg.game

    completion_message = _build_completion_message(
        registration_number=registration_number,
        participation_days=user.participation_days,
        games_map=games_map,
    )
    return _send_user_telegram_message(user.telegram_id, completion_message)


def _resolve_times_by_line(line):
    if line == 1:
        return time(11, 0), time(13, 0)
    if line == 2:
        return time(14, 30), time(16, 30)
    return time(0, 0), time(0, 0)


def _generate_temp_telegram_id():
    while True:
        candidate = -int(uuid.uuid4().int % 9_000_000_000_000_000_000) - 1
        if not TelegramUser.objects.filter(telegram_id=candidate).exists():
            return candidate


def _normalize_web_user_id(raw_web_user_id):
    if not raw_web_user_id:
        return None
    try:
        return uuid.UUID(str(raw_web_user_id).strip())
    except (ValueError, TypeError, AttributeError):
        return None


def _parse_participation_days(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed in (1, 2) else None


def _get_allowed_games_by_paid_mode(user):
    return 4 if user.paid_participation_days == 2 else 2


def _apply_participation_mode(user, participation_days):
    target_days = _parse_participation_days(participation_days)
    if target_days is None:
        return None

    if user.participation_days == target_days:
        if not user.participation_days_selected:
            user.participation_days_selected = True
            user.save(update_fields=["participation_days_selected", "updated_at"])
        return None

    total_registrations = Registration.objects.filter(user=user).count()
    if total_registrations > 2:
        return {
            "success": False,
            "error": "MODE_SWITCH_LOCKED",
            "currentMode": user.participation_days,
            "requestedMode": target_days,
            "totalRegistrations": total_registrations,
        }

    user.participation_days = target_days
    user.participation_days_selected = True
    user.save(update_fields=["participation_days", "participation_days_selected", "updated_at"])
    return None


def _get_or_create_user(name, phone, telegram_id, web_user_id=None, participation_days=None):
    normalized_telegram_id = _normalize_telegram_id(telegram_id)
    normalized_web_user_id = _normalize_web_user_id(web_user_id)
    normalized_participation_days = _parse_participation_days(participation_days)

    user = None
    if normalized_web_user_id is not None:
        user = TelegramUser.objects.filter(web_user_id=normalized_web_user_id).first()

    if normalized_telegram_id is not None:
        user = user or TelegramUser.objects.filter(telegram_id=normalized_telegram_id).first()

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
        if normalized_web_user_id is not None and user.web_user_id is None:
            user.web_user_id = normalized_web_user_id
            updated = True
        if updated:
            user.save(
                update_fields=[
                    "first_name",
                    "phone",
                    "telegram_id",
                    "web_user_id",
                    "updated_at",
                ]
            )
        return user

    return TelegramUser.objects.create(
        telegram_id=normalized_telegram_id if normalized_telegram_id is not None else _generate_temp_telegram_id(),
        web_user_id=normalized_web_user_id,
        username=None,
        first_name=name or "Гость",
        phone=phone or "",
        participation_days=normalized_participation_days or 2,
        participation_days_selected=normalized_participation_days in (1, 2),
    )


@require_http_methods(["GET"])
def bookings_profile(request):
    web_user_id = _normalize_web_user_id(request.COOKIES.get(WEB_USER_COOKIE_NAME))
    if web_user_id is None:
        return JsonResponse(
            {
                "success": True,
                "profile": {
                    "hasPaidMode": False,
                    "paidParticipationDays": 0,
                    "participationDays": None,
                    "name": "",
                    "phone": "",
                    "telegramId": "",
                },
            }
        )

    user = TelegramUser.objects.filter(web_user_id=web_user_id).first()
    if not user:
        return JsonResponse(
            {
                "success": True,
                "profile": {
                    "hasPaidMode": False,
                    "paidParticipationDays": 0,
                    "participationDays": None,
                    "name": "",
                    "phone": "",
                    "telegramId": "",
                },
            }
        )

    response = JsonResponse(
        {
            "success": True,
            "profile": {
                "hasPaidMode": user.paid_participation_days in (1, 2),
                "paidParticipationDays": user.paid_participation_days,
                "participationDays": user.participation_days,
                "name": user.first_name or "",
                "phone": user.phone or "",
                "telegramId": "" if user.telegram_id < 0 else str(user.telegram_id),
            },
        }
    )
    return _set_web_user_cookie(response, user)


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
    participation_days = form_data.get("participationDays")
    slot_id = form_data.get("slotId")
    seat_id = form_data.get("seatId")
    cookie_web_user_id = _normalize_web_user_id(request.COOKIES.get(WEB_USER_COOKIE_NAME))

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

    user = _get_or_create_user(
        name=name,
        phone=phone,
        telegram_id=telegram_id,
        web_user_id=cookie_web_user_id,
        participation_days=participation_days,
    )

    if user.web_user_id is None:
        user.web_user_id = uuid.uuid4()
        user.save(update_fields=["web_user_id", "updated_at"])

    mode_error = _apply_participation_mode(user, participation_days)
    if mode_error:
        response = JsonResponse(mode_error, status=400)
        return _set_web_user_cookie(response, user)

    total_registrations = Registration.objects.filter(user=user).count()
    allowed_games = _get_allowed_games_by_paid_mode(user)
    if total_registrations >= allowed_games:
        response = JsonResponse(
            {
                "success": False,
                "error": "MODE_GAMES_LIMIT_REACHED",
                "allowedGames": allowed_games,
                "paidParticipationDays": user.paid_participation_days,
                "currentMode": user.participation_days,
            },
            status=400,
        )
        return _set_web_user_cookie(response, user)

    booked_days = list(
        Registration.objects.filter(user=user)
        .values_list("day", flat=True)
        .distinct()
    )
    if user.participation_days == 1 and booked_days and day not in booked_days:
        response = JsonResponse(
            {
                "success": False,
                "error": "ONE_DAY_MODE_DAY_LOCK",
                "lockedDay": min(booked_days),
            },
            status=400,
        )
        return _set_web_user_cookie(response, user)

    if Registration.objects.filter(user=user, day=day, line=line).exists():
        response = JsonResponse({"success": False, "error": "ALREADY_BOOKED_THIS_TIME"}, status=400)
        return _set_web_user_cookie(response, user)

    _assign_next_registration_number(user.id)
    time_start, time_end = _resolve_times_by_line(line)

    booking_id = _generate_booking_id()

    auto_paid = user.paid_participation_days in (1, 2)

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
        time_start=time_start,
        time_end=time_end,
        is_paid=auto_paid,
        created_at=timezone.now(),
    )

    message = format_registration_message(registration, user, True)
    send_to_telegram(message, None if auto_paid else registration.booking_id)
    _send_completion_message_if_reached(user)

    response = JsonResponse(
        {
            "success": True,
            "bookingId": booking_id,
            "profile": {
                "hasPaidMode": user.paid_participation_days in (1, 2),
                "paidParticipationDays": user.paid_participation_days,
                "participationDays": user.participation_days,
                "name": user.first_name or "",
                "phone": user.phone or "",
                "telegramId": "" if user.telegram_id < 0 else str(user.telegram_id),
            },
        },
        status=201,
    )
    return _set_web_user_cookie(response, user)


@require_http_methods(["GET"])
def bookings_seats(request, slot_id):
    seat_ids = list(
        Registration.objects.filter(slot_id=slot_id)
        .exclude(seat_id__isnull=True)
        .values_list("seat_id", flat=True)
    )
    return JsonResponse({"success": True, "bookedSeats": seat_ids})


@require_http_methods(["GET"])
def bookings_seats_all(request):
    rows = (
        Registration.objects.exclude(slot_id__isnull=True)
        .exclude(seat_id__isnull=True)
        .values_list("slot_id", "seat_id")
    )

    grouped = {}
    for slot_id, seat_id in rows:
        if slot_id not in grouped:
            grouped[slot_id] = []
        grouped[slot_id].append(seat_id)

    return JsonResponse({"success": True, "bookedSeats": grouped})


@csrf_exempt
@require_http_methods(["DELETE"])
def booking_detail(request, booking_id):
    registration = Registration.objects.filter(booking_id=booking_id).first()
    if not registration:
        return JsonResponse({"success": False, "error": "Booking not found"}, status=404)

    registration.delete()
    return JsonResponse({"success": True})