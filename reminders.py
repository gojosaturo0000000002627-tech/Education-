"""Reminder parsing. Bhejne ka kaam bot.py ke minute-job me hai."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config

IST = ZoneInfo(config.TIMEZONE)

MONTHS = {
    "जनवरी": 1, "january": 1, "jan": 1,
    "फरवरी": 1, "फ़रवरी": 2, "february": 2, "feb": 2,
    "मार्च": 3, "march": 3, "mar": 3,
    "अप्रैल": 4, "april": 4, "apr": 4,
    "मई": 5, "may": 5,
    "जून": 6, "june": 6, "jun": 6,
    "जुलाई": 7, "july": 7, "jul": 7,
    "अगस्त": 8, "august": 8, "aug": 8,
    "सितंबर": 9, "सितम्बर": 9, "september": 9, "sep": 9, "sept": 9,
    "अक्टूबर": 10, "october": 10, "oct": 10,
    "नवंबर": 11, "नवम्बर": 11, "november": 11, "nov": 11,
    "दिसंबर": 12, "दिसम्बर": 12, "december": 12, "dec": 12,
}

# फरवरी was wrongly set to 1 above if I typo'd. Fix in parse by explicit dict.
MONTHS["फरवरी"] = 2
MONTHS["फ़रवरी"] = 2

KIND_ALIASES = {
    "exam": "exam",
    "परीक्षा": "exam",
    "date": "exam",
    "admit": "admit",
    "admitcard": "admit",
    "एडमिट": "admit",
    "result": "result",
    "परिणाम": "result",
    "study": "study",
    "padhai": "study",
    "पढ़ाई": "study",
    "padhai": "study",
}


def ist_now() -> datetime:
    return datetime.now(IST)


def to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def parse_time(text: str) -> str | None:
    raw = text.strip().lower()
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\b", raw)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{hh:02d}:{mm:02d}"
    m = re.search(r"\b(\d{1,2})\s*(baje|bje|am|pm|सुबह|शाम|am|pm)?", raw)
    if m and any(k in raw for k in ("baje", "bje", "सुबह", "शाम", "am", "pm", ":")):
        hh = int(m.group(1))
        if "pm" in raw or "शाम" in raw:
            if hh < 12:
                hh += 12
        if "am" in raw or "सुबह" in raw:
            if hh == 12:
                hh = 0
        if 0 <= hh <= 23:
            return f"{hh:02d}:00"
    return None


def parse_date(text: str, today: date | None = None) -> date | None:
    today = today or ist_now().date()
    raw = text.strip().lower()
    if raw in {"aaj", "आज", "today"}:
        return today
    if raw in {"kal", "कल", "tomorrow"}:
        return today + timedelta(days=1)
    if raw in {"parson", "परसों"}:
        return today + timedelta(days=2)

    m = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b", raw)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})\s+([^\s]+)\s+(20\d{2})\b", text.strip(), flags=re.I)
    if m:
        month = MONTHS.get(m.group(2).lower())
        if month:
            try:
                return date(int(m.group(3)), month, int(m.group(1)))
            except ValueError:
                return None
    return None


def kind_from_token(token: str) -> str | None:
    return KIND_ALIASES.get(token.strip().lower())


def exam_reminder_slots(exam_date: date, now: datetime | None = None) -> list[datetime]:
    """7, 3, 1 din pehle 08:00 IST aur usi din 06:00 IST. Jo beet chuke, unhe chhod do."""
    now = now or ist_now()
    slots = []
    plan = [(7, 8, 0), (3, 8, 0), (1, 8, 0), (0, 6, 0)]
    for days, hour, minute in plan:
        d = exam_date - timedelta(days=days)
        dt = datetime(d.year, d.month, d.day, hour, minute, tzinfo=IST)
        if dt > now:
            slots.append(dt)
    return slots


def reminder_message(kind: str, exam_name: str, when: datetime, exam_date: date) -> str:
    left = (exam_date - when.astimezone(IST).date()).days
    if kind == "admit":
        what = "एडमिट कार्ड की संभावित तिथि"
    elif kind == "result":
        what = "परिणाम की संभावित तिथि"
    else:
        what = "परीक्षा"
    if left <= 0:
        when_txt = "आज"
    elif left == 1:
        when_txt = "कल"
    else:
        when_txt = f"{left} दिन बाद"
    return (
        f"⏰ रिमाइंडर: {exam_name}\n"
        f"{what} {when_txt} है ({exam_date.strftime('%d-%m-%Y')})।\n"
        "एडमिट कार्ड और तिथि आधिकारिक साइट पर दोबारा मिला लें।\n"
        "अभ्यास: /mcq   सिलेबस: /syllabus"
    )


def study_message(hour_label: str) -> str:
    return (
        f"📚 पढ़ाई का समय हो गया ({hour_label})।\n"
        "आज का छोटा लक्ष्य: 10 MCQ या एक पुराना पेपर का एक खंड।\n"
        "/quiz से टाइमर वाला टेस्ट शुरू करें।"
    )
