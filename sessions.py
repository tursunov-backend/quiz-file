"""
sessions.py — Foydalanuvchi sessiyalari va statistika
RAM: tez o'zgaruvchan ma'lumotlar (sessiyalar, poll, guruh holati)
DB:  doimiy ma'lumotlar (testlar, natijalar, til)
"""
import time
import asyncio
import logging

log = logging.getLogger(__name__)

# ── RAM (vaqtinchalik) ────────────────────────────────────────────────────────
sessions:          dict[int, dict] = {}
poll_owner:        dict[str, object] = {}
active_poll:       dict[int, str] = {}
batch_stats:       dict[int, dict[int, dict]] = {}
group_sessions:    dict[int, dict] = {}
group_ready_users: dict[int, set]  = {}
user_group:        dict[int, int]  = {}
group_user_info:   dict[int, dict] = {}
group_results:     dict[int, dict] = {}
# solo_results RAM da ham saqlanadi (tez reyting uchun), DB ga ham yoziladi
solo_results:      dict[str, list] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Yordamchi
# ─────────────────────────────────────────────────────────────────────────────

def _empty_stats() -> dict:
    return {"total": 0, "correct": 0, "wrong": 0, "skipped": 0, "started_at": None}


def _run_async(coro) -> None:
    """Sync funksiyadan async DB chaqiruvi uchun."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        # Running loop yo'q — background thread da chaqirilgan
        try:
            asyncio.run(coro)
        except Exception as e:
            log.warning("DB async xato: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# Sessiyalar (RAM)
# ─────────────────────────────────────────────────────────────────────────────

def get_session(uid: int) -> dict:
    return sessions.setdefault(uid, {
        "state": "idle", "quiz_name": "", "questions": [],
        "batches": [], "batch_start": 0, "open_time": None,
        "batch_size": 30, "active_batch_index": None,
        "stats": _empty_stats(),
    })


def reset_session(uid: int) -> dict:
    old = sessions.get(uid, {})
    sessions[uid] = {
        "state":              "idle",
        "quiz_name":          old.get("quiz_name", ""),
        "questions":          old.get("questions", []),
        "batches":            old.get("batches", []),
        "batch_start":        0,
        "open_time":          old.get("open_time"),
        "batch_size":         old.get("batch_size", 30),
        "active_batch_index": None,
        "lang":               old.get("lang", "uz"),
        "stats":              _empty_stats(),
    }
    return sessions[uid]


def new_quiz_session(uid: int) -> dict:
    old_lang = sessions.get(uid, {}).get("lang", "uz")
    sessions[uid] = {
        "state": "waiting_name", "quiz_name": "", "questions": [],
        "batches": [], "batch_start": 0, "open_time": None,
        "batch_size": 30, "active_batch_index": None,
        "lang": old_lang,
        "stats": _empty_stats(),
    }
    return sessions[uid]


def build_batches(uid: int) -> list:
    import random
    session   = get_session(uid)
    questions = session.get("questions", [])
    questions = questions[:]
    random.shuffle(questions)
    size      = session.get("batch_size", 30)
    batches   = [questions[i:i + size] for i in range(0, len(questions), size)]
    session["batches"] = batches
    return batches


def start_stats(uid: int, batch_index: int = 0) -> None:
    session = get_session(uid)
    session["stats"] = _empty_stats()
    session["stats"]["started_at"] = time.time()
    session["active_batch_index"]  = batch_index


def get_elapsed(uid: int) -> float:
    started = get_session(uid)["stats"].get("started_at")
    return 0.0 if started is None else time.time() - started


# ─────────────────────────────────────────────────────────────────────────────
# Til (DB + RAM)
# ─────────────────────────────────────────────────────────────────────────────

async def load_user_lang(uid: int) -> str:
    """Bot start da DB dan tilni yuklaydi."""
    try:
        from database import get_user_lang
        lang = await get_user_lang(uid)
        session = get_session(uid)
        session["lang"] = lang
        return lang
    except Exception as e:
        log.warning("load_user_lang xato: %s", e)
        return get_session(uid).get("lang", "uz")


async def save_user_lang(uid: int, lang: str) -> None:
    """Til o'zgarganda DB ga yozadi."""
    try:
        from database import upsert_user
        await upsert_user(uid, lang)
    except Exception as e:
        log.warning("save_user_lang xato: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# Testlar (DB + RAM)
# ─────────────────────────────────────────────────────────────────────────────

async def save_quiz_db(uid: int) -> None:
    """Test yaratib bo'lingandan keyin DB ga saqlaydi."""
    try:
        from database import save_quiz as db_save_quiz
        session = get_session(uid)
        await db_save_quiz(
            uid        = uid,
            quiz_name  = session.get("quiz_name", ""),
            questions  = session.get("questions", []),
            batches    = session.get("batches", []),
            open_time  = session.get("open_time"),
            batch_size = session.get("batch_size", 30),
        )
        log.info("Quiz DB ga saqlandi: uid=%s", uid)
    except Exception as e:
        log.warning("save_quiz_db xato: %s", e)


async def load_quiz_from_db(uid: int, quiz_name: str) -> bool:
    """DB dan testni sessionga yuklaydi."""
    try:
        from database import get_quiz_by_name
        quiz = await get_quiz_by_name(uid, quiz_name)
        if not quiz:
            return False
        lang = sessions.get(uid, {}).get("lang", "uz")
        sessions[uid] = {
            "state":              "ready",
            "quiz_name":          quiz["quiz_name"],
            "questions":          quiz["questions"],
            "batches":            quiz["batches"],
            "batch_start":        0,
            "open_time":          quiz["open_time"],
            "batch_size":         quiz["batch_size"],
            "active_batch_index": None,
            "lang":               lang,
            "stats":              _empty_stats(),
        }
        return True
    except Exception as e:
        log.warning("load_quiz_from_db xato: %s", e)
        return False


async def get_user_quizzes_db(uid: int) -> list:
    """Foydalanuvchining barcha testlari."""
    try:
        from database import get_user_quizzes
        return await get_user_quizzes(uid)
    except Exception as e:
        log.warning("get_user_quizzes_db xato: %s", e)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Yakka natijalar (DB + RAM)
# ─────────────────────────────────────────────────────────────────────────────

def save_solo_result(uid: int, correct: int, elapsed: float) -> None:
    """RAM ga yozadi + DB ga async yuboradi."""
    session   = get_session(uid)
    quiz_name = session.get("quiz_name", "")
    bidx      = session.get("active_batch_index", 0)
    total     = session["stats"]["total"]
    quiz_key  = f"{quiz_name}:{bidx}"

    # RAM
    if quiz_key not in solo_results:
        solo_results[quiz_key] = []
    for entry in solo_results[quiz_key]:
        if entry["uid"] == uid:
            entry["correct"] = correct
            entry["elapsed"] = elapsed
            break
    else:
        solo_results[quiz_key].append({"uid": uid, "correct": correct, "elapsed": elapsed})

    # DB
    async def _save():
        try:
            from database import save_solo_result as db_save
            await db_save(uid, quiz_name, bidx, correct, total, elapsed)
        except Exception as e:
            log.warning("save_solo_result DB xato: %s", e)
    _run_async(_save())


async def load_solo_results(quiz_name: str, bidx: int) -> None:
    """DB dan natijalarni RAM ga yuklaydi (reyting uchun)."""
    try:
        from database import get_solo_results
        rows    = await get_solo_results(quiz_name, bidx)
        key     = f"{quiz_name}:{bidx}"
        solo_results[key] = [
            {"uid": r["uid"], "correct": r["correct"], "elapsed": r["elapsed"]}
            for r in rows
        ]
    except Exception as e:
        log.warning("load_solo_results xato: %s", e)


def build_result_text(uid: int) -> str:
    session = get_session(uid)
    stats   = session["stats"]
    name    = session.get("quiz_name", "Quiz")
    bidx    = session.get("active_batch_index", 0)
    batches = session.get("batches", [])
    total   = stats["total"]
    correct = stats["correct"]
    wrong   = stats["wrong"]
    skipped = max(0, total - correct - wrong)
    pct     = round(correct / total * 100) if total > 0 else 0

    batch_label = f"*{bidx + 1}-to'plam*" if batches and bidx is not None else ""
    batch_total = len(batches[bidx]) if batches and bidx is not None and bidx < len(batches) else total

    quiz_key    = f"{name}:{bidx}"
    all_results = solo_results.get(quiz_key, [])
    my_entry    = next((r for r in all_results if r["uid"] == uid), None)
    elapsed     = my_entry["elapsed"] if my_entry else get_elapsed(uid)

    minutes  = int(elapsed // 60)
    secs     = int(elapsed % 60)
    time_str = f"{minutes} daqiqa {secs} soniya" if minutes > 0 else f"{elapsed:.1f} soniya"

    rank_text = ""
    if len(all_results) >= 1:
        sorted_results = sorted(all_results, key=lambda x: (-x["correct"], x["elapsed"]))
        total_players  = len(sorted_results)
        my_rank        = next((i + 1 for i, r in enumerate(sorted_results) if r["uid"] == uid), None)
        if my_rank is not None:
            better_pct = round((total_players - my_rank) / total_players * 100) if total_players > 1 else 100
            medals     = {1: "🥇", 2: "🥈", 3: "🥉"}
            medal      = medals.get(my_rank, "🎖")
            rank_text  = (
                f"\n{medal} *{total_players} tadan* siz *{my_rank}-o'rinda* turibsiz.\n"
                f"Siz ushbu testda ishtirok etgan *{better_pct}%* odamlardan yuqoriroq ball to'pladingiz.\n"
            )

    return (
        f'♟ *"{name}"* {batch_label} testi yakunlandi!\n\n'
        f"Siz *{total} ta* savolga javob berdingiz:\n\n"
        f"✅ To'g'ri – *{correct}*\n"
        f"❌ Xato – *{wrong}*\n"
        f"⏳ Tashlab ketilgan – *{skipped}*\n"
        f"🕐 {time_str}\n\n"
        f"*{batch_total} tadan* 🥇 *{pct}%* to'g'ri."
        f"{rank_text}\n"
        f"_Bu testda yana qatnashishingiz mumkin, lekin bu yetakchilardagi o'rningizni o'zgartirmaydi._"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Guruh natijalari (DB + RAM)
# ─────────────────────────────────────────────────────────────────────────────

def register_group_user(uid: int, first_name: str, username: str | None) -> None:
    group_user_info[uid] = {"name": first_name, "username": username}
    async def _save():
        try:
            from database import upsert_user
            await upsert_user(uid)
        except Exception as e:
            log.warning("register_group_user DB xato: %s", e)
    _run_async(_save())


def save_group_result(chat_id: int, uid: int, correct: int, elapsed: float,
                      wrong: int = 0, answered: int = 0) -> None:
    if chat_id not in group_results:
        group_results[chat_id] = {}
    existing   = group_results[chat_id].get(uid, {})
    started_at = existing.get("started_at") or time.time()
    group_results[chat_id][uid] = {
        "correct":    correct,
        "wrong":      wrong,
        "answered":   answered,
        "elapsed":    time.time() - started_at,
        "started_at": started_at,
    }


def build_group_result_text(chat_id: int, quiz_name: str, total_questions: int) -> str:
    results = group_results.get(chat_id, {})
    user_results = {
        uid: data
        for uid, data in results.items()
        if isinstance(uid, int) and isinstance(data, dict)
    }
    if not user_results:
        return f'♟ "{quiz_name}" testi yakunlandi!\n\nNatijalar topilmadi.'

    sorted_users = sorted(
        user_results.items(),
        key=lambda x: (-x[1].get("correct", 0), x[1].get("elapsed", 0)),
    )

    medals = ["🥇", "🥈", "🥉"]
    lines  = []
    for i, (uid, data) in enumerate(sorted_users):
        medal    = medals[i] if i < len(medals) else "🎖"
        info     = group_user_info.get(uid, {})
        display  = f"@{info['username']}" if info.get("username") else info.get("name", str(uid))
        elapsed  = data.get("elapsed", 0)
        minutes  = int(elapsed // 60)
        secs     = int(elapsed % 60)
        time_str = f"{minutes} daqiqa {secs} soniya" if minutes > 0 else f"{elapsed:.1f} soniya"
        correct  = data.get("correct", 0)
        lines.append(f"{medal} {display} — {correct} ta to'g'ri ({time_str})")

        # DB ga saqlash
        async def _save(c=chat_id, u=uid, d=data, qn=quiz_name):
            try:
                from database import save_group_result as db_save
                await db_save(c, u, qn, d.get("correct",0),
                              d.get("wrong",0), d.get("answered",0), d.get("elapsed",0))
            except Exception as e:
                log.warning("save_group_result DB xato: %s", e)
        _run_async(_save())

    ranking      = "\n".join(lines)
    max_answered = max((d.get("answered", 0) for d in user_results.values()), default=total_questions)

    return (
        f'♟ "{quiz_name}" testi yakunlandi!\n\n'
        f"{max_answered} ta savolga javob berildi\n\n"
        f"{ranking}\n\n"
        f"🏆 G'oliblarni tabriklaymiz!"
    )


def clear_group_results(chat_id: int) -> None:
    group_results.pop(chat_id, None)

# ── Quiz saqlash / yuklash ──────────────────────────────────────────────────

_user_quizzes: dict[int, list[dict]] = {}

def save_quiz_db(uid: int, session: dict) -> None:
    """Sessiyadan quizni foydalanuvchi ro'yxatiga saqlaydi."""
    quiz = {
        "quiz_name": session.get("quiz_name", "Test"),
        "batches":   session.get("batches", []),
        "open_time": session.get("open_time"),
        "total":     sum(len(b) for b in session.get("batches", [])),
    }
    if uid not in _user_quizzes:
        _user_quizzes[uid] = []
    _user_quizzes[uid].append(quiz)


def get_user_quizzes(uid: int) -> list[dict]:
    """Foydalanuvchining saqlangan quizlar ro'yxatini qaytaradi."""
    return _user_quizzes.get(uid, [])


def load_quiz_to_session(uid: int, quiz_index: int) -> bool:
    """Tanlangan quizni sessiyaga yuklaydi. Muvaffaqiyatli bo'lsa True qaytaradi."""
    quizzes = _user_quizzes.get(uid, [])
    if quiz_index < 0 or quiz_index >= len(quizzes):
        return False
    quiz = quizzes[quiz_index]
    s = get_session(uid)
    s["quiz_name"] = quiz["quiz_name"]
    s["batches"]   = quiz["batches"]
    s["open_time"] = quiz["open_time"]
    s["state"]     = "ready"
    return True
