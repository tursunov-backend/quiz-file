"""
parser.py — Fayldan savollarni o'qish

Qo'llab-quvvatlanadigan formatlar:

FORMAT 1 (klassik):
  Savol matni
  #To'g'ri javob
  ==== Noto'g'ri 1
  ==== Noto'g'ri 2
  ==== Noto'g'ri 3
  ++++

FORMAT 2 (raqamli):
  1. Savol matni?
  ====
    # To'g'ri javob
    ====
    Noto'g'ri javob 1
    ====
    Noto'g'ri javob 2
    ====
    Noto'g'ri javob 3
    ++++
"""
import re
import random
from pathlib import Path

_WRONG_POOL = [
    "Yuqoridagilarning hech biri",
    "Barchasi to'g'ri",
    "Ma'lumot yetarli emas",
    "Barchasi noto'g'ri",
    "Javob yo'q",
    "Aniqlanmagan",
    "Hammasi noto'g'ri",
    "Ularning hech biri emas",
]

# Raqamli savol boshlanishi: "1.", "2.", "10." va h.k.
_NUM_RE = re.compile(r"^\d+\.\s+")


def _fill_wrongs(correct: str, wrongs: list[str]) -> list[str]:
    pool = [
        w for w in _WRONG_POOL
        if w.lower() != correct.lower()
        and w.lower() not in [x.lower() for x in wrongs]
    ]
    random.shuffle(pool)
    result = wrongs[:]
    for w in pool:
        if len(result) >= 3:
            break
        result.append(w)
    return result[:3]


def _build_question(question: str, correct: str, wrongs: list[str]) -> dict | None:
    """Savol lug'atini yasaydi. Noto'g'ri bo'lsa None qaytaradi."""
    question = question.strip()
    correct  = correct.strip().rstrip(";").strip()   # oxiridagi ';' ni olib tashlash
    if not question or not correct:
        return None

    wrongs = [w.strip().rstrip(";").strip() for w in wrongs if w.strip()]
    wrongs = _fill_wrongs(correct, wrongs)

    # Takrorlarni olib tashlash
    seen, unique = set(), []
    for opt in [correct] + wrongs:
        if opt.lower() not in seen:
            seen.add(opt.lower())
            unique.append(opt)

    # Kamida 4 ta variant bo'lishi kerak
    while len(unique) < 4:
        for w in _WRONG_POOL:
            if w.lower() not in seen:
                seen.add(w.lower())
                unique.append(w)
                break

    opts = unique[:4]
    random.shuffle(opts)
    return {
        "question":      question,
        "options":       opts,
        "correct_index": opts.index(correct),
    }


# ─────────────────────────────────────────────────────────────────────────────
# FORMAT 1: "++++"-ga bo'lingan bloklar
# ─────────────────────────────────────────────────────────────────────────────

def _parse_format1(text: str) -> list[dict]:
    questions = []
    for block in text.split("++++"):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue

        question_lines: list[str] = []
        correct: str | None = None
        wrongs:  list[str]  = []

        for line in lines:
            if line.startswith("#"):
                correct = line[1:].strip()
            elif line.startswith("===="):
                wrongs.append(line[4:].strip())
            else:
                if correct is None and not wrongs:
                    question_lines.append(line)

        q = _build_question(" ".join(question_lines), correct or "", wrongs)
        if q:
            questions.append(q)
    return questions


# ─────────────────────────────────────────────────────────────────────────────
# FORMAT 2: raqamli savollar ("1. Savol?" ... keyingi raqam)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_format2(text: str) -> list[dict]:
    """
    Har bir savol "N. Savol matni" bilan boshlanadi.
    To'g'ri javob "#..." bilan belgilangan.
    Qolgan qatorlar (bo'sh bo'lmagan, raqamli savol bo'lmagan) — noto'g'ri javoblar.
    """
    questions = []

    # Barcha qatorlarni ol
    lines = [l.strip() for l in text.splitlines()]

    # Savol bloklar chegaralarini top
    block_starts = [i for i, l in enumerate(lines) if _NUM_RE.match(l)]

    for bi, start in enumerate(block_starts):
        end = block_starts[bi + 1] if bi + 1 < len(block_starts) else len(lines)
        block = [l for l in lines[start:end] if l]

        if not block:
            continue

        # Birinchi qator — savol matni (raqamni olib tashlash)
        question_text = _NUM_RE.sub("", block[0]).strip()

        correct: str | None = None
        wrongs:  list[str]  = []

        for line in block[1:]:
            if not line:
                continue
            if line.startswith("#"):
                # To'g'ri javob — birinchi '#' topilgani
                if correct is None:
                    correct = line[1:].strip()
                # Agar yana '#' bo'lsa — noto'g'ri sifatida qo'sh
                else:
                    wrongs.append(line[1:].strip())
            elif line.startswith("===="):
                wrongs.append(line[4:].strip())
            else:
                wrongs.append(line)

        q = _build_question(question_text, correct or "", wrongs)
        if q:
            questions.append(q)

    return questions


# ─────────────────────────────────────────────────────────────────────────────
# ASOSIY PARSER — formatni avtomatik aniqlab, tegishli metodga yo'naltiradi
# ─────────────────────────────────────────────────────────────────────────────

def parse_blocks(text: str) -> list[dict]:
    """
    Matnni tahlil qilib, savollar ro'yxatini qaytaradi.
    Format 1 ("++++") va Format 2 (raqamli) ni avtomatik tanlaydi.
    Agar ikki format aralashgan bo'lsa — har biri alohida parsed qilinadi.
    """
    has_format1 = "++++" in text
    has_format2 = bool(_NUM_RE.search(text))

    if has_format1 and not has_format2:
        return _parse_format1(text)

    if has_format2 and not has_format1:
        return _parse_format2(text)

    if has_format1 and has_format2:
        # Aralash: har ikkisini sinab ko'r, ko'prog'ini ol
        r1 = _parse_format1(text)
        r2 = _parse_format2(text)
        return r1 if len(r1) >= len(r2) else r2

    # Hech biri aniqlanmasa — format1 sifatida urinib ko'r
    return _parse_format1(text)


# ─────────────────────────────────────────────────────────────────────────────
# FAYL O'QISH
# ─────────────────────────────────────────────────────────────────────────────

def read_file(path: str, mime: str) -> str:
    suffix = Path(path).suffix.lower()

    if suffix == ".pdf" or "pdf" in mime:
        try:
            import fitz
            doc  = fitz.open(path)
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
            return text
        except ImportError:
            pass

    if suffix == ".docx" or "word" in mime:
        try:
            from docx import Document
            return "\n".join(p.text for p in Document(path).paragraphs)
        except ImportError:
            pass

    for enc in ("utf-8", "utf-16", "cp1251", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue

    return ""

