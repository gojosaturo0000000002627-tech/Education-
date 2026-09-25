"""राज परीक्षा गुरु — Rajasthan sarkari exam Telegram bot.

Chalane ka tarika: python bot.py
Token .env me BOT_TOKEN.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sys
from datetime import date, datetime
from html import escape
from pathlib import Path

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PollAnswerHandler,
    filters,
)

import ai_assistant
import config
import database
import mcq_engine
import pdf_updater
import reminders
import ui
from exams_seed import EXAMS, PORTALS, SEED_MCQS

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("rajguru")

MENU_TEXT = {
    "📚 परीक्षाएँ": "exams",
    "📄 सिलेबस": "syllabus",
    "📝 पुराने पेपर": "papers",
    "❓ MCQ": "mcq",
    "⏱ क्विज़": "quiz",
    "🤖 AI से पूछो": "ai",
    "🔔 रिमाइंडर": "remind",
    "ℹ️ मदद": "help",
}

COMMANDS = [
    BotCommand("start", "शुरुआत और मेनू"),
    BotCommand("help", "सारे आदेश"),
    BotCommand("exams", "परीक्षाओं की सूची"),
    BotCommand("search", "परीक्षा खोजें"),
    BotCommand("syllabus", "सिलेबस PDF"),
    BotCommand("papers", "पुराने प्रश्नपत्र"),
    BotCommand("mcq", "नया हिंदी MCQ"),
    BotCommand("quiz", "टाइमर वाला टेस्ट"),
    BotCommand("subscribe", "अपडेट सूचना चालू"),
    BotCommand("unsubscribe", "सूचना बंद"),
    BotCommand("daily", "रोज़ का अभ्यास"),
    BotCommand("remind", "रिमाइंडर सेट"),
    BotCommand("myreminders", "मेरे रिमाइंडर"),
    BotCommand("ask", "AI से पूछें"),
    BotCommand("verify", "PDF लिंक जाँचें"),
    BotCommand("whoami", "मेरी Telegram ID"),
    BotCommand("cancel", "रुकी क्रिया बंद"),
]


def is_admin(tg_id: int | None) -> bool:
    return bool(tg_id and tg_id in config.ADMIN_IDS)


async def ensure_user(update: Update) -> dict:
    user = update.effective_user
    return await database.upsert_user(user.id, user.username, user.first_name)


async def reply(update: Update, text: str, **kwargs):
    msg = update.effective_message
    if msg is None:
        return None
    kwargs.setdefault("parse_mode", ParseMode.HTML)
    try:
        return await msg.reply_text(text[:4000], **kwargs)
    except BadRequest:
        return await msg.reply_text(re.sub(r"<[^>]+>", "", text)[:4000])


async def seed_all() -> None:
    await database.upsert_exams(EXAMS)
    rows = []
    for item in SEED_MCQS:
        row = dict(item)
        row["question_hash"] = mcq_engine.question_hash(row["question"])
        rows.append(row)
    added = await database.upsert_mcqs(rows)
    exams = await database.all_active_exams()
    by_slug = {e["slug"]: e["id"] for e in exams}
    for portal in PORTALS:
        exam_id = by_slug.get(portal["exam_slug"]) if portal.get("exam_slug") else None
        await database.add_watch_url(portal["url"], exam_id=exam_id, note=portal["note"])
    logger.info("Seed ready. New MCQs inserted: %s", added)


async def post_init(app: Application) -> None:
    await database.init_db()
    await seed_all()
    jq = app.job_queue
    if jq is None:
        logger.error("JobQueue missing. Install python-telegram-bot[job-queue]")
    else:
        from datetime import time
        from zoneinfo import ZoneInfo

        ist = ZoneInfo(config.TIMEZONE)
        jq.run_repeating(job_minute, interval=60, first=20, name="minute")
        jq.run_daily(job_discover, time=time(6, 5, tzinfo=ist), name="discover")
        jq.run_daily(job_health, time=time(5, 10, tzinfo=ist), name="health")
        jq.run_once(job_discover, when=45, name="discover-soon")
    await app.bot.set_my_commands(COMMANDS)
    me = await app.bot.get_me()
    logger.info("राज परीक्षा गुरु चालू @%s", me.username)


async def split_exam(tokens: list[str]):
    if not tokens:
        return None, [], []
    for i in range(len(tokens), 0, -1):
        exam, _suggestions = await database.resolve_exam_query(" ".join(tokens[:i]))
        if exam:
            return exam, tokens[i:], []
    _none, suggestions = await database.resolve_exam_query(" ".join(tokens))
    return None, tokens, suggestions


async def show_exam(update: Update, exam: dict, user: dict, edit=False):
    syllabus_n = await database.count_pdfs(exam["id"], "syllabus")
    paper_n = await database.count_pdfs(exam["id"], "paper")
    sub = await database.get_sub(user["id"], exam["id"])
    text = ui.exam_card(exam, syllabus_n, paper_n, bool(sub and sub["notify_updates"]))
    markup = ui.exam_keyboard(exam, bool(sub and sub["notify_updates"]))
    if edit and update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
            return
        except BadRequest:
            pass
    await reply(update, text, reply_markup=markup)


async def show_exam_list(update: Update, page: int = 0, edit=False):
    exams = await database.all_active_exams()
    total = len(exams)
    chunk = exams[page * ui.PAGE : (page + 1) * ui.PAGE]
    text = f"<b>राजस्थान की परीक्षाएँ</b> — {total}\nपेज {page + 1}. नाम चुनें या /search लिखें।"
    markup = ui.exams_keyboard(chunk, page, total)
    if edit and update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
            return
        except BadRequest:
            pass
    await reply(update, text, reply_markup=markup)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    context.user_data.clear()
    name = update.effective_user.first_name or "अभ्यर्थी"
    await reply(update, ui.welcome(name), reply_markup=ui.reply_menu())
    await reply(update, "नीचे से शुरू करें।", reply_markup=ui.main_inline())
    if is_admin(user["telegram_id"]):
        await reply(update, "आप एडमिन हैं। पैनल: /admin")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update)
    await reply(update, ui.help_text(), reply_markup=ui.main_inline())


async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update)
    uid = update.effective_user.id
    extra = "\nयह ID .env की ADMIN_IDS में डालें, फिर बॉट दोबारा चलाएँ।" if not is_admin(uid) else "\nआप एडमिन हैं।"
    await reply(update, f"आपकी Telegram ID: <code>{uid}</code>{extra}")


async def cmd_exams(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update)
    await show_exam_list(update, 0)


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update)
    q = " ".join(context.args).strip()
    if not q:
        await reply(update, "उपयोग: /search पटवारी")
        return
    exam, suggestions = await database.resolve_exam_query(q)
    if exam:
        await show_exam(update, exam, await ensure_user(update))
        return
    if not suggestions:
        await reply(update, "कोई परीक्षा नहीं मिली। जोड़ने के लिए लिखें: <code>add exam: नाम</code>")
        return
    await reply(update, "ये मिलती-जुलती परीक्षाएँ हैं। एक चुनें:", reply_markup=ui.suggestions_keyboard(suggestions))


async def need_exam(update, tokens):
    exam, rest, suggestions = await split_exam(tokens)
    if exam:
        return exam, rest
    if suggestions:
        await reply(update, "कौन सी परीक्षा? एक चुनें या नाम साफ़ लिखें।", reply_markup=ui.suggestions_keyboard(suggestions))
    else:
        await reply(update, "परीक्षा का नाम लिखें। सूची: /exams\nउदाहरण: /syllabus patwari")
    return None, rest


async def cmd_syllabus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    if not context.args:
        await reply(update, "किस परीक्षा का सिलेबस? /exams से चुनें या लिखें: /syllabus patwari")
        await show_exam_list(update, 0)
        return
    exam, _rest = await need_exam(update, context.args)
    if not exam:
        return
    await send_kind(update, exam, "syllabus", user)


async def cmd_papers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update)
    if not context.args:
        await reply(update, "किस परीक्षा के पेपर? उदाहरण: /papers patwari")
        await show_exam_list(update, 0)
        return
    exam, _rest = await need_exam(update, context.args)
    if not exam:
        return
    await send_papers_page(update, exam, 0)


async def send_kind(update: Update, exam: dict, kind: str, user: dict):
    pdfs = [p for p in await database.list_pdfs(exam["id"], kind) if p.get("is_official")]
    if not pdfs:
        await reply(
            update,
            f"<b>{escape(exam['name_hi'])}</b> का आधिकारिक {config.KIND_HI.get(kind, kind)} अभी डेटाबेस में नहीं है।\n"
            f"आधिकारिक पेज: {escape(exam.get('official_url') or '—')}\n"
            "बॉट हर सुबह सरकारी साइट जाँचता है। कई पोर्टल JavaScript से चलते हैं, इसलिए एडमिन सीधे PDF लिंक भी जोड़ सकता है।\n"
            "गलत PDF से बचने के लिए /verify इस्तेमाल करें।",
        )
        return
    await reply(update, f"<b>{escape(exam['name_hi'])}</b> — {config.KIND_HI.get(kind, kind)} ({len(pdfs)})")
    for pdf in pdfs[:6]:
        await deliver_pdf(update.effective_chat.id, pdf, exam, update.get_bot())


async def send_papers_page(update: Update, exam: dict, page: int, edit=False):
    pdfs = [p for p in await database.list_pdfs(exam["id"]) if p.get("is_official") and p["kind"] in {"paper", "answer_key"}]
    if not pdfs:
        await reply(
            update,
            f"<b>{escape(exam['name_hi'])}</b> के आधिकारिक पुराने पेपर अभी जुड़े नहीं हैं।\n"
            f"साइट: {escape(exam.get('official_url') or '—')}\n"
            "पेपर तभी जुड़ता है जब सरकारी डोमेन पर सार्वजनिक PDF मिले। लीक पेपर नहीं जोड़े जाते।",
        )
        return
    chunk = pdfs[page * 5 : (page + 1) * 5]
    lines = [f"<b>{escape(exam['name_hi'])}</b> — पेपर / उत्तर कुंजी", f"कुल {len(pdfs)}. बटन से डाउनलोड करें।"]
    for pdf in chunk:
        year = pdf.get("year") or "—"
        shift = pdf.get("shift") or "—"
        lines.append(f"• {config.KIND_HI.get(pdf['kind'], pdf['kind'])} | {year} | शिफ्ट {shift} | {escape(pdf.get('version_label') or '')}")
    text = "\n".join(lines)
    markup = ui.papers_keyboard(exam["id"], chunk, page, len(pdfs))
    if edit and update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
            return
        except BadRequest:
            pass
    await reply(update, text, reply_markup=markup)


async def deliver_pdf(chat_id: int, pdf: dict, exam: dict | None, bot):
    caption = ui.pdf_caption(pdf, exam)
    try:
        if pdf.get("telegram_file_id"):
            await bot.send_document(chat_id, pdf["telegram_file_id"], caption=caption)
            return
        path = pdf.get("local_path")
        if path and Path(path).exists() and Path(path).stat().st_size < 49 * 1024 * 1024:
            with open(path, "rb") as handle:
                msg = await bot.send_document(chat_id, document=handle, filename=pdf["file_name"], caption=caption)
            if msg.document:
                await database.set_telegram_file_id(pdf["id"], msg.document.file_id)
            return
    except Exception:
        logger.exception("pdf send failed")
    await bot.send_message(chat_id, caption + "\n\nफ़ाइल यहीं से खोलें (आधिकारिक लिंक)।")


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    daily = "daily" in [a.lower() for a in context.args]
    tokens = [a for a in context.args if a.lower() != "daily"]
    exam, _rest = await need_exam(update, tokens)
    if not exam:
        return
    await database.subscribe(user["id"], exam["id"], daily=daily)
    extra = " रोज़ का अभ्यास भी चालू है।" if daily else " रोज़ अभ्यास के लिए: /daily on " + exam["slug"] + " 07:00"
    await reply(update, f"🔔 {escape(exam['name_hi'])} की सूचना चालू।{escape(extra)}")


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    exam, _rest = await need_exam(update, context.args)
    if not exam:
        return
    ok = await database.unsubscribe(user["id"], exam["id"])
    await reply(update, "हटा दिया।" if ok else "यह परीक्षा सब्सक्राइब नहीं थी।")


async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    args = list(context.args)
    if not args:
        await reply(update, "उपयोग:\n/daily on patwari 07:00 5\n/daily off patwari")
        return
    action = args[0].lower()
    rest = args[1:]
    count = config.DAILY_MCQ_COUNT
    hhmm = "07:00"
    kept = []
    for token in rest:
        if re.fullmatch(r"\d{1,2}:\d{2}", token):
            hhmm = token
        elif token.isdigit() and int(token) in {5, 10, 20}:
            count = int(token)
        else:
            kept.append(token)
    exam, _r = await need_exam(update, kept)
    if not exam:
        return
    enabled = action not in {"off", "band", "बंद"}
    subject_code = (exam.get("subjects") or [["gk"]])[0][0]
    topic = mcq_engine.topic_from_code(subject_code)
    await database.set_daily(user["id"], exam["id"], enabled, hhmm, topic, "medium", count)
    if enabled:
        await reply(update, f"हर दिन {hhmm} IST पर {escape(exam['name_hi'])} का {count} प्रश्नों का नया सेट आएगा।")
    else:
        await reply(update, "रोज़ का अभ्यास बंद कर दिया। अपडेट सूचना अलग से चालू रह सकती है।")


async def cmd_mcq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    if not context.args:
        await reply(update, "उदाहरण: /mcq patwari rajasthan gk medium\nया परीक्षा चुनें।")
        await show_exam_list(update, 0)
        return
    exam, rest = await split_exam(context.args)
    if not exam:
        await reply(update, "परीक्षा नहीं पहचानी। /exams देखें।")
        return
    difficulty = "medium"
    topic_tokens = []
    for token in rest:
        parsed = mcq_engine.parse_difficulty(token)
        if parsed:
            difficulty = parsed
        else:
            topic_tokens.append(token)
    if not topic_tokens:
        await reply(update, f"<b>{escape(exam['name_hi'])}</b> — विषय चुनें।", reply_markup=ui.subject_keyboard(exam, "m"))
        return
    topic = " ".join(topic_tokens)
    await send_one_mcq(update, user, exam, topic, difficulty)


async def send_one_mcq(update: Update, user: dict, exam: dict, topic: str, difficulty: str):
    await update.effective_chat.send_action(ChatAction.TYPING)
    items = await mcq_engine.next_questions(user["id"], exam, topic, difficulty, 1, allow_ai=True)
    if not items:
        await reply(
            update,
            "इस विषय के नए प्रश्न अभी नहीं बने।\n"
            "• AI कुंजी सेट करें ताकि हर बार नए MCQ बनें\n"
            "• या दूसरा विषय / कठिनाई चुनें\n"
            "दोहराव रोकने के लिए पुराने प्रश्न दोबारा नहीं दिखाए जाते।",
        )
        return
    item = items[0]
    msg = update.effective_message
    q = item["question"]
    options = [str(o)[:100] for o in item["options"]]
    if len(q) <= 280 and all(len(o) <= 100 for o in options):
        poll = await msg.reply_poll(
            question=q[:300],
            options=options,
            type="quiz",
            correct_option_id=item["answer_index"],
            explanation=(item.get("explanation") or "व्याख्या उपलब्ध")[:200],
            is_anonymous=False,
        )
        await database.save_poll(
            {
                "poll_id": poll.poll.id,
                "user_id": user["id"],
                "telegram_id": user["telegram_id"],
                "question_hash": item["question_hash"],
                "question": q,
                "explanation": item.get("explanation") or "",
                "correct_index": item["answer_index"],
                "exam_id": exam["id"],
            }
        )
        return
    await reply(update, mcq_engine.format_question(item) + "\n\n" + mcq_engine.format_reveal(item, None).replace("आपका विकल्प: —\n", ""))


async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    if not context.args:
        await reply(update, "उदाहरण: /quiz patwari gk medium 10")
        await show_exam_list(update, 0)
        return
    exam, rest = await split_exam(context.args)
    if not exam:
        await reply(update, "परीक्षा नहीं पहचानी।")
        return
    difficulty = "medium"
    count = 10
    topic_tokens = []
    for token in rest:
        parsed = mcq_engine.parse_difficulty(token)
        if parsed:
            difficulty = parsed
        elif token.isdigit() and int(token) in {5, 10, 20}:
            count = int(token)
        else:
            topic_tokens.append(token)
    if not topic_tokens:
        await reply(update, "विषय चुनें, फिर 10 या 20 प्रश्न।", reply_markup=ui.subject_keyboard(exam, "q"))
        return
    topic = mcq_engine.topic_from_code(topic_tokens[0]) if len(topic_tokens) == 1 else " ".join(topic_tokens)
    await begin_quiz(update, context, user, exam, topic, difficulty, count)


async def begin_quiz(update, context, user, exam, topic, difficulty, count):
    chat_id = update.effective_chat.id
    await update.effective_chat.send_action(ChatAction.TYPING)
    session = await mcq_engine.start_quiz(user["id"], exam, topic, difficulty, count, chat_id)
    if not session:
        await reply(update, "अभी इतने नए प्रश्न नहीं हैं। AI कुंजी जोड़ें या दूसरा विषय चुनें।")
        return
    await reply(update, f"⏱ क्विज़ शुरू — {escape(exam['name_hi'])} — {session['total']} प्रश्न। अंत में स्कोर और गलत उत्तरों की व्याख्या मिलेगी।")
    await send_quiz_question(context.bot, chat_id, session, user["id"], context.job_queue)


async def send_quiz_question(bot, chat_id: int, quiz: dict, user_db_id: int, job_queue):
    idx = quiz["current_index"]
    questions = quiz["questions"]
    if idx >= len(questions):
        return
    q = questions[idx]
    text = mcq_engine.format_question({**q, "difficulty": quiz["difficulty"]}, idx + 1, quiz["total"])
    text += f"\n\n⏱ {quiz['seconds_per_q']} सेकंड। A/B/C/D चुनें।"
    await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=ui.quiz_answer_keyboard(quiz["id"], idx))
    if job_queue:
        name = f"quiz-{quiz['id']}-{idx}"
        for job in job_queue.get_jobs_by_name(name):
            job.schedule_removal()
        job_queue.run_once(
            quiz_timeout_job,
            when=quiz["seconds_per_q"],
            data={"session_id": quiz["id"], "q_index": idx, "chat_id": chat_id, "user_db_id": user_db_id},
            name=name,
            chat_id=chat_id,
        )


async def quiz_timeout_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    result = await database.apply_quiz_answer(data["session_id"], data["user_db_id"], data["q_index"], None, True)
    if result.get("state") == "ignored":
        return
    quiz = result["quiz"]
    if result["state"] == "done":
        exam = await database.get_exam(quiz["exam_id"]) if quiz.get("exam_id") else None
        await context.bot.send_message(data["chat_id"], mcq_engine.quiz_summary(quiz, exam["name_hi"] if exam else ""))
        return
    await context.bot.send_message(data["chat_id"], "⏱ समय समाप्त। अगला प्रश्न:")
    await send_quiz_question(context.bot, data["chat_id"], quiz, data["user_db_id"], context.job_queue)


async def cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    args = list(context.args)
    if not args:
        await reply(
            update,
            "उदाहरण:\n"
            "/remind patwari 06-12-2026\n"
            "/remind admit patwari 01-11-2026\n"
            "/remind result patwari 20-01-2027\n"
            "/remind study 07:00\n"
            "तिथि dd-mm-yyyy या '6 दिसंबर 2026'।",
        )
        return
    kind = reminders.kind_from_token(args[0]) or "exam"
    rest = args[1:] if kind != "exam" or reminders.kind_from_token(args[0]) else args
    if reminders.kind_from_token(args[0]) is None:
        kind = "exam"
        rest = args
    if kind == "study":
        hhmm = None
        for token in rest:
            hhmm = reminders.parse_time(token) or hhmm
        if not hhmm and rest:
            hhmm = reminders.parse_time(" ".join(rest))
        if not hhmm:
            context.user_data["mode"] = "study_time"
            await reply(update, "किस समय याद दिलाऊँ? उदाहरण: 07:00 या सुबह 7 बजे")
            return
        await database.add_reminder(
            {
                "user_id": user["id"],
                "kind": "study",
                "repeat": "daily",
                "local_time": hhmm,
                "message": reminders.study_message(hhmm),
            }
        )
        await reply(update, f"हर दिन {hhmm} IST पर पढ़ाई की याद आएगी।")
        return
    exam, leftover = await split_exam(rest)
    if not exam:
        context.user_data["mode"] = "remind_date"
        context.user_data["remind_kind"] = kind
        await reply(update, "पहले परीक्षा चुनें: /exams — फिर तिथि भेजें।")
        await show_exam_list(update, 0)
        return
    date_text = " ".join(leftover)
    exam_date = reminders.parse_date(date_text) if date_text else None
    if not exam_date:
        context.user_data.update({"mode": "remind_date", "exam_id": exam["id"], "remind_kind": kind})
        await reply(update, f"{escape(exam['name_hi'])} की तिथि लिखें। उदाहरण: 06-12-2026")
        return
    await create_date_reminders(update, user, exam, kind, exam_date)


async def create_date_reminders(update, user, exam, kind, exam_date: date):
    slots = reminders.exam_reminder_slots(exam_date)
    if not slots:
        await reply(update, "यह तिथि बीत चुकी है या इतनी नज़दीक है कि रिमाइंडर नहीं बन सका। आगे की तिथि दें।")
        return
    for slot in slots:
        await database.add_reminder(
            {
                "user_id": user["id"],
                "exam_id": exam["id"],
                "kind": kind,
                "repeat": "once",
                "remind_at": reminders.to_naive_utc(slot),
                "message": reminders.reminder_message(kind, exam["name_hi"], slot, exam_date),
            }
        )
    await reply(
        update,
        f"⏰ {escape(exam['name_hi'])} के {len(slots)} रिमाइंडर सेट हो गए "
        f"({exam_date.strftime('%d-%m-%Y')})।\n"
        "7 दिन, 3 दिन, 1 दिन पहले और उसी सुबह याद दिलाया जाएगा — जो समय बचे हों।",
    )


async def cmd_myreminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    rows = await database.list_user_reminders(user["id"])
    if not rows:
        await reply(update, "कोई सक्रिय रिमाइंडर नहीं। /remind से सेट करें।")
        return
    lines = ["<b>आपके रिमाइंडर</b>"]
    for row in rows[:20]:
        when = row["local_time"] or (row["remind_at"].strftime("%d-%m-%Y %H:%M UTC") if row["remind_at"] else "—")
        lines.append(f"#{row['id']} {row['kind']} {row['repeat']} — {when}\n{escape(row['message'][:80])}")
    lines.append("\nहटाने के लिए: /cancelremind 4")
    await reply(update, "\n".join(lines))


async def cmd_cancelremind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    if not context.args or not context.args[0].isdigit():
        await reply(update, "उपयोग: /cancelremind 4")
        return
    ok = await database.cancel_reminder(user["id"], int(context.args[0]))
    await reply(update, "हटा दिया।" if ok else "यह रिमाइंडर नहीं मिला।")


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    text = " ".join(context.args).strip()
    context.user_data["mode"] = "ai"
    if not text:
        await reply(update, "पूछिए। उदाहरण: राजस्थान की मृत नदी कौन सी है?\nबंद करने के लिए /cancel")
        return
    await answer_ai(update, user, text)


async def answer_ai(update, user, text: str):
    await update.effective_chat.send_action(ChatAction.TYPING)
    exam = None
    if update.effective_message and context_exam_id(update):
        exam = await database.get_exam(context_exam_id(update))
    reply_text = await ai_assistant.answer_question(user["id"], text, exam["name_hi"] if exam else None)
    await reply(update, escape(reply_text).replace("\n", "\n"))


def context_exam_id(update) -> int | None:
    # user_data is on context, not update. Caller passes via closure in on_text.
    return None


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    context.user_data.clear()
    await database.abandon_active_quizzes(user["id"])
    await reply(update, "रुक गया। मेनू के लिए /start")


async def cmd_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update)
    if not context.args:
        await reply(update, "उपयोग: /verify https://rpsc.rajasthan.gov.in/example.pdf")
        return
    url = context.args[0]
    await reply(update, "जाँच हो रही है। सरकारी साइट धीमी हो तो 20–30 सेकंड लग सकते हैं।")
    report = await pdf_updater.verify_url(url, download=False)
    known = await database.find_pdf_by_url(report.final_url or url)
    extra = "\nडेटाबेस में पहले से है।" if known else "\nडेटाबेस में अभी नहीं है।"
    await reply(update, escape(report.hindi() + extra))


async def cmd_addexam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = " ".join(context.args).strip()
    if not name:
        await reply(update, "उपयोग: /addexam परीक्षा का नाम\nया लिखें: add exam: नाम")
        return
    await cmd_addexam_text(update, context, name)


async def cmd_addexam_text(update, context, name: str):
    user = await ensure_user(update)
    name = name.strip()
    if len(name) < 3:
        await reply(update, "परीक्षा का पूरा नाम लिखें।")
        return
    await reply(update, f"‘{escape(name)}’ के आधिकारिक स्रोत खोज रहा हूँ। कोचिंग साइट नहीं जोड़ी जाएँगी।")
    found = await pdf_updater.discover_official_sources(name)
    official = found["official"]
    slug_base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "exam"
    suffix = hashlib.sha1(name.encode()).hexdigest()[:4]
    slug = f"c-{slug_base[:16]}-{suffix}"[:40]
    keywords = [name] + [t for t in re.split(r"\s+", name) if len(t) > 3]
    exam = await database.create_exam(
        {
            "slug": slug,
            "name_hi": name,
            "name_en": name,
            "category": "Custom",
            "body": "उपयोगकर्ता द्वारा जोड़ा गया — स्रोत जाँचें",
            "official_url": official[0]["url"] if official else "",
            "description_hi": "यह परीक्षा सूची में स्थायी रूप से जोड़ दी गई है। सिलेबस तभी जुड़ेगा जब आधिकारिक PDF मिले।",
            "keywords": keywords,
            "aliases": [name.lower(), slug],
            "subjects": [
                ["gk", "राजस्थान GK"],
                ["his", "इतिहास"],
                ["geo", "भूगोल"],
                ["pol", "राजव्यवस्था"],
            ],
            "added_by": user["telegram_id"],
        }
    )
    for item in official:
        await database.add_watch_url(item["url"], exam_id=exam["id"], note="custom-search")
    docs = []
    if official:
        docs = await pdf_updater.crawl_specific([i["url"] for i in official], exam["id"])
        if docs:
            await pdf_updater.notify_items(context.bot, docs)
    if official:
        lines = [f"✅ <b>{escape(name)}</b> सूची में जुड़ गई।", "आधिकारिक लिंक:"]
        for item in official[:5]:
            lines.append(f"• {escape(item['title'][:80])}\n{escape(item['url'])}")
        lines.append(f"नई PDF: {len(docs)}")
        if found["unofficial_count"]:
            lines.append(f"कोचिंग/अन्य लिंक छोड़ दिए: {found['unofficial_count']}")
        lines.append(f"अब उपयोग करें: /syllabus {exam['slug']}")
        await reply(update, "\n".join(lines))
    else:
        context.user_data.update({"mode": "custom_url", "exam_id": exam["id"]})
        await reply(
            update,
            "परीक्षा जोड़ दी गई, पर आधिकारिक लिंक नहीं मिला।\n"
            "सरकारी पेज का URL भेजें (rajasthan.gov.in या hcraj.nic.in)। "
            "DuckDuckGo कभी-कभी डेटा-सेंटर IP रोक देता है — तब URL हाथ से भेजना ही सही रास्ता है।",
        )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update)
    stats = await database.admin_stats()
    last = await database.last_run()
    last_txt = "अभी तक नहीं चली"
    if last:
        last_txt = f"{last['status']} | पेज {last['pages_checked']} | नए {last['pdfs_new']} | बंद {last['pdfs_dead']}"
    await reply(
        update,
        "📡 बॉट स्थिति\n"
        f"परीक्षाएँ: {stats['exams']}\n"
        f"सक्रिय PDF: {stats['pdfs']} | बंद लिंक: {stats['dead']}\n"
        f"अंतिम जाँच: {escape(last_txt)}\n"
        "PDF तभी आधिकारिक है जब स्रोत सरकारी डोमेन पर हो।",
    )


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await reply(update, "यह पैनल केवल एडमिन के लिए है। अपनी ID /whoami से देखें।")
        return
    await reply(
        update,
        "<b>एडमिन पैनल</b>\n"
        "/forceupdate — सरकारी साइटें अभी जाँचें\n"
        "/addpdf slug kind url [year] [shift]\n"
        "/addwatch slug url\n"
        "/broadcast संदेश\n"
        "PDF अपलोड कैप्शन:\n<code>patwari | paper | 2024 | 1 | https://...</code>\n"
        "बिना आधिकारिक URL वाली फ़ाइल उपयोगकर्ताओं को नहीं भेजी जाती।",
        reply_markup=ui.admin_keyboard(),
    )


async def cmd_forceupdate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await reply(update, "केवल एडमिन।")
        return
    await reply(update, "जाँच शुरू। सरकारी साइटों पर धीरे चलाया जाएगा, एक-दो मिनट लग सकते हैं।")
    report = await pdf_updater.run_update_cycle("discover")
    if report.new_items:
        await pdf_updater.notify_items(context.bot, report.new_items)
    await reply(update, escape(report.summary_hi()))


async def cmd_addpdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await reply(update, "केवल एडमिन।")
        return
    args = list(context.args)
    if len(args) < 3:
        await reply(update, "उपयोग: /addpdf patwari syllabus https://rpsc.rajasthan.gov.in/file.pdf 2026")
        return
    exam, _ = await database.resolve_exam_query(args[0])
    if not exam:
        await reply(update, "परीक्षा नहीं मिली।")
        return
    kind = args[1]
    url = args[2]
    year = int(args[3]) if len(args) > 3 and args[3].isdigit() else pdf_updater.extract_year(url)
    shift = args[4] if len(args) > 4 else pdf_updater.extract_shift(url)
    if kind not in config.KIND_HI:
        await reply(update, "kind इनमें से हो: syllabus, paper, answer_key, notification, calendar")
        return
    filename = pdf_updater.build_filename(exam["slug"], year, shift, kind)
    report = await pdf_updater.verify_url(url, download=config.DOWNLOAD_PDFS, dest_name=filename)
    if not (report.official and report.is_pdf):
        await reply(update, escape(report.hindi()))
        return
    saved = await database.save_pdf(
        {
            "source_url": report.final_url or url,
            "title": f"{exam['name_hi']} {kind} {year or ''}".strip(),
            "kind": kind,
            "year": year,
            "shift": shift,
            "version_label": report.last_modified or datetime.utcnow().strftime("%Y-%m-%d"),
            "file_name": filename,
            "local_path": report.local_path,
            "sha256": report.sha256,
            "file_size": report.file_size,
            "etag": report.etag,
            "is_official": True,
            "status": "active",
            "http_status": report.http_status,
            "content_type": report.content_type,
            "exam_id": exam["id"],
        }
    )
    await reply(update, f"जोड़ दिया: {escape(filename)}")
    if saved.get("created") or saved.get("changed") or saved.get("reactivated"):
        saved["exam_name"] = exam["name_hi"]
        await pdf_updater.notify_items(context.bot, [saved])


async def cmd_addwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await reply(update, "केवल एडमिन।")
        return
    if len(context.args) < 2:
        await reply(update, "उपयोग: /addwatch patwari https://rsmssb.rajasthan.gov.in/")
        return
    exam, _ = await database.resolve_exam_query(context.args[0])
    url = context.args[1]
    if not pdf_updater.is_safe_public_url(url):
        await reply(update, "केवल आधिकारिक http(s) लिंक। निजी IP या कोचिंग साइट नहीं।")
        return
    await database.add_watch_url(url, exam_id=exam["id"] if exam else None, note="admin")
    await reply(update, "वॉच-लिस्ट में जोड़ दिया। अगली जाँच में खुलेगा।")


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await reply(update, "केवल एडमिन।")
        return
    text = " ".join(context.args).strip()
    if not text:
        await reply(update, "उपयोग: /broadcast पटवारी का पेपर आ गया है")
        return
    context.user_data["broadcast"] = text
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ भेजें", callback_data="ad:yes"), InlineKeyboardButton("रद्द", callback_data="ad:no")]]
    )
    await reply(update, f"सभी उपयोगकर्ताओं को यह जाएगा:\n\n{escape(text)}", reply_markup=markup)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await reply(update, "दस्तावेज़ केवल एडमिन जोड़ सकता है, और केवल आधिकारिक स्रोत URL के साथ।")
        return
    doc = update.message.document
    filename = (doc.file_name or "").lower()
    if not filename.endswith(".pdf") and doc.mime_type != "application/pdf":
        await reply(update, "केवल PDF।")
        return
    parts = [p.strip() for p in (update.message.caption or "").split("|")]
    if len(parts) < 5 or not parts[4].startswith("http"):
        await reply(
            update,
            "कैप्शन ज़रूरी है:\n<code>patwari | paper | 2024 | 1 | https://आधिकारिक-लिंक.pdf</code>\n"
            "बिना आधिकारिक URL के फ़ाइल स्वीकार नहीं होती।",
        )
        return
    exam, _ = await database.resolve_exam_query(parts[0])
    if not exam:
        await reply(update, "परीक्षा स्लग नहीं मिला।")
        return
    kind = parts[1]
    year = int(parts[2]) if parts[2].isdigit() else None
    shift = parts[3] if parts[3] not in {"", "-"} else None
    source = parts[4]
    report = await pdf_updater.verify_url(source, download=False)
    if not (report.official and report.is_pdf):
        await reply(update, "स्रोत आधिकारिक PDF नहीं है।\n" + escape(report.hindi()))
        return
    tg_file = await doc.get_file()
    out_name = pdf_updater.build_filename(exam["slug"], year, shift, kind)
    dest = config.PDF_DIR / out_name
    await tg_file.download_to_drive(custom_path=str(dest))
    data = dest.read_bytes()[:8]
    if not pdf_updater.looks_like_pdf(data):
        dest.unlink(missing_ok=True)
        await reply(update, "भेजी गई फ़ाइल PDF नहीं है।")
        return
    import hashlib as hl

    saved = await database.save_pdf(
        {
            "source_url": report.final_url or source,
            "title": out_name,
            "kind": kind,
            "year": year,
            "shift": shift,
            "version_label": report.last_modified or datetime.utcnow().strftime("%Y-%m-%d"),
            "file_name": out_name,
            "local_path": str(dest),
            "sha256": hl.sha256(dest.read_bytes()).hexdigest(),
            "file_size": dest.stat().st_size,
            "is_official": True,
            "status": "active",
            "http_status": report.http_status,
            "exam_id": exam["id"],
        }
    )
    await reply(update, f"आधिकारिक PDF जोड़ दी: {escape(out_name)}")
    if saved.get("created") or saved.get("changed") or saved.get("reactivated"):
        await pdf_updater.notify_items(context.bot, [saved])


async def on_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    if not answer or not answer.option_ids:
        return
    record = await database.get_poll(answer.poll_id)
    if not record:
        return
    selected = answer.option_ids[0]
    correct = selected == record["correct_index"]
    await database.update_history_result(record["user_id"], record["question_hash"], correct)
    letters = ["A", "B", "C", "D"]
    head = "सही।" if correct else "यह विकल्प गलत रहा।"
    text = f"{head}\n{record['explanation'] or ''}\nसही विकल्प: {letters[record['correct_index']]}"
    try:
        await context.bot.send_message(answer.user.id, text[:1000])
    except Exception:
        logger.info("poll explanation not delivered")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if update.effective_chat and update.effective_chat.type != "private":
        return
    user = await ensure_user(update)
    text = update.message.text.strip()
    if text in MENU_TEXT:
        action = MENU_TEXT[text]
        context.args = []
        mapping = {
            "exams": cmd_exams,
            "help": cmd_help,
            "ai": cmd_ask,
            "remind": cmd_remind,
            "mcq": cmd_mcq,
            "quiz": cmd_quiz,
            "syllabus": cmd_syllabus,
            "papers": cmd_papers,
        }
        await mapping[action](update, context)
        return
    match = re.match(r"(?i)^add exam\s*:\s*(.+)$", text)
    if match:
        await cmd_addexam_text(update, context, match.group(1))
        return
    mode = context.user_data.get("mode")
    if mode == "remind_date":
        exam_date = reminders.parse_date(text)
        exam = await database.get_exam(context.user_data.get("exam_id")) if context.user_data.get("exam_id") else None
        if not exam or not exam_date:
            await reply(update, "तिथि समझ नहीं आई। उदाहरण: 06-12-2026")
            return
        context.user_data["mode"] = None
        await create_date_reminders(update, user, exam, context.user_data.get("remind_kind") or "exam", exam_date)
        return
    if mode == "study_time":
        hhmm = reminders.parse_time(text)
        if not hhmm:
            await reply(update, "समय इस रूप में लिखें: 07:00")
            return
        context.user_data["mode"] = None
        await database.add_reminder(
            {"user_id": user["id"], "kind": "study", "repeat": "daily", "local_time": hhmm, "message": reminders.study_message(hhmm)}
        )
        await reply(update, f"हर दिन {hhmm} IST पर याद आएगी।")
        return
    if mode == "custom_url":
        url = text.split()[0]
        exam = await database.get_exam(context.user_data.get("exam_id"))
        if not exam or not pdf_updater.is_safe_public_url(url):
            await reply(update, "यह आधिकारिक लिंक नहीं लगा। rajasthan.gov.in या hcraj.nic.in का पता भेजें।")
            return
        await database.add_watch_url(url, exam_id=exam["id"], note="user-supplied")
        docs = await pdf_updater.crawl_specific([url], exam["id"])
        context.user_data["mode"] = None
        await reply(update, f"लिंक जोड़ दिया। नई PDF: {len(docs)}. /syllabus {exam['slug']}")
        if docs:
            await pdf_updater.notify_items(context.bot, docs)
        return
    context.user_data["mode"] = "ai"
    await answer_ai(update, user, text)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    user = await ensure_user(update)
    data = query.data
    try:
        if data.startswith("qz:"):
            await handle_quiz_callback(query, context, user, data)
            return
        await query.answer()
        if data == "menu:home":
            await query.edit_message_text("मेनू चुनें।", reply_markup=ui.main_inline())
        elif data == "menu:help":
            await query.edit_message_text(ui.help_text(), parse_mode=ParseMode.HTML, reply_markup=ui.main_inline())
        elif data == "menu:exams":
            await show_exam_list(update, 0, edit=True)
        elif data == "menu:ai":
            context.user_data["mode"] = "ai"
            await query.message.reply_text("पूछिए। बंद करने के लिए /cancel")
        elif data == "menu:mcq":
            await query.message.reply_text("परीक्षा चुनें, फिर विषय। या लिखें: /mcq patwari gk")
            await show_exam_list(update, 0)
        elif data == "menu:quiz":
            await query.message.reply_text("क्विज़ के लिए परीक्षा चुनें। या /quiz patwari gk 10")
            await show_exam_list(update, 0)
        elif data == "menu:rem":
            await query.message.reply_text("उदाहरण: /remind patwari 06-12-2026 या /remind study 07:00")
        elif data.startswith("pg:"):
            await show_exam_list(update, int(data.split(":")[1]), edit=True)
        elif data.startswith("ex:"):
            exam = await database.get_exam(int(data.split(":")[1]))
            if exam:
                await show_exam(update, exam, user, edit=True)
        elif data.startswith("sy:"):
            exam = await database.get_exam(int(data.split(":")[1]))
            if exam:
                await send_kind(update, exam, "syllabus", user)
        elif data.startswith("pp:"):
            _, exam_id, page = data.split(":")
            exam = await database.get_exam(int(exam_id))
            if exam:
                await send_papers_page(update, exam, int(page), edit=True)
        elif data.startswith("dl:"):
            pdf = await database.get_pdf(int(data.split(":")[1]))
            if not pdf or not pdf.get("is_official") or pdf.get("status") != "active":
                await query.message.reply_text("यह PDF उपलब्ध नहीं है या आधिकारिक नहीं है।")
                return
            exam = await database.get_exam(pdf["exam_id"]) if pdf.get("exam_id") else None
            await deliver_pdf(query.message.chat_id, pdf, exam, context.bot)
        elif data.startswith("sb:"):
            exam = await database.get_exam(int(data.split(":")[1]))
            if not exam:
                return
            sub = await database.get_sub(user["id"], exam["id"])
            if sub:
                await database.unsubscribe(user["id"], exam["id"])
            else:
                await database.subscribe(user["id"], exam["id"])
            await show_exam(update, exam, user, edit=True)
        elif data.startswith("mc:"):
            exam = await database.get_exam(int(data.split(":")[1]))
            if exam:
                await query.message.reply_text("विषय चुनें:", reply_markup=ui.subject_keyboard(exam, "m"))
        elif data.startswith("qzmenu:"):
            exam = await database.get_exam(int(data.split(":")[1]))
            if exam:
                await query.message.reply_text("क्विज़ का विषय:", reply_markup=ui.subject_keyboard(exam, "q"))
        elif data.startswith("tp:"):
            _, exam_id, code, mode = data.split(":")
            await query.message.reply_text("कठिनाई चुनें:", reply_markup=ui.difficulty_keyboard(int(exam_id), code, mode))
        elif data.startswith("df:"):
            _, exam_id, code, diff, mode = data.split(":")
            exam = await database.get_exam(int(exam_id))
            if not exam:
                return
            difficulty = {"e": "easy", "m": "medium", "h": "hard"}[diff]
            topic = mcq_engine.topic_from_code(code)
            if mode == "q":
                await query.message.reply_text("कितने प्रश्न?", reply_markup=ui.quiz_count_keyboard(exam["id"], code, diff))
            else:
                await send_one_mcq(update, user, exam, topic, difficulty)
        elif data.startswith("go:"):
            _, exam_id, code, diff, count = data.split(":")
            exam = await database.get_exam(int(exam_id))
            if exam:
                difficulty = {"e": "easy", "m": "medium", "h": "hard"}[diff]
                await begin_quiz(update, context, user, exam, mcq_engine.topic_from_code(code), difficulty, int(count))
        elif data.startswith("rm:"):
            exam = await database.get_exam(int(data.split(":")[1]))
            if exam:
                context.user_data.update({"mode": "remind_date", "exam_id": exam["id"], "remind_kind": "exam"})
                await query.message.reply_text(f"{exam['name_hi']} की तिथि लिखें। उदाहरण: 06-12-2026")
        elif data == "ad:update":
            if is_admin(user["telegram_id"]):
                await cmd_forceupdate(update, context)
        elif data == "ad:stats":
            if is_admin(user["telegram_id"]):
                await cmd_status(update, context)
        elif data == "ad:inbox":
            if not is_admin(user["telegram_id"]):
                return
            inbox = await database.list_inbox()
            if not inbox:
                await query.message.reply_text("इनबॉक्स खाली है।")
            else:
                lines = ["असाइन न हुई या अस्पष्ट PDF:"]
                for pdf in inbox:
                    lines.append(f"#{pdf['id']} {pdf['kind']} {pdf['title'][:60]}\n{pdf['source_url']}")
                await query.message.reply_text("\n".join(lines)[:4000])
        elif data == "ad:yes":
            if not is_admin(user["telegram_id"]):
                return
            text = context.user_data.get("broadcast")
            if not text:
                await query.message.reply_text("कोई संदेश लंबित नहीं। /broadcast लिखें।")
                return
            ids = await database.all_telegram_ids()
            sent = 0
            for tg_id in ids:
                try:
                    await context.bot.send_message(tg_id, text)
                    sent += 1
                except Forbidden:
                    await database.set_blocked(tg_id, True)
                except Exception:
                    logger.info("broadcast skip %s", tg_id)
            context.user_data.pop("broadcast", None)
            await query.message.reply_text(f"भेज दिया: {sent}/{len(ids)}")
        elif data == "ad:no":
            context.user_data.pop("broadcast", None)
            await query.message.reply_text("ब्रॉडकास्ट रद्द।")
    except Exception:
        logger.exception("callback failed")
        try:
            await query.answer("त्रुटि हुई, फिर कोशिश करें।", show_alert=True)
        except Exception:
            pass


async def handle_quiz_callback(query, context, user, data: str):
    _qz, sid, q_index, option = data.split(":")
    if context.job_queue:
        for job in context.job_queue.get_jobs_by_name(f"quiz-{sid}-{q_index}"):
            job.schedule_removal()
    result = await database.apply_quiz_answer(int(sid), user["id"], int(q_index), int(option), False)
    if result.get("state") == "ignored":
        await query.answer("यह प्रश्न बंद हो चुका है।", show_alert=False)
        return
    await query.answer("दर्ज हो गया")
    quiz = result["quiz"]
    if result["state"] == "done":
        exam = await database.get_exam(quiz["exam_id"]) if quiz.get("exam_id") else None
        await query.message.reply_text(mcq_engine.quiz_summary(quiz, exam["name_hi"] if exam else ""))
        return
    await send_quiz_question(context.bot, query.message.chat_id, quiz, user["id"], context.job_queue)


async def job_minute(context: ContextTypes.DEFAULT_TYPE):
    now_ist = reminders.ist_now()
    now_utc = reminders.to_naive_utc(now_ist)
    for item in await database.due_once_reminders(now_utc):
        try:
            await context.bot.send_message(item["telegram_id"], item["message"])
            await database.mark_reminder_sent(item["id"], deactivate_if_once=True)
        except Forbidden:
            await database.set_blocked(item["telegram_id"], True)
        except Exception:
            logger.info("reminder send failed")
    for item in await database.due_daily_reminders(now_ist):
        try:
            await context.bot.send_message(item["telegram_id"], item["message"])
            await database.mark_reminder_sent(item["id"], deactivate_if_once=False)
        except Forbidden:
            await database.set_blocked(item["telegram_id"], True)
        except Exception:
            logger.info("daily reminder failed")
    for sub in await database.due_daily_subs(now_ist):
        try:
            session = await mcq_engine.start_quiz(
                sub["user_id"],
                sub["exam"],
                sub["daily_topic"],
                sub["daily_difficulty"],
                sub["daily_count"],
                sub["telegram_id"],
            )
            if session:
                await context.bot.send_message(
                    sub["telegram_id"],
                    f"🌅 आज का अभ्यास — {sub['exam']['name_hi']} — {session['total']} नए प्रश्न",
                )
                await send_quiz_question(context.bot, sub["telegram_id"], session, sub["user_id"], context.job_queue)
            else:
                await context.bot.send_message(
                    sub["telegram_id"],
                    "आज नया unseen MCQ नहीं बचा। AI कुंजी जोड़ें या /daily से दूसरा विषय चुनें।",
                )
        except Exception:
            logger.exception("daily mcq failed")
        await database.mark_daily_sent(sub["id"], now_ist.date().isoformat())


async def job_discover(context: ContextTypes.DEFAULT_TYPE):
    report = await pdf_updater.run_update_cycle("discover")
    logger.info(report.summary_hi())
    if report.new_items:
        await pdf_updater.notify_items(context.bot, report.new_items)


async def job_health(context: ContextTypes.DEFAULT_TYPE):
    report = await pdf_updater.run_update_cycle("health")
    logger.info("health: dead=%s changed=%s", len(report.dead), len(report.new_items))
    if report.new_items:
        await pdf_updater.notify_items(context.bot, report.new_items)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Update error: %s", context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("कुछ गड़बड़ हो गई। थोड़ी देर बाद फिर कोशिश करें।")
        except Exception:
            pass


def main() -> None:
    if sys.version_info < (3, 11):
        sys.exit("Python 3.11+ चाहिए।")
    if not config.BOT_TOKEN:
        print(
            "BOT_TOKEN खाली है।\n"
            "1) Telegram में @BotFather खोलें\n"
            "2) /newbot → नाम: राज परीक्षा गुरु\n"
            "3) token को .env में BOT_TOKEN= के आगे चिपकाएँ\n"
            "4) python bot.py"
        )
        sys.exit(1)
    application = Application.builder().token(config.BOT_TOKEN).post_init(post_init).concurrent_updates(False).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("whoami", cmd_whoami))
    application.add_handler(CommandHandler("exams", cmd_exams))
    application.add_handler(CommandHandler("search", cmd_search))
    application.add_handler(CommandHandler("syllabus", cmd_syllabus))
    application.add_handler(CommandHandler("papers", cmd_papers))
    application.add_handler(CommandHandler("subscribe", cmd_subscribe))
    application.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    application.add_handler(CommandHandler("daily", cmd_daily))
    application.add_handler(CommandHandler("mcq", cmd_mcq))
    application.add_handler(CommandHandler("quiz", cmd_quiz))
    application.add_handler(CommandHandler("remind", cmd_remind))
    application.add_handler(CommandHandler("myreminders", cmd_myreminders))
    application.add_handler(CommandHandler("cancelremind", cmd_cancelremind))
    application.add_handler(CommandHandler("ask", cmd_ask))
    application.add_handler(CommandHandler("cancel", cmd_cancel))
    application.add_handler(CommandHandler("verify", cmd_verify))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("admin", cmd_admin))
    application.add_handler(CommandHandler("forceupdate", cmd_forceupdate))
    application.add_handler(CommandHandler("addpdf", cmd_addpdf))
    application.add_handler(CommandHandler("addwatch", cmd_addwatch))
    application.add_handler(CommandHandler("broadcast", cmd_broadcast))
    application.add_handler(CommandHandler("addexam", cmd_addexam))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(PollAnswerHandler(on_poll_answer))
    application.add_handler(MessageHandler(filters.Document.ALL, on_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_error_handler(on_error)
    if config.MODE == "webhook":
        if not config.WEBHOOK_URL:
            sys.exit("MODE=webhook hai to WEBHOOK_URL bhi chahiye.")
        application.run_webhook(
            listen="0.0.0.0",
            port=config.WEBHOOK_PORT,
            url_path=config.WEBHOOK_PATH,
            webhook_url=f"{config.WEBHOOK_URL}/{config.WEBHOOK_PATH}",
        )
    else:
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=config.DROP_PENDING)


if __name__ == "__main__":
    main()
