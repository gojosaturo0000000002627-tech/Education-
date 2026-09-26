"""राज परीक्षा गुरु — web service.

Render / Railway / कोई भी host जो HTTP पोर्ट माँगे, यही चलाएँ:

    uvicorn web:app --host 0.0.0.0 --port $PORT

या:

    python web.py

साइट हमेशा चलती है। BOT_TOKEN हो तो Telegram बॉट उसी प्रोसेस में जुड़ जाता है।
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

import ai_assistant
import config
import database
import mcq_engine
from telegram import Update

logger = logging.getLogger("rajguru.web")
INDEX = (Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")
telegram_app = None


class McqIn(BaseModel):
    slug: str = "raj-gk"
    topic: str = "gk"
    difficulty: str = "medium"
    n: int = Field(default=1, ge=1, le=20)


class CheckIn(BaseModel):
    hash: str
    selected: int | None = None


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    slug: str | None = None


async def _uid_user(request: Request) -> dict:
    uid = int(getattr(request.state, "uid", 0) or 0)
    if uid <= 0:
        uid = random.randint(1_000_000_000_000, 9_999_999_999_999)
    return await database.upsert_user(uid, None, "वेब अभ्यर्थी")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global telegram_app
    await database.init_db()
    from bot import seed_all

    await seed_all()
    if config.BOT_TOKEN:
        from bot import build_application

        telegram_app = build_application()
        await telegram_app.initialize()
        await telegram_app.start()
        if config.MODE == "webhook" and config.WEBHOOK_URL:
            secret = hashlib.sha256(config.BOT_TOKEN.encode()).hexdigest()[:32]
            await telegram_app.bot.set_webhook(
                url=f"{config.WEBHOOK_URL}/{config.WEBHOOK_PATH}",
                secret_token=secret,
                drop_pending_updates=config.DROP_PENDING,
            )
            logger.info("Telegram webhook set")
        else:
            await telegram_app.updater.start_polling(
                drop_pending_updates=config.DROP_PENDING,
                allowed_updates=Update.ALL_TYPES,
            )
            logger.info("Telegram polling started inside web service")
    else:
        logger.info("BOT_TOKEN nahi hai — sirf website chal rahi hai")
    yield
    if telegram_app is not None:
        updater = telegram_app.updater
        if updater and getattr(updater, "running", False):
            await updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()


app = FastAPI(title="राज परीक्षा गुरु", version=config.VERSION, lifespan=lifespan)


@app.middleware("http")
async def attach_uid(request: Request, call_next):
    raw = request.cookies.get("rpg_uid", "")
    fresh = None
    if raw.isdigit():
        request.state.uid = int(raw)
    else:
        fresh = random.randint(1_000_000_000_000, 9_999_999_999_999)
        request.state.uid = fresh
    response = await call_next(request)
    if fresh:
        response.set_cookie("rpg_uid", str(fresh), max_age=60 * 60 * 24 * 400, samesite="lax")
    return response


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(INDEX)


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "service": "raj-pariksha-guru",
        "version": config.VERSION,
        "telegram": bool(config.BOT_TOKEN),
        "ai": ai_assistant.has_llm(),
    }


@app.get("/api/exams")
async def exams(q: str = ""):
    rows = await database.all_active_exams()
    if q.strip():
        rows = [e for e in rows if database.score_exam(e, q) > 0]
        rows.sort(key=lambda e: -database.score_exam(e, q))
    return [
        {
            "slug": e["slug"],
            "name_hi": e["name_hi"],
            "name_en": e["name_en"],
            "category": e["category"],
            "body": e["body"],
        }
        for e in rows
    ]


@app.get("/api/exams/{slug}")
async def exam_detail(slug: str):
    exam = await database.get_exam_by_slug(slug)
    if not exam:
        exam, _ = await database.resolve_exam_query(slug)
    if not exam:
        raise HTTPException(404, "परीक्षा नहीं मिली")
    pdfs = [p for p in await database.list_pdfs(exam["id"]) if p.get("is_official") and p.get("status") == "active"]
    public = []
    for p in pdfs:
        public.append(
            {
                "id": p["id"],
                "kind": p["kind"],
                "kind_hi": config.KIND_HI.get(p["kind"], p["kind"]),
                "title": p["title"],
                "year": p["year"],
                "shift": p["shift"],
                "version_label": p["version_label"],
                "source_url": p["source_url"],
                "file_name": p["file_name"],
            }
        )
    return {**exam, "pdfs": public}


def _public_mcq(item: dict) -> dict:
    return {
        "hash": item["question_hash"],
        "question": item["question"],
        "options": item["options"],
        "difficulty": item.get("difficulty") or "medium",
        "topic": item.get("topic") or "",
    }


@app.post("/api/mcq")
async def make_mcq(body: McqIn, request: Request):
    user = await _uid_user(request)
    exam, _ = await database.resolve_exam_query(body.slug)
    if not exam:
        raise HTTPException(404, "परीक्षा नहीं मिली")
    difficulty = mcq_engine.parse_difficulty(body.difficulty) or "medium"
    topic = mcq_engine.topic_from_code(body.topic)
    items = await mcq_engine.next_questions(user["id"], exam, topic, difficulty, body.n, allow_ai=True)
    if not items:
        raise HTTPException(404, "इस विषय के नए प्रश्न नहीं बचे। दूसरा विषय चुनें या AI कुंजी जोड़ें।")
    return {"exam": exam["name_hi"], "questions": [_public_mcq(i) for i in items]}


@app.post("/api/mcq/check")
async def check_mcq(body: CheckIn, request: Request):
    item = await database.get_mcq_by_hash(body.hash)
    if not item:
        raise HTTPException(404, "प्रश्न नहीं मिला")
    user = await _uid_user(request)
    correct = body.selected is not None and body.selected == item["answer_index"]
    await database.update_history_result(user["id"], item["question_hash"], correct)
    return {
        "correct": correct,
        "timed_out": body.selected is None,
        "correct_index": item["answer_index"],
        "explanation": item.get("explanation") or "",
        "options": item["options"],
    }


@app.post("/api/ask")
async def ask(body: AskIn, request: Request):
    user = await _uid_user(request)
    exam = None
    if body.slug:
        exam, _ = await database.resolve_exam_query(body.slug)
    text = await ai_assistant.answer_question(user["id"], body.question, exam["name_hi"] if exam else None)
    return {"answer": text}


@app.post("/{webhook_path}")
async def telegram_webhook(webhook_path: str, request: Request):
    if telegram_app is None or webhook_path != config.WEBHOOK_PATH:
        return JSONResponse({"ok": False}, status_code=404)
    secret = hashlib.sha256(config.BOT_TOKEN.encode()).hexdigest()[:32]
    if request.headers.get("x-telegram-bot-api-secret-token") != secret:
        return JSONResponse({"ok": False}, status_code=403)
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
