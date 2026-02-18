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
        "paid_participation_days": user.paid_participation_days,
        "participation_days": user.participation_days,
    }


def _set_user_step_sync(user_id, step):
    TelegramUser.objects.filter(id=user_id).update(step=step)


def _set_participation_days_sync(telegram_id, days):
    user = TelegramUser.objects.filter(telegram_id=telegram_id).first()
    if not user:
        return None
    user.participation_days = days
    user.participation_days_selected = True
    user.save(update_fields=["participation_days", "participation_days_selected", "updated_at"])
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
    registrations_count = Registration.objects.filter(user_id=user.id).count()

    if target_days != previous_participation_days and registrations_count > 2:
        return {
            "success": False,
            "error": "MODE_SWITCH_LOCKED",
            "registrations_count": registrations_count,
            "previous_participation_days": previous_participation_days,
            "participation_days": user.participation_days,
        }

    user.participation_days = target_days
    user.participation_days_selected = True
    user.save(update_fields=["participation_days", "participation_days_selected", "updated_at"])
    return {
        "success": True,
        "registrations_count": registrations_count,
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

        paid_regs = Registration.objects.filter(user_id=user.id).order_by("day", "line", "created_at")
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


def _get_mode_payment_status_sync(user_id):
    user = TelegramUser.objects.filter(id=user_id).first()
    if not user:
        return None

    if user.paid_participation_days == 0:
        return {
            "need_payment": True,
            "reason": "NO_MODE_PAYMENT",
            "target_days": user.participation_days,
        }

    if user.paid_participation_days == 1 and user.participation_days == 2:
        return {
            "need_payment": True,
            "reason": "UPGRADE_TO_TWO_DAYS",
            "target_days": 2,
        }

    return {
        "need_payment": False,
        "reason": "MODE_ALREADY_PAID",
        "target_days": user.paid_participation_days,
    }


@router.message(F.text.in_([MODE_TEXT_ONE_DAY, MODE_TEXT_TWO_DAYS]))
async def participation_mode_text_handler(message: Message, db_user: TelegramUser):
    target_days = 1 if message.text == MODE_TEXT_ONE_DAY else 2
    update_result = await sync_to_async(_set_participation_days_with_rules_sync)(db_user.telegram_id, target_days)
    if update_result is None:
        await message.answer("Пользователь не найден")
        return

    if not update_result["success"] and update_result["error"] == "MODE_SWITCH_LOCKED":
        await message.answer(
            "Нельзя изменить вариант участия после регистрации более 2 игр.",
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

    payment_status = await sync_to_async(_get_mode_payment_status_sync)(db_user.id)
    if payment_status and payment_status["need_payment"]:
        if payment_status["reason"] == "UPGRADE_TO_TWO_DAYS":
            payment_text = (
                "Для перехода на режим 2 дня необходимо доплатить до тарифа 600 000 сум.\n\n"
                "Реквизиты для оплаты: 1234 5678 9012 3456\n\n"
                "После оплаты отправьте скриншот в этот чат."
            )
        else:
            amount = "450 000 сум" if payment_status["target_days"] == 1 else "600 000 сум"
            payment_text = (
                "Для завершения регистрации необходимо внести 100% оплату режима участия.\n\n"
                f"Сумма: {amount}\n"
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

        if not update_result["success"] and update_result["error"] == "MODE_SWITCH_LOCKED":
            await callback.answer(
                "Нельзя изменить вариант участия после регистрации более 2 игр",
                show_alert=True,
            )
            return

        previous_days = update_result.get("previous_participation_days")
        current_days = update_result["participation_days"]

        mode_text = "Режим участия обновлен: 1 день" if current_days == 1 else "Режим участия обновлен: 2 дня"

        if callback.message:
            await callback.message.answer(mode_text)


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

        def get_registrations_count_sync(user_id):
            return Registration.objects.filter(user_id=user_id).count()

        def get_required_count_sync(user_id):
            user = TelegramUser.objects.filter(id=user_id).first()
            if user and user.paid_participation_days == 2:
                return 4
            if user and user.paid_participation_days == 1:
                return 2
            return 2

        def set_paid_mode_sync(user_id):
            user = TelegramUser.objects.filter(id=user_id).first()
            if not user:
                return 0
            target_paid_mode = max(user.paid_participation_days, user.participation_days)
            if target_paid_mode != user.paid_participation_days:
                user.paid_participation_days = target_paid_mode
                user.save(update_fields=["paid_participation_days", "updated_at"])
            return user.paid_participation_days
        
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

            paid_mode = await sync_to_async(set_paid_mode_sync)(result["user_id"])
            
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
                try:
                    await callback.bot.send_message(
                        result["user_telegram_id"],
                        f"✅ Оплата режима подтверждена ({'1 день' if paid_mode == 1 else '2 дня'}).",
                    )
                except Exception as e:
                    print(f"Failed to notify user about mode payment: {e}")
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