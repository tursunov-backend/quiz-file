"""
handlers.py — Barcha Telegram handlerlar
"""
import os
import logging
import tempfile
from pathlib import Path

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes

from keyboards import (
    main_menu_kb, batch_size_kb, time_kb,
    batch_card_kb, group_ready_kb, result_kb, lang_kb,
)
from parser import read_file, parse_blocks
from sessions import (
    sessions, poll_owner,
    get_session, reset_session, new_quiz_session,
    build_result_text, build_batches, _empty_stats,
    group_sessions, group_ready_users, user_group,
    group_user_info, group_results,
    register_group_user, save_group_result,
    clear_group_results,
)
from quiz_runner import start_quiz, cancel_quiz_task, notify_answered
from i18n import t

log = logging.getLogger(__name__)


def _get_chat_id(update: Update) -> int | None:
    if update.callback_query and update.callback_query.message:
        return update.callback_query.message.chat_id
    if update.effective_chat:
        return update.effective_chat.id
    return None


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid  = update.effective_user.id
    lang = get_session(uid).get("lang", "uz")

    if context.args:
        param = context.args[0]
        if param.startswith("batch_"):
            owner_uid   = None
            batch_index = 0
            try:
                parts       = param[6:].split("_")
                owner_uid   = int(parts[0])
                batch_index = int(parts[1]) if len(parts) > 1 else 0
            except (ValueError, IndexError):
                pass

            if owner_uid is not None:
                owner_session = get_session(owner_uid)
                batches       = owner_session.get("batches", [])

                if not batches or batch_index >= len(batches):
                    await update.message.reply_text(
                        "⚠️ Test topilmadi yoki muddati o'tgan.",
                        reply_markup=main_menu_kb(lang),
                    )
                    return

                session                       = get_session(uid)
                session["lang"]               = lang
                session["quiz_name"]          = owner_session.get("quiz_name", "Quiz")
                session["questions"]          = owner_session.get("questions", [])
                session["batches"]            = batches
                session["batch_size"]         = owner_session.get("batch_size", 30)
                session["open_time"]          = owner_session.get("open_time")
                session["state"]              = "waiting_ready"
                session["active_batch_index"] = batch_index

                quiz_name  = session["quiz_name"]
                open_time  = session["open_time"]
                time_label = f"{open_time} soniya" if open_time else "Vaqtsiz"
                total      = len(batches[batch_index])

                await update.message.reply_text(
                    f"♟ *\"{quiz_name}\" — {batch_index+1}-to'plam*\n\n"
                    f"✏️ {total} ta savol\n"
                    f"🕐 Har bir savol uchun *{time_label}*\n\n"
                    f"♟ Tayyor bo'lganingizda quyidagi tugmani bosing.\n"
                    f"Uni to'xtatish uchun /stop buyrug'ini yuboring.",
                    parse_mode   = "Markdown",
                    reply_markup = _solo_ready_kb(batch_index, lang),
                )
                return

    await update.message.reply_text(
        t(lang, "welcome"),
        parse_mode   = "Markdown",
        reply_markup = main_menu_kb(lang),
    )


async def cmd_newquiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid  = update.effective_user.id
    lang = get_session(uid).get("lang", "uz")
    new_quiz_session(uid)
    get_session(uid)["lang"] = lang
    await update.message.reply_text(
        t(lang, "ask_name"),
        parse_mode = "Markdown",
    )


async def cmd_myquiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid     = update.effective_user.id
    session = get_session(uid)
    batches = session.get("batches", [])
    message = update.message or update.callback_query.message
    lang    = session.get("lang", "uz")

    if not batches:
        await message.reply_text(
            t(lang, "no_quiz"),
            reply_markup=main_menu_kb(lang),
        )
    else:
        name  = session.get("quiz_name", "—")
        total = sum(len(b) for b in batches)
        await message.reply_text(
            t(lang, "quiz_info", name=name, total=total, batches=len(batches)),
            parse_mode   = "Markdown",
            reply_markup = main_menu_kb(lang),
        )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid      = update.effective_user.id
    chat_id  = update.effective_chat.id
    is_group = update.effective_chat.type in ("group", "supergroup")
    lang     = get_session(uid).get("lang", "uz")

    if is_group:
        from sessions import build_group_result_text
        from keyboards import group_result_kb
        g_session = group_sessions.get(chat_id)
        if not g_session:
            await update.message.reply_text("⚠️ Hozir aktiv guruh testi yo'q.")
            return

        owner_uid       = g_session.get("owner_uid", uid)
        quiz_name       = g_session.get("quiz_name", "")
        total_questions = len(g_session.get("questions", []))

        await cancel_quiz_task(owner_uid, context)

        text = build_group_result_text(
            chat_id         = chat_id,
            quiz_name       = quiz_name,
            total_questions = total_questions,
        )

        clear_group_results(chat_id)
        group_sessions.pop(chat_id, None)
        for u, cid in list(user_group.items()):
            if cid == chat_id:
                del user_group[u]

        try:
            await update.message.reply_text(
                text,
                parse_mode   = "Markdown",
                reply_markup = group_result_kb(),
            )
        except Exception:
            await update.message.reply_text(text, reply_markup=group_result_kb())
        return

    # Yakka test
    session = get_session(uid)
    if session.get("state") == "idle":
        await update.message.reply_text(t(lang, "no_active"), reply_markup=main_menu_kb(lang))
        return

    from sessions import save_solo_result, get_elapsed

    quiz_name   = session.get("quiz_name", "")
    batch_index = session.get("active_batch_index", 0)
    open_time   = session.get("open_time")
    time_label  = f"{open_time} soniya" if open_time else "Vaqtsiz"

    stats   = session.get("stats", {})
    correct = stats.get("correct", 0)
    elapsed = get_elapsed(uid)
    save_solo_result(uid, correct, elapsed)

    result_text      = build_result_text(uid)
    session["state"] = "idle"
    await cancel_quiz_task(uid, context)

    try:
        await update.message.reply_text(
            result_text,
            parse_mode   = "Markdown",
            reply_markup = result_kb(uid, quiz_name, 0, time_label, batch_index),
        )
    except Exception:
        await update.message.reply_text(
            result_text,
            reply_markup = result_kb(uid, quiz_name, 0, time_label, batch_index),
        )
    reset_session(uid)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 *Yordam*\n\n"
        "/newquiz — Yangi test yaratish\n"
        "/myquiz — Joriy test holati\n"
        "/stop — Testni to'xtatish\n\n"
        "📌 *Fayl formati:*\n"
        "```\nSavol?\n#To'g'ri javob\n==== Noto'g'ri 1\n==== Noto'g'ri 2\n==== Noto'g'ri 3\n++++\n```",
        parse_mode   = "Markdown",
        reply_markup = main_menu_kb(),
    )


async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    if   text == "📝 Yangi test tuzish":   await cmd_newquiz(update, context)
    elif text == "📋 Testlarimni ko'rish": await cmd_myquiz(update, context)
    elif text == "🌐 Til: O'zbek":         await cmd_help(update, context)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid     = update.effective_user.id
    session = get_session(uid)
    state   = session.get("state", "idle")
    text    = update.message.text.strip()
    lang    = session.get("lang", "uz")

    if state == "waiting_name":
        session["quiz_name"] = text
        session["state"]     = "waiting_file"
        await update.message.reply_text(t(lang, "ask_file"), parse_mode="Markdown")
    elif state == "waiting_file":
        await update.message.reply_text(t(lang, "send_file"))
    else:
        await update.message.reply_text(t(lang, "new_quiz"), reply_markup=main_menu_kb(lang))


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid     = update.effective_user.id
    session = get_session(uid)

    if session.get("state") != "waiting_file":
        lang = get_session(uid).get("lang", "uz")
        await update.message.reply_text(t(lang, "start_first"))
        return

    doc = update.message.document
    if not doc:
        await update.message.reply_text("⚠️ Fayl yuboring (.txt, .pdf, .docx)")
        return

    mime   = doc.mime_type or ""
    suffix = Path(doc.file_name or "file.txt").suffix.lower()
    if suffix not in (".txt", ".pdf", ".docx") and "pdf" not in mime and "word" not in mime:
        await update.message.reply_text(t(session.get("lang", "uz"), "only_file"))
        return

    lang = session.get("lang", "uz")
    msg  = await update.message.reply_text(t(lang, "reading"))

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(tmp.name)
        tmp_path = tmp.name

    try:
        raw_text  = read_file(tmp_path, mime)
        questions = parse_blocks(raw_text)
    except Exception as exc:
        log.error("Parse error: %s", exc)
        await msg.edit_text(f"❌ Xatolik: {exc}")
        return
    finally:
        os.unlink(tmp_path)

    if not questions:
        await msg.edit_text(
            "⚠️ Fayldan savol topilmadi. Fayl formatini tekshiring.\n\n"
            "```\nSavol?\n#To'g'ri javob\n==== Noto'g'ri 1\n==== Noto'g'ri 2\n==== Noto'g'ri 3\n++++\n```",
            parse_mode="Markdown",
        )
        return

    session["questions"]   = questions
    session["batch_start"] = 0
    session["state"]       = "waiting_batch_size"
    total = len(questions)

    await msg.edit_text(
        t(lang, "found", total=total),
        parse_mode   = "Markdown",
        reply_markup = batch_size_kb(),
    )


async def handle_batch_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid     = update.effective_user.id
    session = get_session(uid)

    if session.get("state") != "waiting_batch_size":
        return

    total = len(session.get("questions", []))
    size  = int(query.data.split(":")[1])
    if size == 0 or size >= total:
        size = total

    session["batch_size"] = size
    session["state"]      = "waiting_time"
    lang = session.get("lang", "uz")

    await query.edit_message_text(
        t(lang, "batch_confirm", size=size),
        parse_mode   = "Markdown",
        reply_markup = time_kb(),
    )


async def handle_time_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid     = update.effective_user.id
    session = get_session(uid)

    if session.get("state") != "waiting_time":
        await query.answer("⚠️ Avval fayl yuboring!", show_alert=True)
        return

    chat_id = _get_chat_id(update)
    if chat_id is None:
        await query.answer("⚠️ Chat aniqlanmadi!", show_alert=True)
        return

    seconds              = int(query.data.split(":")[1])
    session["open_time"] = seconds if seconds > 0 else None
    session["state"]     = "ready"

    batches   = build_batches(uid)
    quiz_name = session.get("quiz_name", "Quiz")
    time_text = f"{seconds} soniya" if seconds > 0 else "Vaqtsiz"
    total     = sum(len(b) for b in batches)
    lang      = session.get("lang", "uz")

    await query.edit_message_text(
        t(lang, "batches_ready", time=time_text, name=quiz_name, total=total, batches=len(batches)),
        parse_mode="Markdown",
    )

    start = 0
    for i, batch in enumerate(batches):
        end = start + len(batch)
        await context.bot.send_message(
            chat_id      = chat_id,
            text         = t(lang, "batch_card", n=i+1, start=start+1, end=end, count=len(batch), time=time_text),
            parse_mode   = "Markdown",
            reply_markup = batch_card_kb(uid, i),
        )
        start = end


async def handle_start_batch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id

    is_inline = query.inline_message_id is not None and query.message is None
    chat_id   = query.message.chat_id if query.message else None

    parts       = query.data.split(":")
    batch_index = int(parts[1])
    owner_uid   = int(parts[2]) if len(parts) > 2 else uid

    owner_session = get_session(owner_uid)
    batches       = owner_session.get("batches", [])

    if not batches or batch_index >= len(batches):
        await query.answer("⚠️ To'plam topilmadi!", show_alert=True)
        return

    session = get_session(uid)
    if uid != owner_uid:
        if session.get("state") == "running":
            await query.answer("⚠️ Siz hozir boshqa testni ishlayapsiz!", show_alert=True)
            return
        session["quiz_name"]  = owner_session.get("quiz_name", "Quiz")
        session["questions"]  = owner_session.get("questions", [])
        session["batches"]    = batches
        session["batch_size"] = owner_session.get("batch_size", 30)
        session["open_time"]  = owner_session.get("open_time")
        session["lang"]       = session.get("lang", "uz")
    else:
        if session.get("state") == "running":
            await query.answer("⚠️ Avval joriy testni to'xtating (/stop)", show_alert=True)
            return

    session["state"]              = "waiting_ready"
    session["active_batch_index"] = batch_index

    quiz_name  = session.get("quiz_name", "Quiz")
    open_time  = session.get("open_time")
    time_label = f"{open_time} soniya" if open_time else "Vaqtsiz"
    total      = len(batches[batch_index])
    lang       = session.get("lang", "uz")

    text = (
        f"📋 *\"{quiz_name}\" — {batch_index+1}-to'plam*\n\n"
        f"✏️ {total} ta savol  ·  ⏱ *{time_label}*\n\n"
        f"Boshlashga tayyormisiz?"
    )
    kb = _confirm_start_kb(batch_index, lang)

    if is_inline or chat_id is None:
        try:
            await context.bot.send_message(
                chat_id      = uid,
                text         = text,
                parse_mode   = "Markdown",
                reply_markup = kb,
            )
        except Exception as exc:
            log.error("Private chat ga yuborishda xato (uid=%s): %s", uid, exc)
            await query.answer("⚠️ Iltimos, avval botga /start yuboring!", show_alert=True)
    else:
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id, text=text,
                parse_mode="Markdown", reply_markup=kb,
            )


def _confirm_start_kb(batch_index: int, lang: str = "uz"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "start_btn"), callback_data=f"confirmbatch:{batch_index}")],
    ])


def _solo_ready_kb(batch_index: int, lang: str = "uz"):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("♟ Men tayyorman!", callback_data=f"soloready:{batch_index}")],
    ])


async def handle_solo_ready(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid     = update.effective_user.id
    session = get_session(uid)
    chat_id = query.message.chat_id if query.message else uid

    batch_index = int(query.data.split(":")[1])

    if session.get("state") != "waiting_ready":
        await query.answer("⚠️ Avval testni tanlang!", show_alert=True)
        return

    batches = session.get("batches", [])
    if not batches or batch_index >= len(batches):
        await query.answer("⚠️ To'plam topilmadi!", show_alert=True)
        return

    lang = session.get("lang", "uz")
    try:
        await query.edit_message_text(t(lang, "starting"))
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text=t(lang, "starting"))

    await start_quiz(chat_id, uid, session, context, batch_index=batch_index, is_group=False)


async def handle_confirm_batch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid     = update.effective_user.id
    session = get_session(uid)
    chat_id = query.message.chat_id if query.message else uid

    batch_index = int(query.data.split(":")[1])

    if session.get("state") not in ("waiting_ready",):
        await query.answer("⚠️ Avval to'plamni tanlang!", show_alert=True)
        return

    batches = session.get("batches", [])
    if not batches or batch_index >= len(batches):
        await query.answer("⚠️ To'plam topilmadi!", show_alert=True)
        return

    lang = session.get("lang", "uz")
    try:
        await query.edit_message_text(t(lang, "starting"))
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text=t(lang, "starting"))
    await start_quiz(chat_id, uid, session, context, batch_index=batch_index, is_group=False)


async def handle_retry_batch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid         = update.effective_user.id
    session     = get_session(uid)
    batch_index = int(query.data.split(":")[1])

    batches = session.get("batches", [])
    if not batches or batch_index >= len(batches):
        await query.answer("⚠️ To'plam topilmadi!", show_alert=True)
        return

    session["state"]              = "waiting_ready"
    session["active_batch_index"] = batch_index
    session["stats"]              = _empty_stats()

    quiz_name  = session.get("quiz_name", "Quiz")
    open_time  = session.get("open_time")
    time_label = f"{open_time} soniya" if open_time else "Vaqtsiz"
    total      = len(batches[batch_index])
    lang       = session.get("lang", "uz")

    await query.edit_message_text(
        t(lang, "retry_title", name=quiz_name, n=batch_index+1, total=total, time=time_label),
        parse_mode   = "Markdown",
        reply_markup = _confirm_start_kb(batch_index, lang),
    )


async def handle_resume_batch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid     = update.effective_user.id
    session = get_session(uid)
    chat_id = query.message.chat_id if query.message else uid

    parts       = query.data.split(":")
    batch_index = int(parts[1])
    start_idx   = int(parts[2]) if len(parts) > 2 else 0

    session["state"] = "running"

    try:
        await query.edit_message_text("▶️ Test davom ettirilmoqda...")
    except Exception:
        pass

    await start_quiz(
        chat_id, uid, session, context,
        batch_index=batch_index,
        is_group=False,
        start_idx=start_idx,
    )


async def handle_stop_batch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid     = update.effective_user.id
    session = get_session(uid)
    chat_id = query.message.chat_id if query.message else uid

    parts       = query.data.split(":")
    batch_index = int(parts[1])

    quiz_name  = session.get("quiz_name", "")
    open_time  = session.get("open_time")
    time_label = f"{open_time} soniya" if open_time else "Vaqtsiz"

    from sessions import save_solo_result, get_elapsed

    correct = session.get("stats", {}).get("correct", 0)
    elapsed = get_elapsed(uid)
    save_solo_result(uid, correct, elapsed)

    text             = build_result_text(uid)
    session["state"] = "idle"
    await cancel_quiz_task(uid, context)

    try:
        await query.edit_message_text(
            text,
            parse_mode   = "Markdown",
            reply_markup = result_kb(uid, quiz_name, 0, time_label, batch_index),
        )
    except Exception:
        await context.bot.send_message(
            chat_id      = chat_id,
            text         = text,
            parse_mode   = "Markdown",
            reply_markup = result_kb(uid, quiz_name, 0, time_label, batch_index),
        )
    reset_session(uid)


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid   = update.effective_user.id
    stats = get_session(uid).get("stats", {})
    total = stats.get("total", 0)

    if total == 0:
        await query.answer("Hali statistika yo'q.", show_alert=True)
        return

    correct = stats.get("correct", 0)
    wrong   = stats.get("wrong", 0)
    skipped = stats.get("skipped", 0)
    pct     = round(correct / total * 100)

    await query.answer(
        f"✅ To'g'ri: {correct}/{total} ({pct}%)\n❌ Xato: {wrong}\n⏭ O'tkazildi: {skipped}",
        show_alert=True,
    )


async def handle_inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from telegram import InlineQueryResultArticle, InputTextMessageContent
    import uuid

    query   = update.inline_query
    uid     = query.from_user.id
    session = get_session(uid)
    batches = session.get("batches", [])

    if not batches:
        await query.answer([], cache_time=0)
        return

    parts = query.query.split(":")
    try:
        batch_index = int(parts[2]) if len(parts) >= 3 else 0
    except (ValueError, IndexError):
        batch_index = 0

    if batch_index >= len(batches):
        batch_index = 0

    quiz_name  = session.get("quiz_name", "Quiz")
    open_time  = session.get("open_time")
    time_label = f"{open_time} soniya" if open_time else "Vaqtsiz"
    batch      = batches[batch_index]
    total      = len(batch)

    start = sum(len(batches[i]) for i in range(batch_index))
    end   = start + total

    share_text = (
        f"📋 *\"{quiz_name}\" — {batch_index+1}-to'plam*\n"
        f"✏️ {total} ta savol  ·  🕐 {time_label}"
    )

    result = InlineQueryResultArticle(
        id          = str(uuid.uuid4()),
        title       = f'📋 "{quiz_name}" — {batch_index+1}-to\'plam',
        description = f"✏️ {start+1}–{end} savollar ({total} ta)  ·  🕐 {time_label}",
        input_message_content=InputTextMessageContent(
            message_text = share_text,
            parse_mode   = "Markdown",
        ),
        reply_markup = batch_card_kb(uid, batch_index),
    )

    await query.answer([result], cache_time=0, is_personal=True)


async def handle_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = _get_chat_id(update)
    if chat_id is None:
        return

    owner_uid   = None
    batch_index = 0

    if context.args:
        try:
            parts       = context.args[0].split("_")
            owner_uid   = int(parts[0])
            if len(parts) > 1:
                batch_index = int(parts[1])
        except (ValueError, IndexError):
            pass

    if owner_uid is None:
        owner_uid = update.effective_user.id

    session = get_session(owner_uid)
    batches = session.get("batches", [])
    if not batches or batch_index >= len(batches):
        await update.message.reply_text("⚠️ Test topilmadi. Avval bot bilan private chatda test yarating.")
        return

    batch      = batches[batch_index]
    quiz_name  = session.get("quiz_name", "Quiz")
    open_time  = session.get("open_time")
    time_label = f"{open_time} soniya" if open_time else "Vaqtsiz"
    total      = len(batch)

    group_sessions[chat_id] = {
        "owner_uid":          owner_uid,
        "quiz_name":          quiz_name,
        "questions":          batch,
        "batches":            batches,
        "open_time":          open_time,
        "batch_size":         session.get("batch_size", 30),
        "batch_start":        0,
        "active_batch_index": batch_index,
        "state":              "waiting_ready",
        "started_at":         None,
        "stats":              {"total": 0, "correct": 0, "wrong": 0, "skipped": 0, "started_at": None},
    }
    group_ready_users[chat_id] = set()
    user_group[owner_uid]      = chat_id
    clear_group_results(chat_id)

    start_offset = sum(len(batches[i]) for i in range(batch_index))

    await update.message.reply_text(
        f"♟ *\"{quiz_name}\" — {batch_index+1}-to'plam*\n\n"
        f"✏️ {start_offset+1}–{start_offset+total} savollar ({total} ta)\n"
        f"⏱ Har bir savol uchun *{time_label}*\n"
        f"👥 Ovozlar guruh a'zolari va test egasiga *ko'rinadigan* bo'ladi\n\n"
        f"♟ Test kamida 2 kishi ishtirok etganda boshlanadi.\n"
        f"Uni to'xtatish uchun /stop buyrug'ini yuboring.",
        parse_mode   = "Markdown",
        reply_markup = group_ready_kb(owner_uid),
    )


async def handle_group_ready(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    chat_id = _get_chat_id(update)
    if chat_id is None:
        await query.answer("⚠️ Chat aniqlanmadi!", show_alert=True)
        return

    voter_uid  = update.effective_user.id
    voter_name = update.effective_user.first_name

    register_group_user(
        uid        = voter_uid,
        first_name = voter_name,
        username   = update.effective_user.username,
    )

    g_session = group_sessions.get(chat_id)
    if not g_session or g_session.get("state") != "waiting_ready":
        await query.answer("Test topilmadi.", show_alert=True)
        return

    ready_set = group_ready_users.setdefault(chat_id, set())
    ready_set.add(voter_uid)
    count = len(ready_set)

    if count < 1:
        owner_uid   = g_session["owner_uid"]
        quiz_name   = g_session["quiz_name"]
        batch_index = g_session.get("active_batch_index", 0)
        open_time   = g_session["open_time"]
        time_label  = f"{open_time} soniya" if open_time else "Vaqtsiz"
        total       = len(g_session["questions"])

        await query.edit_message_text(
            f"♟ *\"{quiz_name}\" — {batch_index+1}-to'plam*\n\n"
            f"✏️ {total} ta savol · ⏱ *{time_label}*\n\n"
            f"✅ *{voter_name}* tayyor! ({count}/2)\n\n"
            f"♟ Test kamida 2 kishi ishtirok etganda boshlanadi.",
            parse_mode   = "Markdown",
            reply_markup = group_ready_kb(owner_uid),
        )
        return

    import time as _time
    g_session["started_at"] = _time.time()

    batch_index        = g_session.get("active_batch_index", 0)
    g_session["state"] = "running"
    owner_uid          = g_session["owner_uid"]
    lang               = get_session(owner_uid).get("lang", "uz")

    await query.edit_message_text(t(lang, "starting"))
    await start_quiz(chat_id, owner_uid, g_session, context, batch_index=batch_index, is_group=True)


async def handle_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            await context.bot.send_message(
                chat_id    = chat.id,
                text       = (
                    f"👋 Salom, *{chat.title}!*\n\n"
                    f"Quiz Bot guruhga qo'shildi.\n"
                    f"Test boshlash uchun test egasi to'plamni ulashsin."
                ),
                parse_mode = "Markdown",
            )


async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import time as _time

    answer    = update.poll_answer
    poll_id   = answer.poll_id
    voter_uid = answer.user.id
    owner_uid = poll_owner.get(poll_id)

    if owner_uid is None:
        return

    # ── GURUH yoki YAKKA ekanini aniqlash ──
    poll_chat_id  = poll_owner.get(f"{poll_id}:chat_id")
    is_group_poll = False
    g_session     = None

    if poll_chat_id:
        g_session = group_sessions.get(poll_chat_id)
        # state tekshirmaymiz — /stop bosilsa ham natijani saqlaymiz
        if g_session is not None:
            is_group_poll = True
        # state tekshiruvsiz: chat_id guruh sessiyasida bo'lsa guruh testi
        elif poll_chat_id in group_results:
            is_group_poll = True

    if is_group_poll:
        # ── GURUH TESTI ───────────────────────────────────────────────────
        chat_id = poll_chat_id

        if chat_id not in group_results:
            group_results[chat_id] = {}

        existing = group_results[chat_id].get(voter_uid)
        if not isinstance(existing, dict):
            _gs        = group_sessions.get(chat_id, {})
            started_at = _gs.get("started_at") or _time.time()
            existing   = {
                "correct":    0,
                "wrong":      0,
                "answered":   0,
                "elapsed":    0.0,
                "started_at": started_at,
            }
            group_results[chat_id][voter_uid] = existing

        correct_opt  = poll_owner.get(f"{poll_id}:correct")
        sent_at_real = poll_owner.get(f"{poll_id}:sent_at_real")  # real time.time()

        if answer.option_ids and correct_opt is not None:
            existing["answered"] += 1
            if answer.option_ids[0] == correct_opt:
                existing["correct"] += 1
            else:
                existing["wrong"] += 1

        # Vaqt: poll yuborilgan vaqtdan javob kelguncha (real clock)
        if sent_at_real and answer.option_ids:
            answer_time = _time.time() - sent_at_real
            existing["elapsed"] = existing.get("elapsed", 0.0) + answer_time

        # Foydalanuvchi ma'lumotini saqlash
        if voter_uid not in group_user_info:
            register_group_user(
                uid        = voter_uid,
                first_name = answer.user.first_name,
                username   = answer.user.username,
            )

        # Shu poll uchun kim javob berganini belgilash (no_answer_streak uchun)
        poll_key = f"poll_answered:{poll_id}"
        if poll_key not in group_results:
            group_results[poll_key] = set()
        group_results[poll_key].add(voter_uid)

    else:
        # ── YAKKA TEST ────────────────────────────────────────────────────
        session = sessions.get(owner_uid)
        if session is None:
            return

        stats = session.get("stats", {})

        if not answer.option_ids:
            notify_answered(owner_uid)
            return

        if stats.get("skipped", 0) > 0:
            stats["skipped"] -= 1

        correct_opt = poll_owner.get(f"{poll_id}:correct")
        if correct_opt is not None:
            if answer.option_ids[0] == correct_opt:
                stats["correct"] = stats.get("correct", 0) + 1
            else:
                stats["wrong"] = stats.get("wrong", 0) + 1

        notify_answered(owner_uid)


async def handle_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query   = update.callback_query
    uid     = update.effective_user.id

    chat_id = _get_chat_id(update)
    if chat_id is None:
        await query.answer("⚠️ Chat aniqlanmadi!", show_alert=True)
        return

    LANG_NAMES = {
        "uz": "O'zbek",       "ar": "العربية",          "ca": "Català",
        "nl": "Nederlands",   "en": "English",           "fr": "Français",
        "de": "Deutsch",      "id": "Bahasa Indonesia",  "it": "Italiano",
        "ko": "한국어",        "ms": "Bahasa Melayu",     "fa": "فارسی",
        "pl": "Polski",       "pt": "Português (Brasil)", "ru": "Русский",
        "es": "Español",      "tr": "Türkçe",            "uk": "Українська",
    }

    if query.data == "newquiz":
        await query.answer()
        lang = get_session(uid).get("lang", "uz")
        new_quiz_session(uid)
        get_session(uid)["lang"] = lang
        await context.bot.send_message(
            chat_id=chat_id, text=t(lang, "ask_name"), parse_mode="Markdown",
        )
        return

    if query.data == "myquiz":
        await query.answer()
        await cmd_myquiz(update, context)
        return

    if query.data == "show_lang":
        await query.answer()
        lang = get_session(uid).get("lang", "uz")
        try:
            await query.edit_message_text(
                t(lang, "lang_choose"),
                parse_mode   = "Markdown",
                reply_markup = lang_kb(),
            )
        except Exception:
            pass
        return

    if query.data.startswith("lang:"):
        code = query.data.split(":")[1]
        name = LANG_NAMES.get(code, code)
        session = get_session(uid)
        session["lang"] = code
        await query.answer(t(code, "lang_selected", name=name), show_alert=False)
        try:
            await query.edit_message_text(
                t(code, "welcome"),
                parse_mode   = "Markdown",
                reply_markup = main_menu_kb(code),
            )
        except Exception:
            pass
        return

    await query.answer()


async def handle_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid  = update.effective_user.id
    lang = get_session(uid).get("lang", "uz")
    await update.message.reply_text(t(lang, "new_quiz"), reply_markup=main_menu_kb(lang))