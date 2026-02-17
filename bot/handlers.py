from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.filters import CommandStart
from asgiref.sync import sync_to_async
import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Max
import traceback
from bot.models import Registration, TelegramUser

router = Router()

MODE_TEXT_ONE_DAY = "я хочу прийти на 1 день"
MODE_TEXT_TWO_DAYS = "я хочу прийти на 2 дня"
REGISTRATION_NUMBER_START = 1104000


def _build_participation_mode_keyboard(days):
    next_days = 1 if days == 2 else 2
    label = MODE_TEXT_ONE_DAY if next_days == 1 else MODE_TEXT_TWO_DAYS
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label)]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

@router.message(CommandStart())
async def start_handler(message: Message, db_user: TelegramUser):
    # Проверяем есть ли параметр после /start
    if message.text and len(message.text.split()) > 1:
        param = message.text.split()[1]
        if param == "get_my_id":
            await message.answer(f"<code>{message.from_user.id}</code>", parse_mode="HTML")
            return
        if param == "pay":
            payment_text = (
                "Для завершения регистрации необходимо внести 100% оплату участия.\n\n"
                "Реквизиты для оплаты: 1234 5678 9012 3456\n\n"
                "После оплаты отправьте скриншот в этот чат."
            )
            await sync_to_async(_set_user_step_sync)(db_user.id, "awaiting_payment_screenshot")
            await message.answer(
                payment_text,
                reply_markup=_build_participation_mode_keyboard(db_user.participation_days),
            )
            return

    await message.answer(
        "Бот работает. Добро пожаловать!",
        reply_markup=_build_participation_mode_keyboard(db_user.participation_days),
    )

def _resolve_user_registrations_sync(db_user_id, username):
    user = TelegramUser.objects.get(id=db_user_id)
    registrations = Registration.objects.filter(user=user)

    if not registrations.exists() and username:
        alt_user = (
            TelegramUser.objects.filter(username__iexact=username)
            .exclude(id=user.id)
            .first()
        )
        if alt_user:
            Registration.objects.filter(user=alt_user).update(user=user)
            registrations = Registration.objects.filter(user=user)

    return {
        "user_id": user.id,
        "total": registrations.count(),
        "unpaid": registrations.filter(is_paid=False).count(),
    }


def _set_user_step_sync(user_id, step):
    TelegramUser.objects.filter(id=user_id).update(step=step)


def _set_participation_days_sync(telegram_id, days):
    user = TelegramUser.objects.filter(telegram_id=telegram_id).first()
    if not user:
        return None
    user.participation_days = days
    user.save(update_fields=["participation_days", "updated_at"])
    return user.participation_days


def _get_paid_registrations_count_by_telegram_id_sync(telegram_id):
    user = TelegramUser.objects.filter(telegram_id=telegram_id).first()
    if not user:
        return None
    return Registration.objects.filter(user_id=user.id, is_paid=True).count()


def _set_participation_days_with_rules_sync(telegram_id, target_days):
    user = TelegramUser.objects.filter(telegram_id=telegram_id).first()
    if not user:
        return None

    previous_participation_days = user.participation_days
    paid_count = Registration.objects.filter(user_id=user.id, is_paid=True).count()

    if target_days == 1 and paid_count > 2:
        return {
            "success": False,
            "error": "PAID_TOO_MANY_FOR_SWITCH",
            "paid_count": paid_count,
            "previous_participation_days": previous_participation_days,
            "participation_days": user.participation_days,
        }

    user.participation_days = target_days
    user.save(update_fields=["participation_days", "updated_at"])
    return {
        "success": True,
        "paid_count": paid_count,
        "previous_participation_days": previous_participation_days,
        "participation_days": user.participation_days,
    }


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


def _get_or_assign_registration_number_and_games_sync(user_id):
    with transaction.atomic():
        user = TelegramUser.objects.select_for_update().get(id=user_id)
        if user.registration_number is None:
            max_number = TelegramUser.objects.exclude(registration_number__isnull=True).aggregate(
                max_num=Max("registration_number")
            )["max_num"]
            next_number = (max_number + 1) if max_number is not None else REGISTRATION_NUMBER_START
            user.registration_number = next_number
            user.save(update_fields=["registration_number", "updated_at"])

        paid_regs = Registration.objects.filter(user_id=user.id, is_paid=True).order_by("day", "line", "created_at")
        games_map = {}
        for reg in paid_regs:
            key = (reg.day, reg.line)
            if key not in games_map:
                games_map[key] = reg.game

        return {
            "registration_number": user.registration_number,
            "participation_days": user.participation_days,
            "games_map": games_map,
        }


@router.message(F.text.in_([MODE_TEXT_ONE_DAY, MODE_TEXT_TWO_DAYS]))
async def participation_mode_text_handler(message: Message, db_user: TelegramUser):
    target_days = 1 if message.text == MODE_TEXT_ONE_DAY else 2
    update_result = await sync_to_async(_set_participation_days_with_rules_sync)(db_user.telegram_id, target_days)
    if update_result is None:
        await message.answer("Пользователь не найден")
        return

    if not update_result["success"] and update_result["error"] == "PAID_TOO_MANY_FOR_SWITCH":
        await message.answer(
            "Нельзя переключиться на 1 день: у вас уже оплачено больше 2 игр.",
            reply_markup=_build_participation_mode_keyboard(update_result["participation_days"]),
        )
        return

    previous_days = update_result.get("previous_participation_days")
    current_days = update_result["participation_days"]
    mode_text = "Режим участия обновлен: 1 день" if current_days == 1 else "Режим участия обновлен: 2 дня"
    await message.answer(
        mode_text,
        reply_markup=_build_participation_mode_keyboard(current_days),
    )

    if previous_days == 2 and current_days == 1 and update_result.get("paid_count") == 2:
        completion_payload = await sync_to_async(_get_or_assign_registration_number_and_games_sync)(
            db_user.id
        )
        completion_message = _build_completion_message(
            registration_number=completion_payload["registration_number"],
            participation_days=completion_payload["participation_days"],
            games_map=completion_payload["games_map"],
        )
        await message.answer(completion_message)


def _get_latest_unpaid_registration_ref_sync(user_id):
    registration = (
        Registration.objects.filter(user_id=user_id, is_paid=False)
        .order_by("-created_at")
        .first()
    )
    return registration.booking_id if registration else None


def _build_payment_keyboard(registration_ref):
    if not registration_ref:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Оплачено", callback_data=f"pay_{registration_ref}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_{registration_ref}"),
        ]]
    )


@router.message()
async def echo_handler(message: Message, db_user: TelegramUser):
    """Обработчик всех остальных сообщений"""
    if db_user.step == "awaiting_payment_screenshot":
        if message.photo:
            registration_ref = await sync_to_async(_get_latest_unpaid_registration_ref_sync)(
                db_user.id
            )
            caption = (
                "Оплата от пользователя\n"
                f"ID: {message.from_user.id}\n"
                f"Username: @{message.from_user.username or '-'}"
            )
            await message.bot.send_photo(
                chat_id=settings.TELEGRAM_CHAT_ID,
                photo=message.photo[-1].file_id,
                caption=caption,
                reply_markup=_build_payment_keyboard(registration_ref),
            )
            await sync_to_async(_set_user_step_sync)(db_user.id, "start")
            await message.answer("Спасибо! Скриншот оплаты отправлен на проверку.")
            return

        if message.document and (message.document.mime_type or "").startswith("image/"):
            registration_ref = await sync_to_async(_get_latest_unpaid_registration_ref_sync)(
                db_user.id
            )
            caption = (
                "Оплата от пользователя\n"
                f"ID: {message.from_user.id}\n"
                f"Username: @{message.from_user.username or '-'}"
            )
            await message.bot.send_document(
                chat_id=settings.TELEGRAM_CHAT_ID,
                document=message.document.file_id,
                caption=caption,
                reply_markup=_build_payment_keyboard(registration_ref),
            )
            await sync_to_async(_set_user_step_sync)(db_user.id, "start")
            await message.answer("Спасибо! Скриншот оплаты отправлен на проверку.")
            return

        await message.answer("Пожалуйста, пришлите скриншот оплаты файлом или фото.")
        return

    user_info = await sync_to_async(_resolve_user_registrations_sync)(
        db_user.id,
        message.from_user.username,
    )

    if user_info["unpaid"] > 0:
        payment_text = (
            "Для завершения регистрации необходимо внести 100% оплату участия.\n\n"
            "Реквизиты для оплаты: 1234 5678 9012 3456\n\n"
            "После оплаты отправьте скриншот в этот чат."
        )
        await sync_to_async(_set_user_step_sync)(db_user.id, "awaiting_payment_screenshot")
        await message.answer(
            payment_text,
            reply_markup=_build_participation_mode_keyboard(db_user.participation_days),
        )
        return

    if message.text:
        await message.answer(
            f"Вы написали: {message.text}\n\n"
            "Бот работает в режиме приема регистраций."
        )
        return

    await message.answer("Бот работает в режиме приема регистраций.")


@router.callback_query(F.data.startswith("mode_"))
async def participation_mode_callback_handler(callback: CallbackQuery):
    try:
        _, days_value = callback.data.split("_", 1)
        if days_value not in {"1", "2"}:
            await callback.answer("Некорректный режим", show_alert=True)
            return

        selected_days = int(days_value)
        update_result = await sync_to_async(_set_participation_days_with_rules_sync)(
            callback.from_user.id,
            selected_days,
        )

        if update_result is None:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        if not update_result["success"] and update_result["error"] == "PAID_TOO_MANY_FOR_SWITCH":
            await callback.answer(
                "Нельзя переключиться на 1 день: уже оплачено больше 2 игр",
                show_alert=True,
            )
            return

        previous_days = update_result.get("previous_participation_days")
        current_days = update_result["participation_days"]

        mode_text = "Режим участия обновлен: 1 день" if current_days == 1 else "Режим участия обновлен: 2 дня"

        if callback.message:
            await callback.message.answer(mode_text)

            if previous_days == 2 and current_days == 1 and update_result.get("paid_count") == 2:
                db_user = await sync_to_async(TelegramUser.objects.filter(telegram_id=callback.from_user.id).first)()
                if db_user:
                    completion_payload = await sync_to_async(_get_or_assign_registration_number_and_games_sync)(
                        db_user.id
                    )
                    completion_message = _build_completion_message(
                        registration_number=completion_payload["registration_number"],
                        participation_days=completion_payload["participation_days"],
                        games_map=completion_payload["games_map"],
                    )
                    await callback.message.answer(completion_message)

        await callback.answer("Режим обновлен")
    except Exception as e:
        print(f"ERROR in mode callback: {e}")
        print(traceback.format_exc())
        await callback.answer("Ошибка обновления режима", show_alert=True)

@router.callback_query(F.data.startswith("pay_") | F.data.startswith("cancel_"))
async def payment_callback_handler(callback: CallbackQuery):
    print(f"=== Callback received: {callback.data} ===")
    
    try:
        # Сохраняем текст сообщения сразу (для фото используем caption)
        original_text = callback.message.text or callback.message.caption or ""
        
        # Всегда отвечаем на callback сразу, чтобы убрать "часики"
        await callback.answer("Обрабатываю...")
        
        # Импортируем здесь чтобы избежать circular import
        from bot.models import Registration
        
        action, registration_ref = callback.data.split('_', 1)
        print(f"Action: {action}, Registration ref: {registration_ref}")
        
        # Функция для обновления регистрации (полностью синхронная)
        def update_registration_sync(reg_ref, action_name):
            try:
                registration = None

                # Новый формат: booking_id в callback_data
                if reg_ref and not str(reg_ref).isdigit():
                    registration = Registration.objects.filter(booking_id=reg_ref).first()

                # Легаси-формат: numeric Registration.id в callback_data
                if registration is None and str(reg_ref).isdigit():
                    registration = Registration.objects.filter(id=int(reg_ref)).first()

                if registration is None:
                    raise Registration.DoesNotExist

                was_paid = registration.is_paid
                if action_name == 'pay':
                    registration.is_paid = True
                    registration.save()
                    deleted = False
                else:
                    registration.delete()
                    deleted = True

                return {
                    "success": True,
                    "booking_id": registration.booking_id,
                    "registration_id": registration.id,
                    "user_telegram_id": registration.user.telegram_id,
                    "user_username": registration.user.username,
                    "user_id": registration.user_id,
                    "was_paid": was_paid,
                    "deleted": deleted,
                }
            except Registration.DoesNotExist:
                return {"success": False, "error": "not_found"}

        def get_paid_registrations_count_sync(user_id):
            return Registration.objects.filter(user_id=user_id, is_paid=True).count()

        def get_required_paid_count_sync(user_id):
            user = TelegramUser.objects.filter(id=user_id).first()
            if user and user.participation_days == 1:
                return 2
            return 4
        
        # Обновляем регистрацию
        result = await sync_to_async(update_registration_sync)(registration_ref, action)
        
        if not result["success"]:
            print("Registration not found!")
            await callback.message.answer("❌ Регистрация не найдена")
            return
        
        print(f"Registration updated: {result['booking_id']}")
        
        # Формируем статус
        if action == 'pay':
            status_text = "\n\n<b>✅ Статус: Оплачено</b>"
            print("Status set to: Paid")
            
            # Делаем запрос на внешний URL
            try:
                response = requests.post(
                    "https://atmafest.vercel.app/#games",
                    json={
                        "registration_id": result["registration_id"],
                        "booking_id": result["booking_id"],
                        "status": "paid"
                    },
                    timeout=5
                )
                print(f"External API response: {response.status_code}")
            except Exception as e:
                print(f"Failed to notify atmafest: {e}")

            if result.get("user_telegram_id"):
                link = "https://atmafest.vercel.app/#games"
                username = result.get("user_username") or "-"
                notify_text = (
                    "✅ Оплата подтверждена.\n"
                    "Перейдите по ссылке и выберите еще игр:"
                )
                link_keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="Перейти на сайт", url=link)]]
                )
                try:
                    await callback.bot.send_message(
                        result["user_telegram_id"],
                        notify_text,
                        reply_markup=link_keyboard,
                    )
                except Exception as e:
                    print(f"Failed to notify user about payment: {e}")

            if result.get("user_telegram_id") and not result.get("was_paid"):
                paid_count = await sync_to_async(get_paid_registrations_count_sync)(
                    result["user_id"]
                )
                required_paid_count = await sync_to_async(get_required_paid_count_sync)(
                    result["user_id"]
                )
                if paid_count == required_paid_count:
                    completion_payload = await sync_to_async(_get_or_assign_registration_number_and_games_sync)(
                        result["user_id"]
                    )
                    completion_message = _build_completion_message(
                        registration_number=completion_payload["registration_number"],
                        participation_days=completion_payload["participation_days"],
                        games_map=completion_payload["games_map"],
                    )
                    try:
                        await callback.bot.send_message(
                            result["user_telegram_id"],
                            completion_message,
                        )
                    except Exception as e:
                        print(f"Failed to notify user about completed registrations: {e}")
        else:  # cancel
            status_text = "\n\n<b>❌ Статус: Отменено (заявка удалена)</b>"
            print("Status set to: Cancelled")

            if result.get("user_telegram_id"):
                cancel_text = (
                    "❌ Ваша заявка отменена администратором.\n"
                    "Место освобождено.\n\n"
                    "Если это произошло по ошибке, пожалуйста, зарегистрируйтесь снова на сайте."
                )
                try:
                    await callback.bot.send_message(
                        result["user_telegram_id"],
                        cancel_text,
                    )
                except Exception as e:
                    print(f"Failed to notify user about cancellation: {e}")
        
        # Обновляем сообщение и убираем клавиатуру
        new_text = original_text + status_text
        if callback.message.photo or callback.message.document:
            await callback.message.edit_caption(
                caption=new_text,
                parse_mode="HTML",
                reply_markup=None,
            )
        else:
            await callback.message.edit_text(
                text=new_text,
                parse_mode="HTML",
                reply_markup=None,
            )
        print("Message updated successfully")
        
    except Exception as e:
        print(f"ERROR in payment callback: {e}")
        print(traceback.format_exc())
        try:
            await callback.message.answer(f"❌ Произошла ошибка: {str(e)}")
        except:
            pass
        
    except Exception as e:
        print(f"ERROR in payment callback: {e}")
        print(traceback.format_exc())
        await callback.message.answer(f"❌ Произошла ошибка: {str(e)}")
        
    except Exception as e:
        print(f"ERROR in payment callback: {e}")
        print(traceback.format_exc())
        await callback.message.answer(f"❌ Произошла ошибка: {str(e)}")