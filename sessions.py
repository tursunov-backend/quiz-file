"""
sessions.py — Foydalanuvchi sessiyalari va statistika
"""
import time

sessions:          dict[int, dict] = {}
poll_owner:        dict[str, object] = {}
active_poll:       dict[int, str] = {}
batch_stats:       dict[int, dict[int, dict]] = {}
group_sessions:    dict[int, dict] = {}
group_ready_users: dict[int, set]  = {}
user_group:        dict[int, int]  = {}
group_user_info:   dict[int, dict] = {}
group_results:     dict[int, dict] = {}
solo_results:      dict[str, list] = {}
user_quizzes:      dict[int, list] = {}


def _empty_stats() -> dict:
    return {"total": 0, "correct": 0, "wrong": 0, "skipped": 0, "started_at": None}


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
    session   = get_session(uid)
    questions = session.get("questions", [])
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


def save_solo_result(uid: int, correct: int, elapsed: float) -> None:
    session  = get_session(uid)
    quiz_key = f"{session.get('quiz_name', '')}:{session.get('active_batch_index', 0)}"
    if quiz_key not in solo_results:
        solo_results[quiz_key] = []
    for entry in solo_results[quiz_key]:
        if entry["uid"] == uid:
            entry["correct"] = correct
            entry["elapsed"] = elapsed
            return
    solo_results[quiz_key].append({"uid": uid, "correct": correct, "elapsed": elapsed})


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
    elapsed = get_elapsed(uid)
    pct     = round(correct / total * 100) if total > 0 else 0

    minutes  = int(elapsed // 60)
    secs     = int(elapsed % 60)
    time_str = f"{minutes} daqiqa {secs} soniya" if minutes > 0 else f"{elapsed:.1f} soniya"

    batch_label = f"*{bidx + 1}-to'plam*" if batches and bidx is not None else ""
    batch_total = len(batches[bidx]) if batches and bidx is not None and bidx < len(batches) else total

    quiz_key    = f"{name}:{bidx}"
    all_results = solo_results.get(quiz_key, [])
    rank_text   = ""
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


def register_group_user(uid: int, first_name: str, username: str | None) -> None:
    group_user_info[uid] = {"name": first_name, "username": username}


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
        return f'♟ *"{quiz_name}" testi yakunlandi!*\n\nNatijalar topilmadi.'

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
        correct = data.get("correct", 0)
        lines.append(f"{medal} {display} — {correct} ta to'g'ri ({time_str})")

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


def save_quiz(uid: int, session: dict) -> None:
    if uid not in user_quizzes:
        user_quizzes[uid] = []
    quiz_name = session.get("quiz_name", "")
    batches   = session.get("batches", [])
    total     = sum(len(b) for b in batches)
    for q in user_quizzes[uid]:
        if q["quiz_name"] == quiz_name:
            q["batches"]    = batches
            q["open_time"]  = session.get("open_time")
            q["batch_size"] = session.get("batch_size", 30)
            q["total"]      = total
            q["updated_at"] = time.time()
            return
    user_quizzes[uid].append({
        "quiz_name":  quiz_name,
        "batches":    batches,
        "open_time":  session.get("open_time"),
        "batch_size": session.get("batch_size", 30),
        "total":      total,
        "created_at": time.time(),
    })


def get_user_quizzes(uid: int) -> list:
    return user_quizzes.get(uid, [])


def load_quiz_to_session(uid: int, quiz_index: int) -> bool:
    quizzes = user_quizzes.get(uid, [])
    if quiz_index >= len(quizzes):
        return False
    q    = quizzes[quiz_index]
    lang = sessions.get(uid, {}).get("lang", "uz")
    sessions[uid] = {
        "state":              "ready",
        "quiz_name":          q["quiz_name"],
        "questions":          [s for b in q["batches"] for s in b],
        "batches":            q["batches"],
        "batch_start":        0,
        "open_time":          q["open_time"],
        "batch_size":         q["batch_size"],
        "active_batch_index": None,
        "lang":               lang,
        "stats":              _empty_stats(),
    }
    return True