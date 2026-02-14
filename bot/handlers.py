from aiogram import Router
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
import requests
from django.conf import settings

router = Router()

@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer("Бот работает.")

@router.callback_query(lambda c: c.data and (c.data.startswith('pay_') or c.data.startswith('cancel_')))
async def payment_callback_handler(callback: CallbackQuery):
    try:
        # Импортируем здесь чтобы избежать circular import
        from bot.models import Registration
        
        action, registration_id = callback.data.split('_')
        registration_id = int(registration_id)
        
        # Получаем регистрацию
        try:
            registration = Registration.objects.get(id=registration_id)
        except Registration.DoesNotExist:
            await callback.answer("Регистрация не найдена", show_alert=True)
            return
        
        # Обновляем статус оплаты
        if action == 'pay':
            registration.is_paid = True
            status_text = "\n\n<b>✅ Статус: Оплачено</b>"
            
            # Делаем запрос на внешний URL
            try:
                requests.post(
                    "https://atmafest.vercel.app/",
                    json={
                        "registration_id": registration.id,
                        "booking_id": registration.booking_id,
                        "status": "paid"
                    },
                    timeout=5
                )
            except Exception as e:
                print(f"Failed to notify atmafest: {e}")
        else:  # cancel
            registration.is_paid = False
            status_text = "\n\n<b>❌ Статус: Отменено</b>"
        
        registration.save()
        
        # Обновляем сообщение
        new_text = callback.message.text + status_text
        await callback.message.edit_text(
            text=new_text,
            parse_mode="HTML",
            reply_markup=callback.message.reply_markup
        )
        
        await callback.answer(f"Статус обновлен: {'Оплачено' if action == 'pay' else 'Отменено'}")
        
    except Exception as e:
        print(f"Error in payment callback: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)