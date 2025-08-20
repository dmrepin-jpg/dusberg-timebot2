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

# ================== Конфигурация ==================
TOKEN = 8369016774:AAE09_ALathLnzKdHQF7qAbpL4_mJ9wg8IY  # замените на реальный токен
ADMIN_IDS = [104653853]  # замените на реальные ID админов

bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ================== Клавиатуры ==================
user_buttons = [
    [KeyboardButton(text="Начал 🏭"), KeyboardButton(text="Закончил 🏡")],
    [KeyboardButton(text="Мой статус"), KeyboardButton(text="Инструкция")],
]
admin_buttons = user_buttons + [
    [KeyboardButton(text="Отчет 📈"), KeyboardButton(text="Статус смены")]
]

# ================== Данные смен ==================
# user_id -> dict
shift_data: Dict[int, Dict[str, Any]] = {}
# Структура:
# {
#   "start": datetime | None,
#   "end": datetime | None,
#   "start_reason": str | None,
#   "end_reason": str | None,
#   "need_start_reason": bool,
#   "need_end_reason": bool
# }

# ================== Вспомогательные ==================
def is_weekend(date: datetime.date) -> bool:
    # 5/6 -> Sat/Sun
    return calendar.weekday(date.year, date.month, date.day) >= 5

def format_status(user_id: int) -> str:
    data = shift_data.get(user_id)
    if not data:
        return "Смена не начата."
    start = data.get("start")
    end = data.get("end")
    start_s = start.strftime("%H:%M") if start else "—"
    end_s = end.strftime("%H:%M") if end else "—"
    txt = [f"Смена начата в: {start_s}", f"Смена завершена в: {end_s}"]
    if data.get("start_reason"):
        txt.append(f"Причина начала: {data['start_reason']}")
    if data.get("end_reason"):
        txt.append(f"Причина завершения: {data['end_reason']}")
    return "\n".join(txt)

def get_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    kb = admin_buttons if user_id in ADMIN_IDS else user_buttons
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# ================== Хендлеры ==================
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("Добро пожаловать!", reply_markup=get_keyboard(message.from_user.id))

@router.message(F.text == "Начал 🏭")
async def handle_start(message: Message):
    user_id = message.from_user.id
    now = datetime.datetime.now()
    data = shift_data.setdefault(user_id, {})

    # Если смена уже начата и не завершена
    if data.get("start") and not data.get("end"):
        await message.answer("Смена уже начата. Завершите текущую смену, прежде чем начинать новую.")
        return

    # Инициализация новой смены
    data["start"] = now
    data["end"] = None
    data["start_reason"] = None
    data["end_reason"] = None
    data["need_start_reason"] = False
    data["need_end_reason"] = False

    # Проверяем необходимость причины
    need_reason = False
    if is_weekend(now.date()):
        need_reason = True
        await message.answer("Сейчас не рабочий день. Укажи причину начала смены:")
    elif now.time() < datetime.time(8, 0):
        need_reason = True
        await message.answer("Смена начата раньше 08:00. Укажи причину раннего начала:")
    elif now.time() > datetime.time(8, 10):
        need_reason = True
        await message.answer("Смена начата позже 08:10. Укажи причину опоздания:")
    else:
        await message.answer("Смена начата. Продуктивного дня!")

    data["need_start_reason"] = need_reason

@router.message(F.text == "Закончил 🏡")
async def handle_end(message: Message):
    user_id = message.from_user.id
    now = datetime.datetime.now()
    data = shift_data.get(user_id)

    if not data or not data.get("start"):
        await message.answer("Смена ещё не начата.")
        return

    if data.get("end"):
        await message.answer("Смена уже завершена.")
        return

    data["end"] = now

    # Нужна ли причина завершения
    need_reason = False
    if now.time() < datetime.time(17, 30):
        need_reason = True
        await message.answer("Смена завершена раньше 17:30. Укажи причину раннего завершения:")
    elif now.time() > datetime.time(17, 40):
        need_reason = True
        await message.answer("Смена завершена позже. Укажи причину переработки:")
    else:
        await message.answer("Спасибо! Хорошего отдыха!")

    data["need_end_reason"] = need_reason

@router.message(F.text == "Мой статус")
async def handle_my_status(message: Message):
    await message.answer(format_status(message.from_user.id))

@router.message(F.text == "Инструкция")
async def handle_instructions(message: Message):
    await message.answer(
        "Нажимай «Начал 🏭» в начале смены и «Закончил 🏡» по завершению.\n"
        "В выходные или при отклонениях по времени — укажи причину по запросу бота."
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
        start_s = data.get("start").strftime("%H:%M") if data.get("start") else "—"
        end_s = data.get("end").strftime("%H:%M") if data.get("end") else "—"
        lines.append(f"{uid}: начата в {start_s}, завершена в {end_s}")
    await message.answer("\n".join(lines))

@router.message(F.text == "Отчет 📈")
async def handle_report(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Нет доступа.")
        return
    await message.answer("Формирование отчёта пока в разработке.")

# ===== Обработчик ввода причины (комментариев) =====
@router.message(F.text)
async def handle_comment(message: Message):
    user_id = message.from_user.id
    data = shift_data.get(user_id)
    if not data:
        return  # Не начинали смену — игнорируем

    # Приоритет: сначала причина старта, затем причина завершения
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
    # Иначе — это просто свободный текст. Можно проигнорировать или эхо:
    # await message.answer("Принял.")
    # Я оставляю без ответа, чтобы не спамить.

# ================== Точка входа ==================
async def main():
    logging.basicConfig(level=logging.INFO)
    # Установим команды для меню клиента
    await bot.set_my_commands([BotCommand(command="start", description="Запуск бота")])
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
