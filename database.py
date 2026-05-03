"""
database.py — PostgreSQL bilan ishlash
pip install asyncpg
"""
import json
import logging
import asyncpg

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


# ─────────────────────────────────────────────
# Ulanish
# ─────────────────────────────────────────────

async def init_db(dsn: str) -> None:
    """Bot ishga tushganda bir marta chaqiriladi."""
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    await _create_tables()
    log.info("PostgreSQL ulandi ✅")


async def close_db() -> None:
    if _pool:
        await _pool.close()


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool ishga tushmagan. init_db() chaqiring.")
    return _pool


# ─────────────────────────────────────────────
# Jadvallar yaratish
# ─────────────────────────────────────────────

async def _create_tables() -> None:
    async with get_pool().acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                uid        BIGINT PRIMARY KEY,
                lang       TEXT    DEFAULT 'uz',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS quizzes (
                id         SERIAL PRIMARY KEY,
                uid        BIGINT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
                quiz_name  TEXT   NOT NULL,
                questions  JSONB  NOT NULL,
                batches    JSONB  NOT NULL,
                open_time  INT,
                batch_size INT    DEFAULT 30,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(uid, quiz_name)
            );

            CREATE TABLE IF NOT EXISTS solo_results (
                id         SERIAL PRIMARY KEY,
                uid        BIGINT NOT NULL,
                quiz_name  TEXT   NOT NULL,
                batch_idx  INT    DEFAULT 0,
                correct    INT    DEFAULT 0,
                total      INT    DEFAULT 0,
                elapsed    FLOAT  DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(uid, quiz_name, batch_idx)
            );

            CREATE TABLE IF NOT EXISTS group_results (
                id         SERIAL PRIMARY KEY,
                chat_id    BIGINT NOT NULL,
                uid        BIGINT NOT NULL,
                quiz_name  TEXT   NOT NULL,
                correct    INT    DEFAULT 0,
                wrong      INT    DEFAULT 0,
                answered   INT    DEFAULT 0,
                elapsed    FLOAT  DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(chat_id, uid, quiz_name)
            );
        """)
    log.info("Jadvallar tayyor ✅")


# ─────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────

async def upsert_user(uid: int, lang: str = "uz") -> None:
    await get_pool().execute("""
        INSERT INTO users (uid, lang)
        VALUES ($1, $2)
        ON CONFLICT (uid) DO UPDATE SET lang = EXCLUDED.lang
    """, uid, lang)


async def get_user_lang(uid: int) -> str:
    row = await get_pool().fetchrow("SELECT lang FROM users WHERE uid = $1", uid)
    return row["lang"] if row else "uz"


# ─────────────────────────────────────────────
# Quizzes
# ─────────────────────────────────────────────

async def save_quiz(uid: int, quiz_name: str, questions: list,
                    batches: list, open_time: int | None, batch_size: int) -> None:
    await upsert_user(uid)
    await get_pool().execute("""
        INSERT INTO quizzes (uid, quiz_name, questions, batches, open_time, batch_size, updated_at)
        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6, NOW())
        ON CONFLICT (uid, quiz_name)
        DO UPDATE SET
            questions  = EXCLUDED.questions,
            batches    = EXCLUDED.batches,
            open_time  = EXCLUDED.open_time,
            batch_size = EXCLUDED.batch_size,
            updated_at = NOW()
    """, uid, quiz_name,
         json.dumps(questions, ensure_ascii=False),
         json.dumps(batches, ensure_ascii=False),
         open_time, batch_size)


async def get_user_quizzes(uid: int) -> list[dict]:
    rows = await get_pool().fetch("""
        SELECT quiz_name, questions, batches, open_time, batch_size, updated_at
        FROM quizzes WHERE uid = $1
        ORDER BY updated_at DESC
    """, uid)
    result = []
    for r in rows:
        result.append({
            "quiz_name":  r["quiz_name"],
            "questions":  json.loads(r["questions"]),
            "batches":    json.loads(r["batches"]),
            "open_time":  r["open_time"],
            "batch_size": r["batch_size"],
            "updated_at": r["updated_at"],
        })
    return result


async def get_quiz_by_name(uid: int, quiz_name: str) -> dict | None:
    row = await get_pool().fetchrow("""
        SELECT quiz_name, questions, batches, open_time, batch_size
        FROM quizzes WHERE uid = $1 AND quiz_name = $2
    """, uid, quiz_name)
    if not row:
        return None
    return {
        "quiz_name":  row["quiz_name"],
        "questions":  json.loads(row["questions"]),
        "batches":    json.loads(row["batches"]),
        "open_time":  row["open_time"],
        "batch_size": row["batch_size"],
    }


async def delete_quiz(uid: int, quiz_name: str) -> None:
    await get_pool().execute(
        "DELETE FROM quizzes WHERE uid = $1 AND quiz_name = $2", uid, quiz_name
    )


# ─────────────────────────────────────────────
# Solo natijalar
# ─────────────────────────────────────────────

async def save_solo_result(uid: int, quiz_name: str, batch_idx: int,
                           correct: int, total: int, elapsed: float) -> None:
    await upsert_user(uid)
    await get_pool().execute("""
        INSERT INTO solo_results (uid, quiz_name, batch_idx, correct, total, elapsed)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (uid, quiz_name, batch_idx)
        DO NOTHING
    """, uid, quiz_name, batch_idx, correct, total, elapsed)


async def get_solo_results(quiz_name: str, batch_idx: int) -> list[dict]:
    """Reyting uchun — barcha userlar natijasi."""
    rows = await get_pool().fetch("""
        SELECT uid, correct, total, elapsed
        FROM solo_results
        WHERE quiz_name = $1 AND batch_idx = $2
        ORDER BY correct DESC, elapsed ASC
    """, quiz_name, batch_idx)
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# Guruh natijalari
# ─────────────────────────────────────────────

async def save_group_result(chat_id: int, uid: int, quiz_name: str,
                            correct: int, wrong: int, answered: int, elapsed: float) -> None:
    await upsert_user(uid)
    await get_pool().execute("""
        INSERT INTO group_results (chat_id, uid, quiz_name, correct, wrong, answered, elapsed)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (chat_id, uid, quiz_name)
        DO UPDATE SET
            correct  = EXCLUDED.correct,
            wrong    = EXCLUDED.wrong,
            answered = EXCLUDED.answered,
            elapsed  = EXCLUDED.elapsed,
            created_at = NOW()
    """, chat_id, uid, quiz_name, correct, wrong, answered, elapsed)


async def get_group_results(chat_id: int, quiz_name: str) -> list[dict]:
    rows = await get_pool().fetch("""
        SELECT uid, correct, wrong, answered, elapsed
        FROM group_results
        WHERE chat_id = $1 AND quiz_name = $2
        ORDER BY correct DESC, elapsed ASC
    """, chat_id, quiz_name)
    return [dict(r) for r in rows]


async def clear_group_results(chat_id: int, quiz_name: str) -> None:
    await get_pool().execute(
        "DELETE FROM group_results WHERE chat_id = $1 AND quiz_name = $2",
        chat_id, quiz_name
    )
async def get_quiz_stats(quiz_name: str) -> dict:
    """Quiz bo'yicha umumiy statistika."""
    row = await get_pool().fetchrow("""
        SELECT 
            COUNT(DISTINCT uid) as participants,
            AVG(correct::float / NULLIF(total, 0) * 100) as avg_score
        FROM solo_results
        WHERE quiz_name = $1
    """, quiz_name)
    return {
        "participants": row["participants"] or 0,
        "avg_score":    round(row["avg_score"] or 0, 1),
    }
