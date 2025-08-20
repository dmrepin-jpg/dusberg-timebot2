import asyncio
import logging
import os
import json
from datetime import datetime, time, date
import pytz
import pandas as pd
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.types.input_file import FSInputFile
from aiogram.exceptions import TelegramBadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# --- НАСТРОЙКИ ---
API_TOKEN = '8369016774:AAE09_ALathLnzKdHQF7qAbpL4_mJ9wg8IY'
ADMIN_IDS = [104653853]
TIMEZONE = pytz.timezone("Europe/Moscow")

# --- ЛОГИРОВАНИЕ ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- ХРАНИЛИЩЕ ---
data = {}

# --- ФАЙЛЫ ---
DATA_FILE = "data.json"
REPORT_FILE = "report.xlsx"

# --- ЗАГРУЗКА / СОХРАНЕНИЕ ---
def load_data():
    global data
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)


# --- ПРОВЕРКИ ---
def is_admin(user_id):
    return user_id in ADMIN_IDS


def within_working_hours():
    now = datetime.now(TIMEZONE).time()
    return time(8, 0) <= now <= time(17, 30)


def is_working_day():
    return datetime.now(TIMEZONE).weekday() < 5  # ПН=0, ВС=6

# --- КЛАВИАТУРА ---
def get_keyboard(is_admin=False):
    buttons = [
        [KeyboardButton(text="Начал 
