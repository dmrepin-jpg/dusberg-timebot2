# main.py  (aiogram >= 3.7,<3.9)
import io
import csv
import asyncio
import logging
import datetime
import calendar
from collections import defaultdict
from typing import Dict, Any

from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, KeyboardButton, Message, ReplyKeyboardMarkup, BufferedInputFile
from zoneinfo import ZoneInfo

# ================== ЖЁСТКИЕ НАСТРОЙКИ ==================
BOT_TOKEN = "8396016774:AAE09_ALathLnzkKHQf7AqbPL4_m39wgBlY"   # <— ВСТАВЬ СВОЙ ТОКЕН
OWNER_ID  = 104653853
ADMIN_IDS = [104653853, 1155243378]

# Справочник сотрудников: ТОЛЬКО эти люди имеют доступ.
# ФИО берём ТОЛЬКО отсюда — никаких телеграм-ников.
EMPLOYEES: Dict[int, str] = {
    104653853: "Иванов Иван Иванович",
    1155243378: "Петров Пётр Петрович",
    # ...добавляй сотрудников: id: "Фамилия Имя Отчество",
}

# Разрешённые пользователи
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

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def kb(uid: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=admin_buttons if is_admin(uid) else user_buttons,
        resize_keyboard=True
    )

# ================== ДАННЫЕ (ПО ДНЯМ) ==================
# Храним «сегодняшние» смены отдельно по ключу даты (МСК)
# shifts_by_date["YYYY-MM-DD"][user_id] = {...}
shifts_by_date: Dict[str, Dict[int, Dict[str, Any]]] = defaultdict(dict)

# ================== УТИЛИТЫ ВРЕМЕНИ ==================
def msk_now() -> datetime.datetime:
    return datetime.datetime.now(MSK)

def today_key() -> str:
    return msk_now().date().isoformat()  # 'YYYY-MM-DD' по МСК

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

def is_weekend(date: datetime.date) -> bool:
    return calendar.weekday(date.year, date.month, date.day) >= 5

# ================== ИМЕНА ТОЛЬКО ИЗ СПРАВОЧНИКА ==================
def fio(uid: int) -> str:
    """ФИО только из EMPLOYEES. Если нет — показываем 'Неизвестный (ID)'."""
    return EMPLOYEES.get(uid, f"Неизвестный ({uid})")

# ================== ДОСТУП ==================
def ensure_allowed(message: Message) -> bool:
    uid = message.from_user.id
    if uid not in ALLOWED_IDS:
        asyncio.create_task(message.answer("Нет доступа. Обратитесь к администратору."))
        return False
    return True

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
        f"ФИО: <b>{fio(uid)}</b>\n"
        f"ID: <code>{uid}</code>",
        reply_markup=kb(uid)
    )

# ================== БИЗНЕС-ХЕНДЛЕРЫ (СЕГОДНЯ, МСК) ==================
def today_shift(uid: int) -> Dict[str, Any]:
    return shifts_by_date[today_key()].setdefault(uid, {})

@router.message(F.text == "Начал 🏭")
async def handle_start(message: Message):
    if not ensure_allowed(message): return
    uid = message.from_user.id
    now = msk_now()
    shift = today_shift(uid)

    if shift.get("start") and shift.get("end") is None:
        await message.answer("Смена уже начата. Сначала заверши текущую.", reply_markup=kb(uid))
        return

    shift["start"] = now
    shift["end"] = None
    shift["start_reason"] = None
    shift["end_reason"] = None
    shift["comment"] = None

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
    shift = today_shift(uid)

    if not shift.get("start"):
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
    uid = message.from_user.id
    data = shifts_by_date.get(today_key(), {}).get(uid)
    if not data:
        await message.answer("Смена не начата.", reply_markup=kb(uid))
        return
    await message.answer(
        f"Смена начата в: {fmt_hm(data.get('start'))}\n"
        f"Смена завершена в: {fmt_hm(data.get('end'))}",
        reply_markup=kb(uid)
    )

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

    day = today_key()
    day_data = shifts_by_date.get(day, {})
    if not day_data:
        await message.answer("Сегодня смен нет.", reply_markup=kb(message.from_user.id))
        return

    lines = []
    for uid, data in day_data.items():
        s = fmt_hm(data.get("start"))
        e = fmt_hm(data.get("end"))
        # ТОЛЬКО ФИО из справочника:
        lines.append(f"{fio(uid)}: начата в {s}, завершена в {e}")
    await message.answer("\n".join(lines), reply_markup=kb(message.from_user.id))

# ================== ОТЧЁТ (CSV за сегодня) ==================
def build_csv_today_bytes() -> bytes:
    """
    CSV UTF-8-SIG; только за текущий день (MSK).
    Колонки: Date;Name;ID;Start;End;Duration(h);Weekend;StartReason;EndReason;Comment
    """
    out = io.StringIO()
    w = csv.writer(out, delimiter=';', lineterminator='\n')
    w.writerow(["Date", "Name", "ID", "Start", "End", "Duration(h)", "Weekend", "StartReason", "EndReason", "Comment"])

    day = today_key()
    day_data = shifts_by_date.get(day, {})
    # weekend по сегодняшней дате:
    weekend = "yes" if is_weekend(msk_now().date()) else "no"

    for uid, data in day_data.items():
        start: datetime.datetime | None = data.get("start")
        end:   datetime.datetime | None = data.get("end")

        if start and start.tzinfo is None: start = start.replace(tzinfo=MSK)
        if end and end.tzinfo is None:     end   = end.replace(tzinfo=MSK)

        start_str = fmt_hm(start)
        end_str   = fmt_hm(end)

        duration_h = ""
        if start and end:
            delta = end.astimezone(MSK) - start.astimezone(MSK)
            duration_h = f"{round(delta.total_seconds()/3600, 2)}"

        w.writerow([
            day, EMPLOYEES.get(uid, ""), uid, start_str, end_str, duration_h, weekend,
            data.get("start_reason") or "", data.get("end_reason") or "", data.get("comment") or ""
        ])

    return out.getvalue().encode("utf-8-sig")

@router.message(F.text == "Отчет 📈")
async def handle_report_button(message: Message):
    if not ensure_allowed(message): return
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.", reply_markup=kb(message.from_user.id))
        return
    day_data = shifts_by_date.get(today_key(), {})
    if not day_data:
        await message.answer("Сегодня данных для отчёта нет.", reply_markup=kb(message.from_user.id))
        return
    csv_bytes = build_csv_today_bytes()
    fname = f"report_{today_key()}_{msk_now().strftime('%H%M')}.csv"
    file = BufferedInputFile(csv_bytes, filename=fname)
    await message.answer_document(file, caption="Отчёт за сегодня (MSK).", reply_markup=kb(message.from_user.id))

@router.message(F.text == "/export")
async def handle_export_cmd(message: Message):
    if not ensure_allowed(message): return
    await handle_report_button(message)

# ================== СВОБОДНЫЙ ТЕКСТ (причины/коммент) ==================
@router.message()
async def handle_comment(message: Message):
    if not ensure_allowed(message): return
    uid = message.from_user.id
    data = shifts_by_date.get(today_key(), {}).get(uid)
    if not data:
        return
    txt = (message.text or "").strip()
    if not txt:
        return
    if data.get("start") and not data.get("end") and not data.get("comment"):
        data["comment"] = txt
        await message.answer("Спасибо! Смена начата. Продуктивного дня!", reply_markup=kb(uid))
    elif data.get("end") and not data.get("comment_done"):
        data["comment_done"] = True
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
