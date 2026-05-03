"""
parser.py — Fayldan savollarni o'qish  (tuzatilgan versiya)

Qo'llab-quvvatlanadigan formatlar:

FORMAT 1 (klassik - bir qatorda):
  Savol matni
  # To'g'ri javob          ← hash + bo'shliq
  ==== Noto'g'ri 1
  ==== Noto'g'ri 2
  ==== Noto'g'ri 3
  ++++

FORMAT 2 (yangi - ajratilgan qatorlar):
  Savol matni?
  ====
  #To'g'ri javob           ← hash, bo'shliqsiz
  ====
  Noto'g'ri 1
  ====
  Noto'g'ri 2
  ++++

FORMAT 3 (raqamli):
  1. Savol matni?
  #To'g'ri javob
  Noto'g'ri 1
  Noto'g'ri 2
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

_NUM_RE = re.compile(r"^\d+[\.\)]\s+")


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
    question = question.strip()
    correct  = correct.strip().rstrip(";").strip()
    if not question or not correct:
        return None

    wrongs = [w.strip().rstrip(";").strip() for w in wrongs if w.strip()]
    wrongs = _fill_wrongs(correct, wrongs)

    seen, unique = set(), []
    for opt in [correct] + wrongs:
        if opt.lower() not in seen:
            seen.add(opt.lower())
            unique.append(opt)

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
# FORMAT 1 & 2: "++++"-ga bo'lingan bloklar
# ─────────────────────────────────────────────────────────────────────────────

def _parse_format1(text: str) -> list[dict]:
    """
    Ikkala ko'rinishni qo'llab-quvvatlaydi:
      A) "# To'g'ri javob"  va  "==== Noto'g'ri"   (bir qatorda)
      B) "====\n#To'g'ri"   va  "====\nNoto'g'ri"  (ajratilgan qatorlar)
    """
    questions = []

    for block in text.split("++++"):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue

        question_lines: list[str] = []
        answer_blocks:  list[str] = []
        current_answer: list[str] = []
        in_answers = False

        for line in lines:
            if line.startswith("===="):  # "====", "==== Matn", "====Matn"
                # Oldingi javobni saqlash
                if current_answer:
                    answer_blocks.append(" ".join(current_answer))
                current_answer = []
                in_answers     = True
                suffix = line[4:].strip()
                if suffix:
                    current_answer.append(suffix)

            # ★ TUZATISH: "# To'g'ri javob" ham javob sifatida qaraladi
            elif line.startswith("#"):
                if current_answer:
                    answer_blocks.append(" ".join(current_answer))
                current_answer = [line]   # "#..." ni saqlaymiz
                in_answers     = True

            else:
                if in_answers:
                    current_answer.append(line)
                else:
                    question_lines.append(line)

        # Oxirgi javobni saqlash
        if current_answer:
            answer_blocks.append(" ".join(current_answer))

        # To'g'ri javobni topish
        correct: str | None = None
        wrongs:  list[str]  = []

        for ans in answer_blocks:
            if ans.startswith("#"):
                if correct is None:          # birinchi # — to'g'ri javob
                    correct = ans[1:].strip()
                else:
                    wrongs.append(ans[1:].strip())
            else:
                wrongs.append(ans)

        question = " ".join(question_lines).strip()
        q = _build_question(question, correct or "", wrongs)
        if q:
            questions.append(q)

    return questions


# ─────────────────────────────────────────────────────────────────────────────
# FORMAT 3: raqamli savollar
# ─────────────────────────────────────────────────────────────────────────────

def _parse_format3(text: str) -> list[dict]:
    questions = []
    lines     = [l.strip() for l in text.splitlines()]
    block_starts = [i for i, l in enumerate(lines) if _NUM_RE.match(l)]

    for bi, start in enumerate(block_starts):
        end   = block_starts[bi + 1] if bi + 1 < len(block_starts) else len(lines)
        block = [l for l in lines[start:end] if l]
        if not block:
            continue

        question_text = _NUM_RE.sub("", block[0]).strip()
        correct: str | None = None
        wrongs:  list[str]  = []

        for line in block[1:]:
            if line.startswith("#"):
                if correct is None:
                    correct = line[1:].strip().rstrip(";").strip()
                else:
                    wrongs.append(line[1:].strip().rstrip(";").strip())
            elif line.startswith("===="):
                wrongs.append(line[4:].strip())
            else:
                wrongs.append(line.rstrip(";").strip())

        q = _build_question(question_text, correct or "", wrongs)
        if q:
            questions.append(q)

    return questions


# ─────────────────────────────────────────────────────────────────────────────
# ASOSIY PARSER
# ─────────────────────────────────────────────────────────────────────────────

def parse_blocks(text: str) -> list[dict]:
    has_format12 = "++++" in text
    has_format3  = bool(_NUM_RE.search(text))

    if has_format12 and not has_format3:
        return _parse_format1(text)

    if has_format3 and not has_format12:
        return _parse_format3(text)

    if has_format12 and has_format3:
        r1 = _parse_format1(text)
        r3 = _parse_format3(text)
        return r1 if len(r1) >= len(r3) else r3

    return _parse_format1(text)


# ─────────────────────────────────────────────────────────────────────────────
# FAYL O'QISH
# ─────────────────────────────────────────────────────────────────────────────

def read_file(path: str, mime: str = "") -> str:
    suffix = Path(path).suffix.lower()

    if suffix == ".pdf" or "pdf" in mime:
        # PyMuPDF (fitz) — birinchi urinish
        try:
            import fitz
            doc  = fitz.open(path)
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
            if text.strip():
                return text
        except ImportError:
            pass

        # pdfplumber — ikkinchi urinish
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            if text.strip():
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
