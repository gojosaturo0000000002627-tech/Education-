"""Hindi MCQ: seed bank + AI. Ek user ko wahi sawaal dobara nahi dikhta."""

from __future__ import annotations

import hashlib
import logging
import re

import config
import database
import ai_assistant

logger = logging.getLogger(__name__)

TOPIC_CODES = {
    "gk": "rajasthan gk",
    "his": "itihas",
    "geo": "geo",
    "pol": "pol",
    "hin": "hindi",
    "rea": "reasoning",
    "sci": "vigyan",
    "com": "computer",
    "cdp": "cdp",
    "san": "sanskrit",
    "eng": "english",
    "cur": "current affairs",
    "math": "math",
}

DIFF_MAP = {
    "easy": "easy",
    "e": "easy",
    "aasan": "easy",
    "आसान": "easy",
    "medium": "medium",
    "m": "medium",
    "madhyam": "medium",
    "मध्यम": "medium",
    "hard": "hard",
    "h": "hard",
    "kathin": "hard",
    "कठिन": "hard",
}

DIFF_HI = {"easy": "आसान", "medium": "मध्यम", "hard": "कठिन"}


def normalize_question(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\"'“”‘’?.!,।]", "", text)
    return text


def question_hash(text: str) -> str:
    return hashlib.sha256(normalize_question(text).encode("utf-8")).hexdigest()


def parse_difficulty(token: str | None) -> str | None:
    if not token:
        return None
    return DIFF_MAP.get(token.strip().lower())


def topic_from_code(code: str) -> str:
    return TOPIC_CODES.get(code, code)


def validate_mcq(item: dict) -> bool:
    options = item.get("options") or []
    if len(options) != 4:
        return False
    if item.get("answer_index") not in {0, 1, 2, 3}:
        return False
    if len((item.get("question") or "").strip()) < 8:
        return False
    return True


async def remember(user_db_id: int, item: dict, exam_id: int | None, was_correct: bool | None = None) -> None:
    await database.record_shown(
        user_db_id,
        item["question_hash"],
        exam_id,
        item.get("topic") or "",
        item.get("difficulty") or "",
        was_correct,
    )


async def _generate_and_store(exam: dict | None, topic: str, difficulty: str, n: int, seen: set[str], user_db_id: int) -> list[dict]:
    if not ai_assistant.has_llm():
        return []
    usage = await database.get_usage(user_db_id)
    if usage["mcq_generated"] >= config.MCQ_DAILY_LIMIT:
        return []
    avoid = []
    # recent question texts are not stored on history; pass hashes is useless to the model.
    # Pull a few bank questions of this topic as avoid-list.
    bank = await database.fetch_mcqs(topic, difficulty if difficulty != "any" else None, limit=12)
    avoid = [b["question"] for b in bank[:12]]
    try:
        fresh = await ai_assistant.generate_mcqs(
            exam["name_hi"] if exam else "राजस्थान सामान्य परीक्षा",
            topic,
            difficulty if difficulty in {"easy", "medium", "hard"} else "medium",
            n,
            avoid,
        )
    except Exception:
        logger.exception("MCQ generation failed")
        return []
    storable = []
    for item in fresh:
        if not validate_mcq(item):
            continue
        h = question_hash(item["question"])
        if h in seen:
            continue
        item["question_hash"] = h
        item["tags"] = list({topic, item.get("topic") or topic, "ai"})
        item["source"] = "ai"
        item["exam_id"] = exam["id"] if exam else None
        storable.append(item)
    if storable:
        await database.upsert_mcqs(storable)
        await database.bump_usage(user_db_id, mcq=len(storable))
    return storable


async def next_questions(
    user_db_id: int,
    exam: dict | None,
    topic: str,
    difficulty: str,
    n: int,
    allow_ai: bool = True,
) -> list[dict]:
    n = max(1, min(int(n), 20))
    topic = topic_from_code(topic) if topic in TOPIC_CODES else topic
    seen = await database.seen_hashes(user_db_id)
    pool = await database.fetch_mcqs(topic, None, limit=500)
    picked: list[dict] = []
    used = set(seen)

    def take_from(items: list[dict], diff: str | None) -> None:
        for item in items:
            if len(picked) >= n:
                return
            if item["question_hash"] in used:
                continue
            if diff and diff != "any" and item["difficulty"] != diff:
                continue
            picked.append(item)
            used.add(item["question_hash"])

    take_from(pool, difficulty)
    if len(picked) < n:
        # same topic, any difficulty, still unseen
        take_from(pool, None)
    if len(picked) < n and allow_ai:
        generated = await _generate_and_store(exam, topic, difficulty or "medium", n - len(picked) + 2, used, user_db_id)
        for item in generated:
            if len(picked) >= n:
                break
            if item["question_hash"] in used:
                continue
            picked.append(item)
            used.add(item["question_hash"])
    for item in picked:
        await remember(user_db_id, item, exam["id"] if exam else None)
    return picked


def format_question(item: dict, index: int | None = None, total: int | None = None) -> str:
    from html import escape

    letters = ["A", "B", "C", "D"]
    head = ""
    if index is not None and total is not None:
        head = f"प्रश्न {index}/{total}  |  स्तर: {DIFF_HI.get(item.get('difficulty'), item.get('difficulty', ''))}\n\n"
    lines = [f"{head}<b>{escape(item['question'])}</b>"]
    for i, opt in enumerate(item["options"]):
        lines.append(f"{letters[i]}) {escape(str(opt))}")
    return "\n".join(lines)


def format_reveal(item: dict, selected: int | None, timed_out: bool = False) -> str:
    from html import escape

    letters = ["A", "B", "C", "D"]
    correct = item["answer_index"]
    if timed_out:
        head = "⏱ समय समाप्त।"
    elif selected == correct:
        head = "✅ सही।"
    else:
        head = "❌ गलत।"
    chosen = letters[selected] if selected is not None and 0 <= selected <= 3 else "—"
    return (
        f"{head}\nसही उत्तर: {letters[correct]}) {escape(str(item['options'][correct]))}\n"
        f"आपका विकल्प: {chosen}\nकारण: {escape(item.get('explanation') or '—')}"
    )


async def start_quiz(
    user_db_id: int,
    exam: dict | None,
    topic: str,
    difficulty: str,
    n: int,
    chat_id: int,
    seconds: int | None = None,
) -> dict | None:
    questions = await next_questions(user_db_id, exam, topic, difficulty, n, allow_ai=True)
    if not questions:
        return None
    await database.abandon_active_quizzes(user_db_id)
    session = await database.create_quiz(
        {
            "user_id": user_db_id,
            "exam_id": exam["id"] if exam else None,
            "topic": topic,
            "difficulty": difficulty,
            "seconds_per_q": seconds or config.QUIZ_SECONDS,
            "chat_id": chat_id,
            "questions": [
                {
                    "question": q["question"],
                    "options": q["options"],
                    "answer_index": q["answer_index"],
                    "explanation": q.get("explanation") or "",
                    "question_hash": q["question_hash"],
                    "difficulty": q.get("difficulty") or difficulty,
                }
                for q in questions
            ],
        }
    )
    return session


def quiz_summary(quiz: dict, exam_name: str = "") -> str:
    total = quiz["total"] or 1
    score = quiz["correct"]
    lines = [
        f"📊 क्विज़ समाप्त — {exam_name or quiz.get('topic')}",
        f"सही: {quiz['correct']}  |  गलत: {quiz['wrong']}  |  छूटे: {quiz['skipped']}",
        f"स्कोर: {score}/{total}",
        "",
        "गलत / छूटे हुए प्रश्नों की व्याख्या:",
    ]
    wrongs = [a for a in quiz.get("answers") or [] if a.get("result") != "correct"]
    if not wrongs:
        lines.append("सब सही। बहुत बढ़िया।")
    else:
        letters = ["A", "B", "C", "D"]
        for a in wrongs[:12]:
            ci = a.get("correct_index", 0)
            opts = a.get("options") or ["", "", "", ""]
            lines.append(
                f"• {a.get('question')}\n  सही: {letters[ci]}) {opts[ci] if ci < len(opts) else ''}\n  कारण: {a.get('explanation') or '—'}"
            )
    lines.append("\nदोबारा अभ्यास: /quiz")
    return "\n".join(lines)[:4000]
