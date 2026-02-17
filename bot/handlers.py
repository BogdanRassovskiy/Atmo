from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from asgiref.sync import sync_to_async
import requests
from django.conf import settings
import traceback
from bot.models import Registration, TelegramUser

router = Router()

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
            await message.answer(payment_text)
            return
    
    await message.answer("Бот работает. Добро пожаловать!")

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
        await message.answer(payment_text)
        return

    if message.text:
        await message.answer(
            f"Вы написали: {message.text}\n\n"
            "Бот работает в режиме приема регистраций."
        )
        return

    await message.answer("Бот работает в режиме приема регистраций.")

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
                if paid_count == 4:
                    four_games_message = (
                        "✨ Регистрация завершена ✨\n\n"
                        "Благодарим за оплату, Ваше участие подтверждено.\n\n"
                        f"Ваш регистрационный номер: {result['registration_id']}\n\n"
                        "Игры:\n"
                        "1 день -  (11:00 - 13:00)\n"
                        "2 день - (14:30 - 16:30)\n\n"
                        "Обед: 13:00 - 14:30\n\n"
                        "❗️Необходимо придти к 10:30 \n\n"
                        "Адрес:\n\n"
                        "Рады, что Вы с нами в этом пространстве трансформации.\n\n"
                        "До скорой встречи на фестивале ✨"
                    )
                    try:
                        await callback.bot.send_message(
                            result["user_telegram_id"],
                            four_games_message,
                        )
                    except Exception as e:
                        print(f"Failed to notify user about 4 paid regs: {e}")
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