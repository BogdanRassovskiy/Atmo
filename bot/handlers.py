from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
import requests
from django.conf import settings
import traceback

router = Router()

@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer("Бот работает.")

@router.callback_query(F.data.startswith("pay_") | F.data.startswith("cancel_"))
async def payment_callback_handler(callback: CallbackQuery):
    print(f"=== Callback received: {callback.data} ===")
    
    # Всегда отвечаем на callback сразу, чтобы убрать "часики"
    await callback.answer("Обрабатываю...")
    
    try:
        # Импортируем здесь чтобы избежать circular import
        from bot.models import Registration
        
        action, registration_id = callback.data.split('_')
        registration_id = int(registration_id)
        print(f"Action: {action}, Registration ID: {registration_id}")
        
        # Получаем регистрацию
        try:
            registration = Registration.objects.get(id=registration_id)
            print(f"Registration found: {registration.booking_id}")
        except Registration.DoesNotExist:
            print("Registration not found!")
            await callback.message.answer("❌ Регистрация не найдена")
            return
        
        # Обновляем статус оплаты
        if action == 'pay':
            registration.is_paid = True
            status_text = "\n\n<b>✅ Статус: Оплачено</b>"
            print("Setting is_paid = True")
            
            # Делаем запрос на внешний URL
            try:
                response = requests.post(
                    "https://atmafest.vercel.app/",
                    json={
                        "registration_id": registration.id,
                        "booking_id": registration.booking_id,
                        "status": "paid"
                    },
                    timeout=5
                )
                print(f"External API response: {response.status_code}")
            except Exception as e:
                print(f"Failed to notify atmafest: {e}")
        else:  # cancel
            registration.is_paid = False
            status_text = "\n\n<b>❌ Статус: Отменено</b>"
            print("Setting is_paid = False")
        
        registration.save()
        print("Registration saved")
        
        # Обновляем сообщение
        new_text = callback.message.text + status_text
        await callback.message.edit_text(
            text=new_text,
            parse_mode="HTML",
            reply_markup=callback.message.reply_markup
        )
        print("Message updated")
        
    except Exception as e:
        print(f"ERROR in payment callback: {e}")
        print(traceback.format_exc())
        await callback.message.answer(f"❌ Произошла ошибка: {str(e)}")