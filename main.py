import asyncio
import logging
import os
import json
import pandas as pd
from datetime import datetime, time
import pytz
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, Message
from aiogram.exceptions import TelegramBadRequest
from aiogram.types.input_file import FSInputFile

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_TOKEN = '8369016774:AAE09_ALathLnzKdHQF7qAbpL4_mJ9wg8IY'
ADMIN_IDS = [104653853]  # Ваш Telegram ID

data = {}

def load_data():
    global data
    try:
        with open('data.json', 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}

def save_data():
    with open('data.json', 'w') as f:
        json.dump(data, f, default=str)

def get_keyboard(is_admin=False):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(
        KeyboardButton(text="Начал 🏭"),
        KeyboardButton(text="Закончил 🏡")
    )
    keyboard.add(
        KeyboardButton(text="Мой статус"),
        KeyboardButton(text="Инструкция 📖")
    )
    if is_admin:
        keyboard.add(
            KeyboardButton(text="Статус📍"),
            KeyboardButton(text="Отчет 📈"),
            KeyboardButton(text="Сбросить данные")
        )
    return keyboard

def is_admin(user_id):
    return user_id in ADMIN_IDS

def within_working_hours():
    moscow_tz = pytz.timezone('Europe/Moscow')
    now = datetime.now(moscow_tz).time()
    return time(8, 0) <= now <= time(17, 30)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    load_data()
    keyboard = get_keyboard(is_admin(message.from_user.id))
    await message.answer("Желаю продуктивного рабочего дня!", reply_markup=keyboard)

@dp.message(lambda message: message.text == "Начал 🏭")
async def cmd_start_shift(message: Message):
    user_id = message.from_user.id
    now = datetime.now(pytz.timezone('Europe/Moscow'))

    if not within_working_hours():
        await message.answer("Сейчас нерабочее время. Смена начинается с 08:00 до 17:30 по МСК.")
        return

    if user_id in data and 'start' in data[user_id]:
        start_time = data[user_id]['start'].strftime('%H:%M')
        await message.answer(f"Смена уже начата в {start_time}")
        return

    data[user_id] = {'start': now, 'name': message.from_user.full_name}
    save_data()
    logger.info(f"User {user_id} started shift at {now}")
    await message.answer("Смена успешно начата 🏭")

@dp.message(lambda message: message.text == "Закончил 🏡")
async def cmd_end_shift(message: Message):
    user_id = message.from_user.id
    now = datetime.now(pytz.timezone('Europe/Moscow'))

    if user_id not in data or 'start' not in data[user_id]:
        await message.answer("Смена ещё не начата.")
        return

    if 'end' in data[user_id]:
        end_time = data[user_id]['end'].strftime('%H:%M')
        await message.answer(f"Смена уже завершена в {end_time}")
        return

    data[user_id]['end'] = now
    save_data()
    logger.info(f"User {user_id} ended shift at {now}")
    await message.answer("Смена завершена 🏡")

@dp.message(lambda message: message.text == "Мой статус")
async def cmd_status(message: Message):
    user_id = message.from_user.id
    if user_id not in data:
        await message.answer("Вы ещё не начинали смену.")
    elif 'end' in data[user_id]:
        await message.answer("Смена завершена.")
    else:
        await message.answer("Вы на смене.")

@dp.message(lambda message: message.text == "Инструкция 📖")
async def cmd_instructions(message: Message):
    text = (
        "📖 Инструкция\n\n"
        "Команды для сотрудников:\n"
        "🏭 Кнопка \"Начал\" — начало смены\n"
        "🏡 Кнопка \"Закончил\" — завершение смены\n"
        "🔎 Кнопка \"Мой статус\" — текущий статус\n"
        "📖 Кнопка \"Инструкция\" — данная инструкция\n\n"
        "Команды для администратора:\n"
        "📍 Кнопка \"Статус📍\" — список сотрудников на смене\n"
        "📈 Кнопка \"Отчет\" — Excel-отчет о сменах\n"
        "🗑 Кнопка \"Сбросить данные\" — очистка данных о сменах"
    )
    await message.answer(text)

@dp.message(lambda message: message.text == "Статус📍")
async def cmd_admin_status(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    result = []
    for user_id, shift in data.items():
        name = shift.get('name', 'Неизвестно')
        if 'end' in shift:
            status = f"✅ Завершил смену"
        elif 'start' in shift:
            time_str = shift['start'].strftime('%H:%M')
            status = f"🟢 На смене с {time_str}"
        else:
            status = "⛔ Без статуса"
        result.append(f"{name}: {status}")

    await message.answer("\n".join(result) if result else "Нет данных по сотрудникам.")

@dp.message(lambda message: message.text == "Отчет 📈")
async def cmd_admin_report(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    rows = []
    for uid, info in data.items():
        rows.append({
            'Сотрудник': info.get('name', ''),
            'Начало': info.get('start', '').strftime('%Y-%m-%d %H:%M') if 'start' in info else '',
            'Окончание': info.get('end', '').strftime('%Y-%m-%d %H:%M') if 'end' in info else ''
        })

    if not rows:
        await message.answer("Нет данных для отчёта.")
        return

    df = pd.DataFrame(rows)
    file_name = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df.to_excel(file_name, index=False)

    try:
        await bot.send_document(message.chat.id, FSInputFile(file_name))
        logger.info(f"Report sent to admin {message.from_user.id}")
    except TelegramBadRequest as e:
        logger.error(f"Failed to send document: {e}")
        await message.answer("Ошибка при отправке отчёта.")
    finally:
        if os.path.exists(file_name):
            os.remove(file_name)

@dp.message(lambda message: message.text == "Сбросить данные")
async def cmd_reset_data(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    global data
    data = {}
    save_data()
    logger.info(f"Data reset by admin {message.from_user.id}")
    await message.answer("Данные о сменах сброшены.")

@dp.message()
async def handle_unknown(message: Message):
    await message.answer("Неизвестная команда. Используйте кнопки меню.")

async def main():
    load_data()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
