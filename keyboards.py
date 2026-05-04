"""
keyboards.py — Barcha Telegram klaviaturalar
"""
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    SwitchInlineQueryChosenChat,
)
from config import BOT_USERNAME
from i18n import t

def _private_start_url(owner_uid: int, batch_index: int = 0) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=batch_{owner_uid}_{batch_index}"


def _group_start_url(uid: int, batch_index: int = 0) -> str:
    return f"https://t.me/{BOT_USERNAME}?startgroup={uid}_{batch_index}"


def _share_btn(uid: int, batch_index: int = 0) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        "📤 Testni ulashish",
        switch_inline_query=f"share:{uid}:{batch_index}",
    )


def main_menu_kb(lang: str = "uz") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "create"),   callback_data="newquiz")],
        [InlineKeyboardButton(t(lang, "view"),     callback_data="myquiz")],
        [InlineKeyboardButton(t(lang, "lang_btn"), callback_data="show_lang")],
    ])


def batch_size_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("10 ta",  callback_data="bsize:10"),
            InlineKeyboardButton("20 ta",  callback_data="bsize:20"),
        ],
        [
            InlineKeyboardButton("30 ta",  callback_data="bsize:30"),
            InlineKeyboardButton("50 ta",  callback_data="bsize:50"),
        ],
    ])


def time_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏱ 10 sek", callback_data="time:10"),
            InlineKeyboardButton("⏱ 15 sek", callback_data="time:15"),
        ],
        [
            InlineKeyboardButton("⏱ 20 sek", callback_data="time:20"),
            InlineKeyboardButton("⏱ 30 sek", callback_data="time:30"),
        ],
    ])


def batch_card_kb(uid: int, batch_index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Boshlash",         url=_private_start_url(uid, batch_index))],
        [InlineKeyboardButton("👥 Guruhda boshlash",  url=_group_start_url(uid, batch_index))],
        [_share_btn(uid, batch_index)],
    ])


def group_ready_kb(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Men tayyorman!", callback_data=f"gready:{uid}")],
    ])


def group_result_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Testni ulashish", switch_inline_query="")],
    ])


def result_kb(uid: int, quiz_name: str = "", total: int = 0,
              time_label: str = "", batch_index: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Qaytadan urinish",     callback_data=f"retrybatch:{batch_index}")],
        [InlineKeyboardButton("👥 Guruhda testni boshlash", url=_group_start_url(uid, batch_index))],
        [_share_btn(uid, batch_index)],
    ])


def lang_kb() -> InlineKeyboardMarkup:
    langs = [
        ("O'zbek",             "uz"),
        ("العربية",            "ar"),
        ("Català",             "ca"),
        ("Nederlands",         "nl"),
        ("English",            "en"),
        ("Français",           "fr"),
        ("Deutsch",            "de"),
        ("Bahasa Indonesia",   "id"),
        ("Italiano",           "it"),
        ("한국어",              "ko"),
        ("Bahasa Melayu",      "ms"),
        ("فارسی",              "fa"),
        ("Polski",             "pl"),
        ("Português (Brasil)", "pt"),
        ("Русский",            "ru"),
        ("Español",            "es"),
        ("Türkçe",             "tr"),
        ("Українська",         "uk"),
    ]
    rows = []
    for i in range(0, len(langs), 2):
        row = [
            InlineKeyboardButton(name, callback_data=f"lang:{code}")
            for name, code in langs[i:i+2]
        ]
        rows.append(row)
    return InlineKeyboardMarkup(rows)

def quiz_list_kb(quizzes: list, lang: str = "uz") -> InlineKeyboardMarkup:
    rows = []
    for i, q in enumerate(quizzes):
        name = q.get("quiz_name") or f"Test {i+1}"
        rows.append([
            InlineKeyboardButton(f"📋 {name}", callback_data=f"selectquiz:{i}")
        ])
    return InlineKeyboardMarkup(rows)


def quiz_batches_kb(uid: int, quiz_index: int, batches: list,
                    open_time=None, lang: str = "uz") -> InlineKeyboardMarkup:
    rows = []
    time_lbl = f"{open_time} soniya" if open_time else "Vaqtsiz"
    for i, batch in enumerate(batches):
        rows.append([
            InlineKeyboardButton(
                f"📦 {i+1}-to'plam — {len(batch)} ta savol",
                callback_data=f"startbatch:{i}:{uid}"
            )
        ])
    return InlineKeyboardMarkup(rows)

def shuffle_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Ha, aralashtir", callback_data="shuffle:yes"),
            InlineKeyboardButton("❌ Yo'q, tartibda", callback_data="shuffle:no"),
        ]
    ])

def shuffle_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Ha, aralashtir", callback_data="shuffle:yes"),
            InlineKeyboardButton("❌ Yo'q, tartibda", callback_data="shuffle:no"),
        ]
    ])
