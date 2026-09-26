"""SQLite (start) / PostgreSQL (production) — saare tables aur queries.

Public functions dict return karte hain, ORM object nahi, taaki session
band hone ke baad DetachedInstanceError na aaye.
"""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    delete,
    event,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

import config

logger = logging.getLogger(__name__)
IST = ZoneInfo(config.TIMEZONE)

engine = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ist_now() -> datetime:
    return datetime.now(IST)


def ist_date_of_utc_naive(dt: datetime | None) -> date | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(IST).date()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Exam(Base):
    __tablename__ = "exams"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name_hi: Mapped[str] = mapped_column(String(200))
    name_en: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(80), index=True)
    body: Mapped[str] = mapped_column(String(200))
    official_url: Mapped[str] = mapped_column(String(500))
    description_hi: Mapped[str] = mapped_column(Text, default="")
    pattern_hi: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    subjects: Mapped[list] = mapped_column(JSON, default=list)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WatchUrl(Base):
    __tablename__ = "watch_urls"
    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id"), nullable=True, index=True)
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(400), nullable=True)


class Pdf(Base):
    __tablename__ = "pdfs"
    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True, default="other")
    title: Mapped[str] = mapped_column(String(400))
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    shift: Mapped[str | None] = mapped_column(String(40), nullable=True)
    version_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_url: Mapped[str] = mapped_column(String(1000), unique=True)
    source_page: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    local_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_name: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    etag: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(400), nullable=True)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "exam_id", name="uq_sub"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    notify_updates: Mapped[bool] = mapped_column(Boolean, default=True)
    daily_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_time: Mapped[str] = mapped_column(String(5), default="07:00")
    daily_topic: Mapped[str] = mapped_column(String(80), default="rajasthan gk")
    daily_difficulty: Mapped[str] = mapped_column(String(20), default="medium")
    daily_count: Mapped[int] = mapped_column(Integer, default=5)
    last_daily_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Mcq(Base):
    __tablename__ = "mcq_bank"
    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id"), nullable=True, index=True)
    topic: Mapped[str] = mapped_column(String(80), index=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    difficulty: Mapped[str] = mapped_column(String(20), index=True, default="medium")
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON)
    answer_index: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str] = mapped_column(Text, default="")
    question_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(20), default="seed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class McqHistory(Base):
    __tablename__ = "mcq_history"
    __table_args__ = (UniqueConstraint("user_id", "question_hash", name="uq_seen"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    exam_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    question_hash: Mapped[str] = mapped_column(String(64), index=True)
    topic: Mapped[str] = mapped_column(String(80), default="")
    difficulty: Mapped[str] = mapped_column(String(20), default="")
    was_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    shown_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    remind_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    local_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    repeat: Mapped[str] = mapped_column(String(10), default="once")
    message: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class QuizSession(Base):
    __tablename__ = "quiz_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    exam_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    topic: Mapped[str] = mapped_column(String(80), default="")
    difficulty: Mapped[str] = mapped_column(String(20), default="medium")
    total: Mapped[int] = mapped_column(Integer, default=0)
    current_index: Mapped[int] = mapped_column(Integer, default=0)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    wrong: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    seconds_per_q: Mapped[int] = mapped_column(Integer, default=30)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    answers: Mapped[list] = mapped_column(JSON, default=list)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    question_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Usage(Base):
    __tablename__ = "usage"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_usage"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[str] = mapped_column(String(10))
    mcq_generated: Mapped[int] = mapped_column(Integer, default=0)
    ai_calls: Mapped[int] = mapped_column(Integer, default=0)


class PollRecord(Base):
    __tablename__ = "polls"
    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    question_hash: Mapped[str] = mapped_column(String(64))
    question: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text, default="")
    correct_index: Mapped[int] = mapped_column(Integer)
    exam_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class UpdateRun(Base):
    __tablename__ = "update_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    pages_checked: Mapped[int] = mapped_column(Integer, default=0)
    pdfs_new: Mapped[int] = mapped_column(Integer, default=0)
    pdfs_dead: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class JobLock(Base):
    __tablename__ = "job_locks"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    until: Mapped[datetime] = mapped_column(DateTime)
    owner: Mapped[str] = mapped_column(String(80), default="")


def _engine_for(url: str):
    kwargs: dict[str, Any] = {"echo": False, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    eng = create_async_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(eng.sync_engine, "connect")
        def _fk(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    return eng


async def init_db() -> None:
    global engine, SessionLocal
    if engine is None:
        engine = _engine_for(config.DATABASE_URL)
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database ready: %s", config.DATABASE_URL.split("@")[-1])


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    if SessionLocal is None:
        await init_db()
    assert SessionLocal is not None
    session = SessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def row_exam(e: Exam) -> dict:
    return {
        "id": e.id,
        "slug": e.slug,
        "name_hi": e.name_hi,
        "name_en": e.name_en,
        "category": e.category,
        "body": e.body,
        "official_url": e.official_url,
        "description_hi": e.description_hi or "",
        "pattern_hi": e.pattern_hi or "",
        "keywords": list(e.keywords or []),
        "aliases": list(e.aliases or []),
        "subjects": list(e.subjects or []),
        "is_custom": bool(e.is_custom),
        "active": bool(e.active),
    }


def row_pdf(p: Pdf) -> dict:
    return {
        "id": p.id,
        "exam_id": p.exam_id,
        "kind": p.kind,
        "title": p.title,
        "year": p.year,
        "shift": p.shift,
        "version_label": p.version_label,
        "source_url": p.source_url,
        "source_page": p.source_page,
        "local_path": p.local_path,
        "file_name": p.file_name,
        "sha256": p.sha256,
        "file_size": p.file_size,
        "telegram_file_id": p.telegram_file_id,
        "etag": p.etag,
        "is_official": bool(p.is_official),
        "status": p.status,
        "http_status": p.http_status,
        "fail_count": p.fail_count,
        "content_type": p.content_type,
        "discovered_at": p.discovered_at,
        "verified_at": p.verified_at,
        "last_error": p.last_error,
        "notified": bool(p.notified),
    }


def row_user(u: User) -> dict:
    return {
        "id": u.id,
        "telegram_id": u.telegram_id,
        "username": u.username,
        "first_name": u.first_name,
        "blocked": bool(u.blocked),
    }


def row_sub(s: Subscription) -> dict:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "exam_id": s.exam_id,
        "notify_updates": bool(s.notify_updates),
        "daily_enabled": bool(s.daily_enabled),
        "daily_time": s.daily_time,
        "daily_topic": s.daily_topic,
        "daily_difficulty": s.daily_difficulty,
        "daily_count": s.daily_count,
        "last_daily_on": s.last_daily_on,
    }


def row_reminder(r: Reminder) -> dict:
    return {
        "id": r.id,
        "user_id": r.user_id,
        "exam_id": r.exam_id,
        "kind": r.kind,
        "remind_at": r.remind_at,
        "local_time": r.local_time,
        "repeat": r.repeat,
        "message": r.message,
        "active": bool(r.active),
        "last_sent_at": r.last_sent_at,
    }


def row_mcq(m: Mcq) -> dict:
    return {
        "id": m.id,
        "exam_id": m.exam_id,
        "topic": m.topic,
        "tags": list(m.tags or []),
        "difficulty": m.difficulty,
        "question": m.question,
        "options": list(m.options or []),
        "answer_index": m.answer_index,
        "explanation": m.explanation or "",
        "question_hash": m.question_hash,
        "source": m.source,
    }


async def upsert_user(telegram_id: int, username: str | None, first_name: str | None) -> dict:
    async with session_scope() as s:
        user = (
            await s.execute(select(User).where(User.telegram_id == telegram_id))
        ).scalar_one_or_none()
        if user is None:
            user = User(telegram_id=telegram_id, username=username, first_name=first_name)
            s.add(user)
            await s.flush()
        else:
            user.username = username
            user.first_name = first_name
            user.last_seen = utcnow()
            user.blocked = False
        return row_user(user)


async def set_blocked(telegram_id: int, blocked: bool = True) -> None:
    async with session_scope() as s:
        await s.execute(update(User).where(User.telegram_id == telegram_id).values(blocked=blocked))


async def all_active_exams() -> list[dict]:
    async with session_scope() as s:
        rows = (await s.execute(select(Exam).where(Exam.active == True).order_by(Exam.category, Exam.name_en))).scalars().all()  # noqa: E712
        return [row_exam(e) for e in rows]


async def get_exam(exam_id: int) -> dict | None:
    async with session_scope() as s:
        e = await s.get(Exam, exam_id)
        return row_exam(e) if e else None


async def get_exam_by_slug(slug: str) -> dict | None:
    async with session_scope() as s:
        e = (await s.execute(select(Exam).where(Exam.slug == slug))).scalar_one_or_none()
        return row_exam(e) if e else None


async def upsert_exams(items: list[dict]) -> int:
    count = 0
    async with session_scope() as s:
        for item in items:
            existing = (await s.execute(select(Exam).where(Exam.slug == item["slug"]))).scalar_one_or_none()
            fields = {
                "name_hi": item["name_hi"],
                "name_en": item["name_en"],
                "category": item["category"],
                "body": item["body"],
                "official_url": item["official_url"],
                "description_hi": item.get("description_hi", ""),
                "pattern_hi": item.get("pattern_hi", ""),
                "keywords": item.get("keywords", []),
                "aliases": item.get("aliases", []),
                "subjects": item.get("subjects", []),
                "updated_at": utcnow(),
            }
            if existing is None:
                s.add(Exam(slug=item["slug"], is_custom=False, active=True, **fields))
                count += 1
            elif not existing.is_custom:
                for k, v in fields.items():
                    setattr(existing, k, v)
        await s.flush()
    return count


async def create_exam(data: dict) -> dict:
    async with session_scope() as s:
        existing = (await s.execute(select(Exam).where(Exam.slug == data["slug"]))).scalar_one_or_none()
        if existing:
            if data.get("official_url") and existing.official_url != data["official_url"]:
                existing.official_url = data["official_url"]
            existing.active = True
            existing.updated_at = utcnow()
            await s.flush()
            return row_exam(existing)
        exam = Exam(
            slug=data["slug"],
            name_hi=data["name_hi"],
            name_en=data.get("name_en") or data["name_hi"],
            category=data.get("category") or "Custom",
            body=data.get("body") or "उपयोगकर्ता द्वारा जोड़ा गया",
            official_url=data.get("official_url") or "",
            description_hi=data.get("description_hi") or "",
            pattern_hi=data.get("pattern_hi") or "आधिकारिक अधिसूचना आने पर पैटर्न अपडेट होगा।",
            keywords=data.get("keywords") or [],
            aliases=data.get("aliases") or [],
            subjects=data.get("subjects") or [],
            is_custom=True,
            active=True,
            added_by=data.get("added_by"),
        )
        s.add(exam)
        await s.flush()
        return row_exam(exam)


async def add_watch_url(url: str, exam_id: int | None = None, note: str = "") -> None:
    async with session_scope() as s:
        row = (await s.execute(select(WatchUrl).where(WatchUrl.url == url))).scalar_one_or_none()
        if row is None:
            s.add(WatchUrl(url=url, exam_id=exam_id, note=note, active=True))
        else:
            row.active = True
            if exam_id and not row.exam_id:
                row.exam_id = exam_id
            if note:
                row.note = note


async def list_watch_urls(active_only: bool = True) -> list[dict]:
    async with session_scope() as s:
        stmt = select(WatchUrl)
        if active_only:
            stmt = stmt.where(WatchUrl.active == True)  # noqa: E712
        rows = (await s.execute(stmt)).scalars().all()
        return [
            {
                "id": r.id,
                "exam_id": r.exam_id,
                "url": r.url,
                "note": r.note,
                "active": r.active,
                "last_status": r.last_status,
                "last_error": r.last_error,
            }
            for r in rows
        ]


async def touch_watch(url: str, status: int | None, error: str | None) -> None:
    async with session_scope() as s:
        row = (await s.execute(select(WatchUrl).where(WatchUrl.url == url))).scalar_one_or_none()
        if row:
            row.last_checked = utcnow()
            row.last_status = status
            row.last_error = (error or "")[:400] or None
            if status == 404:
                row.active = False


async def find_pdf_by_url(url: str) -> dict | None:
    async with session_scope() as s:
        p = (await s.execute(select(Pdf).where(Pdf.source_url == url))).scalar_one_or_none()
        return row_pdf(p) if p else None


async def get_pdf(pdf_id: int) -> dict | None:
    async with session_scope() as s:
        p = await s.get(Pdf, pdf_id)
        return row_pdf(p) if p else None


async def list_pdfs(exam_id: int, kind: str | None = None, include_dead: bool = False) -> list[dict]:
    async with session_scope() as s:
        stmt = select(Pdf).where(Pdf.exam_id == exam_id)
        if kind:
            stmt = stmt.where(Pdf.kind == kind)
        if not include_dead:
            stmt = stmt.where(Pdf.status == "active")
        stmt = stmt.order_by(Pdf.year.desc(), Pdf.id.desc())
        rows = (await s.execute(stmt)).scalars().all()
        return [row_pdf(p) for p in rows]


async def count_pdfs(exam_id: int, kind: str | None = None) -> int:
    async with session_scope() as s:
        stmt = select(Pdf).where(Pdf.exam_id == exam_id, Pdf.status == "active")
        if kind:
            stmt = stmt.where(Pdf.kind == kind)
        rows = (await s.execute(stmt)).scalars().all()
        return len(rows)


async def list_inbox(limit: int = 15) -> list[dict]:
    async with session_scope() as s:
        stmt = (
            select(Pdf)
            .where((Pdf.exam_id.is_(None)) | (Pdf.kind == "other"), Pdf.status == "active")
            .order_by(Pdf.id.desc())
            .limit(limit)
        )
        rows = (await s.execute(stmt)).scalars().all()
        return [row_pdf(p) for p in rows]


async def health_candidates(limit: int) -> list[dict]:
    async with session_scope() as s:
        stmt = select(Pdf).where(Pdf.status == "active").order_by(Pdf.verified_at.asc()).limit(limit)
        rows = (await s.execute(stmt)).scalars().all()
        return [row_pdf(p) for p in rows]


async def save_pdf(data: dict) -> dict:
    """Insert or update by source_url. Returns dict with keys created/reactivated/changed."""
    async with session_scope() as s:
        row = (await s.execute(select(Pdf).where(Pdf.source_url == data["source_url"]))).scalar_one_or_none()
        created = reactivated = changed = False
        if row is None:
            row = Pdf(source_url=data["source_url"], title=data.get("title") or "PDF", file_name=data.get("file_name") or "file.pdf")
            s.add(row)
            created = True
        else:
            if row.status == "dead" and data.get("status", "active") == "active":
                reactivated = True
            if data.get("etag") and row.etag and data["etag"] != row.etag:
                changed = True
            if data.get("sha256") and row.sha256 and data["sha256"] != row.sha256:
                changed = True
        for key in (
            "exam_id",
            "kind",
            "title",
            "year",
            "shift",
            "version_label",
            "source_page",
            "local_path",
            "file_name",
            "sha256",
            "file_size",
            "etag",
            "is_official",
            "status",
            "http_status",
            "content_type",
            "last_error",
        ):
            if key in data and data[key] is not None:
                setattr(row, key, data[key])
        if data.get("status") == "active":
            row.fail_count = 0
            row.verified_at = utcnow()
            row.last_error = None
        if created or reactivated or changed:
            row.notified = False
            row.discovered_at = row.discovered_at if not created else utcnow()
        await s.flush()
        out = row_pdf(row)
        out["created"] = created
        out["reactivated"] = reactivated
        out["changed"] = changed
        return out


async def mark_pdf_failure(url: str, http_status: int | None, error: str) -> dict | None:
    async with session_scope() as s:
        row = (await s.execute(select(Pdf).where(Pdf.source_url == url))).scalar_one_or_none()
        if not row:
            return None
        row.fail_count = (row.fail_count or 0) + 1
        row.http_status = http_status
        row.last_error = (error or "")[:400]
        row.verified_at = utcnow()
        became_dead = False
        if row.fail_count >= 2 or http_status == 404:
            if row.status != "dead":
                became_dead = True
            row.status = "dead"
        out = row_pdf(row)
        out["became_dead"] = became_dead
        return out


async def set_telegram_file_id(pdf_id: int, file_id: str) -> None:
    async with session_scope() as s:
        row = await s.get(Pdf, pdf_id)
        if row:
            row.telegram_file_id = file_id


async def mark_pdfs_notified(ids: list[int]) -> None:
    if not ids:
        return
    async with session_scope() as s:
        await s.execute(update(Pdf).where(Pdf.id.in_(ids)).values(notified=True))


async def assign_pdf(pdf_id: int, exam_id: int, kind: str | None = None) -> dict | None:
    async with session_scope() as s:
        row = await s.get(Pdf, pdf_id)
        if not row:
            return None
        row.exam_id = exam_id
        if kind:
            row.kind = kind
        row.notified = False
        return row_pdf(row)


async def subscribe(user_db_id: int, exam_id: int, daily: bool = False, daily_time: str = "07:00", daily_count: int = 5) -> dict:
    async with session_scope() as s:
        row = (
            await s.execute(select(Subscription).where(Subscription.user_id == user_db_id, Subscription.exam_id == exam_id))
        ).scalar_one_or_none()
        if row is None:
            row = Subscription(user_id=user_db_id, exam_id=exam_id)
            s.add(row)
        row.notify_updates = True
        if daily:
            row.daily_enabled = True
            row.daily_time = daily_time
            row.daily_count = daily_count
        await s.flush()
        return row_sub(row)


async def unsubscribe(user_db_id: int, exam_id: int) -> bool:
    async with session_scope() as s:
        row = (
            await s.execute(select(Subscription).where(Subscription.user_id == user_db_id, Subscription.exam_id == exam_id))
        ).scalar_one_or_none()
        if not row:
            return False
        await s.delete(row)
        return True


async def get_sub(user_db_id: int, exam_id: int) -> dict | None:
    async with session_scope() as s:
        row = (
            await s.execute(select(Subscription).where(Subscription.user_id == user_db_id, Subscription.exam_id == exam_id))
        ).scalar_one_or_none()
        return row_sub(row) if row else None


async def list_user_subs(user_db_id: int) -> list[dict]:
    async with session_scope() as s:
        rows = (await s.execute(select(Subscription).where(Subscription.user_id == user_db_id))).scalars().all()
        return [row_sub(r) for r in rows]


async def set_daily(user_db_id: int, exam_id: int, enabled: bool, daily_time: str = "07:00", topic: str = "rajasthan gk", difficulty: str = "medium", count: int = 5) -> dict:
    async with session_scope() as s:
        row = (
            await s.execute(select(Subscription).where(Subscription.user_id == user_db_id, Subscription.exam_id == exam_id))
        ).scalar_one_or_none()
        if row is None:
            row = Subscription(user_id=user_db_id, exam_id=exam_id, notify_updates=True)
            s.add(row)
        row.daily_enabled = enabled
        row.daily_time = daily_time
        row.daily_topic = topic
        row.daily_difficulty = difficulty
        row.daily_count = count
        await s.flush()
        return row_sub(row)


async def subscribers_for_exam(exam_id: int) -> list[dict]:
    async with session_scope() as s:
        stmt = (
            select(Subscription, User)
            .join(User, User.id == Subscription.user_id)
            .where(Subscription.exam_id == exam_id, Subscription.notify_updates == True, User.blocked == False)  # noqa: E712
        )
        rows = (await s.execute(stmt)).all()
        out = []
        for sub, user in rows:
            item = row_sub(sub)
            item["telegram_id"] = user.telegram_id
            out.append(item)
        return out


async def due_daily_subs(now_ist: datetime, grace_min: int = 10) -> list[dict]:
    today = now_ist.date().isoformat()
    async with session_scope() as s:
        stmt = (
            select(Subscription, User, Exam)
            .join(User, User.id == Subscription.user_id)
            .join(Exam, Exam.id == Subscription.exam_id)
            .where(Subscription.daily_enabled == True, User.blocked == False)  # noqa: E712
        )
        rows = (await s.execute(stmt)).all()
        out = []
        for sub, user, exam in rows:
            if sub.last_daily_on == today:
                continue
            if not _in_window(sub.daily_time or "07:00", now_ist, grace_min):
                continue
            item = row_sub(sub)
            item["telegram_id"] = user.telegram_id
            item["exam"] = row_exam(exam)
            out.append(item)
        return out


async def mark_daily_sent(sub_id: int, day: str) -> None:
    async with session_scope() as s:
        row = await s.get(Subscription, sub_id)
        if row:
            row.last_daily_on = day


def _in_window(local_time: str, now_ist: datetime, grace_min: int) -> bool:
    try:
        hh, mm = [int(x) for x in local_time.split(":")[:2]]
    except ValueError:
        return False
    target = now_ist.replace(hour=hh, minute=mm, second=0, microsecond=0)
    delta = (now_ist - target).total_seconds()
    return 0 <= delta < grace_min * 60


async def add_reminder(data: dict) -> dict:
    async with session_scope() as s:
        row = Reminder(
            user_id=data["user_id"],
            exam_id=data.get("exam_id"),
            kind=data.get("kind") or "custom",
            remind_at=data.get("remind_at"),
            local_time=data.get("local_time"),
            repeat=data.get("repeat") or "once",
            message=data["message"],
            active=True,
        )
        s.add(row)
        await s.flush()
        return row_reminder(row)


async def list_user_reminders(user_db_id: int) -> list[dict]:
    async with session_scope() as s:
        rows = (
            await s.execute(
                select(Reminder).where(Reminder.user_id == user_db_id, Reminder.active == True).order_by(Reminder.id.desc())  # noqa: E712
            )
        ).scalars().all()
        return [row_reminder(r) for r in rows]


async def cancel_reminder(user_db_id: int, reminder_id: int) -> bool:
    async with session_scope() as s:
        row = await s.get(Reminder, reminder_id)
        if not row or row.user_id != user_db_id:
            return False
        row.active = False
        return True


async def due_once_reminders(now: datetime | None = None) -> list[dict]:
    now = now or utcnow()
    async with session_scope() as s:
        stmt = (
            select(Reminder, User)
            .join(User, User.id == Reminder.user_id)
            .where(
                Reminder.active == True,  # noqa: E712
                Reminder.repeat == "once",
                Reminder.last_sent_at.is_(None),
                Reminder.remind_at.is_not(None),
                Reminder.remind_at <= now,
                User.blocked == False,  # noqa: E712
            )
        )
        rows = (await s.execute(stmt)).all()
        out = []
        for rem, user in rows:
            item = row_reminder(rem)
            item["telegram_id"] = user.telegram_id
            out.append(item)
        return out


async def due_daily_reminders(now_ist: datetime, grace_min: int = 10) -> list[dict]:
    today = now_ist.date()
    async with session_scope() as s:
        stmt = (
            select(Reminder, User)
            .join(User, User.id == Reminder.user_id)
            .where(Reminder.active == True, Reminder.repeat == "daily", User.blocked == False)  # noqa: E712
        )
        rows = (await s.execute(stmt)).all()
        out = []
        for rem, user in rows:
            if not rem.local_time or not _in_window(rem.local_time, now_ist, grace_min):
                continue
            if ist_date_of_utc_naive(rem.last_sent_at) == today:
                continue
            item = row_reminder(rem)
            item["telegram_id"] = user.telegram_id
            out.append(item)
        return out


async def mark_reminder_sent(reminder_id: int, deactivate_if_once: bool = False) -> None:
    async with session_scope() as s:
        row = await s.get(Reminder, reminder_id)
        if not row:
            return
        row.last_sent_at = utcnow()
        if deactivate_if_once and row.repeat == "once":
            row.active = False


async def upsert_mcqs(items: list[dict]) -> int:
    added = 0
    async with session_scope() as s:
        for item in items:
            exists = (
                await s.execute(select(Mcq).where(Mcq.question_hash == item["question_hash"]))
            ).scalar_one_or_none()
            if exists:
                continue
            s.add(
                Mcq(
                    exam_id=item.get("exam_id"),
                    topic=item.get("topic") or "rajasthan gk",
                    tags=item.get("tags") or [],
                    difficulty=item.get("difficulty") or "medium",
                    question=item["question"],
                    options=item["options"],
                    answer_index=item["answer_index"],
                    explanation=item.get("explanation") or "",
                    question_hash=item["question_hash"],
                    source=item.get("source") or "seed",
                )
            )
            added += 1
        await s.flush()
    return added


async def seen_hashes(user_db_id: int) -> set[str]:
    async with session_scope() as s:
        rows = (await s.execute(select(McqHistory.question_hash).where(McqHistory.user_id == user_db_id))).all()
        return {r[0] for r in rows}


async def fetch_mcqs(topic: str | None, difficulty: str | None, limit: int = 200) -> list[dict]:
    async with session_scope() as s:
        stmt = select(Mcq)
        if difficulty and difficulty != "any":
            stmt = stmt.where(Mcq.difficulty == difficulty)
        rows = (await s.execute(stmt.limit(2000))).scalars().all()
        topic_l = (topic or "").strip().lower()
        out = []
        for m in rows:
            if topic_l:
                tags = [t.lower() for t in (m.tags or [])]
                if topic_l != m.topic.lower() and topic_l not in tags and topic_l not in m.question.lower():
                    # loose: topic token inside topic field
                    if topic_l not in (m.topic or "").lower():
                        continue
            out.append(row_mcq(m))
            if len(out) >= limit:
                break
        return out


async def record_shown(user_db_id: int, question_hash: str, exam_id: int | None, topic: str, difficulty: str, was_correct: bool | None = None) -> None:
    async with session_scope() as s:
        row = (
            await s.execute(
                select(McqHistory).where(McqHistory.user_id == user_db_id, McqHistory.question_hash == question_hash)
            )
        ).scalar_one_or_none()
        if row is None:
            s.add(
                McqHistory(
                    user_id=user_db_id,
                    exam_id=exam_id,
                    question_hash=question_hash,
                    topic=topic,
                    difficulty=difficulty,
                    was_correct=was_correct,
                )
            )
        elif was_correct is not None:
            row.was_correct = was_correct


async def update_history_result(user_db_id: int, question_hash: str, was_correct: bool) -> None:
    async with session_scope() as s:
        row = (
            await s.execute(
                select(McqHistory).where(McqHistory.user_id == user_db_id, McqHistory.question_hash == question_hash)
            )
        ).scalar_one_or_none()
        if row:
            row.was_correct = was_correct


async def search_mcq_text(query: str, limit: int = 3) -> list[dict]:
    q = query.strip().lower()
    if len(q) < 3:
        return []
    async with session_scope() as s:
        rows = (await s.execute(select(Mcq).limit(2000))).scalars().all()
        scored = []
        tokens = [t for t in q.replace("?", " ").split() if len(t) > 2]
        for m in rows:
            blob = f"{m.question} {m.explanation}".lower()
            hits = sum(1 for t in tokens if t in blob)
            if hits:
                scored.append((hits, m))
        scored.sort(key=lambda x: -x[0])
        return [row_mcq(m) for _, m in scored[:limit]]


async def abandon_active_quizzes(user_db_id: int) -> None:
    async with session_scope() as s:
        await s.execute(
            update(QuizSession)
            .where(QuizSession.user_id == user_db_id, QuizSession.status == "active")
            .values(status="abandoned")
        )


async def create_quiz(data: dict) -> dict:
    async with session_scope() as s:
        row = QuizSession(
            user_id=data["user_id"],
            exam_id=data.get("exam_id"),
            topic=data.get("topic") or "",
            difficulty=data.get("difficulty") or "medium",
            total=len(data.get("questions") or []),
            current_index=0,
            status="active",
            seconds_per_q=data.get("seconds_per_q") or config.QUIZ_SECONDS,
            questions=data.get("questions") or [],
            answers=[],
            chat_id=data.get("chat_id"),
            question_started_at=utcnow(),
        )
        s.add(row)
        await s.flush()
        return _row_quiz(row)


def _row_quiz(row: QuizSession) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "exam_id": row.exam_id,
        "topic": row.topic,
        "difficulty": row.difficulty,
        "total": row.total,
        "current_index": row.current_index,
        "correct": row.correct,
        "wrong": row.wrong,
        "skipped": row.skipped,
        "status": row.status,
        "seconds_per_q": row.seconds_per_q,
        "questions": list(row.questions or []),
        "answers": list(row.answers or []),
        "chat_id": row.chat_id,
        "started_at": row.started_at,
        "question_started_at": row.question_started_at,
    }


async def get_quiz(session_id: int) -> dict | None:
    async with session_scope() as s:
        row = await s.get(QuizSession, session_id)
        return _row_quiz(row) if row else None


async def apply_quiz_answer(session_id: int, user_db_id: int, q_index: int, selected: int | None, timed_out: bool) -> dict:
    async with session_scope() as s:
        row = await s.get(QuizSession, session_id)
        if not row or row.user_id != user_db_id or row.status != "active":
            return {"state": "ignored"}
        if row.current_index != q_index:
            return {"state": "ignored"}
        questions = list(row.questions or [])
        if q_index >= len(questions):
            row.status = "finished"
            return {"state": "done", "quiz": _row_quiz(row)}
        q = questions[q_index]
        correct_index = int(q["answer_index"])
        is_correct = selected is not None and selected == correct_index and not timed_out
        if timed_out or selected is None:
            row.skipped += 1
            result = "timeout"
        elif is_correct:
            row.correct += 1
            result = "correct"
        else:
            row.wrong += 1
            result = "wrong"
        answers = list(row.answers or [])
        answers.append(
            {
                "index": q_index,
                "selected": selected,
                "correct_index": correct_index,
                "result": result,
                "question": q.get("question"),
                "options": q.get("options"),
                "explanation": q.get("explanation"),
            }
        )
        row.answers = answers
        row.current_index = q_index + 1
        row.question_started_at = utcnow()
        finished = row.current_index >= row.total
        if finished:
            row.status = "finished"
        await s.flush()
        return {"state": "done" if finished else "next", "result": result, "quiz": _row_quiz(row)}


async def add_chat(user_db_id: int, role: str, content: str, keep: int = 12) -> None:
    content = (content or "")[:4000]
    async with session_scope() as s:
        s.add(ChatMessage(user_id=user_db_id, role=role, content=content))
        await s.flush()
        rows = (
            await s.execute(select(ChatMessage).where(ChatMessage.user_id == user_db_id).order_by(ChatMessage.id.desc()))
        ).scalars().all()
        if len(rows) > keep:
            for old in rows[keep:]:
                await s.delete(old)


async def recent_chat(user_db_id: int, limit: int = 8) -> list[dict]:
    async with session_scope() as s:
        rows = (
            await s.execute(
                select(ChatMessage).where(ChatMessage.user_id == user_db_id).order_by(ChatMessage.id.desc()).limit(limit)
            )
        ).scalars().all()
        rows = list(reversed(rows))
        return [{"role": r.role, "content": r.content} for r in rows]


async def bump_usage(user_db_id: int, mcq: int = 0, ai: int = 0) -> dict:
    day = ist_now().date().isoformat()
    async with session_scope() as s:
        row = (
            await s.execute(select(Usage).where(Usage.user_id == user_db_id, Usage.day == day))
        ).scalar_one_or_none()
        if row is None:
            row = Usage(user_id=user_db_id, day=day, mcq_generated=0, ai_calls=0)
            s.add(row)
        row.mcq_generated += mcq
        row.ai_calls += ai
        await s.flush()
        return {"mcq_generated": row.mcq_generated, "ai_calls": row.ai_calls, "day": day}


async def get_usage(user_db_id: int) -> dict:
    day = ist_now().date().isoformat()
    async with session_scope() as s:
        row = (
            await s.execute(select(Usage).where(Usage.user_id == user_db_id, Usage.day == day))
        ).scalar_one_or_none()
        if not row:
            return {"mcq_generated": 0, "ai_calls": 0, "day": day}
        return {"mcq_generated": row.mcq_generated, "ai_calls": row.ai_calls, "day": day}


async def save_poll(data: dict) -> None:
    async with session_scope() as s:
        s.add(
            PollRecord(
                poll_id=data["poll_id"],
                user_id=data["user_id"],
                telegram_id=data["telegram_id"],
                question_hash=data["question_hash"],
                question=data["question"],
                explanation=data.get("explanation") or "",
                correct_index=data["correct_index"],
                exam_id=data.get("exam_id"),
            )
        )


async def get_poll(poll_id: str) -> dict | None:
    async with session_scope() as s:
        row = (await s.execute(select(PollRecord).where(PollRecord.poll_id == poll_id))).scalar_one_or_none()
        if not row:
            return None
        return {
            "poll_id": row.poll_id,
            "user_id": row.user_id,
            "telegram_id": row.telegram_id,
            "question_hash": row.question_hash,
            "question": row.question,
            "explanation": row.explanation,
            "correct_index": row.correct_index,
            "exam_id": row.exam_id,
        }


async def acquire_lock(name: str, minutes: int = 30, owner: str = "bot") -> bool:
    async with session_scope() as s:
        row = await s.get(JobLock, name)
        now = utcnow()
        if row and row.until > now:
            return False
        if row is None:
            s.add(JobLock(name=name, until=now + timedelta(minutes=minutes), owner=owner))
        else:
            row.until = now + timedelta(minutes=minutes)
            row.owner = owner
        return True


async def release_lock(name: str) -> None:
    async with session_scope() as s:
        await s.execute(delete(JobLock).where(JobLock.name == name))


async def start_run() -> int:
    async with session_scope() as s:
        row = UpdateRun(status="running")
        s.add(row)
        await s.flush()
        return row.id


async def finish_run(run_id: int, status: str, pages: int, new: int, dead: int, error: str | None = None) -> None:
    async with session_scope() as s:
        row = await s.get(UpdateRun, run_id)
        if not row:
            return
        row.status = status
        row.finished_at = utcnow()
        row.pages_checked = pages
        row.pdfs_new = new
        row.pdfs_dead = dead
        row.error = (error or "")[:2000] or None


async def last_run() -> dict | None:
    async with session_scope() as s:
        row = (await s.execute(select(UpdateRun).order_by(UpdateRun.id.desc()).limit(1))).scalar_one_or_none()
        if not row:
            return None
        return {
            "id": row.id,
            "status": row.status,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "pages_checked": row.pages_checked,
            "pdfs_new": row.pdfs_new,
            "pdfs_dead": row.pdfs_dead,
            "error": row.error,
        }


async def admin_stats() -> dict:
    async with session_scope() as s:
        users = len((await s.execute(select(User))).scalars().all())
        exams = len((await s.execute(select(Exam).where(Exam.active == True))).scalars().all())  # noqa: E712
        pdfs = len((await s.execute(select(Pdf).where(Pdf.status == "active"))).scalars().all())
        dead = len((await s.execute(select(Pdf).where(Pdf.status == "dead"))).scalars().all())
        subs = len((await s.execute(select(Subscription))).scalars().all())
        return {"users": users, "exams": exams, "pdfs": pdfs, "dead": dead, "subs": subs}


async def all_telegram_ids() -> list[int]:
    async with session_scope() as s:
        rows = (await s.execute(select(User.telegram_id).where(User.blocked == False))).all()  # noqa: E712
        return [r[0] for r in rows]


def score_exam(exam: dict, q: str) -> int:
    q = (q or "").strip().lower()
    if not q:
        return 0
    aliases = [str(a).lower() for a in exam.get("aliases") or []]
    names = [exam["slug"].lower(), exam["name_en"].lower(), exam["name_hi"].lower(), *aliases]
    if q in names:
        return 100
    blob = " ".join(names + [str(exam.get("category", "")).lower(), str(exam.get("body", "")).lower()])
    if q in blob:
        return 80
    tokens = [t for t in re.split(r"\s+", q) if t]
    if tokens and all(t in blob for t in tokens):
        return 60 + len(tokens)
    hits = sum(1 for t in tokens if t in blob)
    return 20 + hits if hits else 0


async def resolve_exam_query(q: str) -> tuple[dict | None, list[dict]]:
    exams = await all_active_exams()
    scored = sorted(((score_exam(e, q), e) for e in exams), key=lambda x: -x[0])
    scored = [(s, e) for s, e in scored if s > 0]
    exact = [e for s, e in scored if s >= 100]
    if len(exact) == 1:
        return exact[0], []
    if len(exact) > 1:
        return None, exact
    if scored and scored[0][0] >= 80 and (len(scored) == 1 or scored[1][0] < scored[0][0]):
        return scored[0][1], []
    return None, [e for _, e in scored[:6]]


async def user_by_telegram(telegram_id: int) -> dict | None:
    async with session_scope() as s:
        user = (await s.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
        return row_user(user) if user else None


async def get_mcq_by_hash(question_hash: str) -> dict | None:
    async with session_scope() as s:
        row = (await s.execute(select(Mcq).where(Mcq.question_hash == question_hash))).scalar_one_or_none()
        return row_mcq(row) if row else None
