import asyncio
import logging
import os
import json
from datetime import datetime, time
import pytz
import pandas as pd
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.types.input_file import FSInputFile
from aiogram.exceptions import TelegramBadRequest

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_TOKEN = '8369016774:AAE09_ALathLnzKdHQF7qAbpL4_mJ9wg8IY'
ADMIN_IDS = [104653853]  # ID администратора

data = {}

# Загрузка и сохранение данных
def load_data():
    global data
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}

def save_data():
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)

# Проверка временного интервала
def within_working_hours():
    now = datetime.now(pytz.timezone("Europe/Moscow")).time()
    return time(8, 0) <= now <= time(17, 30)

# Проверка администратора
def is_admin(user_id):
    return user_id in ADMIN_IDS

# Клавиатура
def get_keyboard(is_admin=False):
    buttons = [
        [KeyboardButton(text="Начал 🏭"), KeyboardButton(text="Закончил 🏡")],
        [KeyboardButton(text="Мой статус"), KeyboardButton(text="Инструкция")]
    ]
    if is_admin:
        buttons.append([KeyboardButton(text="Статус📍"), KeyboardButton(text="Отчет 📈")])
        buttons.append([KeyboardButton(text="Сбросить данные")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# Telegram-объекты
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Команда /start
@dp.message(CommandStart())
async def cmd_start(message: Message):
    load_data()
    keyboard = get_keyboard(is_admin(message.from_user.id))
    await message.answer("Желаю продуктивного рабочего дня!", reply_markup=keyboard)

# Начало смены
@dp.message(F.text == "Начал 🏭")
async def start_shift(message: Message):
    user_id = str(message.from_user.id)
    now = datetime.now(pytz.timezone("Europe/Moscow"))

    if not within_working_hours():
        await message.answer("Сейчас нерабочее время. Смена возможна с 08:00 до 17:30 по МСК.")
        return

    if user_id in data and "start" in data[user_id]:
        await message.answer("Вы уже начали смену.")
        return

    data[user_id] = {
        "name": message.from_user.full_name,
        "start": now.isoformat()
    }
    save_data()
    await message.answer("Смена успешно начата.")

# Завершение смены
@dp.message(F.text == "Закончил 🏡")
async def end_shift(message: Message):
    user_id = str(message.from_user.id)
    now = datetime.now(pytz.timezone("Europe/Moscow"))

    if user_id not in data or "start" not in data[user_id]:
        await message.answer("Смена ещё не начиналась.")
        return

    if "end" in data[user_id]:
        await message.answer("Смена уже завершена.")
        return

    data[user_id]["end"] = now.isoformat()
    save_data()
    await message.answer("Спасибо! Желаю точно отдохнуть!")

# Мой статус
@dp.message(F.text == "Мой статус")
async def my_status(message: Message):
    user_id = str(message.from_user.id)
    record = data.get(user_id)
    if not record:
        await message.answer("Вы ещё не начали смену.")
    elif "end" in record:
        await message.answer("Смена завершена.")
    else:
        await message.answer("Вы на смене.")

# Инструкция
@dp.message(F.text == "Инструкция")
async def show_instruction(message: Message):
    await message.answer(
        "📋 Инструкция:\n\n"
        "Начал 🏭 — отметить начало смены\n"
        "Закончил 🏡 — отметить завершение смены\n"
        "Мой статус — проверить статус\n"
        "Инструкция — показать инструкцию\n\n"
        "Доступно администраторам:\n"
        "Статус📍 — кто сейчас на смене\n"
        "Отчет 📈 — Excel-файл смен\n"
        "Сбросить данные — удалить все записи"
    )

# Статус сотрудников
@dp.message(F.text == "Статус📍")
async def admin_status(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    text = []
    for user_id, entry in data.items():
        name = entry.get("name", "Неизвестно")
        if "end" in entry:
            status = "Смена завершена"
        elif "start" in entry:
            dt = datetime.fromisoformat(entry["start"]).strftime("%H:%M")
            status = f"На смене с {dt}"
        else:
            status = "Нет данных"
        text.append(f"{name}: {status}")

    await message.answer("\n".join(text) if text else "Нет активных сотрудников.")

# Отчёт в Excel
@dp.message(F.text == "Отчет 📈")
async def send_report(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    if not data:
        await message.answer("Нет данных.")
        return

    rows = []
    for entry in data.values():
        rows.append({
            "Сотрудник": entry.get("name", ""),
            "Начало": entry.get("start", ""),
            "Окончание": entry.get("end", "")
        })

    df = pd.DataFrame(rows)
    filename = "report.xlsx"
    df.to_excel(filename, index=False)

    try:
        await bot.send_document(message.chat.id, FSInputFile(filename))
    except TelegramBadRequest as e:
        await message.answer(f"Ошибка при отправке: {e}")
    finally:
        if os.path.exists(filename):
            os.remove(filename)

# Сброс данных
@dp.message(F.text == "Сбросить данные")
async def reset_data(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    global data
    data = {}
    save_data()
    await message.answer("Данные сброшены.")

# Неизвестная команда
@dp.message()
async def unknown_command(message: Message):
    await message.answer("Неизвестная команда. Пожалуйста, используйте кнопки меню.")

# Точка входа
async def main():
    load_data()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
