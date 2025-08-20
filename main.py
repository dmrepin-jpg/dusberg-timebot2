# telegram_shift_bot/main.py
import os
import asyncio
from datetime import datetime, time
import pytz
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor
from openpyxl import Workbook, load_workbook

# --- Константы ---
ADMIN_ID = 123456789  # Замените на ваш Telegram user_id
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
user_shift_data = {}  # {user_id: {"start": datetime, "start_reason": str, "end": datetime, "end_reason": str}}
registered_users = set()

# --- Инициализация Excel ---
if not os.path.exists(EXCEL_FILE):
    wb = Workbook()
    ws = wb.active
    ws.append(["Дата", "Пользователь", "Начало", "Причина задержки", "Окончание", "Причина переработки/раннего завершения"])
    wb.save(EXCEL_FILE)


# --- Меню ---
user_kb = ReplyKeyboardMarkup(resize_keyboard=True)
user_kb.add("Начал \ud83d\udfdd", "Закончил\ud83c\udfe1")
user_kb.add("Мой статус", "\ud83d\udcd6 Инструкция")

admin_kb = ReplyKeyboardMarkup(resize_keyboard=True)
admin_kb.add("Начал \ud83d\udfdd", "Закончил\ud83c\udfe1")
admin_kb.add("Мой статус", "\ud83d\udcd6 Инструкция")
admin_kb.add("\ud83d\udcca Статус смены", "\ud83d\udcc8 Отчет")


# --- Логирование ---
def log_shift(user_name, date, start=None, start_reason="", end=None, end_reason=""):
    wb = load_workbook(EXCEL_FILE)
    ws = wb.active
    ws.append([date, user_name, start, start_reason, end, end_reason])
    wb.save(EXCEL_FILE)


# --- Обработка сообщений ---
@dp.message_handler(lambda m: m.text == "\ud83d\udcd6 Инструкция")
async def show_instruction(message: types.Message):
    await message.answer(
        "\ud83d\udcd6 <b>Инструкция</b>\n\n"
        "<b>Команды для сотрудников:</b>\n"
        "\ud83d\udfdd <b>Начал</b> — запуск начала смены\n"
        "\ud83c\udfe1 <b>Закончил</b> — завершение смены\n"
        "<b>Мой статус</b> — текущий статус сотрудника\n"
        "<b>Инструкция</b> — показать инструкцию\n\n"
        "<b>Команды для администратора:</b>\n"
        "\ud83d\udcca <b>Статус смены</b> — текстовый отчет по всем\n"
        "\ud83d\udcc8 <b>Отчет</b> — Excel-файл со всеми данными",
        parse_mode="HTML"
    )


@dp.message_handler(lambda m: m.text == "Начал \ud83d\udfdd")
async def handle_start(message: types.Message):
    now = datetime.now(TZ)
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    registered_users.add((user_id, user_name))

    if not (time(7, 0) <= now.time() <= LATE_END):
        await message.answer("Сейчас нерабочее время. Начать смену можно с 07:00 до 17:40.")
        return

    shift = user_shift_data.get(user_id, {})
    if shift.get("start"):
        start_time = shift["start"].strftime("%H:%M")
        await message.answer(f"Вы уже начали смену в {start_time}.")
        return

    user_shift_data[user_id] = {"start": now, "start_reason": "", "end": None, "end_reason": ""}
    date_str = now.strftime("%Y-%m-%d")

    if now.time() <= LATE_START:
        log_shift(user_name, date_str, start=now.strftime("%H:%M"))
        await message.answer("Смена начата. Желаю продуктивного рабочего дня!")
    else:
        await message.answer("Смена начата позже. Укажите причину задержки:")

        @dp.message_handler(lambda m: m.from_user.id == user_id and not user_shift_data[user_id]["start_reason"])
        async def get_late_reason(m: types.Message):
            user_shift_data[user_id]["start_reason"] = m.text
            log_shift(user_name, date_str, start=now.strftime("%H:%M"), start_reason=m.text)
            await m.answer("Спасибо! Желаю продуктивного рабочего дня!")


@dp.message_handler(lambda m: m.text == "Закончил\ud83c\udfe1")
async def handle_end(message: types.Message):
    now = datetime.now(TZ)
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    date_str = now.strftime("%Y-%m-%d")

    shift = user_shift_data.get(user_id)
    if not shift or not shift.get("start"):
        await message.answer("Вы ещё не начали смену.")
        return

    if shift.get("end"):
        end_time = shift["end"].strftime("%H:%M")
        await message.answer(f"Смена уже завершена в {end_time}.")
        return

    def log_and_ack(reason=""):
        shift["end"] = now
        shift["end_reason"] = reason
        log_shift(
            user_name,
            date_str,
            start=shift["start"].strftime("%H:%M"),
            start_reason=shift["start_reason"],
            end=now.strftime("%H:%M"),
            end_reason=reason,
        )

    if now.time() < SHIFT_END:
        await message.answer("Смена завершена раньше. Укажите причину:")

        @dp.message_handler(lambda m: m.from_user.id == user_id)
        async def early_reason(m: types.Message):
            log_and_ack(m.text)
            await m.answer("Спасибо! Желаю хорошего отдыха!")

    elif SHIFT_END <= now.time() <= LATE_END:
        log_and_ack()
        await message.answer("Смена завершена. Спасибо! Желаю хорошего отдыха!")
    else:
        await message.answer("Вы задержались. Укажите причину переработки или напишите 'ошибка':")

        @dp.message_handler(lambda m: m.from_user.id == user_id)
        async def overtime_reason(m: types.Message):
            log_and_ack(m.text)
            await m.answer("Спасибо! Желаю хорошего отдыха!")


@dp.message_handler(lambda m: m.text == "Мой статус")
async def my_status(message: types.Message):
    user_id = message.from_user.id
    shift = user_shift_data.get(user_id)
    if not shift:
        await message.answer("Вы ещё не начали смену.")
    elif shift.get("end"):
        await message.answer("Смена завершена.")
    else:
        start = shift["start"].strftime("%H:%M")
        await message.answer(f"Смена начата в {start}, ещё не завершена.")


@dp.message_handler(lambda m: m.text == "\ud83d\udcc8 Отчет")
async def send_excel(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer_document(types.InputFile(EXCEL_FILE))
    else:
        await message.answer("У вас нет прав для просмотра отчета.")


@dp.message_handler(lambda m: m.text == "\ud83d\udcca Статус смены")
async def shift_status(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет доступа к статусу смены.")
        return

    report = []
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    for user_id, user_name in registered_users:
        shift = user_shift_data.get(user_id)
        if not shift:
            report.append(f"{user_name}: \u274c Не на смене")
        else:
            if shift.get("end"):
                report.append(f"{user_name}: \u2705 Был на смене. Закончил в {shift['end'].strftime('%H:%M')}")
            else:
                report.append(f"{user_name}: \u2705 На смене с {shift['start'].strftime('%H:%M')}")

    await message.answer("\n".join(report))


# --- Напоминания ---
async def scheduler():
    while True:
        now = datetime.now(TZ)
        if now.weekday() < 5:
            if now.strftime("%H:%M") == SHIFT_START.strftime("%H:%M"):
                await bot.send_message(ADMIN_ID, "Напоминание: нажмите \"Начал \ud83d\udfdd\" для начала смены")
            elif now.strftime("%H:%M") == SHIFT_END.strftime("%H:%M"):
                await bot.send_message(ADMIN_ID, "Напоминание: нажмите \"Закончил\ud83c\udfe1\" для завершения смены")
        await asyncio.sleep(60)


# --- Старт ---
@dp.message_handler(commands=["start"])
async def start_bot(message: types.Message):
    kb = admin_kb if message.from_user.id == ADMIN_ID else user_kb
    await message.answer("Добро пожаловать! Используйте кнопки ниже:", reply_markup=kb)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(scheduler())
    executor.start_polling(dp, skip_updates=True)
