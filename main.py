import os
import asyncio
import logging
import datetime
import calendar
from typing import Dict, Any, List

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import CommandStart, Command
from aiogram.types import BotCommand, KeyboardButton, Message, ReplyKeyboardMarkup

# ========== конфиг ==========
def parse_admin_ids(env_value: str | None) -> List[int]:
    if not env_value:
        return []
    ids: List[int] = []
    for part in env_value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            logging.warning("ADMIN_IDS: пропускаю нечисловое значение %r", part)
    return ids

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN не задан. Railway → Settings → Variables.")

ADMIN_IDS: List[int] = parse_admin_ids(os.getenv("ADMIN_IDS"))

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ========== клавиатуры ==========
user_buttons = [
    [KeyboardButton(text="Начал 🏭"), KeyboardButton(text="Закончил 🏡")],
    [KeyboardButton(text="Мой статус"), KeyboardButton(text="Инструкция")],
]
admin_buttons = user_buttons + [
    [KeyboardButton(text="Отчет 📈"), KeyboardButton(text="Статус смены")]
]

def kb(user_id: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=admin_buttons if user_id in ADMIN_IDS else user_buttons,
        resize_keyboard=True
    )

# ========== данные ==========
shift_data: Dict[int, Dict[str, Any]] = {}
# структура на пользователя:
# {
#   "start": datetime | None,
#   "end": datetime | None,
#   "start_reason": str | None,
#   "end_reason": str | None,
#   "need_start_reason": bool,
#   "need_end_reason": bool,
# }

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

# ========== хендлеры ==========
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("Добро пожаловать!", reply_markup=kb(message.from_user.id))

@router.message(Command("myid"))
async def cmd_myid(message: Message):
    await message.answer(
        f"Твой Telegram ID: <code>{message.from_user.id}</code>\n"
        f"Админ: {'да' if message.from_user.id in ADMIN_IDS else 'нет'}",
        reply_markup=kb(message.from_user.id)
    )

@router.message(Command("refresh"))
async def cmd_refresh(message: Message):
    """Перечитать ADMIN_IDS из переменных окружения без рестарта."""
    global ADMIN_IDS
    ADMIN_IDS = parse_admin_ids(os.getenv("ADMIN_IDS"))
    await message.answer("Меню обновлено.", reply_markup=kb(message.from_user.id))

@router.message(F.text == "Начал 🏭")
async def handle_start(message: Message):
    uid = message.from_user.id
    now = datetime.datetime.now()
    data = shift_data.setdefault(uid, {})
    if data.get("start") and not data.get("end"):
        await message.answer(
            "Смена уже начата. Завершите текущую смену, прежде чем начинать новую.",
            reply_markup=kb(uid)
        )
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
        txt = "Сейчас не рабочий день. Укажи причину начала смены:"
    elif now.time() < datetime.time(8, 0):
        need = True
        txt = "Смена начата раньше 08:00. Укажи причину раннего начала:"
    elif now.time() > datetime.time(8, 10):
        need = True
        txt = "Смена начата позже 08:10. Укажи причину опоздания:"
    else:
        txt = "Смена начата. Продуктивного дня!"

    data["need_start_reason"] = need
    await message.answer(txt, reply_markup=kb(uid))

@router.message(F.text == "Закончил 🏡")
async def handle_end(message: Message):
    uid = message.from_user.id
    now = datetime.datetime.now()
    data = shift_data.get(uid)

    if not data or not data.get("start"):
        await message.answer("Смена ещё не начата.", reply_markup=kb(uid))
        return
    if data.get("end"):
        await message.answer("Смена уже завершена.", reply_markup=kb(uid))
        return

    data["end"] = now
    if now.time() < datetime.time(17, 30):
        data["need_end_reason"] = True
        txt = "Смена завершена раньше 17:30. Укажи причину раннего завершения:"
    elif now.time() > datetime.time(17, 40):
        data["need_end_reason"] = True
        txt = "Смена завершена позже. Укажи причину переработки:"
    else:
        data["need_end_reason"] = False
        txt = "Спасибо! Хорошего отдыха!"
    await message.answer(txt, reply_markup=kb(uid))

@router.message(F.text == "Мой статус")
async def handle_status(message: Message):
    await message.answer(format_status(message.from_user.id), reply_markup=kb(message.from_user.id))

@router.message(F.text == "Инструкция")
async def handle_help(message: Message):
    await message.answer(
        "Нажимай «Начал 🏭» в начале смены и «Закончил 🏡» по завершению.\n"
        "В выходные или при отклонениях по времени — бот попросит указать причину.",
        reply_markup=kb(message.from_user.id)
    )

@router.message(F.text == "Статус смены")
async def handle_shift_status(message: Message):
    if message.from_user.id not in ADMIN_IDS:
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
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Нет доступа.", reply_markup=kb(message.from_user.id))
        return
    await message.answer("Формирование отчёта пока в разработке.", reply_markup=kb(message.from_user.id))

# комментарии / причины (только если требуются)
@router.message(F.text)
async def handle_comment(message: Message):
    uid = message.from_user.id
    data = shift_data.get(uid)
    if not data:
        return
    if data.get("need_start_reason") and not data.get("start_reason"):
        data["start_reason"] = message.text.strip()
        data["need_start_reason"] = False
        await message.answer("Спасибо! Смена начата. Продуктивного дня!", reply_markup=kb(uid))
        return
    if data.get("need_end_reason") and not data.get("end_reason"):
        data["end_reason"] = message.text.strip()
        data["need_end_reason"] = False
        await message.answer("Спасибо! Хорошего отдыха!", reply_markup=kb(uid))

# ========== точка входа ==========
async def main():
    logging.basicConfig(level=logging.INFO)
    logging.info("ADMIN_IDS (parsed): %s", ADMIN_IDS)

    await bot.set_my_commands([
        BotCommand(command="start", description="Запуск бота"),
        BotCommand(command="myid", description="Показать мой ID"),
        BotCommand(command="refresh", description="Обновить меню"),
    ])
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
