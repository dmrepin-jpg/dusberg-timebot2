from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.utils import executor
import os

TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

@dp.message_handler(commands=['start', 'начать_смену'])
async def start_shift(message: Message):
    await message.reply("Смена начата.")

@dp.message_handler(commands=['stop', 'закончить_смену'])
async def stop_shift(message: Message):
    await message.reply("Смена завершена.")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)