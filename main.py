import os
import asyncio
from datetime import datetime, time
import pytz
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor
from openpyxl import Workbook, load_workbook

# --- Константы ---
ADMIN_ID = 123456789  # Заменить на ваш Telegram user_id
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
registered_users = set()

# --- Инициализация Excel ---
if not os.path.exists(EXCEL_FILE):
    wb = Workbook()
    ws = wb.active
    ws.append(["Дата", "Пользователь", "Начало", "Причина задержки", "Окончание", "Причина переработки/раннего завершения"])
    wb.save(EXCEL_FILE)

# --- Клавиатура ---
kb = ReplyKeyboardMarkup(resize_keyboard=True)
kb.add(KeyboardButton("инструкция"), KeyboardButton("мой статус"))
kb.add(KeyboardButton("начал"), KeyboardButton("закончил"))

# --- Логика Excel ---
def log_shift(user_name, date, start=None, start_reason="", end=None, end_reason=""):
    wb = load_workbook(EXCEL_FILE)
    ws = wb.active
    ws.append([date, user_name, start, start_reason, end, end_reason])
    wb.save(EXCEL_FILE)

# --- Обработка начала смены ---
@dp.message_handler(lambda m: m.text.lower() == "начал")
async def start_shift(message: Message):
    now = datetime.now(TZ)
    if now.time() < time(7, 0) or now.time() > SHIFT_END:
        await message.answer("Сейчас нерабочее время. Отметка невозможна.", reply_markup=kb)
        return

    user_id = message.from_user.id
    user_name = message.from_user.full_name
    registered_users.add((user_id, user_name))
    date_str = now.strftime("%Y-%m-%d")
    user_shift_data[user_id] = {"start": now, "start_reason": ""}

    if now.time() <= LATE_START:
        await message.answer("Смена начата. Желаю продуктивного рабочего дня!", reply_markup=kb)
        log_shift(user_name, date_str, start=now.strftime("%H:%M"))
    else:
        await message.answer("Смена начата позже. Укажите причину задержки:", reply_markup=kb)

        @dp.message_handler(lambda m: m.from_user.id == user_id and user_shift_data[user_id]["start_reason"] == "")
        async def get_late_reason(m: Message):
            user_shift_data[user_id]["start_reason"] = m.text
            log_shift(user_name, date_str, start=now.strftime("%H:%M"), start_reason=m.text)
            await m.answer("Спасибо! Желаю продуктивного рабочего дня!", reply_markup=kb)

# --- Обработка окончания смены ---
@dp.message_handler(lambda m: m.text.lower() == "закончил")
async def stop_shift(message: Message):
    now = datetime.now(TZ)
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    date_str = now.strftime("%Y-%m-%d")

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
        await message.answer("Смена завершена раньше. Укажите причину:", reply_markup=kb)

        @dp.message_handler(lambda m: m.from_user.id == user_id)
        async def early_end(m: Message):
            log_and_ack(end_reason=m.text)
            await m.answer("Спасибо! Желаю хорошего отдыха!", reply_markup=kb)

    elif SHIFT_END <= now.time() <= LATE_END:
        log_and_ack()
        await message.answer("Смена завершена. Спасибо! Желаю хорошего отдыха!", reply_markup=kb)

    else:
        await message.answer("Вы задержались. Укажите причину переработки или напишите 'ошибка':", reply_markup=kb)

        @dp.message_handler(lambda m: m.from_user.id == user_id)
        async def late_end(m: Message):
            log_and_ack(end_reason=m.text)
            await m.answer("Спасибо! Желаю хорошего отдыха!", reply_markup=kb)

# --- Инструкция ---
@dp.message_handler(lambda m: m.text.lower() == "инструкция")
async def show_help(message: Message):
    await message.answer(
        "\U0001F4D6 Инструкция\n\n"
        "Команды для сотрудников:\n"
        "- 'начал' — отметить начало смены\n"
        "- 'закончил' — отметить завершение смены\n"
        "- 'мой статус' — текущий статус\n"
        "- 'инструкция' — показать эту инструкцию\n\n"
        "Для администратора дополнительно:\n"
        "- 'статус смены' — список всех сотрудников сегодня\n"
        "- 'отчет' — выгрузка Excel-файла"
    , reply_markup=kb)

# --- Мой статус ---
@dp.message_handler(lambda m: m.text.lower() == "мой статус")
async def my_status(message: Message):
    user_id = message.from_user.id
    shift = user_shift_data.get(user_id)
    if shift:
        start = shift["start"].strftime("%H:%M")
        await message.answer(f"Вы на смене с {start}.")
    else:
        await message.answer("Вы не на смене.")

# --- Статус смены для админа ---
@dp.message_handler(lambda m: m.text.lower() == "статус смены")
async def shift_status(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет доступа.")
        return

    today = datetime.now(TZ).strftime("%Y-%m-%d")
    report = []
    for user_id, user_name in registered_users:
        shift = user_shift_data.get(user_id)
        if shift and shift["start"].date().strftime("%Y-%m-%d") == today:
            report.append(f"{user_name}: на смене с {shift['start'].strftime('%H:%M')}")
        else:
            report.append(f"{user_name}: не на смене")
    await message.answer("\n".join(report))

# --- Отчет для администратора ---
@dp.message_handler(lambda m: m.text.lower() == "отчет")
async def send_report(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer_document(types.InputFile(EXCEL_FILE))
    else:
        await message.answer("У вас нет прав на просмотр отчета.")

# --- Напоминания ---
async def scheduler():
    await bot.wait_until_ready()
    while True:
        now = datetime.now(TZ)
        if now.weekday() < 5:
            current_time = now.strftime("%H:%M")
            if current_time == SHIFT_START.strftime("%H:%M"):
                await bot.send_message(ADMIN_ID, "Доброе утро! Вы начали смену? Не забудьте написать 'начал'.")
            elif current_time == SHIFT_END.strftime("%H:%M"):
                await bot.send_message(ADMIN_ID, "Рабочий день окончен. Не забудьте написать 'закончил'.")
        await asyncio.sleep(60)

# --- Запуск ---
if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(scheduler())
    executor.start_polling(dp, skip_updates=True)
