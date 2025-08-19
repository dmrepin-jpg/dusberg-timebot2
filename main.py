import os
import asyncio
from datetime import datetime, time
import pytz
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.utils import executor
from aiogram.dispatcher.filters import Command
from openpyxl import Workbook, load_workbook

# --- Константы ---
ADMIN_ID = 123456789  # ← замени на свой Telegram user_id
EXCEL_FILE = "shift_log.xlsx"
TZ = pytz.timezone("Europe/Moscow")
SHIFT_START = time(8, 0)
SHIFT_END = time(17, 30)
LATE_START = time(8, 10)
LATE_END = time(17, 40)

# --- Инициализация бота ---
TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

# --- Хранилище статуса ---
user_shift_data = {}

# --- Инициализация Excel ---
if not os.path.exists(EXCEL_FILE):
    wb = Workbook()
    ws = wb.active
    ws.append(["Дата", "Пользователь", "Начало", "Причина задержки", "Окончание", "Причина переработки/раннего завершения"])
    wb.save(EXCEL_FILE)


# --- Функция логирования в Excel ---
def log_shift(user_name, date, start=None, start_reason="", end=None, end_reason=""):
    wb = load_workbook(EXCEL_FILE)
    ws = wb.active
    ws.append([date, user_name, start, start_reason, end, end_reason])
    wb.save(EXCEL_FILE)


# --- Обработка начала смены ---
@dp.message_handler(commands=["start", "начал", "начать_смену"])
async def start_shift(message: Message):
    now = datetime.now(TZ)
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    date_str = now.strftime("%Y-%m-%d")

    user_shift_data[user_id] = {"start": now, "start_reason": ""}

    if now.time() <= LATE_START:
        await message.answer("Смена начата. Желаю продуктивного рабочего дня!")
        log_shift(user_name, date_str, start=now.strftime("%H:%M"))
    else:
        await message.answer("Смена начата позже. Укажите причину задержки.")

        @dp.message_handler(lambda m: m.from_user.id == user_id and user_shift_data[user_id]["start_reason"] == "")
        async def get_late_reason(m: Message):
            user_shift_data[user_id]["start_reason"] = m.text
            log_shift(user_name, date_str, start=now.strftime("%H:%M"), start_reason=m.text)
            await m.answer("Спасибо! Желаю продуктивного рабочего дня!")


# --- Обработка окончания смены ---
@dp.message_handler(commands=["stop", "закончил", "закончить_смену"])
async def stop_shift(message: Message):
    now = datetime.now(TZ)
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    date_str = now.strftime("%Y-%m-%d")

    shift = user_shift_data.get(user_id, {})
    shift_start = shift.get("start")
    start_reason = shift.get("start_reason", "")

    def log_and_ack(end_reason=""):
        log_shift(
            user_name,
            date_str,
            start=shift_start.strftime("%H:%M") if shift_start else "",
            start_reason=start_reason,
            end=now.strftime("%H:%M"),
            end_reason=end_reason,
        )

    if now.time() < SHIFT_END:
        await message.answer("Смена завершена раньше. Укажите причину:")

        @dp.message_handler(lambda m: m.from_user.id == user_id)
        async def early_end(m: Message):
            log_and_ack(end_reason=m.text)
            await m.answer("Спасибо! Желаю хорошего отдыха!")

    elif SHIFT_END <= now.time() <= LATE_END:
        log_and_ack()
        await message.answer("Смена завершена. Спасибо! Желаю хорошего отдыха!")

    else:
        await message.answer("Вы задержались. Укажите причину переработки или напишите 'ошибка':")

        @dp.message_handler(lambda m: m.from_user.id == user_id)
        async def late_end(m: Message):
            log_and_ack(end_reason=m.text)
            await m.answer("Спасибо! Желаю хорошего отдыха!")


# --- Отправка отчета ---
@dp.message_handler(commands=["отчет"])
async def send_report(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer_document(types.InputFile(EXCEL_FILE))
    else:
        await message.answer("У вас нет прав на просмотр отчета.")


# --- Напоминания ---
async def scheduler():
    while True:
        now = datetime.now(TZ)
        if now.weekday() < 5:  # Пн–Пт
            current_time = now.time().strftime("%H:%M")
            if current_time == SHIFT_START.strftime("%H:%M"):
                await bot.send_message(ADMIN_ID, "Доброе утро! Вы начали смену? Не забудьте написать 'начал'.")
            elif current_time == SHIFT_END.strftime("%H:%M"):
                await bot.send_message(ADMIN_ID, "Рабочий день окончен. Не забудьте написать 'закончил'.")
        await asyncio.sleep(60)


# --- Запуск ---
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(scheduler())
    executor.start_polling(dp, skip_updates=True)
