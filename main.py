from aiogram import Bot, Dispatcher, types, executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.dispatcher.filters import Text
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from datetime import datetime, timedelta
import pandas as pd
import os
import asyncio

API_TOKEN = 'YOUR_TOKEN_HERE'
ADMIN_ID = 123456789

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

class ShiftStates(StatesGroup):
    WaitingForReason = State()

users_data = {}

main_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
main_keyboard.add(
    KeyboardButton("Начал 🏭"), KeyboardButton("Закончил 🏡")
)
main_keyboard.add(
    KeyboardButton("Мой статус"), KeyboardButton("Инструкция")
)

admin_keyboard = main_keyboard.add(KeyboardButton("Отчет 📈"), KeyboardButton("Статус смены"))

# Функция — проверка рабочего дня

def is_working_day():
    return datetime.today().weekday() < 5  # 0=Monday, ..., 6=Sunday

# Проверка времени на начало смены, раннее/позднее

def get_shift_status():
    lines = []
    for user_id, data in users_data.items():
        username = data.get("username", str(user_id))
        start = data.get("start", "—")
        end = data.get("end", "—")
        lines.append(f"{username}:\nСмена начата в: {start}\nСмена завершена в: {end}\n")
    return "\n".join(lines)

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Добро пожаловать, админ.", reply_markup=admin_keyboard)
    else:
        await message.answer("Привет! Используй кнопки ниже для учёта смены.", reply_markup=main_keyboard)

@dp.message_handler(Text(equals="Начал 🏭"))
async def shift_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    now = datetime.now()
    weekday = now.weekday()
    time_now = now.strftime("%H:%M")
    
    if user_id not in users_data:
        users_data[user_id] = {"username": message.from_user.full_name, "start": None, "end": None}

    if users_data[user_id].get("start") and not users_data[user_id].get("end"):
        await message.answer("Смена уже начата.")
        return

    # Выходной день — запрашиваем причину
    if weekday >= 5:
        await state.set_state(ShiftStates.WaitingForReason.state)
        await state.update_data(reason_type="weekend_start")
        await message.answer("Сейчас не рабочий день, укажи причину начала смены:")
        return

    if now.time() < datetime.strptime("08:00", "%H:%M").time():
        await state.set_state(ShiftStates.WaitingForReason.state)
        await state.update_data(reason_type="early_start")
        await message.answer("Смена начата раньше 08:00. Укажи причину:")
        return

    if now.time() > datetime.strptime("08:10", "%H:%M").time():
        await state.set_state(ShiftStates.WaitingForReason.state)
        await state.update_data(reason_type="late_start")
        await message.answer("Смена начата позже 08:10. Укажи причину опоздания:")
        return

    users_data[user_id]["start"] = time_now
    users_data[user_id]["end"] = None
    await message.answer("Смена начата. Желаю продуктивного рабочего дня!")

@dp.message_handler(Text(equals="Закончил 🏡"))
async def shift_end(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    now = datetime.now()
    time_now = now.strftime("%H:%M")

    if user_id not in users_data or not users_data[user_id].get("start"):
        await message.answer("Сначала нажми 'Начал 🏭'")
        return

    if users_data[user_id].get("end"):
        await message.answer("Смена уже завершена.")
        return

    if now.time() < datetime.strptime("17:30", "%H:%M").time():
        await state.set_state(ShiftStates.WaitingForReason.state)
        await state.update_data(reason_type="early_end")
        await message.answer("Смена завершена раньше. Укажи причину:")
        return

    if now.time() > datetime.strptime("17:40", "%H:%M").time():
        await state.set_state(ShiftStates.WaitingForReason.state)
        await state.update_data(reason_type="late_end")
        await message.answer("Смена завершена позже. Укажи причину переработки:")
        return

    users_data[user_id]["end"] = time_now
    await message.answer("Спасибо! Желаю хорошего отдыха!")

@dp.message_handler(Text(equals="Инструкция"))
async def send_instruction(message: types.Message):
    await message.answer("📌 Нажми 'Начал 🏭' в начале смены и 'Закончил 🏡' в конце. Если опаздываешь, раньше начинаешь или перерабатываешь — укажи причину.")

@dp.message_handler(Text(equals="Мой статус"))
async def my_status(message: types.Message):
    user_id = message.from_user.id
    data = users_data.get(user_id)
    if not data:
        await message.answer("Данных нет. Нажмите 'Начал 🏭' для начала смены.")
    else:
        await message.answer(f"Смена начата: {data.get('start', '—')}\nЗавершена: {data.get('end', '—')}")

@dp.message_handler(Text(equals="Статус смены"))
async def status_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(get_shift_status())

@dp.message_handler(state=ShiftStates.WaitingForReason)
async def handle_reason(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    reason_type = data.get("reason_type")
    now = datetime.now().strftime("%H:%M")

    if user_id not in users_data:
        users_data[user_id] = {"username": message.from_user.full_name}

    if reason_type in ["early_start", "late_start", "weekend_start"]:
        users_data[user_id]["start"] = now
        users_data[user_id]["end"] = None
        await message.answer("Спасибо, смена начата. Продуктивного дня!")

    elif reason_type in ["early_end", "late_end"]:
        users_data[user_id]["end"] = now
        await message.answer("Спасибо! Хорошего отдыха!")

    await state.finish()

async def scheduled_reminders():
    while True:
        now = datetime.now()
        if now.strftime("%H:%M") == "08:00" and is_working_day():
            await bot.send_message(ADMIN_ID, "🔔 Напоминание: смена должна быть начата. Нажмите 'Начал 🏭'")
        if now.strftime("%H:%M") == "17:30" and is_working_day():
            await bot.send_message(ADMIN_ID, "🔔 Напоминание: смена заканчивается. Не забудьте нажать 'Закончил 🏡'")
        await asyncio.sleep(60)

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(scheduled_reminders())
    executor.start_polling(dp, skip_updates=True)
