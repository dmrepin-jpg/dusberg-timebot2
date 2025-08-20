# main.py  (aiogram >= 3.7, <3.9)
import io
import csv
import asyncio
import logging
import datetime
import calendar
from typing import Dict, Any

from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, KeyboardButton, Message, ReplyKeyboardMarkup, BufferedInputFile
from zoneinfo import ZoneInfo

# ================== ЖЁСТКИЕ НАСТРОЙКИ ==================
BOT_TOKEN = "PASTE_TELEGRAM_BOT_TOKEN_HERE"     # <-- ВСТАВЬ СВОЙ ТОКЕН
OWNER_ID  = 104653853                           # ты — владелец
ADMIN_IDS = [104653853, 1155243378]             # админы (включая тебя)

# СПРАВОЧНИК СОТРУДНИКОВ: ID -> ФИО
EMPLOYEES: Dict[int, str] = {
    104653853: "Иванов Иван Иванович",
    1155243378: "Петров Пётр Петрович",
    # добавляй сюда остальных сотрудников: id: "Фамилия Имя Отчество",
}

# Разрешённые пользователи — только из справочника (+ на всякий случай OWNER/ADMIN)
ALLOWED_IDS = set(EMPLOYEES.keys()) | {OWNER_ID, *ADMIN_IDS}

# Часовой пояс Москва
MSK = ZoneInfo("Europe/Moscow")

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
# {uid: {"start": dt, "end": dt, "start_reason": str, "end_reason": str, "comment": str}}
shift_data: Dict[int, Dict[str, Any]] = {}

# ================== ХЕЛПЕРЫ ==================
def ensure_allowed(message: Message) -> bool:
    uid = message.from_user.id
    if uid not in ALLOWED_IDS:
        # Жёсткий запрет: никого лишнего
        # Можно заменить на silent return, если не хочешь отвечать.
        asyncio.create_task(message.answer("Нет доступа. Обратитесь к администратору."))
        return False
    return True

def is_weekend(date: datetime.date) -> bool:
    return calendar.weekday(date.year, date.month, date.day) >= 5

def msk_now() -> datetime.datetime:
    return datetime.datetime.now(MSK)

def fmt_hm(dt: datetime.datetime | None) -> str:
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    return dt.astimezone(MSK).strftime("%H:%M")

def fmt_date(dt: datetime.datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    return dt.astimezone(MSK).strftime("%Y-%m-%d")

def display_name(uid: int) -> str:
    # Только из справочника
    return EMPLOYEES.get(uid, f"Неизвестный ({uid})")

def format_status(user_id: int) -> str:
    data = shift_data.get(user_id)
    if not data:
        return "Смена не начата."
    start = data.get("start"); end = data.get("end")
    lines = [
        f"Смена начата в: {fmt_hm(start)}",
        f"Смена завершена в: {fmt_hm(end)}",
    ]
    if data.get("start_reason"):
        lines.append(f"Причина начала: {data['start_reason']}")
    if data.get("end_reason"):
        lines.append(f"Причина завершения: {data['end_reason']}")
    return "\n".join(lines)

# ================== КОМАНДЫ ==================
@router.message(F.text == "/start")
async def cmd_start(message: Message):
    if not ensure_allowed(message): return
    await message.answer("Добро пожаловать!", reply_markup=kb(message.from_user.id))

@router.message(F.text == "/whoami")
async def cmd_whoami(message: Message):
    if not ensure_allowed(message): return
    uid = message.from_user.id
    role = "OWNER" if uid == OWNER_ID else ("ADMIN" if is_admin(uid) else "USER")
    await message.answer(
        f"Ты: <b>{role}</b>\n"
        f"ФИО: <b>{display_name(uid)}</b>\n"
        f"ID: <code>{uid}</code>",
        reply_markup=kb(uid)
    )

# ================== БИЗНЕС-ХЕНДЛЕРЫ ==================
@router.message(F.text == "Начал 🏭")
async def handle_start(message: Message):
    if not ensure_allowed(message): return
    uid = message.from_user.id
    now = msk_now()
    shift = shift_data.setdefault(uid, {})

    if shift.get("start") and shift.get("end") is None:
        await message.answer("Смена уже начата. Сначала заверши текущую.", reply_markup=kb(uid))
        return

    shift["start"] = now
    shift["end"] = None
    shift["start_reason"] = None
    shift["end_reason"] = None
    shift["comment"] = shift.get("comment")  # сохраняем старый комментарий если был

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
    if not ensure_allowed(message): return
    uid = message.from_user.id
    now = msk_now()
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
    if not ensure_allowed(message): return
    await message.answer(format_status(message.from_user.id), reply_markup=kb(message.from_user.id))

@router.message(F.text == "Инструкция")
async def handle_help(message: Message):
    if not ensure_allowed(message): return
    await message.answer(
        "Нажимай «Начал 🏭» в начале смены и «Закончил 🏡» по завершению.\n"
        "В выходные/при отклонениях по времени — напиши причину по запросу.",
        reply_markup=kb(message.from_user.id)
    )

@router.message(F.text == "Статус смены")
async def handle_shift_status(message: Message):
    if not ensure_allowed(message): return
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.", reply_markup=kb(message.from_user.id))
        return
    if not shift_data:
        await message.answer("Нет данных о сменах.", reply_markup=kb(message.from_user.id))
        return
    lines = []
    for uid, data in shift_data.items():
        s = fmt_hm(data.get("start"))
        e = fmt_hm(data.get("end"))
        lines.append(f"{display_name(uid)}: начата в {s}, завершена в {e}")
    await message.answer("\n".join(lines), reply_markup=kb(message.from_user.id))

# ======== ОТЧЁТ CSV (только данные из справочника) ========
def build_csv_bytes() -> bytes:
    """
    CSV UTF-8-SIG; колонки: Date;Name;ID;Start;End;Duration(h);Weekend;StartReason;EndReason;Comment
    """
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', lineterminator='\n')
    writer.writerow(["Date", "Name", "ID", "Start", "End", "Duration(h)", "Weekend", "StartReason", "EndReason", "Comment"])

    for uid, data in shift_data.items():
        start: datetime.datetime | None = data.get("start")
        end:   datetime.datetime | None = data.get("end")

        if start and start.tzinfo is None: start = start.replace(tzinfo=MSK)
        if end and end.tzinfo is None:     end   = end.replace(tzinfo=MSK)

        date_str   = fmt_date(start) or fmt_date(end) or datetime.datetime.now(MSK).strftime("%Y-%m-%d")
        start_str  = fmt_hm(start)
        end_str    = fmt_hm(end)
        duration_h = ""
        if start and end:
            delta = end.astimezone(MSK) - start.astimezone(MSK)
            duration_h = f"{round(delta.total_seconds()/3600, 2)}"

        weekend = ""
        base_dt = start or end
        if base_dt:
            weekend = "yes" if is_weekend(base_dt.astimezone(MSK).date()) else "no"

        name = EMPLOYEES.get(uid, "")
        writer.writerow([
            date_str, name, uid, start_str, end_str, duration_h, weekend,
            data.get("start_reason") or "", data.get("end_reason") or "", data.get("comment") or ""
        ])

    return output.getvalue().encode("utf-8-sig")

@router.message(F.text == "Отчет 📈")
async def handle_report_button(message: Message):
    if not ensure_allowed(message): return
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.", reply_markup=kb(message.from_user.id))
        return
    if not shift_data:
        await message.answer("Нет данных для отчёта.", reply_markup=kb(message.from_user.id))
        return
    csv_bytes = build_csv_bytes()
    fname = f"report_{datetime.datetime.now(MSK).strftime('%Y%m%d_%H%M')}.csv"
    file = BufferedInputFile(csv_bytes, filename=fname)
    await message.answer_document(file, caption="Отчёт по сменам (MSK).", reply_markup=kb(message.from_user.id))

@router.message(F.text == "/export")
async def handle_export_cmd(message: Message):
    if not ensure_allowed(message): return
    await handle_report_button(message)

# комментарии / причины (простая версия)
@router.message()
async def handle_comment(message: Message):
    if not ensure_allowed(message): return
    uid = message.from_user.id
    shift = shift_data.get(uid)
    if not shift:
        return
    # сохраняем первое текстовое сообщение как комментарий
    if shift.get("start") and not shift.get("end") and not shift.get("comment"):
        shift["comment"] = message.text.strip()
        await message.answer("Спасибо! Смена начата. Продуктивного дня!", reply_markup=kb(uid))
    elif shift.get("end") and not shift.get("comment_done"):
        shift["comment_done"] = True
        await message.answer("Спасибо! Хорошего отдыха!", reply_markup=kb(uid))

# ================== ЗАПУСК ==================
async def main():
    await bot.set_my_commands([
        BotCommand(command="start", description="Запуск бота"),
        BotCommand(command="whoami", description="Показать мою роль"),
        BotCommand(command="export", description="Экспорт отчёта CSV (админ)"),
    ])
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
