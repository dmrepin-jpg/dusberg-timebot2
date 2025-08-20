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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

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

# Проверка рабочего времени
def within_working_hours():
    now = datetime.now(pytz.timezone("Europe/Moscow")).time()
    return time(8, 0) <= now <= time(17, 30)

def is_admin(user_id):
    return user_id in ADMIN_IDS

# Кнопки
def get_keyboard(is_admin=False):
    buttons = [
        [KeyboardButton(text="Начал 🏭"), KeyboardButton(text="Закончил 🏡")],
        [KeyboardButton(text="Мой статус"), KeyboardButton(text="Инструкция")]
    ]
    if is_admin:
        buttons.append([KeyboardButton(text="Статус📍"), KeyboardButton(text="Отчет 📈")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# Telegram-объекты
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# Напоминания
async def morning_reminder():
    for user_id in data:
        try:
            await bot.send_message(int(user_id), "🕗 08:00 — время начала смены. Не забудь нажать \"Начал 🏭\".")
        except Exception as e:
            logger.warning(f"Не удалось отправить утреннее напоминание: {e}")

async def evening_reminder():
    for user_id, entry in data.items():
        if "start" in entry and "end" not in entry:
            try:
                await bot.send_message(int(user_id), "🏁 17:30 — смена окончена? Не забудь нажать \"Закончил 🏡\".")
            except Exception as e:
                logger.warning(f"Не удалось отправить вечернее напоминание: {e}")

scheduler.add_job(morning_reminder, CronTrigger(hour=8, minute=0, day_of_week='mon-fri'))
scheduler.add_job(evening_reminder, CronTrigger(hour=17, minute=30, day_of_week='mon-fri'))

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
    weekday = now.weekday()

    if user_id in data and "start" in data[user_id]:
        await message.answer("Вы уже начали смену.")
        return

    data[user_id] = {
        "name": message.from_user.full_name,
        "start": now.isoformat()
    }

    if weekday >= 5:
        await message.answer("Сегодня нерабочий день. Укажи причину начала смены:")
    elif now.time() > time(8, 10):
        await message.answer("Начало смены позже 08:10. Укажи причину:")

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

    start_time = datetime.fromisoformat(data[user_id]["start"]).time()
    if now.time() < time(17, 30):
        await message.answer("Смена завершена раньше 17:30. Укажи причину:")
    elif now.time() > time(17, 40):
        await message.answer("Смена завершена позже 17:40. Укажи причину переработки:")

    data[user_id]["end"] = now.isoformat()
    save_data()
    await message.answer("Спасибо! Желаю хорошего отдыха!")

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
        "Отчет 📈 — Excel-файл смен"
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

# Отчёт
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

# Неизвестная команда
@dp.message()
async def unknown_command(message: Message):
    await message.answer("Неизвестная команда. Пожалуйста, используйте кнопки меню.")

# Точка входа
async def main():
    load_data()
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
