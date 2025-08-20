# main.py
import os
import asyncio
import logging
import datetime
import calendar
from typing import Dict, Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import CommandStart
from aiogram.types import (
    BotCommand,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

# ======== конфиг ========
TOKEN = os.getenv("BOT_TOKEN")  # ЧИТАЕМ из переменной окружения
ADMIN_IDS = [123456789]  # замените на реальные ID

if not TOKEN:
    raise RuntimeError(
        "Переменная окружения BOT_TOKEN не задана. "
        "Создайте её в Railway → Settings → Variables."
    )

bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ======== клавиатуры ========
user_buttons = [
    [KeyboardButton(text="Начал 🏭"), KeyboardButton(text="Закончил 🏡")],
    [KeyboardButton(text="Мой статус"), KeyboardButton(text="Инструкция")],
]
admin_buttons = user_buttons + [
    [KeyboardButton(text="Отчет 📈"), KeyboardButton(text="Статус смены")]
]

# ======== данные ========
shift_data: Dict[int, Dict[str, Any]] = {}

def is_weekend(date: datetime.date) -> bool:
    return calendar.weekday(date.year, date.month, date.day) >= 5

def format_status(user_id: int) -> str:
    data = shift_data.get(user_id)
    if not data:
        return "Смена не начата."
    start = data.get("start")
    end = data.get("end")
    out = [
        f"Смена начата в: {start.strftime('%H:%M') if start else '—'}",
        f"Смена завершена в: {end.strftime('%H:%M') if end else '—'}",
    ]
    if data.get("start_reason"):
        out.append(f"Причина начала: {data['start_reason']}")
    if data.get("end_reason"):
        out.append(f"Причина завершения: {data['end_reason']}")
    return "\n".join(out)

def kb(user_id: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=admin_buttons if user_id in ADMIN_IDS else user_buttons,
        resize_keyboard=True
    )

# ======== хендлеры ========
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("Добро пожаловать!", reply_markup=kb(message.from_user.id))

@router.message(F.text == "Начал 🏭")
async def handle_start(message: Message):
    uid = message.from_user.id
    now = datetime.datetime.now()
    data = shift_data.setdefault(uid, {})
    if data.get("start") and not data.get("end"):
        await message.answer("Смена уже начата. Завершите текущую смену, прежде чем начинать новую.")
        return
    data.update({
        "start": now,
        "end": None,
        "start_reason": None,
        "end_reason": None,
        "need_start_reason": False,
        "need_end_reason": False,
    })

    need = False
    if is_weekend(now.date()):
        need = True
        await message.answer("Сейчас не рабочий день. Укажи причину начала смены:")
    elif now.time() < datetime.time(8, 0):
        need = True
        await message.answer("Смена начата раньше 08:00. Укажи причину раннего начала:")
    elif now.time() > datetime.time(8, 10):
        need = True
        await message.answer("Смена начата позже 08:10. Укажи причину опоздания:")
    else:
        await message.answer("Смена начата. Продуктивного дня!")
    data["need_start_reason"] = need

@router.message(F.text == "Закончил 🏡")
async def handle_end(message: Message):
    uid = message.from_user.id
    now = datetime.datetime.now()
    data = shift_data.get(uid)
    if not data or not data.get("start"):
        await message.answer("Смена ещё не начата.")
        return
    if data.get("end"):
        await message.answer("Смена уже завершена.")
        return

    data["end"] = now
    need = False
    if now.time() < datetime.time(17, 30):
        need = True
        await message.answer("Смена завершена раньше 17:30. Укажи причину раннего завершения:")
    elif now.time() > datetime.time(17, 40):
        need = True
        await message.answer("Смена завершена позже. Укажи причину переработки:")
    else:
        await message.answer("Спасибо! Хорошего отдыха!")
    data["need_end_reason"] = need

@router.message(F.text == "Мой статус")
async def handle_status(message: Message):
    await message.answer(format_status(message.from_user.id))

@router.message(F.text == "Инструкция")
async def handle_help(message: Message):
    await message.answer(
        "Нажимай «Начал 🏭» в начале смены и «Закончил 🏡» по завершению.\n"
        "В выходные или при отклонениях по времени — бот попросит указать причину."
    )

@router.message(F.text == "Статус смены")
async def handle_shift_status(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Нет доступа.")
        return
    if not shift_data:
        await message.answer("Нет данных о сменах.")
        return
    lines = []
    for uid, data in shift_data.items():
        s = data.get("start").strftime("%H:%M") if data.get("start") else "—"
        e = data.get("end").strftime("%H:%M") if data.get("end") else "—"
        lines.append(f"{uid}: начата в {s}, завершена в {e}")
    await message.answer("\n".join(lines))

@router.message(F.text == "Отчет 📈")
async def handle_report(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Нет доступа.")
        return
    await message.answer("Формирование отчёта пока в разработке.")

# коммент/причина
@router.message(F.text)
async def handle_comment(message: Message):
    uid = message.from_user.id
    data = shift_data.get(uid)
    if not data:
        return
    if data.get("need_start_reason") and not data.get("start_reason"):
        data["start_reason"] = message.text.strip()
        data["need_start_reason"] = False
        await message.answer("Спасибо! Смена начата. Продуктивного дня!")
        return
    if data.get("need_end_reason") and not data.get("end_reason"):
        data["end_reason"] = message.text.strip()
        data["need_end_reason"] = False
        await message.answer("Спасибо! Хорошего отдыха!")
        return

async def main():
    logging.basicConfig(level=logging.INFO)
    await bot.set_my_commands([BotCommand(command="start", description="Запуск бота")])
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
