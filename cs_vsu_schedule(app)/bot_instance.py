import os
from aiogram import Bot
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)

# Настройки для пересылки
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
except:
    ADMIN_ID = 0

try:
    REPORTS_CHAT_ID = int(os.getenv("REPORTS_CHAT_ID", ADMIN_ID))
except:
    REPORTS_CHAT_ID = ADMIN_ID
