import os
import asyncio
from datetime import datetime, timedelta, time
import pytz
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.utils import executor
from aiogram.dispatcher.filters import Command
from openpyxl import Workbook, load_workbook

# Константы
ADMIN_ID = 123456789  # Замените на ваш Telegram user_id
EXCEL_FILE = "shift_log.xlsx"
TZ = pytz.timezone("Europe/Moscow")
SHIFT_START = time(8, 0)
SHIFT_END = time(17, 30)
LATE_START = time(8, 10)
LATE_END = time(17, 40)

# Инициализация бота
TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

# Хранилище статуса
user_shift_data = {}

# Инициализация Excel
if not os.path.exists(EXCEL_FILE):
    wb = Workbook()
    ws = wb.active
    ws.append(["Дата", "Пользователь", "Начало", "Причина задержки", "Окончание", "Причина переработки/раннего завершения"])
    wb.save(EXCEL_FILE)


def log_shift(user_name, date, start=None, start_reason="", end=None, end_reason=""):
    wb = load_workbook(EXCEL_FILE)
    ws = wb.active
    ws.append([date, user_name, start, start_reason, end, end_reason])
    wb.save(EXCEL_FILE)


@dp.message_handler(commands=["start", "начал", "начать_смену"])
async def start_shift(message: Message):
    now = datetime.now(TZ)
    date_str = now.strftime("%Y-%m-%d")
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    user_shift_data[user_id] = {"start": now, "start_reason": ""}

    if now.time() <= LATE_START:
        await message.answer("Доброе утро! Смена начата. Продуктивного дня!")
    else:
        await message.answer("Доброе утро! Смена начата позже, укажите причину.")

        @dp.message_handler()
        async def late_reason(m: Message):
            if m.from_user.id == user_id and user_shift_data[user_id].get("start_reason") == "":
                user_shift_data[user_id]["start_reason"] = m.text
                log_shift(user_name, date_str, start=now.strftime("%H:%M"), start_reason=m.text)
                await m.answer("Спасибо за комментарий. Продуктивного дня!")


@dp.message_handler(commands=["stop", "закончил", "закончить_смену"])
async def stop_shift(message: Message):
    now = datetime.now(TZ)
    date_str = now.strftime("%Y-%m-%d")
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    shift = user_shift_data.get(user_id, {})
    shift_start = shift.get("start")
    start_reason = shift.get("start_reason", "")

    def log_and_ack(end_reason=""):
        log_shift(user_name, date_str, 
                  start=shift_start.strftime("%H:%M") if shift_start else "", 
                  start_reason=start_reason, 
                  end=now.strftime("%H:%M"), 
                  end_reason=end_reason)

    if now.time() < SHIFT_END:
        await message.answer("Смена завершена раньше. Укажите причину.")

        @dp.message_handler()
        async def early_end_reason(m: Message):
            if m.from_user.id == user_id:
                log_and_ack(end_reason=m.text)
                await m.answer("Спасибо за комментарий. Желаю хорошего отдыха!")

    elif SHIFT_END <= now.time() <= LATE_END:
        log_and_ack()
        await message.answer("Смена завершена. Желаю хорошего отдыха!")

    else:
        await message.answer("Вы задержались после смены. Уточните причину переработки или напишите 'ошибка'.")

        @dp.message_handler()
        async def late_end_reason(m: Message):
            if m.from_user.id == user_id:
                log_and_ack(end_reason=m.text)
                await m.answer("Спасибо за комментарий. Желаю хорошего отдыха!")


@dp.message_handler(commands=["отчет"])
async def send_report(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer_document(types.InputFile(EXCEL_FILE))
    else:
        await message.answer("У вас нет прав на просмотр отчета.")


async def scheduler():
    while True:
        now = datetime.now(TZ)
        if now.weekday() < 5:
            if now.hour == SHIFT_START.hour and now.minute == SHIFT_START.minute:
                await bot.send_message(ADMIN_ID, "Доброе утро! Вы начали смену? Не забудьте написать 'начал'.")
            elif now.hour == SHIFT_END.hour and now.minute == SHIFT_END.minute:
                await bot.send_message(ADMIN_ID, "Рабочий день окончен. Не забудьте написать 'закончил'.")
        await asyncio.sleep(60)


async def on_startup(dp):
    asyncio.create_task(scheduler())


if __name__ == '__main__':
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True, timeout=30, allowed_updates=["message"])
