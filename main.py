"""
main.py — QuizBot ishga tushirish
"""
import logging
from telegram import BotCommand, MenuButtonCommands
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, InlineQueryHandler, PollAnswerHandler, filters,
)
from config import TG_TOKEN, DATABASE_URL
from database import init_db, close_db
from handlers import (
    cmd_start, cmd_newquiz, cmd_myquiz, cmd_stop, cmd_help,
    handle_text, handle_file,
    handle_batch_size, handle_time_choice,
    handle_solo_ready,
    handle_start_batch, handle_confirm_batch,
    handle_retry_batch, handle_resume_batch, handle_stop_batch,
    handle_stats, handle_lang,
    handle_inline_query, handle_poll_answer, handle_fallback,
    handle_group_start, handle_group_ready, handle_bot_added,
)

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)


async def post_init(app) -> None:
    # PostgreSQL ulanish
    await init_db(DATABASE_URL)

    await app.bot.set_my_commands([
        BotCommand("newquiz", "Yangi test yaratish"),
        BotCommand("myquiz",  "Joriy test holati"),
        BotCommand("stop",    "Testni to'xtatish"),
        BotCommand("help",    "Yordam"),
    ])
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def post_shutdown(app) -> None:
    await close_db()


def main() -> None:
    app = (
        ApplicationBuilder()
        .token(TG_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Private chat buyruqlari
    app.add_handler(CommandHandler("start",   cmd_start,   filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("newquiz", cmd_newquiz, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("myquiz",  cmd_myquiz,  filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("stop",    cmd_stop,    filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("help",    cmd_help,    filters=filters.ChatType.PRIVATE))

    # Guruh buyruqlari
    app.add_handler(CommandHandler("start", handle_group_start, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("stop",  cmd_stop,           filters=filters.ChatType.GROUPS))
    # Callback handlerlar
    app.add_handler(CallbackQueryHandler(handle_lang,          pattern=r"^(newquiz|myquiz|show_lang|lang:|selectquiz:)"))
    app.add_handler(CallbackQueryHandler(handle_batch_size,    pattern=r"^bsize:"))
    app.add_handler(CallbackQueryHandler(handle_time_choice,   pattern=r"^time:"))
    app.add_handler(CallbackQueryHandler(handle_start_batch,   pattern=r"^startbatch:"))
    app.add_handler(CallbackQueryHandler(handle_confirm_batch, pattern=r"^confirmbatch:"))
    app.add_handler(CallbackQueryHandler(handle_retry_batch,   pattern=r"^retrybatch:"))
    app.add_handler(CallbackQueryHandler(handle_solo_ready,    pattern=r"^soloready:"))
    app.add_handler(CallbackQueryHandler(handle_resume_batch,  pattern=r"^resumebatch:"))
    app.add_handler(CallbackQueryHandler(handle_stop_batch,    pattern=r"^stopbatch:"))
    app.add_handler(CallbackQueryHandler(handle_stats,         pattern=r"^stats:"))
    app.add_handler(CallbackQueryHandler(handle_group_ready,   pattern=r"^gready:"))
    # Inline va poll
    app.add_handler(InlineQueryHandler(handle_inline_query))
    app.add_handler(PollAnswerHandler(handle_poll_answer))
    # Xabar handlerlar
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_bot_added))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.ChatType.PRIVATE, handle_file))
    menu_filter = filters.Regex(r"^(📝 Yangi test tuzish|📋 Testlarimni ko'rish|🌐 Til: O'zbek)$")
    app.add_handler(MessageHandler(filters.TEXT & menu_filter & filters.ChatType.PRIVATE, handle_text))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_text))
    log.info("QuizBot ishga tushdi...")
    app.run_polling(allowed_updates=[
        "message", "callback_query", "inline_query", "poll_answer", "my_chat_member"
    ])

if __name__ == "__main__":
    main()
