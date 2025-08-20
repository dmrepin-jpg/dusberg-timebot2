# main.py  (aiogram >= 3.7,<3.9)
import os
import io
import json
import asyncio
import logging
import datetime
import calendar
from pathlib import Path
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
    BotCommandScopeDefault,
    BotCommandScopeChat,
)
from aiogram.filters import CommandStart, Command, CommandObject
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
ADMIN_IDS = [104653853, 1155243378]  # можно расширять

# Файлы данных
EMP_FILE   = Path("employees.json")
SHIFT_FILE = Path("shifts.json")

# МСК
MSK = ZoneInfo("Europe/Moscow")

# ===== Нормативы для ОТЧЁТА (Excel) — НЕ МЕНЯЕМ =====
START_NORM = datetime.time(8, 0)      # начало: норма
START_OK_TILL = datetime.time(8, 10)  # начало: допустимо до
END_NORM = datetime.time(17, 30)      # конец: норма
END_OK_TILL = datetime.time(17, 40)   # конец: допустимо до

# ===== Допуски ТОЛЬКО для вопросов в БОТЕ =====
PROMPT_EARLY_OK_FROM = datetime.time(7, 45)  # начало до 07:45 — спросим причину
PROMPT_START_OK_TILL = datetime.time(8, 10)  # после 08:10 — спросим причину
PROMPT_END_OK_TILL   = datetime.time(17, 45) # после 17:45 — спросим причину

# ================== ИНИЦИАЛИЗАЦИЯ ==================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# ================== ДАННЫЕ (ПО ДНЯМ, МСК) ==================
# shifts_by_date["YYYY-MM-DD"][user_id] = {...}
shifts_by_date: Dict[str, Dict[int, Dict[str, Any]]] = defaultdict(dict)

# Справочник сотрудников: ID -> ФИО (из файла)
DEFAULT_EMPLOYEES = {
    str(OWNER_ID): "OWNER",
}
EMPLOYEES: Dict[int, str] = {}  # загрузим из файла ниже

# Ожидание ввода причины: { user_id: "start_early"|"start_late"|"end_early"|"end_late" }
pending_reason: Dict[int, str] = {}

# ================== УТИЛИТЫ ==================
def msk_now() -> datetime.datetime:
    return datetime.datetime.now(MSK)

def today_key() -> str:
    return msk_now().date().isoformat()

def fmt_hm(dt: datetime.datetime | None) -> str:
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    return dt.astimezone(MSK).strftime("%H:%M")

def is_weekend(date: datetime.date) -> bool:
    return calendar.weekday(date.year, date.month, date.day) >= 5  # 5=Сб, 6=Вс

def fio(uid: int) -> str:
    return EMPLOYEES.get(uid, f"Неизвестный ({uid})")

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS or uid == OWNER_ID

def is_allowed(uid: int) -> bool:
    return uid == OWNER_ID or uid in ADMIN_IDS or uid in EMPLOYEES

def ensure_allowed(message: Message) -> bool:
    uid = message.from_user.id
    if not is_allowed(uid):
        asyncio.create_task(message.answer("Нет доступа. Обратитесь к администратору."))
        return False
    return True

def today_shift(uid: int) -> Dict[str, Any]:
    return shifts_by_date[today_key()].setdefault(uid, {})

# ================== I/O СПРАВОЧНИКА И СМЕН ==================
def load_employees() -> dict[int, str]:
    if EMP_FILE.exists():
        try:
            raw = json.loads(EMP_FILE.read_text("utf-8"))
            return {int(k): str(v) for k, v in raw.items()}
        except Exception as e:
            logging.exception("Не удалось прочитать employees.json: %s", e)
    # создаём по умолчанию
    EMP_FILE.write_text(json.dumps(DEFAULT_EMPLOYEES, ensure_ascii=False, indent=2), "utf-8")
    return {int(k): v for k, v in DEFAULT_EMPLOYEES.items()}

def save_employees() -> None:
    out = {str(k): v for k, v in EMPLOYEES.items()}
    EMP_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")

def dt_to_iso(dt: datetime.datetime | None) -> str | None:
    return dt.astimezone(MSK).isoformat() if dt else None

def dt_from_iso(s: str | None) -> datetime.datetime | None:
    if not s:
        return None
    return datetime.datetime.fromisoformat(s)  # tz-aware

def save_shifts() -> None:
    data_out: dict[str, dict[str, dict[str, Any]]] = {}
    for day, users in shifts_by_date.items():
        data_out[day] = {}
        for uid, d in users.items():
            data_out[day][str(uid)] = {
                "start": dt_to_iso(d.get("start")),
                "end": dt_to_iso(d.get("end")),
                "start_reason": d.get("start_reason"),
                "end_reason": d.get("end_reason"),
                "comment": d.get("comment"),
                "comment_done": d.get("comment_done"),
            }
    SHIFT_FILE.write_text(json.dumps(data_out, ensure_ascii=False, indent=2), "utf-8")

def load_shifts() -> None:
    if not SHIFT_FILE.exists():
        return
    try:
        data_in = json.loads(SHIFT_FILE.read_text("utf-8"))
    except Exception as e:
        logging.exception("Не удалось прочитать shifts.json: %s", e)
        return
    for day, users in data_in.items():
        shifts_by_date[day] = {}
        for uid_str, d in users.items():
            uid = int(uid_str)
            shifts_by_date[day][uid] = {
                "start": dt_from_iso(d.get("start")),
                "end": dt_from_iso(d.get("end")),
                "start_reason": d.get("start_reason"),
                "end_reason": d.get("end_reason"),
                "comment": d.get("comment"),
                "comment_done": d.get("comment_done"),
            }

# Загрузим данные при старте процесса
EMPLOYEES = load_employees()
load_shifts()

# ================== КНОПКИ ==================
user_buttons = [
    [KeyboardButton(text="Смену начал 🏭"), KeyboardButton(text="Смену закончил 🏡")],
    [KeyboardButton(text="Мой статус"), KeyboardButton(text="Инструкция")],
]
admin_buttons = user_buttons + [[KeyboardButton(text="Отчет 📈"), KeyboardButton(text="Статус смены")]]

def kb(uid: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=admin_buttons if is_admin(uid) else user_buttons,
        resize_keyboard=True
    )

# ================== КОМАНДЫ ==================
@router.message(CommandStart())
async def cmd_start(message: Message):
    if not ensure_allowed(message): return
    await message.answer("Добро пожаловать в бот учёта рабочего времени DUSBERG!", reply_markup=kb(message.from_user.id))

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

# ----- OWNER-Команды управления справочником -----
def owner_only(uid: int) -> bool:
    return uid == OWNER_ID

@router.message(Command("emp_list"))
async def emp_list(message: Message):
    if not owner_only(message.from_user.id):
        return
    if not EMPLOYEES:
        return await message.answer("Справочник пуст.")
    lines = [f"{uid}: {name}" for uid, name in sorted(EMPLOYEES.items(), key=lambda kv: kv[0])]
    await message.answer("Сотрудники:\n" + "\n".join(lines))

@router.message(Command("emp_add"))
async def emp_add(message: Message, command: CommandObject):
    if not owner_only(message.from_user.id):
        return
    text = (command.args or "").strip()
    if not text:
        return await message.answer('Формат: /emp_add <id> <ФИО в кавычках или без>')
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.answer('Нужно и ID, и ФИО. Пример: /emp_add 123 "Иванов И.И."')
    try:
        new_id = int(parts[0])
    except ValueError:
        return await message.answer("ID должен быть числом.")
    name = parts[1].strip().strip('"').strip("'")
    if not name:
        return await message.answer("Пустое имя.")
    EMPLOYEES[new_id] = name
    save_employees()
    await message.answer(f"Добавлен: {new_id} — {name}")

@router.message(Command("emp_del"))
async def emp_del(message: Message, command: CommandObject):
    if not owner_only(message.from_user.id):
        return
    text = (command.args or "").strip()
    if not text:
        return await message.answer("Формат: /emp_del <id>")
    try:
        uid = int(text)
    except ValueError:
        return await message.answer("ID должен быть числом.")
    if EMPLOYEES.pop(uid, None) is None:
        return await message.answer("Такого ID нет в справочнике.")
    save_employees()
    await message.answer(f"Удалён: {uid}")

@router.message(Command("emp_reload"))
async def emp_reload(message: Message):
    if not owner_only(message.from_user.id):
        return
    global EMPLOYEES
    EMPLOYEES = load_employees()
    await message.answer("Справочник перезагружен из файла.")

# ================== БИЗНЕС-ЛОГИКА ==================
@router.message(F.text == "Смену начал 🏭")
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
    pending_reason.pop(uid, None)
    save_shifts()

    t = now.time()
    if is_weekend(now.date()):
        pending_reason[uid] = "start_early"
        await message.answer("Сегодня выходной. Укажи причину начала смены (текстом):", reply_markup=kb(uid))
    elif t < PROMPT_EARLY_OK_FROM:
        pending_reason[uid] = "start_early"
        await message.answer("Смена начата слишком рано (до 07:45). Укажи причину (текстом):", reply_markup=kb(uid))
    elif t > PROMPT_START_OK_TILL:
        pending_reason[uid] = "start_late"
        await message.answer("Смена начата позже 08:10. Укажи причину опоздания (текстом):", reply_markup=kb(uid))
    else:
        await message.answer("Смена начата. Продуктивного дня!", reply_markup=kb(uid))

@router.message(F.text == "Смену закончил 🏡")
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
    pending_reason.pop(uid, None)
    save_shifts()

    t = now.time()
    if t < END_NORM:
        pending_reason[uid] = "end_early"
        await message.answer("Смена завершена слишком рано (до 17:30). Укажи причину (текстом):", reply_markup=kb(uid))
    elif t > PROMPT_END_OK_TILL:
        pending_reason[uid] = "end_late"
        await message.answer("Смена завершена позже 17:45. Укажи причину переработки (текстом):", reply_markup=kb(uid))
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

    lines = [
        f"Смена начата в: {fmt_hm(data.get('start'))}",
        f"Смена завершена в: {fmt_hm(data.get('end'))}",
    ]
    if data.get("start_reason"):
        lines.append(f"Причина начала: {data['start_reason']}")
    if data.get("end_reason"):
        lines.append(f"Причина завершения: {data['end_reason']}")
    if data.get("comment"):
        lines.append(f"Комментарий: {data['comment']}")

    await message.answer("\n".join(lines), reply_markup=kb(uid))

@router.message(F.text == "Инструкция")
async def handle_help(message: Message):
    if not ensure_allowed(message): return
    await message.answer(
        "Для регистрации времени начала смены нажми «Смену начал 🏭». Для регистрации завершения — «Смену закончил 🏡».\n"
        "Если бот спрашивает причину — ответь одним сообщением (текстом), это сохранится как причина начала/завершения.\n"
        "Дополнительные пояснения можно прислать отдельным сообщением — это общий комментарий.",
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
        who = fio(uid)
        suffix = []
        if data.get("start_reason"):
            suffix.append("причина начала есть")
        if data.get("end_reason"):
            suffix.append("причина завершения есть")
        extra = f" ({', '.join(suffix)})" if suffix else ""
        lines.append(f"{who}: начата в {s}, завершена в {e}{extra}")
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
    dt_a = datetime.datetime.combine(datetime.date.today(), a)
    dt_b = datetime.datetime.combine(datetime.date.today(), b)
    return int((dt_b - dt_a).total_seconds() // 60)

def deviation_columns(start_dt: datetime.datetime | None, end_dt: datetime.datetime | None) -> tuple[int,int,int,int]:
    """(раньше_начало, позже_начало, раньше_конец, позже_конец) в минутах (>=0) — ДЛЯ ОТЧЁТА"""
    early_start = late_start = early_end = late_end = 0
    if start_dt:
        st_local = start_dt.astimezone(MSK).time()
        if st_local < START_NORM:
            early_start = calc_minutes(st_local, START_NORM)
        if st_local > START_OK_TILL:
            late_start = calc_minutes(START_OK_TILL, st_local)
    if end_dt:
        en_local = end_dt.astimezone(MSK).time()
        if en_local < END_NORM:
            early_end = calc_minutes(en_local, END_NORM)
        if en_local > END_OK_TILL:
            late_end = calc_minutes(END_OK_TILL, en_local)
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
    ws_params.append(["Период отчёта", f"{date_from.isoformat()} — {date_to.isoformat()}"])

    # ---- Данные
    for day in daterange_inclusive(date_from, date_to):
        key = day.isoformat()
        day_data = shifts_by_date.get(key, {})
        weekend = "Да" if is_weekend(day) else "Нет"

        for uid, data in day_data.items():
            name = fio(uid)
            start_dt: datetime.datetime | None = data.get("start")
            end_dt:   datetime.datetime | None = data.get("end")

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

    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()

# ======== FSM: просим период у админа по кнопке «Отчет 📈» ========
class ReportStates(StatesGroup):
    waiting_period = State()

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

    if d2 < d1:
        d1, d2 = d2, d1

    if (d2 - d1).days > 92:
        await message.answer("Слишком длинный период (>92 дней). Сократите интервал.")
        await state.clear()
        return

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

# ================== СВОБОДНЫЙ ТЕКСТ (причины/комментарии) ==================
@router.message()
async def handle_comment_or_reason(message: Message):
    if not ensure_allowed(message): return
    uid = message.from_user.id
    txt = (message.text or "").strip()
    if not txt:
        return

    # Если ждём причину — сохраняем приоритетно в start_reason/end_reason
    reason_flag = pending_reason.get(uid)
    if reason_flag:
        shift = shifts_by_date.get(today_key(), {}).get(uid)
        if not shift:
            pending_reason.pop(uid, None)
            return
        if reason_flag in ("start_early", "start_late"):
            shift["start_reason"] = txt
            await message.answer("Спасибо! Причина начала зафиксирована.", reply_markup=kb(uid))
        elif reason_flag in ("end_early", "end_late"):
            shift["end_reason"] = txt
            await message.answer("Спасибо! Причина завершения зафиксирована.", reply_markup=kb(uid))
        pending_reason.pop(uid, None)
        save_shifts()
        return

    # Иначе — это общий комментарий к текущей смене
    shift = shifts_by_date.get(today_key(), {}).get(uid)
    if not shift:
        return
    if shift.get("start") and not shift.get("end") and not shift.get("comment"):
        shift["comment"] = txt
        await message.answer("Комментарий сохранён. Продуктивного дня!", reply_markup=kb(uid))
        save_shifts()
    elif shift.get("end") and not shift.get("comment_done"):
        shift["comment_done"] = True
        await message.answer("Комментарий получен. Хорошего отдыха!", reply_markup=kb(uid))
        save_shifts()

# ================== ЗАПУСК ==================
async def main():
    try:
        me = await bot.get_me()
        logging.info("Авторизован как @%s (id=%s)", me.username, me.id)

        # Базовые команды (видны всем)
        base_cmds = [
            BotCommand(command="start", description="Запуск бота"),
            BotCommand(command="whoami", description="Показать мою роль"),
            BotCommand(command="cancel", description="Отменить ввод периода"),
        ]
        await bot.set_my_commands(base_cmds, scope=BotCommandScopeDefault())

        # Доп. команды только OWNER (видны только тебе в личке)
        owner_cmds = base_cmds + [
            BotCommand(command="emp_list", description="(OWNER) Список сотрудников"),
            BotCommand(command="emp_add", description="(OWNER) Добавить сотрудника"),
            BotCommand(command="emp_del", description="(OWNER) Удалить сотрудника"),
            BotCommand(command="emp_reload", description="(OWNER) Перезагрузить справочник"),
        ]
        await bot.set_my_commands(owner_cmds, scope=BotCommandScopeChat(chat_id=OWNER_ID))

        await dp.start_polling(bot)
    except Exception as e:
        logging.exception("Старт не удался: %s", e)
    finally:
        # Сохраним состояние смен на всякий случай
        try:
            save_shifts()
        finally:
            await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
