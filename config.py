"""Runtime config. Values .env se aati hain — code me key mat likho."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=False)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PDF_DIR = DATA_DIR / "pdfs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PDF_DIR.mkdir(parents=True, exist_ok=True)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MODE = os.getenv("MODE", "polling").strip().lower()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "rajguru-webhook").strip().strip("/")
DROP_PENDING = os.getenv("DROP_PENDING", "false").lower() in {"1", "true", "yes"}


def _id_set(raw: str) -> set[int]:
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


ADMIN_IDS = _id_set(os.getenv("ADMIN_IDS", ""))


def normalize_db_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        url = f"sqlite+aiosqlite:///{DATA_DIR / 'bot.db'}"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("sqlite:///") and not url.startswith("sqlite+aiosqlite:///"):
        url = "sqlite+aiosqlite:///" + url[len("sqlite:///") :]
    if url.startswith("sqlite+aiosqlite:///") and not url.startswith("sqlite+aiosqlite:////"):
        rest = url[len("sqlite+aiosqlite:///") :]
        if rest.startswith("./"):
            rest = str((BASE_DIR / rest[2:]).resolve())
        elif not rest.startswith("/") and ":" not in rest[:3]:
            rest = str((BASE_DIR / rest).resolve())
        url = "sqlite+aiosqlite:///" + rest
    return url


DATABASE_URL = normalize_db_url(os.getenv("DATABASE_URL", ""))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "").strip()

DOWNLOAD_PDFS = os.getenv("DOWNLOAD_PDFS", "true").lower() in {"1", "true", "yes"}
MAX_PDF_MB = int(os.getenv("MAX_PDF_MB", "45"))
CRAWL_DELAY_SECONDS = float(os.getenv("CRAWL_DELAY_SECONDS", "2"))
MAX_PAGES_PER_RUN = int(os.getenv("MAX_PAGES_PER_RUN", "25"))
HEALTH_URLS_PER_RUN = int(os.getenv("HEALTH_URLS_PER_RUN", "40"))
MCQ_DAILY_LIMIT = int(os.getenv("MCQ_DAILY_LIMIT", "40"))
AI_DAILY_LIMIT = int(os.getenv("AI_DAILY_LIMIT", "40"))
QUIZ_SECONDS = int(os.getenv("QUIZ_SECONDS", "30"))
DAILY_MCQ_COUNT = int(os.getenv("DAILY_MCQ_COUNT", "5"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

USER_AGENT = "RajParikshaGuruBot/1.0 (+educational; official-sources-only; contact: admin)"
VERSION = "1.0.0"

# rajasthan.gov.in ke saare subdomain apne aap official hain.
# Inke alawa sirf ye hosts.
EXTRA_OFFICIAL_HOSTS = {
    "hcraj.nic.in",
    "www.hcraj.nic.in",
    "uniraj.ac.in",
    "www.uniraj.ac.in",
    "ncvtmis.gov.in",
    "www.ncvtmis.gov.in",
}

NOTIFY_KINDS = {"syllabus", "paper", "answer_key", "notification", "calendar"}
KIND_HI = {
    "syllabus": "सिलेबस",
    "paper": "प्रश्न पत्र",
    "answer_key": "उत्तर कुंजी",
    "notification": "विज्ञापन / अधिसूचना",
    "calendar": "परीक्षा कैलेंडर",
    "other": "अन्य दस्तावेज़",
}
