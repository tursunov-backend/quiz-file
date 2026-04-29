"""
config.py — Bot sozlamalari (.env dan o'qiladi)
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(".env"))

TG_TOKEN      = os.environ["TG_TOKEN"]
BATCH_SIZE    = 30
DEFAULT_PAUSE = 2

# Bot username (.env da yozing, @ belgisisiz)
# Masalan: BOT_USERNAME=QuizBot
BOT_USERNAME = os.getenv("BOT_USERNAME", "")