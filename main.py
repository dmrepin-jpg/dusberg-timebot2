# main.py  (aiogram >= 3.7,<3.9)
import os
import io
import asyncio
import logging
import datetime
import calendar
from collections import defaultdict
from typing import Dict, Any, Iterable

from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    BufferedInputFile,
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

# ================== НАСТРОЙКИ ==================

# Токен из ENV
RAW_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_TOKEN = (
    RAW_TOKEN.replace("\u00A0", " ").replace("\r", "").replace("\n", "").strip().strip('"').strip("'")
)
if not BOT_TOKEN or ":" not in BOT_TOKEN:
    raise RuntimeError(f"BOT_TOKEN выглядит неверно. RAW={RAW_TOKEN!r}")

# Роли
OWNER_ID  = 104653853
ADMIN_IDS = [104653853, 1155243378]

# Справочник сотрудников: ID -> ФИО
EMPLOYEES: Dict[int, str] = {
    104653853: "Иванов Иван Иванович",
    1155243378: "Петров Пётр Петрович",
    # добавляй здесь: 123456789: "Фамилия Имя Отчество",
}
ALLOWED_IDS = set(EMPLOYEES.keys()) | {OWNER_ID, *ADMIN_IDS}

# МСК
MSK = ZoneInfo("Europe/Moscow")

# Нормативы (МСК)
START_NORM = datetime.time(8, 0)
START_OK_TILL = datetime.time(8, 10)
END_NORM = datetime.time(17, 30)
END_OK_TILL = datetime.time(17, 40)

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
    return uid in ADMIN_IDS or uid == OWNER_ID

def kb(uid: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=admin_buttons if is_admin(uid) else user_buttons,
        resize_keyboard=True
    )

# ================== ДАННЫЕ (ПО ДНЯМ, МСК) ==================
# shifts_by_date["YYYY-MM-DD"][user_id] = {...}
shifts_by_date: Dict[str, Dict[int, Dict[str, Any]]] = defaultdict(dict)

def today_key() -> str:
    return datetime.datetime.now(MSK).date().isoformat()

def msk_now() -> datetime.datetime:
    return datetime.datetime.now(MSK)

def fmt_hm(dt: datetime.datetime | None) -> str:
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    return dt.astimezone(MSK).strftime("%H:%M")

def is_weekend(date: datetime.date) -> bool:
    return calendar.weekday(date.year, date.month, date.day) >= 5  # 5=Сб, 6=Вс

def ensure_allowed(message: Message) -> bool:
    uid = message.from_user.id
    if uid not in ALLOWED_IDS:
        asyncio.create_task(message.answer("Нет доступа. Обратитесь к администратору."))
        return False
    return True

def today_shift(uid: int) -> Dict[str, Any]:
    return shifts_by_date[today_key()].setdefault(uid, {})

def fio(uid: int) -> str:
    return EMPLOYEES.get(uid, f"Неизвестный ({uid})")

# ================== КОМАНДЫ ==================
@router.message(CommandStart())
async def cmd_start(message: Message):
    if not ensure_allowed(message): return
    await message.answer("Добро пожаловать!", reply_markup=kb(message.from_user.id))

@router.message(Command("whoami"))
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

# ================== БИЗНЕС-ЛОГИКА ==================
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
    elif now.time() < START_NORM:
        await message.answer("Раньше 08:00. Укажи причину раннего начала:", reply_markup=kb(uid))
    elif now.time() > START_OK_TILL:
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

    if now.time() < END_NORM:
        await message.answer("Раньше 17:30. Укажи причину раннего завершения:", reply_markup=kb(uid))
    elif now.time() > END_OK_TILL:
        await message.answer("Позже 17:40. Укажи причину переработки:", reply_markup=kb(uid))
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
        "В выходные/при отклонениях по времени — укажи причину по запросу.",
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
        lines.append(f"{fio(uid)}: начата в {s}, завершена в {e}")
    await message.answer("\n".join(lines), reply_markup=kb(message.from_user.id))

# ================== ОТЧЁТ ПО ДИАПАЗОНУ (XLSX) ==================
class ReportStates(StatesGroup):
    waiting_period = State()

def daterange_inclusive(d1: datetime.date, d2: datetime.date) -> Iterable[datetime.date]:
    step = 1 if d1 <= d2 else -1
    cur = d1
    while True:
        yield cur
        if cur == d2:
            break
        cur = cur + datetime.timedelta(days=step)

def parse_date(s: str) -> datetime.date | None:
    try:
        y, m, d = s.split("-")
        return datetime.date(int(y), int(m), int(d))
    except Exception:
        return None

def calc_minutes(a: datetime.time, b: datetime.time) -> int:
    """b - a в минутах (оба локальные времени), может быть отрицательным."""
    dt_a = datetime.datetime.combine(datetime.date.today(), a)
    dt_b = datetime.datetime.combine(datetime.date.today(), b)
    return int((dt_b - dt_a).total_seconds() // 60)

def deviation_columns(start_dt: datetime.datetime | None, end_dt: datetime.datetime | None) -> tuple[int,int,int,int]:
    """(раньше_начало, позже_начало, раньше_конец, позже_конец) в минутах (>=0)"""
    early_start = late_start = early_end = late_end = 0
    if start_dt:
        st_local = start_dt.astimezone(MSK).time()
        # раннее начало: сколько минут до 08:00
        if st_local < START_NORM:
            early_start = calc_minutes(st_local, START_NORM) * -1  # отрицательное → в плюс
            early_start = max(0, early_start)
        # позднее начало: сколько минут после 08:10
        if st_local > START_OK_TILL:
            late_start = calc_minutes(START_OK_TILL, st_local)
            late_start = max(0, late_start)
    if end_dt:
        en_local = end_dt.astimezone(MSK).time()
        # раннее завершение: сколько минут до 17:30
        if en_local < END_NORM:
            early_end = calc_minutes(en_local, END_NORM) * -1
            early_end = max(0, early_end)
        # позднее завершение: сколько минут после 17:40
        if en_local > END_OK_TILL:
            late_end = calc_minutes(END_OK_TILL, en_local)
            late_end = max(0, late_end)
    return early_start, late_start, early_end, late_end

def minutes_between(start_dt: datetime.datetime | None, end_dt: datetime.datetime | None) -> int:
    if not start_dt or not end_dt:
        return 0
    a = start_dt.astimezone(MSK)
    b = end_dt.astimezone(MSK)
    if b < a:
        return 0
    return int((b - a).total_seconds() // 60)

def build_xlsx_bytes(date_from: datetime.date, date_to: datetime.date) -> bytes:
    wb = Workbook()
    ws_shifts = wb.active
    ws_shifts.title = "Смены"
    ws_daily = wb.create_sheet("Свод по дням")
    ws_emps = wb.create_sheet("Сотрудники")
    ws_params = wb.create_sheet("Параметры")

    # ---- Шапки
    shifts_header = [
        "Дата","Сотрудник","ID","Начало","Конец",
        "Раннее начало, мин","Позднее начало, мин","Раннее завершение, мин","Позднее завершение, мин",
        "Длительность, мин","Длительность, ч","Выходной","Причина начала","Причина завершения","Комментарий"
    ]
    ws_shifts.append(shifts_header)

    daily_header = [
        "Дата","Сотрудник","ID","Начало","Конец",
        "Раннее начало, мин","Позднее начало, мин","Раннее завершение, мин","Позднее завершение, мин",
        "Длительность, мин","Длительность, ч","Выходной"
    ]
    ws_daily.append(daily_header)

    ws_emps.append(["ID","Сотрудник"])
    for uid, name in sorted(EMPLOYEES.items()):
        ws_emps.append([uid, name])

    ws_params.append(["Параметр","Значение"])
    ws_params.append(["Часовой пояс","Europe/Moscow"])
    ws_params.append(["Норма начала","08:00"])
    ws_params.append(["Допустимо до (начало)","08:10"])
    ws_params.append(["Норма конца","17:30"])
    ws_params.append(["Допустимо до (конец)","17:40"])

    # ---- Данные
    # Собираем свод сразу по ходу (на случай если когда-то появятся несколько интервалов в день)
    # Здесь у нас по дизайну одна запись в день на сотрудника.
    for day in daterange_inclusive(date_from, date_to):
        key = day.isoformat()
        day_data = shifts_by_date.get(key, {})
        weekend = "Да" if is_weekend(day) else "Нет"

        for uid, data in day_data.items():
            name = EMPLOYEES.get(uid, "")
            start_dt: datetime.datetime | None = data.get("start")
            end_dt:   datetime.datetime | None = data.get("end")

            # Приводим к МСК и форматы
            start_str = fmt_hm(start_dt)
            end_str   = fmt_hm(end_dt)

            early_start, late_start, early_end, late_end = deviation_columns(start_dt, end_dt)
            work_min = minutes_between(start_dt, end_dt)
            work_hours = round(work_min/60, 2)

            ws_shifts.append([
                day, name, uid, start_str, end_str,
                early_start, late_start, early_end, late_end,
                work_min, work_hours, weekend,
                data.get("start_reason") or "",
                data.get("end_reason") or "",
                data.get("comment") or "",
            ])

            ws_daily.append([
                day, name, uid, start_str, end_str,
                early_start, late_start, early_end, late_end,
                work_min, work_hours, weekend
            ])

    # ---- Форматы столбцов и немного красоты
    def fit_columns(ws):
        widths = {}
        for row in ws.iter_rows(values_only=True):
            for i, cell in enumerate(row, 1):
                s = "" if cell is None else str(cell)
                widths[i] = max(widths.get(i, 0), len(s))
        for i, w in widths.items():
            ws.column_dimensions[get_column_letter(i)].width = min(max(10, w + 2), 40)

    for ws in (ws_shifts, ws_daily, ws_emps, ws_params):
        fit_columns(ws)
        # центрируем заголовки
        for cell in next(ws.iter_rows(min_row=1, max_row=1)):
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center")

    # Сохраняем в память
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()

# ======== FSM: просим период у админа по кнопке «Отчет 📈» ========
@router.message(F.text == "Отчет 📈")
async def ask_report_period(message: Message, state: FSMContext):
    if not ensure_allowed(message): return
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.", reply_markup=kb(message.from_user.id))
        return
    await state.set_state(ReportStates.waiting_period)
    await message.answer(
        "Введите период дат (включительно) в формате:\n"
        "• Один день: <code>2025-08-20</code>\n"
        "• Диапазон: <code>2025-08-01 2025-08-20</code>\n"
        "Для отмены: /cancel"
    )

@router.message(Command("cancel"))
async def cancel_report(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=kb(message.from_user.id))

@router.message(ReportStates.waiting_period, F.text)
async def handle_report_period(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.", reply_markup=kb(message.from_user.id))
        await state.clear()
        return

    parts = message.text.strip().split()
    if len(parts) == 1:
        d1 = parse_date(parts[0]); d2 = d1
    elif len(parts) == 2:
        d1 = parse_date(parts[0]); d2 = parse_date(parts[1])
    else:
        d1 = d2 = None

    if not d1 or not d2:
        await message.answer("Неверный формат. Пример: <code>2025-08-01 2025-08-20</code> или <code>2025-08-20</code>")
        return

    # нормализуем порядок
    if d2 < d1:
        d1, d2 = d2, d1

    # проверим, есть ли вообще данные в диапазоне
    has_any = any(shifts_by_date.get(day.isoformat()) for day in daterange_inclusive(d1, d2))
    if not has_any:
        await message.answer("В указанном периоде нет данных.")
        await state.clear()
        return

    try:
        xlsx = build_xlsx_bytes(d1, d2)
        fname = f"Отчёт_{d1.isoformat()}_{d2.isoformat()}.xlsx" if d1 != d2 else f"Отчёт_{d1.isoformat()}.xlsx"
        await message.answer_document(
            BufferedInputFile(xlsx, filename=fname),
            caption=f"Отчёт за период {d1.isoformat()} — {d2.isoformat()} (МСК).",
            reply_markup=kb(message.from_user.id)
        )
    except Exception as e:
        logging.exception("Ошибка формирования отчёта: %s", e)
        await message.answer("Не удалось сформировать отчёт. Проверьте данные и попробуйте ещё раз.")
    finally:
        await state.clear()

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
    try:
        me = await bot.get_me()
        logging.info("Авторизован как @%s (id=%s)", me.username, me.id)
        await bot.set_my_commands([
            BotCommand(command="start", description="Запуск бота"),
            BotCommand(command="whoami", description="Показать мою роль"),
            BotCommand(command="cancel", description="Отменить ввод периода"),
        ])
        await dp.start_polling(bot)
    except Exception as e:
        logging.exception("Старт не удался: %s", e)
        await bot.session.close()
        raise

if __name__ == "__main__":
    asyncio.run(main())
