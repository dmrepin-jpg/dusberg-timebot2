import asyncio
import logging
import datetime
import calendar
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.utils.markdown import hbold

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "8396016774:AAE09_ALathLnzkKHQf7AqbPL4_m39wgBlY"

OWNER_ID = 104653853  # жёстко твой ID
ADMIN_IDS = [104653853, 1155243378]  # список админов в коде

# ================== ИНИЦИАЛИЗАЦИЯ ==================
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# ================== КНОПКИ ==================
user_buttons = [
    [KeyboardButton(text="Начал 🏭"), KeyboardButton(text="Закончил 🏡")],
    [KeyboardButton(text="Мой статус"), KeyboardButton(text="Инструкция")],
]

admin_buttons = user_buttons + [
    [KeyboardButton(text="Отчет 📈"), KeyboardButton(text="Статус смены")]
]

# ================== ДАННЫЕ ==================
shift_data = {}  # user_id: {"start": datetime, "end": datetime, "comment": str}

# ================== ВСПОМОГАТЕЛЬНЫЕ ==================
def is_weekend(date: datetime.date):
    return calendar.weekday(date.year, date.month, date.day) >= 5

def format_status(user_id):
    data = shift_data.get(user_id)
    if not data:
        return "Смена не начата."
    start = data.get("start")
    end = data.get("end")
    return f"Смена начата в: {start.strftime('%H:%M') if start else '—'}\nСмена завершена в: {end.strftime('%H:%M') if end else '—'}"

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ================== ХЕНДЛЕРЫ ==================
@router.message(F.text == "/start")
async def cmd_start(message: Message):
    keyboard = ReplyKeyboardMarkup(
        keyboard=admin_buttons if is_admin(message.from_user.id) else user_buttons,
        resize_keyboard=True
    )
    await message.answer("Добро пожаловать!", reply_markup=keyboard)

@router.message(F.text == "Начал 🏭")
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

@router.message(F.text == "Закончил 🏡")
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
        await message.answer("Спасибо! Желаю отличного отдыха!")

@router.message(F.text == "Мой статус")
async def handle_my_status(message: Message):
    await message.answer(format_status(message.from_user.id))

@router.message(F.text == "Инструкция")
async def handle_instructions(message: Message):
    await message.answer("Нажимай 'Начал 🏭' в начале смены и 'Закончил 🏡' по завершению. В выходные — обязательно укажи причину.")

@router.message(F.text == "Статус смены")
async def handle_shift_status(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    report = "\n".join(
        f"{user_id}: начата в {data.get('start').strftime('%H:%M') if data.get('start') else '—'}, завершена в {data.get('end').strftime('%H:%M') if data.get('end') else '—'}"
        for user_id, data in shift_data.items()
    )
    await message.answer(report or "Нет данных о сменах.")

@router.message(F.text == "Отчет 📈")
async def handle_report(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    await message.answer("Формирование отчёта пока в разработке.")

@router.message()
async def handle_comment(message: Message):
    user_id = message.from_user.id
    shift = shift_data.get(user_id)
    if not shift:
        return
    if "comment" not in shift and not shift.get("end"):
        shift["comment"] = message.text
        await message.answer("Спасибо! Смена начата. Продуктивного дня!")
    elif shift.get("end") and shift.get("comment_done") is not True:
        shift["comment_done"] = True
        await message.answer("Спасибо! Хорошего отдыха!")

# ================== СТАРТ ==================
async def main():
    logging.basicConfig(level=logging.INFO)
    await bot.set_my_commands([
        BotCommand(command="start", description="Запуск бота")
    ])
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
