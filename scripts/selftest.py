"""Network ke bina core logic ki jaanch. Telegram token ki zaroorat nahi."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB_PATH = ROOT / "data" / "selftest.db"
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH}"
os.environ["BOT_TOKEN"] = ""
os.environ["ADMIN_IDS"] = "42"

import config  # noqa: E402
import database  # noqa: E402
import mcq_engine  # noqa: E402
import pdf_updater  # noqa: E402
import reminders  # noqa: E402
from exams_seed import EXAMS, SEED_MCQS  # noqa: E402


def check(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise SystemExit(f"FAIL {name} {detail}")
    print(f"OK  {name}")


def test_hosts() -> None:
    check("rpsc official", pdf_updater.is_official_host("rpsc.rajasthan.gov.in"))
    check("rssb official", pdf_updater.is_official_host("rsmssb.rajasthan.gov.in"))
    check("hc official", pdf_updater.is_official_host("hcraj.nic.in"))
    check("coaching blocked", not pdf_updater.is_official_host("www.adda247.com"))
    check("private blocked", not pdf_updater.is_safe_public_url("http://127.0.0.1/syllabus.pdf"))
    check("file scheme blocked", not pdf_updater.is_safe_public_url("file:///tmp/a.pdf"))
    check("pdf magic", pdf_updater.looks_like_pdf(b"%PDF-1.7\n"))
    check("not pdf", not pdf_updater.looks_like_pdf(b"<html>"))


def test_classify() -> None:
    exams = [
        {"id": 1, "slug": "patwari", "keywords": ["patwari", "पटवारी"], "aliases": ["पटवारी", "patwari"]},
        {"id": 2, "slug": "reet-l1", "keywords": ["reet level 1", "रीट"], "aliases": ["reet"]},
    ]
    hit = pdf_updater.classify_exam("Patwari 2024 Shift 1 Question Paper", "https://rsmssb.rajasthan.gov.in/a.pdf", exams)
    check("classify patwari", hit and hit["slug"] == "patwari")
    check("year", pdf_updater.extract_year("Patwari_2024_Shift1.pdf") == 2024)
    check("shift", pdf_updater.extract_shift("Patwari 2024 Shift 1") == "1")
    check("kind paper", pdf_updater.guess_kind("question paper 2024") == "paper")
    check("kind syllabus", pdf_updater.guess_kind("scheme and syllabus") == "syllabus")
    check("kind key", pdf_updater.guess_kind("final answer key") == "answer_key")
    name = pdf_updater.build_filename("patwari", 2021, "1", "paper")
    check("filename", name == "Patwari_2021_Shift1_Paper.pdf", name)
    html = '<a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Frpsc.rajasthan.gov.in%2Fa.pdf">RAS</a>'
    results = pdf_updater.extract_ddg_results(html)
    check("ddg parse", results and results[0]["url"].startswith("https://rpsc.rajasthan.gov.in"))


def test_dates() -> None:
    check("dmy", reminders.parse_date("06-12-2026") == date(2026, 12, 6))
    check("iso", reminders.parse_date("2026-12-06") == date(2026, 12, 6))
    check("hindi month", reminders.parse_date("6 दिसंबर 2026") == date(2026, 12, 6))
    check("time", reminders.parse_time("07:00") == "07:00")
    check("subah 7", reminders.parse_time("सुबह 7 बजे") == "07:00")
    ist = ZoneInfo("Asia/Kolkata")
    now = datetime(2026, 9, 24, 12, 0, tzinfo=ist)
    slots = reminders.exam_reminder_slots(date(2026, 12, 6), now=now)
    check("future slots", len(slots) == 4, str(len(slots)))
    past = reminders.exam_reminder_slots(date(2020, 1, 1), now=now)
    check("past slots empty", past == [])


async def test_db() -> None:
    await database.init_db()
    await database.upsert_exams(EXAMS)
    exams = await database.all_active_exams()
    check("exam count", len(exams) >= 30, str(len(exams)))
    exam, suggestions = await database.resolve_exam_query("पटवारी")
    check("resolve hindi", exam and exam["slug"] == "patwari", str(suggestions[:2]))
    exam2, _ = await database.resolve_exam_query("reet level 2")
    check("resolve reet2", exam2 and exam2["slug"] == "reet-l2")
    rows = []
    for item in SEED_MCQS:
        row = dict(item)
        row["question_hash"] = mcq_engine.question_hash(row["question"])
        check("mcq shape " + row["question"][:18], mcq_engine.validate_mcq(row) and "हि" in row["question"] or any("\u0900" <= ch <= "\u097F" for ch in row["question"]))
        rows.append(row)
    added = await database.upsert_mcqs(rows)
    check("seed inserted", added == len(SEED_MCQS), str(added))
    again = await database.upsert_mcqs(rows)
    check("seed no duplicate", again == 0)
    user = await database.upsert_user(1001, "tester", "रीना")
    patwari = await database.resolve_exam_query("patwari")
    exam = patwari[0]
    first = await mcq_engine.next_questions(user["id"], exam, "rajasthan gk", "easy", 3, allow_ai=False)
    check("mcq batch", len(first) == 3, str(len(first)))
    second = await mcq_engine.next_questions(user["id"], exam, "rajasthan gk", "any", 3, allow_ai=False)
    overlap = {q["question_hash"] for q in first} & {q["question_hash"] for q in second}
    check("no repeat", not overlap, str(overlap))
    saved = await database.save_pdf(
        {
            "source_url": "https://rpsc.rajasthan.gov.in/demo-syllabus.pdf",
            "title": "RAS syllabus",
            "kind": "syllabus",
            "year": 2026,
            "file_name": "Raspre_2026_Syllabus.pdf",
            "is_official": True,
            "status": "active",
            "exam_id": (await database.resolve_exam_query("ras"))[0]["id"],
            "http_status": 200,
        }
    )
    check("pdf created", saved["created"] is True)
    listed = await database.list_pdfs(saved["exam_id"], "syllabus")
    check("pdf listed", len(listed) == 1)
    dead = await database.mark_pdf_failure(saved["source_url"], 404, "gone")
    check("dead after 404", dead and dead["status"] == "dead")
    locked = await database.acquire_lock("pdf-discover", minutes=5, owner="test")
    check("lock", locked is True)
    locked2 = await database.acquire_lock("pdf-discover", minutes=5, owner="test2")
    check("lock busy", locked2 is False)
    await database.release_lock("pdf-discover")
    sub = await database.subscribe(user["id"], exam["id"], daily=True, daily_time="00:00")
    check("subscribed", sub["notify_updates"] and sub["daily_enabled"])
    print("SAMPLE MCQ:")
    print(first[0]["question"])
    print("Answer index", first[0]["answer_index"], first[0]["options"][first[0]["answer_index"]])
    print(first[0]["explanation"])


def main() -> None:
    test_hosts()
    test_classify()
    test_dates()
    asyncio.run(test_db())
    print("ALL CHECKS PASSED")
    print("DB file", config.DATABASE_URL)


if __name__ == "__main__":
    main()
