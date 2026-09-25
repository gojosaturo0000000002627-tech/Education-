"""Official sites se syllabus / paper links. Coaching sites kabhi official nahi manti.

Ye crawler:
- sirf allowlisted sarkari hosts
- robots.txt ka samman
- 2 second ka antar, har cycle par page limit
- login/CAPTCHA bypass nahi karta
- JS-only page par PDF na mile to saaf log karta hai
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

import config
import database

logger = logging.getLogger(__name__)

PDF_HINTS = (
    "pdf",
    "syllabus",
    "question",
    "answer",
    "notification",
    "advertisement",
    "result",
    "calendar",
    "पाठ्यक्रम",
    "प्रश्न",
    "विज्ञापन",
    "उत्तर",
)
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".css", ".js", ".svg", ".zip", ".mp4", ".mp3")


@dataclass
class VerifyReport:
    url: str
    final_url: str = ""
    ok: bool = False
    official: bool = False
    is_pdf: bool = False
    http_status: int | None = None
    content_type: str = ""
    file_size: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    sha256: str | None = None
    local_path: str | None = None
    error: str = ""

    def hindi(self) -> str:
        flag = "✅" if self.official else "❌"
        pdf_flag = "✅" if self.is_pdf else "❌"
        lines = [
            "🔎 लिंक जाँच",
            f"URL: {self.url}",
        ]
        if self.final_url and self.final_url != self.url:
            lines.append(f"अंतिम URL: {self.final_url}")
        lines.append(f"आधिकारिक डोमेन: {flag}")
        lines.append(f"HTTP: {self.http_status or '—'}")
        lines.append(f"PDF हस्ताक्षर: {pdf_flag}")
        if self.content_type:
            lines.append(f"Content-Type: {self.content_type}")
        if self.file_size:
            lines.append(f"आकार: {self.file_size / 1024:.0f} KB")
        if self.last_modified:
            lines.append(f"साइट की तिथि (Last-Modified): {self.last_modified}")
        if self.sha256:
            lines.append(f"SHA256: {self.sha256[:16]}…")
        if self.error:
            lines.append(f"नोट: {self.error}")
        if not self.official:
            lines.append("यह लिंक आधिकारिक सूची में नहीं है। बॉट इसे सिलेबस/पेपर के रूप में सेव नहीं करेगा।")
        elif self.is_pdf:
            lines.append("यह आधिकारिक PDF लगता है। एडमिन /addpdf से जोड़ सकता है, या ऑटो-अपडेटर स्वयं जोड़ देगा।")
        else:
            lines.append("डोमेन आधिकारिक है, पर फ़ाइल PDF नहीं लगी। पेज खोलकर सीधे PDF लिंक जाँचें।")
        return "\n".join(lines)


@dataclass
class UpdateReport:
    pages_checked: int = 0
    new_items: list[dict] = field(default_factory=list)
    dead: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped_lock: bool = False

    def summary_hi(self) -> str:
        if self.skipped_lock:
            return "अपडेट पहले से चल रहा है। कुछ मिनट बाद /status देखें।"
        lines = [
            "🔄 आधिकारिक साइट जाँच पूरी",
            f"पेज देखे: {self.pages_checked}",
            f"नए / बदले दस्तावेज़: {len(self.new_items)}",
            f"बंद लिंक: {len(self.dead)}",
        ]
        if self.errors:
            lines.append("कुछ पेज नहीं खुले: " + str(len(self.errors)))
            lines.append("सरकारी साइटें अक्सर JavaScript से चलती हैं। ऐसे में एडमिन सीधे PDF लिंक /addpdf से जोड़ें।")
        if not self.new_items:
            lines.append("इस चक्र में कोई नई आधिकारिक PDF नहीं मिली। यह खराबी नहीं — लिंक पेज के अंदर छिपा हो सकता है।")
        return "\n".join(lines)


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")


def is_official_host(host: str | None) -> bool:
    if not host:
        return False
    host = host.lower().rstrip(".")
    if host in config.EXTRA_OFFICIAL_HOSTS:
        return True
    if host == "rajasthan.gov.in" or host.endswith(".rajasthan.gov.in"):
        return True
    return False


def _ip_is_blocked(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return True
        for info in infos:
            addr = info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return True
        return False
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)


def is_safe_public_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.hostname
    if not host or not is_official_host(host):
        return False
    if _ip_is_blocked(host):
        return False
    return True


def looks_like_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def guess_kind(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ("answer key", "answerkey", "answer-key", "उत्तर कुंजी", "final key", "model key")):
        return "answer_key"
    if any(k in t for k in ("syllabus", "पाठ्यक्रम", "scheme and syllabus", "योजना और पाठ्यक्रम")):
        return "syllabus"
    if any(k in t for k in ("question paper", "questionpaper", "question-paper", "प्रश्न पत्र", "प्रश्न-पत्र", "old paper")):
        return "paper"
    if any(k in t for k in ("exam calendar", "परीक्षा कैलेंडर", "tentative calendar")):
        return "calendar"
    if any(k in t for k in ("notification", "advertisement", "विज्ञापन", "अधिसूचना", "recruitment")):
        return "notification"
    return "other"


def extract_year(text: str, now_year: int | None = None) -> int | None:
    now_year = now_year or datetime.now(timezone.utc).year
    years = [int(y) for y in re.findall(r"(20\d{2}|19\d{2})", text)]
    years = [y for y in years if 1990 <= y <= now_year + 1]
    if not years:
        return None
    return max(years)


def extract_shift(text: str) -> str | None:
    m = re.search(r"(?:shift|शिफ्ट)\s*[-:]?\s*(\d+)", text, flags=re.I)
    if m:
        return m.group(1)
    return None


def keyword_hit(text: str, keyword: str) -> bool:
    kw = keyword.lower().strip()
    if not kw:
        return False
    if len(kw) <= 3:
        return re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", text, flags=re.I) is not None
    return kw in text


def classify_exam(title: str, url: str, exams: list[dict]) -> dict | None:
    blob = f"{title} {url}".lower()
    best = None
    best_score = 0
    for exam in exams:
        score = 0
        for kw in exam.get("keywords") or []:
            if keyword_hit(blob, kw):
                score += max(len(kw), 4)
        for alias in exam.get("aliases") or []:
            if len(alias) >= 4 and keyword_hit(blob, alias):
                score += 3
        if score > best_score:
            best, best_score = exam, score
    if best_score < 6:
        return None
    return best


def build_filename(exam_slug: str, year: int | None, shift: str | None, kind: str) -> str:
    slug = "".join(ch for ch in exam_slug.title() if ch.isalnum()) or "Exam"
    year_part = str(year) if year else "Undated"
    shift_part = f"_Shift{shift}" if shift else ""
    kind_part = {
        "syllabus": "Syllabus",
        "paper": "Paper",
        "answer_key": "AnswerKey",
        "notification": "Notification",
        "calendar": "Calendar",
    }.get(kind, "Document")
    return f"{slug}_{year_part}{shift_part}_{kind_part}.pdf"


def extract_links(html: str, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[tuple[str, str]] = []
    seen = set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        if "uddg=" in href:
            qs = parse_qs(urlparse(href).query)
            href = unquote(qs.get("uddg", [href])[0])
        absolute = urljoin(base_url, href)
        if absolute in seen:
            continue
        seen.add(absolute)
        title = a.get_text(" ", strip=True) or Path(urlparse(absolute).path).name
        found.append((title, absolute))
    return found


def extract_ddg_results(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    anchors = soup.select("a.result__a") or soup.find_all("a")
    for a in anchors:
        href = a.get("href") or ""
        title = a.get_text(" ", strip=True)
        if "uddg=" in href:
            qs = parse_qs(urlparse(href).query)
            href = unquote(qs.get("uddg", [""])[0])
        if href.startswith("http") and title:
            out.append({"title": title, "url": href})
    # unique
    dedup = []
    seen = set()
    for item in out:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        dedup.append(item)
    return dedup


class Fetcher:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(25.0, connect=10.0),
            follow_redirects=True,
            headers={"User-Agent": config.USER_AGENT, "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.8"},
            limits=httpx.Limits(max_connections=4),
        )
        self.robots: dict[str, RobotFileParser | None] = {}
        self.last_hit = 0.0

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _pace(self) -> None:
        now = asyncio.get_event_loop().time()
        wait = config.CRAWL_DELAY_SECONDS - (now - self.last_hit)
        if wait > 0:
            await asyncio.sleep(wait)
        self.last_hit = asyncio.get_event_loop().time()

    async def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self.robots:
            rp = RobotFileParser()
            robots_url = base + "/robots.txt"
            try:
                await self._pace()
                resp = await self.client.get(robots_url)
                if resp.status_code >= 400:
                    self.robots[base] = None
                else:
                    rp.parse(resp.text.splitlines())
                    self.robots[base] = rp
            except Exception:
                self.robots[base] = None
        rp = self.robots[base]
        if rp is None:
            return True
        return rp.can_fetch(config.USER_AGENT, url)

    async def get_text(self, url: str) -> tuple[int, str, str]:
        await self._pace()
        resp = await self.client.get(url)
        final = str(resp.url)
        if not is_official_host(host_of(final)):
            raise PermissionError("redirect official host se bahar chala gaya")
        ctype = resp.headers.get("content-type", "")
        return resp.status_code, resp.text[:500_000], ctype

    async def inspect_pdf(self, url: str, download: bool, dest_name: str) -> VerifyReport:
        report = VerifyReport(url=url, official=is_safe_public_url(url))
        if not report.official:
            report.error = "डोमेन आधिकारिक सूची में नहीं है या पता असुरक्षित है।"
            return report
        if not await self.allowed(url):
            report.error = "robots.txt इस पते की स्वचालित जाँच नहीं करने देता।"
            return report
        await self._pace()
        path = config.PDF_DIR / dest_name
        handle = None
        try:
            async with self.client.stream("GET", url) as resp:
                report.http_status = resp.status_code
                report.final_url = str(resp.url)
                report.content_type = resp.headers.get("content-type", "")
                report.etag = resp.headers.get("etag")
                report.last_modified = resp.headers.get("last-modified")
                if not is_official_host(host_of(report.final_url)):
                    report.error = "रीडायरेक्ट गैर-आधिकारिक होस्ट पर गया।"
                    return report
                if resp.status_code >= 400:
                    report.error = f"HTTP {resp.status_code}"
                    return report
                pending = bytearray()
                hasher = hashlib.sha256()
                size = 0
                max_bytes = config.MAX_PDF_MB * 1024 * 1024
                too_big = False
                writing = False
                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue
                    if not writing:
                        pending.extend(chunk)
                        if len(pending) < 5:
                            continue
                        report.is_pdf = looks_like_pdf(bytes(pending[:8]))
                        if not report.is_pdf:
                            report.error = "शुरुआती बाइट्स PDF नहीं हैं।"
                            return report
                        if not download:
                            report.ok = True
                            return report
                        handle = path.open("wb")
                        writing = True
                        chunk = bytes(pending)
                    size += len(chunk)
                    if size > max_bytes:
                        too_big = True
                        break
                    hasher.update(chunk)
                    handle.write(chunk)
                if not report.is_pdf:
                    report.error = report.error or "PDF हस्ताक्षर नहीं मिला।"
                    return report
                if too_big:
                    report.ok = True
                    report.file_size = size
                    report.error = "फ़ाइल बड़ी है, केवल लिंक रखा जाएगा।"
                    return report
                report.ok = True
                report.file_size = size or None
                if download and handle:
                    report.local_path = str(path)
                    report.sha256 = hasher.hexdigest()
                return report
        except Exception as exc:
            report.error = f"{type(exc).__name__}: {exc}"[:300]
            return report
        finally:
            if handle:
                handle.close()
                if not report.local_path and path.exists():
                    path.unlink(missing_ok=True)


async def verify_url(url: str, download: bool = False, dest_name: str = "check.pdf") -> VerifyReport:
    fetcher = Fetcher()
    try:
        return await fetcher.inspect_pdf(url, download=download, dest_name=dest_name)
    finally:
        await fetcher.aclose()


async def search_web(query: str) -> list[dict]:
    if config.SERPAPI_KEY:
        url = "https://serpapi.com/search.json"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params={"q": query, "api_key": config.SERPAPI_KEY, "engine": "google", "num": 8})
            resp.raise_for_status()
            data = resp.json()
        return [{"title": i.get("title", ""), "url": i.get("link", "")} for i in data.get("organic_results", []) if i.get("link")]
    endpoint = "https://html.duckduckgo.com/html/"
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": config.USER_AGENT}) as client:
        resp = await client.post(endpoint, data={"q": query})
        if resp.status_code >= 400:
            return []
        return extract_ddg_results(resp.text)[:10]


async def discover_official_sources(exam_name: str) -> dict:
    queries = [
        f"{exam_name} syllabus site:rajasthan.gov.in",
        f"{exam_name} syllabus OR notification site:nic.in",
    ]
    official: list[dict] = []
    other = 0
    seen = set()
    for q in queries:
        try:
            results = await search_web(q)
        except Exception as exc:
            logger.info("search failed: %s", exc)
            continue
        for item in results:
            url = item.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            if is_official_host(host_of(url)):
                official.append(item)
            else:
                other += 1
        if len(official) >= 5:
            break
    return {"official": official[:6], "unofficial_count": other}


def _should_follow(url: str) -> bool:
    path = urlparse(url).path.lower()
    if any(path.endswith(ext) for ext in SKIP_EXT):
        return False
    blob = url.lower()
    return any(h in blob for h in PDF_HINTS)


async def ingest_pdf_url(
    fetcher: Fetcher,
    url: str,
    title: str,
    exams: list[dict],
    source_page: str | None = None,
    force_exam_id: int | None = None,
    download: bool | None = None,
) -> dict | None:
    if not is_safe_public_url(url):
        return None
    download = config.DOWNLOAD_PDFS if download is None else download
    kind = guess_kind(f"{title} {url}")
    exam = None
    if force_exam_id:
        exam = next((e for e in exams if e["id"] == force_exam_id), None)
    if exam is None:
        exam = classify_exam(title, url, exams)
    slug = exam["slug"] if exam else "unassigned"
    year = extract_year(f"{title} {url}")
    shift = extract_shift(f"{title} {url}")
    filename = build_filename(slug, year, shift, kind if kind != "other" else "paper")
    report = await fetcher.inspect_pdf(url, download=download, dest_name=filename)
    if report.http_status and report.http_status >= 400:
        dead = await database.mark_pdf_failure(url, report.http_status, report.error)
        return {"dead": dead} if dead and dead.get("became_dead") else None
    if not report.is_pdf:
        return None
    saved = await database.save_pdf(
        {
            "source_url": report.final_url or url,
            "source_page": source_page,
            "title": (title or filename)[:400],
            "kind": kind,
            "year": year,
            "shift": shift,
            "version_label": report.last_modified or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "file_name": filename,
            "local_path": report.local_path,
            "sha256": report.sha256,
            "file_size": report.file_size,
            "etag": report.etag,
            "is_official": True,
            "status": "active",
            "http_status": report.http_status,
            "content_type": report.content_type,
            "exam_id": exam["id"] if exam else None,
        }
    )
    saved["exam_name"] = exam["name_hi"] if exam else ""
    saved["exam_slug"] = exam["slug"] if exam else ""
    return saved


async def run_update_cycle(mode: str = "discover") -> UpdateReport:
    """mode=discover naye link dhundhta hai. mode=health purane link check karta hai."""
    report = UpdateReport()
    locked = await database.acquire_lock(f"pdf-{mode}", minutes=40, owner=mode)
    if not locked:
        report.skipped_lock = True
        return report
    run_id = await database.start_run()
    fetcher = Fetcher()
    try:
        exams = await database.all_active_exams()
        if mode == "health":
            rows = await database.health_candidates(config.HEALTH_URLS_PER_RUN)
            for row in rows:
                report.pages_checked += 1
                try:
                    checked = await fetcher.inspect_pdf(row["source_url"], download=False, dest_name="health.pdf")
                except Exception as exc:
                    report.errors.append(str(exc)[:160])
                    continue
                if not checked.ok:
                    dead = await database.mark_pdf_failure(row["source_url"], checked.http_status, checked.error or "health fail")
                    if dead and dead.get("became_dead"):
                        report.dead.append(dead)
                    continue
                saved = await database.save_pdf(
                    {
                        "source_url": row["source_url"],
                        "etag": checked.etag,
                        "version_label": checked.last_modified or row.get("version_label"),
                        "status": "active",
                        "http_status": checked.http_status,
                        "is_official": True,
                        "title": row["title"],
                        "file_name": row["file_name"],
                        "kind": row["kind"],
                        "exam_id": row["exam_id"],
                    }
                )
                if saved.get("changed") or saved.get("reactivated"):
                    saved["exam_name"] = ""
                    report.new_items.append(saved)
        else:
            watches = await database.list_watch_urls(active_only=True)
            queue: list[tuple[str, str | None, int]] = [(w["url"], w.get("exam_id"), 0) for w in watches]
            seen_pages: set[str] = set()
            while queue and report.pages_checked < config.MAX_PAGES_PER_RUN:
                url, force_exam, depth = queue.pop(0)
                if url in seen_pages or not is_safe_public_url(url):
                    continue
                seen_pages.add(url)
                if not await fetcher.allowed(url):
                    await database.touch_watch(url, None, "robots disallow")
                    report.errors.append(f"robots: {url}")
                    continue
                report.pages_checked += 1
                try:
                    status, html, ctype = await fetcher.get_text(url)
                except Exception as exc:
                    await database.touch_watch(url, None, str(exc)[:180])
                    report.errors.append(f"{url} — {type(exc).__name__}")
                    continue
                await database.touch_watch(url, status, None if status < 400 else f"HTTP {status}")
                if "pdf" in ctype.lower() or looks_like_pdf(html[:8].encode("latin1", errors="ignore")):
                    saved = await ingest_pdf_url(fetcher, url, Path(urlparse(url).path).name, exams, force_exam_id=force_exam)
                    if saved and (saved.get("created") or saved.get("changed") or saved.get("reactivated")):
                        if saved.get("kind") in config.NOTIFY_KINDS or saved.get("exam_id"):
                            report.new_items.append(saved)
                    continue
                links = extract_links(html, url)
                pdf_links = []
                html_links = []
                for title, link in links:
                    if not is_safe_public_url(link):
                        continue
                    low = link.lower()
                    if low.endswith(".pdf") or "pdf" in low:
                        pdf_links.append((title, link))
                    elif depth == 0 and _should_follow(link):
                        html_links.append((title, link))
                for title, link in pdf_links[:8]:
                    if report.pages_checked >= config.MAX_PAGES_PER_RUN:
                        break
                    report.pages_checked += 1
                    try:
                        saved = await ingest_pdf_url(
                            fetcher,
                            link,
                            title,
                            exams,
                            source_page=url,
                            force_exam_id=force_exam,
                        )
                    except Exception as exc:
                        report.errors.append(str(exc)[:160])
                        continue
                    if not saved or saved.get("dead"):
                        if saved and saved.get("dead"):
                            report.dead.append(saved["dead"])
                        continue
                    useful = saved.get("kind") in config.NOTIFY_KINDS
                    if (saved.get("created") or saved.get("changed") or saved.get("reactivated")) and useful:
                        report.new_items.append(saved)
                if depth == 0:
                    for _title, link in html_links[:4]:
                        queue.append((link, force_exam, 1))
        await database.finish_run(run_id, "ok", report.pages_checked, len(report.new_items), len(report.dead), None)
    except Exception as exc:
        logger.exception("update cycle failed")
        report.errors.append(str(exc)[:300])
        await database.finish_run(run_id, "error", report.pages_checked, len(report.new_items), len(report.dead), str(exc))
    finally:
        await fetcher.aclose()
        await database.release_lock(f"pdf-{mode}")
    return report


async def notify_items(bot, items: list[dict]) -> None:
    grouped: dict[int, list[dict]] = {}
    inbox = []
    for item in items:
        if not item.get("exam_id") or item.get("kind") not in config.NOTIFY_KINDS:
            inbox.append(item)
            continue
        grouped.setdefault(item["exam_id"], []).append(item)
    notified_ids = []
    for exam_id, docs in grouped.items():
        exam = await database.get_exam(exam_id)
        subs = await database.subscribers_for_exam(exam_id)
        if not exam or not subs:
            continue
        kind_hi = "दस्तावेज़"
        lines = [f"📢 {exam['name_hi']} का नया अपडेट जोड़ दिया गया है — नीचे से डाउनलोड करें।"]
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        buttons = []
        for doc in docs[:8]:
            label = config.KIND_HI.get(doc.get("kind"), "PDF")
            year = doc.get("year") or ""
            shift = f" शिफ्ट {doc['shift']}" if doc.get("shift") else ""
            lines.append(f"• {label} {year}{shift} — जाँच तिथि: {doc.get('version_label') or 'आज'}")
            buttons.append([InlineKeyboardButton(f"⬇️ {label} {year}{shift}".strip(), callback_data=f"dl:{doc['id']}")])
            notified_ids.append(doc["id"])
        lines.append(f"स्रोत आधिकारिक डोमेन पर जाँचा गया। सूची: /papers {exam['slug']}")
        markup = InlineKeyboardMarkup(buttons) if buttons else None
        text = "\n".join(lines)
        for sub in subs:
            try:
                await bot.send_message(chat_id=sub["telegram_id"], text=text, reply_markup=markup)
                await asyncio.sleep(0.05)
            except Exception as exc:
                logger.info("notify fail %s: %s", sub["telegram_id"], exc)
                if "Forbidden" in type(exc).__name__ or "blocked" in str(exc).lower():
                    await database.set_blocked(sub["telegram_id"], True)
    if notified_ids:
        await database.mark_pdfs_notified(notified_ids)
    if inbox and config.ADMIN_IDS:
        note = f"📥 इनबॉक्स: {len(inbox)} दस्तावेज़ किसी परीक्षा से नहीं जुड़ पाए या प्रकार अस्पष्ट है। /admin खोलें।"
        for admin_id in config.ADMIN_IDS:
            try:
                await bot.send_message(chat_id=admin_id, text=note)
            except Exception:
                logger.info("admin inbox notify failed")


async def crawl_specific(urls: list[str], force_exam_id: int) -> list[dict]:
    """Custom exam ke 2-3 official pages. Poori crawl cycle nahi chalati."""
    found: list[dict] = []
    exams = await database.all_active_exams()
    fetcher = Fetcher()
    try:
        for url in urls[:3]:
            if not is_safe_public_url(url):
                continue
            if url.lower().split("?")[0].endswith(".pdf"):
                saved = await ingest_pdf_url(fetcher, url, Path(urlparse(url).path).name, exams, force_exam_id=force_exam_id)
                if saved and (saved.get("created") or saved.get("changed") or saved.get("reactivated")):
                    found.append(saved)
                continue
            try:
                _status, html, ctype = await fetcher.get_text(url)
            except Exception as exc:
                logger.info("custom crawl page fail: %s", exc)
                continue
            if "pdf" in ctype.lower():
                saved = await ingest_pdf_url(fetcher, url, Path(urlparse(url).path).name, exams, force_exam_id=force_exam_id)
                if saved and (saved.get("created") or saved.get("changed") or saved.get("reactivated")):
                    found.append(saved)
                continue
            pdfs = [(t, link) for t, link in extract_links(html, url) if "pdf" in link.lower()]
            for title, link in pdfs[:4]:
                saved = await ingest_pdf_url(fetcher, link, title, exams, source_page=url, force_exam_id=force_exam_id)
                if saved and (saved.get("created") or saved.get("changed") or saved.get("reactivated")):
                    found.append(saved)
    finally:
        await fetcher.aclose()
    return found


async def _cli(notify: bool) -> None:
    await database.init_db()
    report = await run_update_cycle("discover")
    print(report.summary_hi())
    if notify and config.BOT_TOKEN and report.new_items:
        from telegram import Bot

        bot = Bot(config.BOT_TOKEN)
        await notify_items(bot, report.new_items)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rajasthan official PDF updater")
    parser.add_argument("--notify", action="store_true", help="Subscribers ko Telegram sandesh bhejein")
    parser.add_argument("--health", action="store_true", help="Purane links ki sehat jaanchen")
    args = parser.parse_args()
    if args.health:
        async def _health():
            await database.init_db()
            report = await run_update_cycle("health")
            print(report.summary_hi())

        asyncio.run(_health())
    else:
        asyncio.run(_cli(args.notify))
