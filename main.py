import asyncio
import logging
import os
import json
import pandas as pd
from datetime import datetime, time
import pytz
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, Message
from aiogram.exceptions import TelegramBadRequest
from aiogram.types.input_file import FSInputFile

# --- Настройки ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_TOKEN = '8369016774:AAE09_ALathLnzKdHQF7qAbpL4_mJ9wg8IY'  # ← ваш токен, не публикуйте его в открытом доступе
ADMIN_IDS = [104653853]  # ← ваш Telegram user_id
DATA_FILE = 'data.json'
TZ = pytz.timezone('Europe/Moscow')

# --- Инициализация ---
bot = Bot(token=API_TOKEN, parse_mode='HTML')
dp = Dispatcher()
data = {}

# --- Утилиты ---
def load_data():
    global data
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f)
            data.clear()
            for k, v in raw.items():
                data[str(k)] = {
                    'name': v.get('name'),
                    'start': datetime.fromisoformat(v['start']) if v.get('start') else None,
                    'end': datetime.fromisoformat(v['end']) if v.get('end') else None
                }
    except FileNotFoundError:
        data.clear()

def save_data():
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        serializable = {
            uid: {
                'name': v['name'],
                'start': v['start'].isoformat() if v.get('start') else None,
                'end': v['end'].isoformat() if v.get('end') else None
            } for uid, v in data.items()
        }
        json.dump(serializable, f, ensure_ascii=False, indent=2)

def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_keyboard(is_admin=False):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton(text="Начал 🏭"), KeyboardButton(text="Закончил 🏡"))
    kb.add(KeyboardButton(text="Мой статус"), KeyboardButton(text="Инструкция 📖"))
    if is_admin:
        kb.add(KeyboardButton(text="Статус📍"), KeyboardButton(text="Отчет 📈"))
    return kb

def within_working_hours():
    now = datetime.now(TZ).time()
    return time(7, 0) <= now <= time(17, 30)

# --- Команды ---
@dp.message(CommandStart())
async def on_start(message: Message):
    load_data()
    await message.answer("Желаю продуктивного рабочего дня!", reply_markup=get_keyboard(is_admin(message.from_user.id)))

@dp.message(lambda m: m.text.startswith("Начал"))
async def handle_start_shift(message: Message):
    user_id = str(message.from_user.id)
    now = datetime.now(TZ)
    if not within_working_hours():
        await message.answer("Сейчас нерабочее время. Смена возможна с 07:00 до 17:30 по МСК.")
        return
    shift = data.get(user_id, {})
    if shift.get('start'):
        await message.answer(f"Смена уже начата в {shift['start'].strftime('%H:%M')}.")
    else:
        data[user_id] = {'name': message.from_user.full_name, 'start': now, 'end': None}
        save_data()
        await message.answer("Смена начата. Желаю продуктивного рабочего дня!")

@dp.message(lambda m: m.text.startswith("Закончил"))
async def handle_end_shift(message: Message):
    user_id = str(message.from_user.id)
    now = datetime.now(TZ)
    shift = data.get(user_id)
    if not shift or not shift.get('start'):
        await message.answer("Смена ещё не начата.")
        return
    if shift.get('end'):
        await message.answer(f"Смена уже завершена в {shift['end'].strftime('%H:%M')}.")
    else:
        data[user_id]['end'] = now
        save_data()
        await message.answer("Смена завершена. Спасибо! Желаю хорошо отдохнуть!")

@dp.message(lambda m: m.text == "Мой статус")
async def handle_my_status(message: Message):
    user_id = str(message.from_user.id)
    shift = data.get(user_id)
    if not shift:
        await message.answer("Вы ещё не начинали смену.")
    elif shift.get('end'):
        await message.answer(f"Смена завершена в {shift['end'].strftime('%H:%M')}.")
    elif shift.get('start'):
        await message.answer(f"Смена начата в {shift['start'].strftime('%H:%M')}, вы на смене.")
    else:
        await message.answer("Неопределённый статус.")

@dp.message(lambda m: m.text.startswith("Статус") and is_admin(m.from_user.id))
async def handle_admin_status(message: Message):
    now = datetime.now(TZ).date()
    report = []
    for uid, shift in data.items():
        name = shift['name']
        start = shift.get('start')
        end = shift.get('end')
        if start and start.date() == now:
            if end:
                report.append(f"{name}: завершил смену в {end.strftime('%H:%M')}")
            else:
                report.append(f"{name}: на смене с {start.strftime('%H:%M')}")
        else:
            report.append(f"{name}: не на смене")
    await message.answer("\n".join(report) if report else "Нет сотрудников в базе.")

@dp.message(lambda m: m.text.startswith("Отчет") and is_admin(m.from_user.id))
async def handle_report(message: Message):
    rows = []
    for uid, shift in data.items():
        rows.append({
            'Имя': shift.get('name', ''),
            'Начало': shift.get('start').strftime('%Y-%m-%d %H:%M') if shift.get('start') else '',
            'Окончание': shift.get('end').strftime('%Y-%m-%d %H:%M') if shift.get('end') else ''
        })
    df = pd.DataFrame(rows)
    file_name = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df.to_excel(file_name, index=False)
    await message.answer_document(FSInputFile(file_name))
    os.remove(file_name)

@dp.message(lambda m: m.text.startswith("Инструкция"))
async def handle_instructions(message: Message):
    text = (
        "📖 <b>Инструкция</b>\n\n"
        "<b>Команды для сотрудников:</b>\n"
        "Начал 🏭 — начало смены\n"
        "Закончил 🏡 — завершение смены\n"
        "Мой статус — ваш текущий статус\n"
        "Инструкция 📖 — правила использования бота\n\n"
        "<b>Команды для администратора:</b>\n"
        "Статус📍 — статус всех сотрудников\n"
        "Отчет 📈 — отчёт в Excel по сменам"
    )
    await message.answer(text)

@dp.message()
async def fallback(message: Message):
    await message.answer("Пожалуйста, используйте кнопки для взаимодействия с ботом.")

async def main():
    load_data()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
