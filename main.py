import asyncio
import logging
import datetime
import calendar
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.utils.markdown import hbold

# Конфигурация
TOKEN = "<your-token>"
ADMIN_IDS = [123456789]  # замените на реальные ID

bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())

# Команды
user_buttons = [
    [KeyboardButton(text="Начал 🏭"), KeyboardButton(text="Закончил 🏡")],
    [KeyboardButton(text="Мой статус"), KeyboardButton(text="Инструкция")],
]
admin_buttons = user_buttons + [[KeyboardButton(text="Отчет 📈"), KeyboardButton(text="Статус смены")]]

# Состояние смен
shift_data = {}  # user_id: {"start": datetime, "end": datetime, "comment": str}

# Вспомогательные функции
def is_weekend(date: datetime.date):
    return calendar.weekday(date.year, date.month, date.day) >= 5

def format_status(user_id):
    data = shift_data.get(user_id)
    if not data:
        return "Смена не начата."
    start = data.get("start")
    end = data.get("end")
    return f"Смена начата в: {start.strftime('%H:%M') if start else '—'}\nСмена завершена в: {end.strftime('%H:%M') if end else '—'}"

# Хендлеры
@dp.message(lambda message: message.text == "Начал 🏭")
async def handle_start(message: Message):
    user_id = message.from_user.id
    now = datetime.datetime.now()
    shift = shift_data.setdefault(user_id, {})

    if shift.get("start") and shift.get("end") is None:
        await message.answer("Смена уже начата. Завершите текущую смену, прежде чем начинать новую.")
        return

    shift["start"] = now
    shift["end"] = None

    if is_weekend(now.date()):
        await message.answer("Сейчас не рабочий день, укажи причину начала смены:")
    elif now.time() < datetime.time(8, 0):
        await message.answer("Смена начата раньше 08:00. Укажи причину раннего начала:")
    elif now.time() > datetime.time(8, 10):
        await message.answer("Смена начата позже 08:10. Укажи причину опоздания:")
    else:
        await message.answer("Желаю продуктивного рабочего дня!")

@dp.message(lambda message: message.text == "Закончил 🏡")
async def handle_end(message: Message):
    user_id = message.from_user.id
    now = datetime.datetime.now()
    shift = shift_data.get(user_id)

    if not shift or not shift.get("start"):
        await message.answer("Смена ещё не начата.")
        return

    if shift.get("end"):
        await message.answer("Смена уже завершена.")
        return

    shift["end"] = now

    if now.time() < datetime.time(17, 30):
        await message.answer("Смена завершена раньше 17:30. Укажи причину раннего завершения:")
    elif now.time() > datetime.time(17, 40):
        await message.answer("Смена завершена позже. Укажи причину переработки:")
    else:
        await message.answer("Спасибо! Желаю точно отдохнуть!")

@dp.message(lambda message: message.text == "Мой статус")
async def handle_my_status(message: Message):
    await message.answer(format_status(message.from_user.id))

@dp.message(lambda message: message.text == "Инструкция")
async def handle_instructions(message: Message):
    await message.answer("Нажимай 'Начал 🏭' в начале смены и 'Закончил 🏡' по завершению. В выходные — обязательно укажи причину.")

@dp.message(lambda message: message.text == "Статус смены")
async def handle_shift_status(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Нет доступа.")
        return
    report = "\n".join(
        f"{user_id}: начата в {data.get('start').strftime('%H:%M') if data.get('start') else '—'}, завершена в {data.get('end').strftime('%H:%M') if data.get('end') else '—'}"
        for user_id, data in shift_data.items()
    )
    await message.answer(report or "Нет данных о сменах.")

@dp.message(lambda message: message.text == "Отчет 📈")
async def handle_report(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Нет доступа.")
        return
    await message.answer("Формирование отчёта пока в разработке.")

# Хендлер для комментариев
@dp.message()
async def handle_comment(message: Message):
    user_id = message.from_user.id
    shift = shift_data.get(user_id)
    if not shift:
        return
    if "comment" not in shift:
        shift["comment"] = message.text
        await message.answer("Спасибо! Смена начата. Продуктивного дня!")
    elif shift.get("end") and shift.get("comment_done") is not True:
        shift["comment_done"] = True
        await message.answer("Спасибо! Хорошего отдыха!")

# Меню команд
@dp.startup()
async def on_startup(dispatcher: Dispatcher):
    await bot.set_my_commands([
        BotCommand(command="start", description="Запуск бота")
    ])

@dp.message(lambda message: message.text == "/start")
async def cmd_start(message: Message):
    keyboard = ReplyKeyboardMarkup(
        keyboard=admin_buttons if message.from_user.id in ADMIN_IDS else user_buttons,
        resize_keyboard=True
    )
    await message.answer("Добро пожаловать!", reply_markup=keyboard)

# Запуск
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(dp.start_polling(bot))
