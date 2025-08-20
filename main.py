# main.py
import os
import re
import asyncio
import logging
import datetime
import calendar
from typing import Dict, Any, Set

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import CommandStart, Command
from aiogram.types import BotCommand, KeyboardButton, Message, ReplyKeyboardMarkup

# ----- логирование включаем сразу
logging.basicConfig(level=logging.INFO)

# ====================== ENV utils ======================
def clean_env_value(value: str | None) -> str:
    if not value:
        return ""
    return (
        value.replace("\u00A0", " ")  # NBSP -> space
             .replace("\r", " ")
             .replace("\n", " ")
             .strip()
             .strip('"')
             .strip("'")
             .strip()
    )

def parse_admin_ids(env_value: str | None) -> Set[int]:
    cleaned = clean_env_value(env_value)
    if not cleaned:
        return set()
    parts = re.split(r"[,\s;]+", cleaned)
    out: Set[int] = set()
    for p in parts:
        if not p:
            continue
        m = re.search(r"-?\d+", p)
        if not m:
            logging.warning("ADMIN_IDS: пропускаю фрагмент %r", p)
            continue
        out.add(int(m.group(0)))
    return out

# ====================== ENV read (устойчивый) ======================
RAW_BOT_TOKEN = os.getenv("BOT_TOKEN", "")
RAW_OWNER_ID  = os.getenv("OWNER_ID", "")
RAW_ADMIN_IDS = os.getenv("ADMIN_IDS", "")
OWNER_SECRET  = clean_env_value(os.getenv("OWNER_SECRET"))

TOKEN = clean_env_value(RAW_BOT_TOKEN)
if not TOKEN:
    raise RuntimeError(f"BOT_TOKEN пуст. RAW={RAW_BOT_TOKEN!r}")

ADMIN_IDS: Set[int] = parse_admin_ids(RAW_ADMIN_IDS)

owner_clean = clean_env_value(RAW_OWNER_ID)
OWNER_ID = None
if owner_clean:
    try:
        OWNER_ID = int(owner_clean)
    except ValueError:
        OWNER_ID = None

# fallback: если OWNER_ID пуст, берём первого из ADMIN_IDS
if OWNER_ID is None:
    if ADMIN_IDS:
        OWNER_ID = sorted(ADMIN_IDS)[0]
        logging.warning("OWNER_ID не задан/не число. Использую первого из ADMIN_IDS: %s", OWNER_ID)
    else:
        raise RuntimeError(
            f"OWNER_ID не задан и ADMIN_IDS пуст. RAW_OWNER_ID={RAW_OWNER_ID!r}, RAW_ADMIN_IDS={RAW_ADMIN_IDS!r}"
        )

# Диагностика ENV
logging.info("RAW OWNER_ID: %r | CLEAN: %r | USED: %s", RAW_OWNER_ID, owner_clean, OWNER_ID)
logging.info("RAW ADMIN_IDS: %r | PARSED: %s", RAW_ADMIN_IDS, sorted(ADMIN_IDS))

# ====================== Bot / DP ======================
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# ====================== Keyboards / roles ======================
user_buttons = [
    [KeyboardButton(text="Начал 🏭"), KeyboardButton(text="Закончил 🏡")],
    [KeyboardButton(text="Мой статус"), KeyboardButton(text="Инструкция")],
]
admin_buttons = user_buttons + [[KeyboardButton(text="Отчет 📈"), KeyboardButton(text="Статус смены")]]

def is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in ADMIN_IDS

def kb(user_id: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=admin_buttons if is_admin(user_id) else user_buttons,
        resize_keyboard=True
    )

# ====================== In-memory data ======================
shift_data: Dict[int, Dict[str, Any]] = {}

def is_weekend(date: datetime.date) -> bool:
    return calendar.weekday(date.year, date.month, date.day) >= 5  # 5-6 = Sat/Sun

def format_status(user_id: int) -> str:
    data = shift_data.get(user_id)
    if not data:
        return "Смена не начата."
    start = data.get("start"); end = data.get("end")
    lines = [
        f"Смена начата в: {start.strftime('%H:%M') if start else '—'}",
        f"Смена завершена в: {end.strftime('%H:%M') if end else '—'}",
    ]
    if data.get("start_reason"): lines.append(f"Причина начала: {data['start_reason']}")
    if data.get("end_reason"):   lines.append(f"Причина завершения: {data['end_reason']}")
    return "\n".join(lines)

# ====================== Commands (service / owner) ======================
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("Добро пожаловать!", reply_markup=kb(message.from_user.id))

@router.message(Command("myid"))
async def cmd_myid(message: Message):
    uid = message.from_user.id
    listed = ", ".join(map(str, sorted(ADMIN_IDS))) or "—"
    await message.answer(
        f"Твой ID: <code>{uid}</code>\n"
        f"OWNER_ID: <code>{OWNER_ID}</code>\n"
        f"Админ: {'да' if is_admin(uid) else 'нет'}\n"
        f"Админы (без owner): <code>{listed}</code>",
        reply_markup=kb(uid)
    )

@router.message(Command("admins"))
async def cmd_admins(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.", reply_markup=kb(message.from_user.id)); return
    listed = ", ".join(map(str, sorted(ADMIN_IDS))) or "—"
    await message.answer(f"OWNER: <code>{OWNER_ID}</code>\nАдмины: <code>{listed}</code>", reply_markup=kb(message.from_user.id))

@router.message(Command("admin_add"))
async def cmd_admin_add(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("Только владелец может добавлять админов.", reply_markup=kb(message.from_user.id)); return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат: /admin_add <id>", reply_markup=kb(message.from_user.id)); return
    try:
        new_id = int(parts[1].strip())
    except ValueError:
        await message.answer("ID должен быть числом.", reply_markup=kb(message.from_user.id)); return
    if new_id == OWNER_ID:
        await message.answer("Владелец и так имеет все права.", reply_markup=kb(message.from_user.id)); return
    if new_id in ADMIN_IDS:
        await message.answer("Этот ID уже админ.", reply_markup=kb(message.from_user.id)); return
    ADMIN_IDS.add(new_id)
    listed = ", ".join(map(str, sorted(ADMIN_IDS)))
    await message.answer(
        f"Добавлен админ: <code>{new_id}</code>\n"
        f"Текущие админы: <code>{listed}</code>\n"
        "⚠️ Сохрани это в Railway → ADMIN_IDS и Redeploy.",
        reply_markup=kb(message.from_user.id)
    )

@router.message(Command("admin_remove"))
async def cmd_admin_remove(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("Только владелец может удалять админов.", reply_markup=kb(message.from_user.id)); return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат: /admin_remove <id>", reply_markup=kb(message.from_user.id)); return
    try:
        rem_id = int(parts[1].strip())
    except ValueError:
        await message.answer("ID должен быть числом.", reply_markup=kb(message.from_user.id)); return
    if rem_id == OWNER_ID:
        await message.answer("Нельзя удалить владельца.", reply_markup=kb(message.from_user.id)); return
    if rem_id not in ADMIN_IDS:
        await message.answer("Такого админа нет.", reply_markup=kb(message.from_user.id)); return
    ADMIN_IDS.remove(rem_id)
    listed = ", ".join(map(str, sorted(ADMIN_IDS))) or "—"
    await message.answer(f"Удалён: <code>{rem_id}</code>\nТекущие: <code>{listed}</code>\n⚠️ Обнови Railway → ADMIN_IDS и Redeploy.", reply_markup=kb(message.from_user.id))

@router.message(Command("refresh"))
async def cmd_refresh(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("Только владелец может обновлять список из ENV.", reply_markup=kb(message.from_user.id)); return
    global ADMIN_IDS, RAW_ADMIN_IDS
    RAW_ADMIN_IDS = os.getenv("ADMIN_IDS", "")
    ADMIN_IDS = parse_admin_ids(RAW_ADMIN_IDS)
    listed = ", ".join(map(str, sorted(ADMIN_IDS))) or "—"
    await message.answer(f"Перечитал ADMIN_IDS. Сейчас: <code>{listed}</code>", reply_markup=kb(message.from_user.id))

@router.message(Command("setowner"))
async def cmd_setowner(message: Message):
    """
    /setowner <секрет> <id> — назначить владельца на лету (если OWNER_SECRET задан).
    Нужен только если ENV внезапно не подхватился, но бот уже запущен.
    """
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Формат: /setowner <секрет> <id>", reply_markup=kb(message.from_user.id)); return
    secret, id_str = parts[1], parts[2]
    if not OWNER_SECRET:
        await message.answer("OWNER_SECRET не задан в ENV.", reply_markup=kb(message.from_user.id)); return
    if secret != OWNER_SECRET:
        await message.answer("Неверный секрет.", reply_markup=kb(message.from_user.id)); return
    try:
        new_owner = int(id_str)
    except ValueError:
        await message.answer("ID должен быть числом.", reply_markup=kb(message.from_user.id)); return
    global OWNER_ID
    OWNER_ID = new_owner
    await message.answer(
        f"Владелец установлен: <code>{OWNER_ID}</code>\n"
        f"Запиши его в Railway → OWNER_ID и Redeploy.",
        reply_markup=kb(message.from_user.id)
    )

# ====================== Business ======================
@router.message(F.text == "Начал 🏭")
async def handle_start(message: Message):
    uid = message.from_user.id
    now = datetime.datetime.now()
    data = shift_data.setdefault(uid, {})
    if data.get("start") and not data.get("end"):
        await message.answer("Смена уже начата. Сначала заверши текущую.", reply_markup=kb(uid)); return
    data.update({
        "start": now, "end": None,
        "start_reason": None, "end_reason": None,
        "need_start_reason": False, "need_end_reason": False,
    })
    if is_weekend(now.date()):
        data["need_start_reason"] = True; txt = "Сегодня выходной. Укажи причину начала смены:"
    elif now.time() < datetime.time(8, 0):
        data["need_start_reason"] = True; txt = "Раньше 08:00. Укажи причину раннего начала:"
    elif now.time() > datetime.time(8, 10):
        data["need_start_reason"] = True; txt = "Позже 08:10. Укажи причину опоздания:"
    else:
        txt = "Смена начата. Продуктивного дня!"
    await message.answer(txt, reply_markup=kb(uid))

@router.message(F.text == "Закончил 🏡")
async def handle_end(message: Message):
    uid = message.from_user.id
    now = datetime.datetime.now()
    data = shift_data.get(uid)
    if not data or not data.get("start"):
        await message.answer("Смена ещё не начата.", reply_markup=kb(uid)); return
    if data.get("end"):
        await message.answer("Смена уже завершена.", reply_markup=kb(uid)); return
    data["end"] = now
    if now.time() < datetime.time(17, 30):
        data["need_end_reason"] = True; txt = "Раньше 17:30. Укажи причину раннего завершения:"
    elif now.time() > datetime.time(17, 40):
        data["need_end_reason"] = True; txt = "Позже нормы. Укажи причину переработки:"
    else:
        data["need_end_reason"] = False; txt = "Спасибо! Хорошего отдыха!"
    await message.answer(txt, reply_markup=kb(uid))

@router.message(F.text == "Мой статус")
async def handle_status(message: Message):
    await message.answer(format_status(message.from_user.id), reply_markup=kb(message.from_user.id))

@router.message(F.text == "Инструкция")
async def handle_help(message: Message):
    await message.answer(
        "Нажимай «Начал 🏭» в начале смены и «Закончил 🏡» по завершению.\n"
        "В выходные и при отклонениях по времени — укажи причину по запросу.",
        reply_markup=kb(message.from_user.id)
    )

@router.message(F.text == "Статус смены")
async def handle_shift_status(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.", reply_markup=kb(message.from_user.id)); return
    if not shift_data:
        await message.answer("Нет данных о сменах.", reply_markup=kb(message.from_user.id)); return
    lines = []
    for uid, data in shift_data.items():
        s = data.get("start").strftime("%H:%M") if data.get("start") else "—"
        e = data.get("end").strftime("%H:%M") if data.get("end") else "—"
        lines.append(f"{uid}: начата в {s}, завершена в {e}")
    await message.answer("\n".join(lines), reply_markup=kb(message.from_user.id))

@router.message(F.text == "Отчет 📈")
async def handle_report(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.", reply_markup=kb(message.from_user.id)); return
    # TODO: сформировать и отправить реальный отчёт (CSV/Excel/текст)
    await message.answer("Формирование отчёта пока в разработке.", reply_markup=kb(message.from_user.id))

# комментарии / причины (по запросу)
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

# ====================== Entry ======================
async def main():
    await bot.set_my_commands([
        BotCommand(command="start", description="Запуск бота"),
        BotCommand(command="myid", description="Показать мой ID и статус"),
        BotCommand(command="admins", description="Список админов"),
        BotCommand(command="admin_add", description="(OWNER) Добавить админа: /admin_add <id>"),
        BotCommand(command="admin_remove", description="(OWNER) Удалить админа: /admin_remove <id>"),
        BotCommand(command="refresh", description="(OWNER) Перечитать ADMIN_IDS из ENV"),
        BotCommand(command="setowner", description="Назначить владельца: /setowner <секрет> <id>"),
    ])
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
