"""
quiz_runner.py — Countdown, savollar, natija
"""
import asyncio
import time as _time
import random
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import DEFAULT_PAUSE

log = logging.getLogger(__name__)

_tasks:         dict[int, asyncio.Task]  = {}
_poll_answered: dict[int, asyncio.Event] = {}


async def send_countdown(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await context.bot.send_message(chat_id=chat_id, text="🕐 *4*", parse_mode="Markdown")
    for n in ("3", "2", "1"):
        await asyncio.sleep(1)
        await msg.edit_text(f"🕐 *{n}*", parse_mode="Markdown")
    await asyncio.sleep(1)
    await msg.edit_text("🚀 *GO!*", parse_mode="Markdown")
    await asyncio.sleep(0.5)
    await msg.delete()


def notify_answered(uid: int) -> None:
    event = _poll_answered.get(uid)
    if event:
        event.set()


async def wait_for_answer_or_timeout(
    seconds: int,
    uid: int,
    session: dict,
    is_group: bool,
    poll_sent_at: float = 0.0,
) -> bool:
    """
    poll_sent_at — poll yuborilgan vaqt (asyncio.get_event_loop().time()).
    Network latency ni hisobga olib, qolgan vaqtni aniq kutadi.
    """
    wait = seconds or DEFAULT_PAUSE

    if not is_group:
        # Yakka rejim: javob kelsa darhol o'tsin, vaqt tugasa to'xta
        event = asyncio.Event()
        _poll_answered[uid] = event
        try:
            elapsed   = asyncio.get_event_loop().time() - poll_sent_at
            remaining = max(0.0, wait - elapsed)
            try:
                await asyncio.wait_for(event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                pass
            if session.get("state") in ("idle", "paused"):
                return False
        finally:
            _poll_answered.pop(uid, None)
    else:
        # Guruh rejimi: poll ning open_period tugashini aniq kutish
        elapsed   = asyncio.get_event_loop().time() - poll_sent_at
        remaining = max(0.0, wait - elapsed)
        deadline  = asyncio.get_event_loop().time() + remaining
        while asyncio.get_event_loop().time() < deadline:
            if session.get("state") in ("idle", "paused"):
                return False
            sleep_time = min(0.5, deadline - asyncio.get_event_loop().time())
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    return session.get("state") not in ("idle", "paused")


async def stop_active_poll(uid: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    from sessions import active_poll, poll_owner
    poll_id = active_poll.get(uid)
    if not poll_id:
        return
    chat_id    = poll_owner.get(f"{poll_id}:chat_id")
    message_id = poll_owner.get(f"{poll_id}:message_id")
    if chat_id and message_id:
        try:
            await context.bot.stop_poll(chat_id=chat_id, message_id=message_id)
        except Exception as exc:
            log.warning("Poll yopishda xato: %s", exc)
    active_poll.pop(uid, None)


async def show_results(
    chat_id: int,
    uid: int,
    session: dict,
    context: ContextTypes.DEFAULT_TYPE,
    batch_index: int = 0,
    is_group: bool = False,
) -> None:
    from keyboards import result_kb, group_result_kb
    from sessions import (
        build_result_text, build_group_result_text,
        clear_group_results, reset_session,
        group_sessions, user_group,
        save_solo_result, get_elapsed,
    )

    quiz_name  = session.get("quiz_name", "")
    open_time  = session.get("open_time")
    time_label = f"{open_time} soniya" if open_time else "Vaqtsiz"

    if is_group:
        total_questions = len(session.get("questions", []))
        text = build_group_result_text(
            chat_id         = chat_id,
            quiz_name       = quiz_name,
            total_questions = total_questions,
        )
        try:
            await context.bot.send_message(
                chat_id      = chat_id,
                text         = text,
                parse_mode   = "Markdown",
                reply_markup = group_result_kb(),
            )
        except Exception:
            await context.bot.send_message(
                chat_id      = chat_id,
                text         = text,
                reply_markup = group_result_kb(),
            )
        clear_group_results(chat_id)
        group_sessions.pop(chat_id, None)
        for u, cid in list(user_group.items()):
            if cid == chat_id:
                del user_group[u]

    else:
        stats   = session.get("stats", {})
        correct = stats.get("correct", 0)
        elapsed = get_elapsed(uid)
        save_solo_result(uid, correct, elapsed)
        total = (
            len(session.get("batches", [[]])[batch_index])
            if session.get("batches") else 0
        )
        text = build_result_text(uid)
        reset_session(uid)
        await context.bot.send_message(
            chat_id      = chat_id,
            text         = text,
            parse_mode   = "Markdown",
            reply_markup = result_kb(uid, quiz_name, total, time_label, batch_index),
        )


async def send_batch(
    chat_id: int,
    uid: int,
    session: dict,
    context: ContextTypes.DEFAULT_TYPE,
    batch_index: int = 0,
    is_group: bool = False,
    start_idx: int = 0,
) -> None:
    from sessions import poll_owner, active_poll, group_results

    batches = session.get("batches", [])
    if batch_index >= len(batches):
        return

    questions        = batches[batch_index]
    open_time        = session.get("open_time") or 30  # None bo'lsa default 30 sek
    total_in_batch   = len(questions)
    stats            = session["stats"]
    no_answer_streak = 0
    MAX_NO_ANSWER    = 2

    for idx, q in enumerate(questions):
        if idx < start_idx:
            continue

        if session.get("state") in ("idle", "paused"):
            return

        opts         = q["options"][:]
        correct_text = opts[q["correct_index"]]
        random.shuffle(opts)
        correct_id   = opts.index(correct_text)
        mid          = None
        pid          = None

        # Poll yuborilgan aniq vaqtni olish
        poll_sent_at      = asyncio.get_event_loop().time()  # wait uchun
        poll_sent_at_real = _time.time()                     # elapsed uchun
        try:
            sent = await context.bot.send_poll(
                chat_id           = chat_id,
                question          = f"[{idx+1}/{total_in_batch}] {q['question']}",
                options           = opts,
                type              = "quiz",
                correct_option_id = correct_id,
                is_anonymous      = False,
                open_period       = open_time,
            )
            pid = sent.poll.id
            mid = sent.message_id

            poll_owner[pid]                 = uid
            poll_owner[f"{pid}:correct"]    = correct_id
            poll_owner[f"{pid}:chat_id"]    = chat_id
            poll_owner[f"{pid}:message_id"] = mid
            poll_owner[f"{pid}:sent_at_real"] = poll_sent_at_real  # real clock, guruh elapsed uchun
            active_poll[uid]                = pid

            stats["total"]   += 1
            stats["skipped"] += 1

        except Exception as exc:
            log.error("Poll xato (savol %d): %s", idx + 1, exc)
            await asyncio.sleep(1)
            continue

        answered_before = stats.get("correct", 0) + stats.get("wrong", 0)

        # poll_sent_at uzatiladi — vaqtni aniq hisoblash uchun
        ok = await wait_for_answer_or_timeout(open_time, uid, session, is_group, poll_sent_at)

        if mid is not None:
            try:
                await context.bot.stop_poll(chat_id=chat_id, message_id=mid)
            except Exception:
                pass

        if not ok:
            return

        if is_group:
            poll_key         = f"poll_answered:{pid}"
            someone_answered = len(group_results.get(poll_key, set())) > 0
            group_results.pop(poll_key, None)
        else:
            answered_after   = stats.get("correct", 0) + stats.get("wrong", 0)
            someone_answered = answered_after > answered_before

        if someone_answered:
            no_answer_streak = 0
        else:
            no_answer_streak += 1
            if no_answer_streak >= MAX_NO_ANSWER:
                session["state"]         = "paused"
                session["paused_at_idx"] = idx + 1

                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "▶️ Testni davom ettirish",
                        callback_data=f"resumebatch:{batch_index}:{idx+1}",
                    )],
                    [InlineKeyboardButton(
                        "⏹ Testni to'xtatish",
                        callback_data=f"stopbatch:{batch_index}",
                    )],
                ])

                text = (
                    "⏸ Test to'xtatildi, chunki hech kim javob bermadi."
                    if is_group else
                    "⏸ Test to'xtatildi, chunki siz javob berishni to'xtatdingiz."
                )
                await context.bot.send_message(
                    chat_id      = chat_id,
                    text         = text,
                    reply_markup = kb,
                )
                return

    if session.get("state") in ("idle", "paused"):
        return

    session["state"] = "idle"
    await show_results(chat_id, uid, session, context, batch_index, is_group=is_group)


async def _quiz_task(
    chat_id: int,
    uid: int,
    session: dict,
    context: ContextTypes.DEFAULT_TYPE,
    batch_index: int = 0,
    is_group: bool = False,
    start_idx: int = 0,
) -> None:
    try:
        if start_idx == 0:
            await send_countdown(chat_id, context)
        await send_batch(
            chat_id, uid, session, context,
            batch_index=batch_index,
            is_group=is_group,
            start_idx=start_idx,
        )
    except asyncio.CancelledError:
        log.info("uid=%d quiz task bekor qilindi", uid)
    except Exception as exc:
        log.error("uid=%d quiz task xatosi: %s", uid, exc)


async def start_quiz(
    chat_id: int,
    uid: int,
    session: dict,
    context: ContextTypes.DEFAULT_TYPE,
    batch_index: int = 0,
    is_group: bool = False,
    start_idx: int = 0,
) -> None:
    from sessions import start_stats

    session["state"] = "running"
    if start_idx == 0:
        start_stats(uid, batch_index)

    old = _tasks.get(uid)
    if old and not old.done():
        old.cancel()

    task = asyncio.create_task(
        _quiz_task(
            chat_id, uid, session, context,
            batch_index=batch_index,
            is_group=is_group,
            start_idx=start_idx,
        )
    )
    _tasks[uid] = task


async def cancel_quiz_task(uid: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    await stop_active_poll(uid, context)
    task = _tasks.pop(uid, None)
    if task and not task.done():
        task.cancel()
    _poll_answered.pop(uid, None)