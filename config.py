"""
config.py — Bot sozlamalari (.env dan o'qiladi)
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(".env"))

# Bot username (.env da yozing, @ belgisisiz)
# Masalan: BOT_USERNAME=QuizBot
TG_TOKEN     = os.getenv("TG_TOKEN", "YOUR_BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "YourBotUsername")

BATCH_SIZE    = 30
DEFAULT_PAUSE = 2

# PostgreSQL
DATABASE_URL = os.getenv(
    "DATABASE_URL"
)