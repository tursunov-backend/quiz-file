"""
handlers.py — Barcha Telegram handlerlar
"""
import os
import logging
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from keyboards import (
    main_menu_kb, batch_size_kb, time_kb,
    batch_card_kb, group_ready_kb, result_kb, lang_kb,
    quiz_list_kb, quiz_batches_kb,
)
from parser import read_file, parse_blocks
from database import save_quiz, get_user_quizzes, get_quiz_by_name
from sessions import (
    sessions, poll_owner, active_poll,
    get_session, reset_session, new_quiz_session,
    build_result_text, build_batches, _empty_stats,
    group_sessions, group_ready_users, user_group,
    group_user_info, group_results,
    register_group_user, save_group_result, clear_group_results,

    save_solo_result, get_elapsed, build_group_result_text,
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


# ══════════════════════════════════════════════════════════════════════════════
# BUYRUQLAR
# ══════════════════════════════════════════════════════════════════════════════

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
    lang    = session.get("lang", "uz")
    message = (
        update.message
        or (update.callback_query.message if update.callback_query else None)
    )
    chat_id = update.effective_chat.id if update.effective_chat else uid

    quizzes = await get_user_quizzes(uid)
    if not quizzes:
        text = t(lang, "no_quiz")
        kb   = main_menu_kb(lang)
        if message:
            await message.reply_text(text, reply_markup=kb)
        else:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)
        return

    lines = []
    for i, q in enumerate(quizzes, 1):
        name      = q["quiz_name"] or f"Test {i}"
        total     = sum(len(b) for b in q.get("batches", []))
        batches_n = len(q.get("batches", []))
        open_time = q.get("open_time")
        time_lbl  = f"{open_time} soniya" if open_time else "Vaqtsiz"
        lines.append(
            f"*{i}. {name}*\n"
            f"   ✏️ {total} ta savol  ·  📦 {batches_n} ta to'plam  ·  ⏱ {time_lbl}"
        )

    text = f"📋 *Sizning testlaringiz* ({len(quizzes)} ta):\n\n" + "\n\n".join(lines)
    kb   = quiz_list_kb(quizzes, lang)

    if message:
        try:
            await message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            await message.reply_text(text, reply_markup=kb)
    else:
        await context.bot.send_message(chat_id=chat_id, text=text,
                                       parse_mode="Markdown", reply_markup=kb)


async def handle_select_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    uid        = update.effective_user.id
    quiz_index = int(query.data.split(":")[1])
    session    = get_session(uid)
    lang       = session.get("lang", "uz")

    ok = load_quiz_to_session(uid, quiz_index)
    if not ok:
        await query.answer("⚠️ Test topilmadi!", show_alert=True)
        return

    session   = get_session(uid)
    quiz_name = session.get("quiz_name", "Quiz")
    batches   = session.get("batches", [])
    open_time = session.get("open_time")
    total     = sum(len(b) for b in batches)
    time_lbl  = f"{open_time} soniya" if open_time else "Vaqtsiz"

    lines = [f"📦 *{i+1}-to'plam* — {len(b)} ta savol" for i, b in enumerate(batches)]
    text  = (
        f"📋 *\"{quiz_name}\"*\n\n"
        f"✏️ {total} ta savol  ·  📦 {len(batches)} ta to'plam  ·  ⏱ {time_lbl}\n\n"
        + "\n".join(lines)
        + "\n\nQaysi to'plamni boshlaysiz?"
    )
    kb = quiz_batches_kb(uid, quiz_index, batches, open_time, lang)
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        chat_id = update.effective_chat.id if update.effective_chat else uid
        await context.bot.send_message(chat_id=chat_id, text=text,
                                       parse_mode="Markdown", reply_markup=kb)


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid      = update.effective_user.id
    chat_id  = update.effective_chat.id
    is_group = update.effective_chat.type in ("group", "supergroup")

    if is_group:
        g_session = group_sessions.get(chat_id)
        if not g_session:
            await update.message.reply_text("⚠️ Hozir aktiv guruh testi yo'q.")
            return

        owner_uid       = g_session.get("owner_uid", uid)
        quiz_name       = g_session.get("quiz_name", "")
        total_questions = len(g_session.get("questions", []))
        batch_index     = g_session.get("active_batch_index", 0)

        await cancel_quiz_task(owner_uid, context)

        text = build_group_result_text(chat_id, quiz_name, total_questions)

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup, SwitchInlineQueryChosenChat
        share_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "📤 Testni ulashish",
                switch_inline_query_chosen_chat=SwitchInlineQueryChosenChat(
                    query=f"share:{owner_uid}:{batch_index}",
                    allow_user_chats=True,
                    allow_bot_chats=False,
                    allow_group_chats=True,
                    allow_channel_chats=True,
                )
            )
        ]])

        clear_group_results(chat_id)
        group_sessions.pop(chat_id, None)
        for u, cid in list(user_group.items()):
            if cid == chat_id:
                del user_group[u]

        try:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=share_kb)
        except Exception:
            await update.message.reply_text(text, reply_markup=share_kb)
        return

    # ── Yakka test ─────────────────────────────────────────────────────────
    session = get_session(uid)
    lang    = session.get("lang", "uz")

    if session.get("state") == "idle":
        await update.message.reply_text(t(lang, "no_active"), reply_markup=main_menu_kb(lang))
        return

    quiz_name   = session.get("quiz_name", "")
    batch_index = session.get("active_batch_index", 0)
    open_time   = session.get("open_time")
    time_label  = f"{open_time} soniya" if open_time else "Vaqtsiz"

    correct = session.get("stats", {}).get("correct", 0)
    elapsed = get_elapsed(uid)
    save_solo_result(uid, correct, elapsed)

    result_text = build_result_text(uid)
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
    uid  = update.effective_user.id
    lang = get_session(uid).get("lang", "uz")
    await update.message.reply_text(
        t(lang, "help_text"),
        parse_mode   = "Markdown",
        reply_markup = main_menu_kb(lang),
    )


# ══════════════════════════════════════════════════════════════════════════════
# MATN
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# FAYL
# ══════════════════════════════════════════════════════════════════════════════

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid     = update.effective_user.id
    session = get_session(uid)
    lang    = session.get("lang", "uz")

    if session.get("state") != "waiting_file":
        await update.message.reply_text(t(lang, "start_first"))
        return

    doc = update.message.document
    if not doc:
        await update.message.reply_text("⚠️ Fayl yuboring (.txt, .pdf, .docx)")
        return

    mime   = doc.mime_type or ""
    suffix = Path(doc.file_name or "file.txt").suffix.lower()
    if suffix not in (".txt", ".pdf", ".docx") and "pdf" not in mime and "word" not in mime:
        await update.message.reply_text(t(lang, "only_file"))
        return

    msg = await update.message.reply_text(t(lang, "reading"))

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
        await msg.edit_text(t(lang, "not_found"), parse_mode="Markdown")
        return

    session["questions"]   = questions
    session["batch_start"] = 0
    session["state"]       = "waiting_batch_size"

    await msg.edit_text(
        t(lang, "found", total=len(questions)),
        parse_mode   = "Markdown",
        reply_markup = batch_size_kb(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACK: batch size
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACK: vaqt tanlash
# ══════════════════════════════════════════════════════════════════════════════

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
    await save_quiz(uid, session.get("quiz_name","Quiz"), session.get("questions",[]), session.get("batches",[]), session.get("open_time"), session.get("batch_size",10))
    quiz_name = session.get("quiz_name", "Quiz")
    time_text = f"{seconds} soniya" if seconds > 0 else "Vaqtsiz"
    total     = sum(len(b) for b in batches)
    lang      = session.get("lang", "uz")

    await query.edit_message_text(
        t(lang, "batches_ready", time=time_text, name=quiz_name,
          total=total, batches=len(batches)),
        parse_mode="Markdown",
    )

    start = 0
    for i, batch in enumerate(batches):
        end = start + len(batch)
        await context.bot.send_message(
            chat_id      = chat_id,
            text         = t(lang, "batch_card", n=i+1, start=start+1,
                             end=end, count=len(batch), time=time_text),
            parse_mode   = "Markdown",
            reply_markup = batch_card_kb(uid, i),
        )
        start = end


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACK: to'plamni boshlash (inline yoki oddiy)
# ══════════════════════════════════════════════════════════════════════════════

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
                chat_id=uid, text=text, parse_mode="Markdown", reply_markup=kb,
            )
        except Exception as exc:
            log.error("Private chat ga yuborishda xato (uid=%s): %s", uid, exc)
            await query.answer("⚠️ Iltimos, avval botga /start yuboring!", show_alert=True)
    else:
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=kb,
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

    if session.get("state") != "waiting_ready":
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
        t(lang, "retry_title", name=quiz_name, n=batch_index+1,
          total=total, time=time_label),
        parse_mode   = "Markdown",
        reply_markup = _confirm_start_kb(batch_index, lang),
    )


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACK: statistika
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# INLINE QUERY
# ══════════════════════════════════════════════════════════════════════════════

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
    start      = sum(len(batches[i]) for i in range(batch_index))
    end        = start + total

    share_text = (
        f"📋 *\"{quiz_name}\" — {batch_index+1}-to'plam*\n"
        f"✏️ {total} ta savol  ·  🕐 {time_label}"
    )

    result = InlineQueryResultArticle(
        id          = str(uuid.uuid4()),
        title       = f'📋 "{quiz_name}" — {batch_index+1}-to\'plam',
        description = f"✏️ {start+1}–{end} savollar ({total} ta)  ·  🕐 {time_label}",
        input_message_content=InputTextMessageContent(
            message_text=share_text, parse_mode="Markdown",
        ),
        reply_markup=batch_card_kb(uid, batch_index),
    )
    await query.answer([result], cache_time=0, is_personal=True)


# ══════════════════════════════════════════════════════════════════════════════
# GURUH HANDLERLAR
# ══════════════════════════════════════════════════════════════════════════════

async def handle_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = _get_chat_id(update)
    if chat_id is None:
        return

    owner_uid   = None
    batch_index = 0

    if context.args:
        try:
            parts     = context.args[0].split("_")
            owner_uid = int(parts[0])
            if len(parts) > 1:
                batch_index = int(parts[1])
        except (ValueError, IndexError):
            pass

    if owner_uid is None:
        owner_uid = update.effective_user.id

    session = get_session(owner_uid)
    batches = session.get("batches", [])
    if not batches or batch_index >= len(batches):
        await update.message.reply_text(
            "⚠️ Test topilmadi. Avval bot bilan private chatda test yarating."
        )
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

    if count < 2:
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
    g_session["state"]      = "running"
    owner_uid               = g_session["owner_uid"]
    batch_index             = g_session.get("active_batch_index", 0)
    lang                    = get_session(owner_uid).get("lang", "uz")

    await query.edit_message_text(t(lang, "starting"))
    await start_quiz(chat_id, owner_uid, g_session, context,
                     batch_index=batch_index, is_group=True)


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


# ══════════════════════════════════════════════════════════════════════════════
# POLL JAVOBLARI
# ══════════════════════════════════════════════════════════════════════════════

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    answer    = update.poll_answer
    poll_id   = answer.poll_id
    voter_uid = answer.user.id
    owner_uid = poll_owner.get(poll_id)

    if owner_uid is None:
        return

    chat_id = user_group.get(owner_uid)

    if chat_id:
        # ── GURUH TESTI ───────────────────────────────────────────────────
        if chat_id not in group_results:
            group_results[chat_id] = {}

        existing = group_results[chat_id].get(voter_uid, {})
        voter_stats = {
            "correct":    existing.get("correct", 0),
            "wrong":      existing.get("wrong", 0),
            "answered":   existing.get("answered", 0),
            "elapsed":    existing.get("elapsed", 0.0),
            "started_at": existing.get("started_at"),
        }

        if voter_stats["started_at"] is None:
            import time as _time
            g_session = group_sessions.get(chat_id, {})
            voter_stats["started_at"] = g_session.get("started_at") or _time.time()

        correct_opt = poll_owner.get(f"{poll_id}:correct")
        if answer.option_ids and correct_opt is not None:
            if answer.option_ids[0] == correct_opt:
                voter_stats["correct"] += 1
            else:
                voter_stats["wrong"] += 1
        voter_stats["answered"] += 1

        import time as _time
        voter_stats["elapsed"] = _time.time() - voter_stats["started_at"]

        group_results[chat_id][voter_uid] = voter_stats

        if voter_uid not in group_user_info:
            register_group_user(
                uid        = voter_uid,
                first_name = answer.user.first_name,
                username   = answer.user.username,
            )

        # Guruhda vaqt tugaguncha kutish — notify_answered chaqirilmaydi

    else:
        # ── YAKKA TEST ────────────────────────────────────────────────────
        session = sessions.get(owner_uid)
        if session is None:
            return

        stats = session.get("stats", {})
        if stats.get("skipped", 0) > 0:
            stats["skipped"] -= 1

        if not answer.option_ids:
            stats["skipped"] = stats.get("skipped", 0) + 1
            notify_answered(owner_uid)
            return

        correct_opt = poll_owner.get(f"{poll_id}:correct")
        if correct_opt is not None:
            if answer.option_ids[0] == correct_opt:
                stats["correct"] = stats.get("correct", 0) + 1
            else:
                stats["wrong"] = stats.get("wrong", 0) + 1

        notify_answered(owner_uid)


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACK: til tanlash + menyu
# ══════════════════════════════════════════════════════════════════════════════

async def handle_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query   = update.callback_query
    uid     = update.effective_user.id
    chat_id = _get_chat_id(update)
    if chat_id is None:
        await query.answer("⚠️ Chat aniqlanmadi!", show_alert=True)
        return

    LANG_NAMES = {
        "uz": "O'zbek",        "ar": "العربية",           "ca": "Català",
        "nl": "Nederlands",    "en": "English",            "fr": "Français",
        "de": "Deutsch",       "id": "Bahasa Indonesia",   "it": "Italiano",
        "ko": "한국어",         "ms": "Bahasa Melayu",      "fa": "فارسی",
        "pl": "Polski",        "pt": "Português (Brasil)", "ru": "Русский",
        "es": "Español",       "tr": "Türkçe",             "uk": "Українська",
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
        code    = query.data.split(":")[1]
        name    = LANG_NAMES.get(code, code)
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

    if query.data.startswith("selectquiz:"):
        await handle_select_quiz(update, context)
        return

    await query.answer()


# ══════════════════════════════════════════════════════════════════════════════
# FALLBACK
# ══════════════════════════════════════════════════════════════════════════════

async def handle_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid  = update.effective_user.id
    lang = get_session(uid).get("lang", "uz")
    await update.message.reply_text(
        t(lang, "new_quiz"), reply_markup=main_menu_kb(lang)
    )