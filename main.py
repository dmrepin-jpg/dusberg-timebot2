# main.py  (aiogram >= 3.7)
import asyncio
import logging
import datetime
import calendar
from typing import Dict, Any

from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, KeyboardButton, Message, ReplyKeyboardMarkup

# ================== ЖЁСТКИЕ НАСТРОЙКИ ==================
BOT_TOKEN = "8369016774:AAE09_ALathLnzKdHQF7qAbpL4_mJ9wg8IY"  # <-- ВСТАВЬ СВОЙ ТОКЕН
OWNER_ID = 104653853                         # ты — владелец
ADMIN_IDS = [104653853, 1155243378]          # список админов (включая тебя)

# ================== ИНИЦИАЛИЗАЦИЯ ==================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# ================== КНОПКИ ==================
user_buttons = [
    [KeyboardButton(text="Начал 🏭"), KeyboardButton(text="Закончил 🏡")],
    [KeyboardButton(text="Мой статус"), KeyboardButton(text="Инструкция")],
]
admin_buttons = user_buttons + [[KeyboardButton(text="Отчет 📈"), KeyboardButton(text="Статус смены")]]

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def kb(user_id: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=admin_buttons if is_admin(user_id) else user_buttons,
        resize_keyboard=True
    )

# ================== ДАННЫЕ ==================
shift_data: Dict[int, Dict[str, Any]] = {}

# ================== ХЕЛПЕРЫ ==================
def is_weekend(date: datetime.date) -> bool:
    return calendar.weekday(date.year, date.month, date.day) >= 5

def format_status(user_id: int) -> str:
    data = shift_data.get(user_id)
    if not data:
        return "Смена не начата."
    start = data.get("start"); end = data.get("end")
    return (
        f"Смена начата в: {start.strftime('%H:%M') if start else '—'}\n"
        f"Смена завершена в: {end.strftime('%H:%M') if end else '—'}"
    )

# ================== КОМАНДЫ ==================
@router.message(F.text == "/start")
async def cmd_start(message: Message):
    await message.answer("Добро пожаловать!", reply_markup=kb(message.from_user.id))

@router.message(F.text == "/whoami")
async def cmd_whoami(message: Message):
    uid = message.from_user.id
    role = "OWNER" if uid == OWNER_ID else ("ADMIN" if uid in ADMIN_IDS else "USER")
    await message.answer(
        f"Ты: <b>{role}</b>\n"
        f"Твой ID: <code>{uid}</code>\n"
        f"OWNER_ID: <code>{OWNER_ID}</code>"
    , reply_markup=kb(uid))

# ================== БИЗНЕС-ХЕНДЛЕРЫ ==================
@router.message(F.text == "Начал 🏭")
async def handle_start(message: Message):
    uid = message.from_user.id
    now = datetime.datetime.now()
    shift = shift_data.setdefault(uid, {})

    if shift.get("start") and shift.get("end") is None:
        await message.answer("Смена уже начата. Сначала заверши текущую.", reply_markup=kb(uid))
        return

    shift["start"] = now
    shift["end"] = None

    if is_weekend(now.date()):
        await message.answer("Сегодня выходной. Укажи причину начала смены:", reply_markup=kb(uid))
    elif now.time() < datetime.time(8, 0):
        await message.answer("Раньше 08:00. Укажи причину раннего начала:", reply_markup=kb(uid))
    elif now.time() > datetime.time(8, 10):
        await message.answer("Позже 08:10. Укажи причину опоздания:", reply_markup=kb(uid))
    else:
        await message.answer("Смена начата. Продуктивного дня!", reply_markup=kb(uid))

@router.message(F.text == "Закончил 🏡")
async def handle_end(message: Message):
    uid = message.from_user.id
    now = datetime.datetime.now()
    shift = shift_data.get(uid)

    if not shift or not shift.get("start"):
        await message.answer("Смена ещё не начата.", reply_markup=kb(uid))
        return
    if shift.get("end"):
        await message.answer("Смена уже завершена.", reply_markup=kb(uid))
        return

    shift["end"] = now

    if now.time() < datetime.time(17, 30):
        await message.answer("Раньше 17:30. Укажи причину раннего завершения:", reply_markup=kb(uid))
    elif now.time() > datetime.time(17, 40):
        await message.answer("Позже нормы. Укажи причину переработки:", reply_markup=kb(uid))
    else:
        await message.answer("Спасибо! Хорошего отдыха!", reply_markup=kb(uid))

@router.message(F.text == "Мой статус")
async def handle_status(message: Message):
    await message.answer(format_status(message.from_user.id), reply_markup=kb(message.from_user.id))

@router.message(F.text == "Инструкция")
async def handle_help(message: Message):
    await message.answer(
        "Нажимай «Начал 🏭» в начале смены и «Закончил 🏡» по завершению.\n"
        "В выходные/при отклонениях по времени — напиши причину по запросу.",
        reply_markup=kb(message.from_user.id)
    )

@router.message(F.text == "Статус смены")
async def handle_shift_status(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.", reply_markup=kb(message.from_user.id))
        return
    if not shift_data:
        await message.answer("Нет данных о сменах.", reply_markup=kb(message.from_user.id))
        return
    lines = []
    for uid, data in shift_data.items():
        s = data.get("start").strftime("%H:%M") if data.get("start") else "—"
        e = data.get("end").strftime("%H:%M") if data.get("end") else "—"
        lines.append(f"{uid}: начата в {s}, завершена в {e}")
    await message.answer("\n".join(lines), reply_markup=kb(message.from_user.id))

@router.message(F.text == "Отчет 📈")
async def handle_report(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.", reply_markup=kb(message.from_user.id))
        return
    await message.answer("Формирование отчёта пока в разработке.", reply_markup=kb(message.from_user.id))

# комментарии / причины (простая версия)
@router.message()
async def handle_comment(message: Message):
    uid = message.from_user.id
    shift = shift_data.get(uid)
    if not shift:
        return
    if "comment" not in shift and not shift.get("end"):
        shift["comment"] = message.text
        await message.answer("Спасибо! Смена начата. Продуктивного дня!", reply_markup=kb(uid))
    elif shift.get("end") and not shift.get("comment_done"):
        shift["comment_done"] = True
        await message.answer("Спасибо! Хорошего отдыха!", reply_markup=kb(uid))

# ================== ЗАПУСК ==================
async def main():
    await bot.set_my_commands([
        BotCommand(command="start", description="Запуск бота"),
        BotCommand(command="whoami", description="Показать мою роль"),
    ])
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
