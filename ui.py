"""Hindi text aur inline keyboards."""

from __future__ import annotations

from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

import config

PAGE = 8


def reply_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["📚 परीक्षाएँ", "📄 सिलेबस"],
            ["📝 पुराने पेपर", "❓ MCQ"],
            ["⏱ क्विज़", "🤖 AI से पूछो"],
            ["🔔 रिमाइंडर", "ℹ️ मदद"],
        ],
        resize_keyboard=True,
    )


def main_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📚 परीक्षाएँ", callback_data="menu:exams"), InlineKeyboardButton("ℹ️ मदद", callback_data="menu:help")],
            [InlineKeyboardButton("❓ MCQ", callback_data="menu:mcq"), InlineKeyboardButton("⏱ क्विज़", callback_data="menu:quiz")],
            [InlineKeyboardButton("🤖 AI से पूछो", callback_data="menu:ai"), InlineKeyboardButton("🔔 रिमाइंडर", callback_data="menu:rem")],
        ]
    )


def welcome(name: str) -> str:
    return (
        f"🙏 नमस्ते {escape(name)}!\n\n"
        "मैं <b>राज परीक्षा गुरु</b> हूँ — राजस्थान की सरकारी परीक्षाओं का साथी।\n\n"
        "मैं इनमें मदद कर सकता हूँ:\n"
        "• RPSC, RSSB, पुलिस, हाई कोर्ट, REET, BSTC, नर्सिंग और अन्य परीक्षाएँ\n"
        "• आधिकारिक सिलेबस और पुराने पेपर (केवल सरकारी स्रोत)\n"
        "• हर बार नए हिंदी MCQ और टाइमर वाला क्विज़\n"
        "• पढ़ाई के सवालों के जवाब\n"
        "• परीक्षा, एडमिट कार्ड और रोज़ की पढ़ाई के रिमाइंडर\n"
        "• नई PDF आने पर सूचना\n\n"
        "सूची में न हो तो लिखें: <code>add exam: परीक्षा का नाम</code>\n\n"
        "⚠️ तिथि, कटऑफ और परिणाम के लिए आधिकारिक वेबसाइट ही अंतिम है। "
        "AI गलती कर सकता है। लीक पेपर यहाँ नहीं मिलेंगे।\n\n"
        "नीचे मेनू चुनें या /help लिखें।"
    )


def help_text() -> str:
    return (
        "<b>आदेश</b>\n"
        "/start — मेनू\n"
        "/exams — सारी परीक्षाएँ\n"
        "/search पटवारी — खोज\n"
        "/syllabus patwari — ताज़ा सिलेबस\n"
        "/papers patwari — पुराने पेपर, वर्ष और शिफ्ट के साथ\n"
        "/mcq patwari rajasthan gk medium — नया हिंदी MCQ\n"
        "/quiz patwari gk medium 10 — 10 या 20 प्रश्नों का टेस्ट\n"
        "/subscribe patwari — अपडेट सूचना\n"
        "/unsubscribe patwari\n"
        "/daily on patwari 07:00 5 — रोज़ नया सेट\n"
        "/daily off patwari\n"
        "/remind patwari 06-12-2026 — परीक्षा रिमाइंडर\n"
        "/remind admit patwari 01-11-2026\n"
        "/remind result patwari 20-01-2027\n"
        "/remind study 07:00 — रोज़ पढ़ाई\n"
        "/myreminders — मेरी सूची\n"
        "/cancelremind 4 — रिमाइंडर हटाएँ\n"
        "/ask राजस्थान का राज्य पक्षी?\n"
        "/verify https://rpsc.rajasthan.gov.in/file.pdf\n"
        "/whoami — अपनी Telegram ID\n"
        "/cancel — रुकी हुई क्रिया बंद\n\n"
        "<b>कस्टम परीक्षा</b>\n"
        "<code>add exam: वन रक्षक विशेष भर्ती</code>\n"
        "बॉट वेब पर खोजेगा और केवल rajasthan.gov.in / hcraj.nic.in जैसे आधिकारिक लिंक जोड़ेगा।\n\n"
        "<b>PDF पर भरोसा कैसे करें</b>\n"
        "1) डोमेन सरकारी हो\n"
        "2) फ़ाइल %PDF- से शुरू हो\n"
        "3) कैप्शन में स्रोत लिंक और जाँच तिथि हो\n"
        "4) कोचिंग साइट की PDF को आधिकारिक नहीं कहा जाता\n"
        "जाँच: /verify &lt;लिंक&gt;"
    )


def exam_card(exam: dict, syllabus_n: int, paper_n: int, subscribed: bool) -> str:
    custom = " (आपके द्वारा जोड़ी गई)" if exam.get("is_custom") else ""
    return (
        f"<b>{escape(exam['name_hi'])}</b>{custom}\n"
        f"{escape(exam['name_en'])}\n"
        f"श्रेणी: {escape(exam['category'])}\n"
        f"संचालक: {escape(exam['body'])}\n"
        f"आधिकारिक साइट: {escape(exam['official_url'] or 'अभी लिंक नहीं')}\n\n"
        f"{escape(exam.get('description_hi') or '')}\n\n"
        f"<b>पैटर्न नोट</b>\n{escape(exam.get('pattern_hi') or '')}\n\n"
        f"सिलेबस PDF: {syllabus_n}  |  पेपर PDF: {paper_n}\n"
        f"सूचना: {'चालू' if subscribed else 'बंद'}\n"
        "आदेश: "
        f"/syllabus {exam['slug']}  /papers {exam['slug']}  /mcq {exam['slug']}"
    )


def exam_keyboard(exam: dict, subscribed: bool) -> InlineKeyboardMarkup:
    sub_label = "🔕 अनसब्सक्राइब" if subscribed else "🔔 सब्सक्राइब"
    url = exam.get("official_url") or ""
    rows = [
        [
            InlineKeyboardButton("📄 सिलेबस", callback_data=f"sy:{exam['id']}"),
            InlineKeyboardButton("📝 पेपर", callback_data=f"pp:{exam['id']}:0"),
        ],
        [
            InlineKeyboardButton("❓ MCQ", callback_data=f"mc:{exam['id']}"),
            InlineKeyboardButton("⏱ क्विज़", callback_data=f"qzmenu:{exam['id']}"),
        ],
        [InlineKeyboardButton(sub_label, callback_data=f"sb:{exam['id']}")],
        [InlineKeyboardButton("🔔 परीक्षा तिथि सेट करें", callback_data=f"rm:{exam['id']}")],
    ]
    if url.startswith("http"):
        rows.append([InlineKeyboardButton("🌐 आधिकारिक साइट", url=url)])
    rows.append([InlineKeyboardButton("🏠 मेनू", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


def exams_keyboard(exams: list[dict], page: int, total: int) -> InlineKeyboardMarkup:
    rows = []
    for exam in exams:
        label = exam["name_hi"][:40]
        rows.append([InlineKeyboardButton(label, callback_data=f"ex:{exam['id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ पीछे", callback_data=f"pg:{page - 1}"))
    if (page + 1) * PAGE < total:
        nav.append(InlineKeyboardButton("आगे ➡️", callback_data=f"pg:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🏠 मेनू", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


def subject_keyboard(exam: dict, mode: str) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for code, label in exam.get("subjects") or []:
        row.append(InlineKeyboardButton(label, callback_data=f"tp:{exam['id']}:{code}:{mode}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("↩️ वापस", callback_data=f"ex:{exam['id']}")])
    return InlineKeyboardMarkup(rows)


def difficulty_keyboard(exam_id: int, code: str, mode: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("आसान", callback_data=f"df:{exam_id}:{code}:e:{mode}"),
                InlineKeyboardButton("मध्यम", callback_data=f"df:{exam_id}:{code}:m:{mode}"),
                InlineKeyboardButton("कठिन", callback_data=f"df:{exam_id}:{code}:h:{mode}"),
            ],
            [InlineKeyboardButton("↩️ वापस", callback_data=f"ex:{exam_id}")],
        ]
    )


def quiz_count_keyboard(exam_id: int, code: str, diff: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("10 प्रश्न", callback_data=f"go:{exam_id}:{code}:{diff}:10"),
                InlineKeyboardButton("20 प्रश्न", callback_data=f"go:{exam_id}:{code}:{diff}:20"),
            ]
        ]
    )


def quiz_answer_keyboard(session_id: int, q_index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("A", callback_data=f"qz:{session_id}:{q_index}:0"),
                InlineKeyboardButton("B", callback_data=f"qz:{session_id}:{q_index}:1"),
            ],
            [
                InlineKeyboardButton("C", callback_data=f"qz:{session_id}:{q_index}:2"),
                InlineKeyboardButton("D", callback_data=f"qz:{session_id}:{q_index}:3"),
            ],
        ]
    )


def papers_keyboard(exam_id: int, pdfs: list[dict], page: int, total: int) -> InlineKeyboardMarkup:
    rows = []
    for pdf in pdfs:
        kind = config.KIND_HI.get(pdf["kind"], "PDF")
        year = pdf.get("year") or "वर्ष नहीं"
        shift = f" S{pdf['shift']}" if pdf.get("shift") else ""
        rows.append([InlineKeyboardButton(f"⬇️ {kind} {year}{shift}"[:40], callback_data=f"dl:{pdf['id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"pp:{exam_id}:{page - 1}"))
    if (page + 1) * 5 < total:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"pp:{exam_id}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("↩️ परीक्षा", callback_data=f"ex:{exam_id}")])
    return InlineKeyboardMarkup(rows)


def pdf_caption(pdf: dict, exam: dict | None) -> str:
    kind = config.KIND_HI.get(pdf.get("kind"), "दस्तावेज़")
    name = exam["name_hi"] if exam else "असाइन नहीं"
    year = pdf.get("year") or "अंकित नहीं"
    shift = pdf.get("shift") or "—"
    official = "आधिकारिक डोमेन ✅" if pdf.get("is_official") else "आधिकारिक नहीं ❌ — सावधानी"
    return (
        f"{name} — {kind}\n"
        f"वर्ष: {year} | शिफ्ट: {shift}\n"
        f"संस्करण/जाँच: {pdf.get('version_label') or 'तिथि नहीं'}\n"
        f"स्थिति: {official}\n"
        f"फ़ाइल: {pdf.get('file_name')}\n"
        f"स्रोत: {pdf.get('source_url')}"
    )[:1000]


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔄 अभी अपडेट चलाएँ", callback_data="ad:update")],
            [InlineKeyboardButton("📥 इनबॉक्स", callback_data="ad:inbox")],
            [InlineKeyboardButton("📊 आँकड़े", callback_data="ad:stats")],
        ]
    )


def suggestions_keyboard(exams: list[dict]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(e["name_hi"][:40], callback_data=f"ex:{e['id']}")] for e in exams[:6]]
    return InlineKeyboardMarkup(rows)
