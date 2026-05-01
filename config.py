"""
config.py — Bot sozlamalari (.env dan o'qiladi)
"""
import os
from dotenv import load_dotenv

load_dotenv()

TG_TOKEN = os.getenv("TG_TOKEN")
BASE_URL = os.getenv("DATABASE_URL")


BATCH_SIZE = 30
DEFAULT_PAUSE = 2
