"""
sessions.py — Foydalanuvchi sessiyalari va statistika
"""
import time

# uid → session dict
sessions: dict[int, dict] = {}

# poll_id → uid
# f"{poll_id}:correct"    → correct_option_id (int)
# f"{poll_id}:chat_id"    → chat_id (int)
# f"{poll_id}:message_id" → message_id (int)
poll_owner: dict[str, object] = {}

# uid → oxirgi aktiv poll_id
active_poll: dict[int, str] = {}

# uid → {batch_index → stats}
batch_stats: dict[int, dict[int, dict]] = {}

# Guruh sessiyalari
group_sessions:    dict[int, dict] = {}
group_ready_users: dict[int, set]  = {}
user_group:        dict[int, int]  = {}

# uid → {"name": str, "username": str | None}
group_user_info: dict[int, dict] = {}

# chat_id → {uid → {"correct": int, "elapsed": float}}
group_results: dict[int, dict[int, dict]] = {}


# ──────────────────────────────────────────────────────────────────────────────
# Yordamchi
# ──────────────────────────────────────────────────────────────────────────────

def _empty_stats() -> dict:
    return {"total": 0, "correct": 0, "wrong": 0, "skipped": 0, "started_at": None}


# ──────────────────────────────────────────────────────────────────────────────
# Yakka sessiyalar
# ──────────────────────────────────────────────────────────────────────────────

def get_session(uid: int) -> dict:
    return sessions.setdefault(uid, {
        "state": "idle", "quiz_name": "", "questions": [],
        "batches": [],
        "batch_start": 0,
        "open_time": None,
        "batch_size": 30,
        "active_batch_index": None,
        "stats": _empty_stats(),
    })


def reset_session(uid: int) -> dict:
    old = sessions.get(uid, {})
    sessions[uid] = {
        "state": "idle",
        "quiz_name":          old.get("quiz_name", ""),
        "questions":          old.get("questions", []),
        "batches":            old.get("batches", []),
        "batch_start":        0,
        "open_time":          old.get("open_time"),
        "batch_size":         old.get("batch_size", 30),
        "active_batch_index": None,
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
    """Savollarni batch_size ga bo'lib, batches ro'yxatini qaytaradi."""
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


def build_result_text(uid: int) -> str:
    """Yakka foydalanuvchi uchun natija matni (2-rasmdagidek)."""
    session = get_session(uid)
    stats   = session["stats"]
    name    = session.get("quiz_name", "Quiz")
    bidx    = session.get("active_batch_index", 0)
    batches = session.get("batches", [])
    total   = stats["total"]
    correct = stats["correct"]
    wrong   = stats["wrong"]
    skipped = stats["skipped"]
    elapsed = get_elapsed(uid)
    pct     = round(correct / total * 100) if total > 0 else 0

    batch_label = ""
    if batches and bidx is not None:
        batch_label = f"*{bidx + 1}-to'plam* "

    # O'rinni aniqlash: solo_results dagi barcha natijalar bilan taqqoslash
    all_results = list(solo_results.values())
    rank        = 1
    total_users = len(all_results)
    for r in all_results:
        if r.get("correct", 0) > correct:
            rank += 1

    if total_users > 0:
        better_pct = round((total_users - rank) / total_users * 100) if total_users > 1 else 100
        rank_line  = (
            f"\n\n🥇 *{total_users} tadan* siz *{rank}-o'rinda* turibsiz.\n"
            f"Siz ushbu testda ishtirok etgan *{better_pct}%* odamlardan "
            f"yuqoriroq ball to'pladingiz.\n\n"
            f"_Bu testda yana qatnashishingiz mumkin, lekin bu "
            f"yetakchilardagi o'rningizni o'zgartirmaydi._"
        )
    else:
        rank_line = ""

    return (
        f'♟ *"{name}" {batch_label}testi yakunlandi!*\n\n'
        f"Siz *{total} ta* savolga javob berdingiz:\n"
        f"✅ To'g'ri – *{correct}*\n"
        f"❌ Xato – *{wrong}*\n"
        f"⏳ Tashlab ketilgan – *{skipped}*\n"
        f"⏱ *{elapsed:.1f} soniya*"
        f"{rank_line}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Guruh natijalari
# ──────────────────────────────────────────────────────────────────────────────

def register_group_user(uid: int, first_name: str, username: str | None) -> None:
    """Guruh testiga kirgan foydalanuvchi ma'lumotlarini saqlaydi."""
    group_user_info[uid] = {
        "name":     first_name,
        "username": username,  # @ belgisisiz yoki None
    }


def save_group_result(chat_id: int, uid: int, correct: int, elapsed: float) -> None:
    """Foydalanuvchi natijasini saqlaydi (har bir poll javobida yangilanadi)."""
    if chat_id not in group_results:
        group_results[chat_id] = {}
    group_results[chat_id][uid] = {"correct": correct, "elapsed": elapsed}

# uid → {"correct": int, "elapsed": float}  — yakka test oxirgi natijasi
solo_results: dict[int, dict] = {}


def save_solo_result(uid: int, correct: int, elapsed: float) -> None:
    """Yakka test natijasini saqlaydi."""
    solo_results[uid] = {"correct": correct, "elapsed": elapsed}


def build_group_result_text(chat_id: int, quiz_name: str, total_questions: int) -> str:
    """
    2-rasmdagidek guruh natija matni:

    🏆 "KT 1-30 test" testi yakunlandi!
    30 ta savolga javob berildi

    🥇 @Tursunoff_19 – 22 (4 daqiqa 51 soniya)
    🥈 @OJ_2727 – 17 (4 daqiqa 59 soniya)

    🏆 G'oliblarni tabriklaymiz!
    """
    raw     = group_results.get(chat_id, {})
    # faqat dict tipidagi (foydalanuvchi natijalari), set tipidagi poll_key larni o'tkazib yuboramiz
    results = {uid: v for uid, v in raw.items() if isinstance(v, dict)}
    if not results:
        return f'♟ *"{quiz_name}" testi yakunlandi!*\n\nNatijalar topilmadi.'

    # To'g'ri javob bo'yicha kamayish tartibida, teng bo'lsa vaqt bo'yicha oshish
    sorted_users = sorted(
        results.items(),
        key=lambda x: (-x[1]["correct"], x[1]["elapsed"]),
    )

    medals = ["🥇", "🥈", "🥉"]
    lines  = []
    for i, (uid, data) in enumerate(sorted_users):
        if not isinstance(data, dict):
            continue
        medal = medals[i] if i < len(medals) else "🎖"
        info  = group_user_info.get(uid, {})

        if info.get("username"):
            display = f"@{info['username']}"
        elif info.get("name"):
            display = info["name"]
        else:
            display = str(uid)

        correct = data.get("correct", 0)

        # Vaqt: har bir savolga ketgan vaqtlar yig'indisi
        elapsed   = data.get("elapsed", 0.0)
        minutes   = int(elapsed // 60)
        seconds_r = elapsed % 60
        time_str  = f"{minutes} daqiqa {seconds_r:.1f} soniya" if minutes > 0 else f"{seconds_r:.1f} soniya"

        lines.append(f"{medal} {display} — {correct} ta to'g'ri ({time_str})")

    ranking = "\n".join(lines)

    # Ishtirokchilar orasida eng ko'p javob bergan sonini topish
    max_answered = max(
        (v.get("answered", 0) for v in results.values() if isinstance(v, dict)),
        default=total_questions
    )

    return (
        f'🏆 "{quiz_name}" testi yakunlandi!\n\n'
        f"{max_answered} ta savolga javob berildi\n\n"
        f"{ranking}\n\n"
        f"🏆 G'oliblarni tabriklaymiz!"
    )


def clear_group_results(chat_id: int) -> None:
    """Yangi test oldidan eski natijalarni tozalaydi."""
    group_results.pop(chat_id, None)