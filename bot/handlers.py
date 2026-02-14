from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from asgiref.sync import sync_to_async
import requests
from django.conf import settings
import traceback

router = Router()

@router.message(CommandStart())
async def start_handler(message: Message):
    # Проверяем есть ли параметр после /start
    if message.text and len(message.text.split()) > 1:
        param = message.text.split()[1]
        if param == "get_my_id":
            await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>", parse_mode="HTML")
            return
    
    await message.answer("Бот работает. Добро пожаловать!")

@router.message()
async def echo_handler(message: Message):
    """Обработчик всех остальных текстовых сообщений"""
    await message.answer(f"Вы написали: {message.text}\n\nБот работает в режиме приема регистраций.")

@router.callback_query(F.data.startswith("pay_") | F.data.startswith("cancel_"))
async def payment_callback_handler(callback: CallbackQuery):
    print(f"=== Callback received: {callback.data} ===")
    
    try:
        # Сохраняем текст сообщения сразу
        original_text = callback.message.text
        
        # Всегда отвечаем на callback сразу, чтобы убрать "часики"
        await callback.answer("Обрабатываю...")
        
        # Импортируем здесь чтобы избежать circular import
        from bot.models import Registration
        
        action, registration_id = callback.data.split('_')
        registration_id = int(registration_id)
        print(f"Action: {action}, Registration ID: {registration_id}")
        
        # Функция для обновления регистрации (полностью синхронная)
        def update_registration_sync(reg_id, is_paid):
            try:
                registration = Registration.objects.get(id=reg_id)
                registration.is_paid = is_paid
                registration.save()
                return {
                    "success": True,
                    "booking_id": registration.booking_id,
                    "registration_id": registration.id
                }
            except Registration.DoesNotExist:
                return {"success": False, "error": "not_found"}
        
        # Обновляем регистрацию
        result = await sync_to_async(update_registration_sync)(registration_id, action == 'pay')
        
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
                    "https://atmafest.vercel.app/",
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
        else:  # cancel
            status_text = "\n\n<b>❌ Статус: Отменено</b>"
            print("Status set to: Cancelled")
        
        # Обновляем сообщение и убираем клавиатуру
        new_text = original_text + status_text
        await callback.message.edit_text(
            text=new_text,
            parse_mode="HTML",
            reply_markup=None
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