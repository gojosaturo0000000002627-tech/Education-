# राज परीक्षा गुरु

**Web service build 1.1.0-web** — purani ZIP nahi. Start command neeche hai.

## Web service — build aur start

Render / Railway / Docker ke liye yahi use karo. `python bot.py` web host par mat chalao.

Build:

```bash
pip install -r requirements.txt
```

Start:

```bash
uvicorn web:app --host 0.0.0.0 --port $PORT
```

Apne computer par:

```bash
python web.py
```

Site: `http://127.0.0.1:8000`  
Health: `http://127.0.0.1:8000/api/health`  
Nayi files: `web.py`, `web/index.html`, `WEB-SERVICE.txt`

---

Rajasthan ki sarkari parikshaon ke liye Telegram bot + website. Naam suggestion: **राज परीक्षा गुरु** (`@RajParikshaGuruBot` — BotFather par availability check karein).

Dusre naam: राजस्थान एग्जाम मित्र, सिलेबस साथी.

Yeh bot taiyari ke liye hai. Leak paper, chori-chhipe question paper, ya exam ke dauran nakal ke liye nahi.

---

## 1. Architecture

```
Telegram user
    |
    v
bot.py            Hindi commands, buttons, admin, jobs
    |
    +-- database.py       users, exams, pdfs, mcq, reminders, subscriptions
    |                     SQLite abhi, PostgreSQL baad me (same code)
    +-- exams_seed.py     built-in exam list + Hindi seed MCQs
    +-- mcq_engine.py     naye MCQ, repeat-rok, quiz score
    +-- ai_assistant.py   OpenAI-compatible / Gemini / offline FAQ
    +-- pdf_updater.py    sirf sarkari domain, robots.txt, dead-link check
    +-- reminders.py      tarikh / roz ka time
    +-- ui.py             Hindi text + inline buttons
    +-- config.py         .env
```

| Module | Kaam |
| --- | --- |
| `bot.py` | /start se lekar admin broadcast tak. JobQueue (APScheduler) roz 6:05 baje sites check karta hai, har minute reminder aur daily MCQ bhejta hai. |
| `database.py` | Tables: users, exams, watch_urls, pdfs, subscriptions, mcq_bank, mcq_history, reminders, quiz_sessions, chat_messages, usage, polls, update_runs, job_locks |
| `pdf_updater.py` | Official homepage crawl (depth 1), PDF signature check, SHA256, ETag change par dubara notice. Coaching site reject. |
| `mcq_engine.py` | User ke dikhaye gaye sawaal dobara nahi. Bank khatam ho to AI se naye Hindi MCQ. |
| `ai_assistant.py` | Conversation last 8 messages. Cutoff / vacancy nahi ghadta. |
| `reminders.py` | Exam se 7, 3, 1 din pehle aur usi subah. Daily study time. |

Celery yahan nahi lagaya. Ek hi process me APScheduler (python-telegram-bot job-queue) kaafi hai. Alag cron chahiye to:

```bash
python pdf_updater.py --notify
```

Bina Redis ke Celery adhura rehta, isliye default path yahi hai.

### PDF niyam (zaroori)

Bot tabhi PDF ko **official** maanta hai jab:

1. Host `*.rajasthan.gov.in`, `hcraj.nic.in`, `uniraj.ac.in`, ya `ncvtmis.gov.in` ho.
2. Redirect bhi usi allowlist par ruke.
3. Private IP / localhost na ho.
4. File `%PDF-` se shuru ho.
5. `robots.txt` mana kare to auto-crawl ruk jaye. Login ya CAPTCHA bypass nahi hota.

RSSB/RPSC ki kai pages JavaScript se chalti hain. Crawler ko wahan PDF na mile to yeh kharabi nahi. Admin seedha official PDF URL `/addpdf` se jodta hai. Galat ya purani commercial PDF users ko "official" kehkar nahi bheji jati.

---

## 2. Code kahan hai

Poora runnable code isi folder me hai. Chat me paste karne se kat jata, isliye yahi copy-paste source hai.

| File | |
| --- | --- |
| `bot.py` | Entry point |
| `config.py` | Settings |
| `database.py` | DB |
| `pdf_updater.py` | Auto-update |
| `mcq_engine.py` | MCQ + quiz |
| `ai_assistant.py` | Sawaal-jawaab |
| `reminders.py` | Dates |
| `exams_seed.py` | Exam list + sample MCQs |
| `ui.py` | Buttons |
| `scripts/selftest.py` | Token ke bina tests |
| `.env.example` | Keys |

Built-in exams: RAS/RTS pre+mains, school/college lecturer, AEn, Statistical Officer, SI/Platoon, Patwari, LDC, VDO, CET grad + 12th, Junior Accountant, Agriculture Supervisor, Librarian, Lab Assistant, Mahila Supervisor, Constable, REET L1/L2, Grade 2, Grade 3, JEn, HC LDC/JJA/Steno, Vanrakshak, Forester, BSTC, Nursing/GNM, ANM, ITI, Anganwadi, UniRaj, Raj GK practice.

Custom: `add exam: नाम` — web search, sirf official links save, phir wahi syllabus/papers/MCQ/subscribe.

---

## 3. Setup

### 3.1 BotFather

1. Telegram me `@BotFather` kholen.
2. `/newbot`
3. Name: `राज परीक्षा गुरु`
4. Username: `RajParikshaGuruBot` (agar lena ho to koi khali username)
5. Token copy karein. Token kisi chat me forward mat karein.

### 3.2 Apni admin ID

Bot start karne ke baad `/whoami` bhejein. Jo number aaye use `ADMIN_IDS` me daalein. Pehle se pata ho to `@userinfobot` se bhi mil jata hai.

### 3.3 Install

Python 3.11+.

```bash
cd rajasthan-exam-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` me kam se kam:

```env
BOT_TOKEN=123456:abc
ADMIN_IDS=123456789
DATABASE_URL=sqlite+aiosqlite:///data/bot.db
```

AI ke liye koi ek:

```env
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

Sasta Hindi MCQ ke liye Groq bhi chalega (OpenAI-compatible):

```env
OPENAI_API_KEY=gsk_...
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_MODEL=llama-3.3-70b-versatile
```

Ya Gemini:

```env
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.0-flash
```

Bina key ke bhi bot chalta hai: seed MCQ, FAQ (मत्स्य संघ, मृत नदी, कटऑफ wali imaandaar tip), syllabus links. Naye unlimited MCQ aur lambi vyakhya ke liye key chahiye.

### 3.4 Run

```bash
python bot.py
```

Pehli baar database seed hota hai. 45 second baad pehli official-site jaanch shuru hoti hai. Uske baad roz subah 6:05 IST.

Alag cron (bot ke sath double na chalayein, lock hai phir bhi):

```bash
python pdf_updater.py --notify
python pdf_updater.py --health
```

### 3.5 PostgreSQL (production)

```env
DATABASE_URL=postgresql://user:pass@localhost:5432/rajguru
```

Code `postgresql+asyncpg://` bana deta hai. Tables khud banenge. SQLite file `data/bot.db` ko migrate karne ki zaroorat ho to pehle backup lein — seed exams dubara aa jayengi, users nahi.

### 3.6 Hosting

**Free Render/Railway web service roz so jata hai.** Reminder aur subah ki PDF jaanch ke liye process 24x7 hona chahiye.

| Jagah | Kaise | Note |
| --- | --- | --- |
| Sasta VPS (Hetzner / Oracle free / ₹300-500 mahina) | `deploy/raj-pariksha-guru.service` | Sabse bharosemand |
| Railway | Procfile `worker: python bot.py` | Worker rakhein, web service nahi |
| Render | `render.yaml` background worker | Free tier so sakta hai |
| Docker | `docker compose up -d --build` | VPS par |

VPS:

```bash
sudo mkdir -p /opt/raj-pariksha-guru
sudo cp -r . /opt/raj-pariksha-guru
cd /opt/raj-pariksha-guru
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo cp deploy/raj-pariksha-guru.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now raj-pariksha-guru
sudo journalctl -u raj-pariksha-guru -f
```

Webhook tabhi jab aapke paas HTTPS URL ho. Warna `MODE=polling` rehne dein.

---

## 4. Testing checklist

Pehle, token ke bina:

```bash
python scripts/selftest.py
```

Yeh check karta hai: official domain filter, coaching site reject, filename `Patwari_2021_Shift1_Paper.pdf`, tarikh parser, 30+ exams, Hindi resolve `पटवारी`, MCQ repeat nahi, dead link 404.

Phir Telegram par, private chat me:

- [ ] `/start` Hindi welcome aur neeche menu
- [ ] `/exams` buttons, panna aage-peeche, पटवारी khule
- [ ] `/search reet` sahi exam
- [ ] `/whoami` ID aaye, ADMIN_IDS set karke restart, `/admin` khule
- [ ] `/syllabus patwari` — PDF na ho to official link + saaf sandesh, fake PDF nahi
- [ ] `/verify https://www.adda247.com/file.pdf` — आधिकारिक नहीं
- [ ] `/verify` ek asli `rajasthan.gov.in` PDF par — domain haan, PDF signature haan/na
- [ ] Admin: `/addpdf patwari syllabus <official.pdf url>` — caption me source, date, link
- [ ] `/papers patwari` year/shift buttons
- [ ] `/subscribe patwari` phir naya PDF par notification
- [ ] `/mcq patwari rajasthan gk` — Hindi, 4 option, poll. Dobara same command — wahi sawaal nahi
- [ ] `/quiz patwari gk medium 10` — timer, end me score + galat ki vyakhya
- [ ] `/ask राजस्थान की मृत नदी कौन सी है?` — घग्गर. Follow-up: `मत्स्य संघ?`
- [ ] `patwari me kitne marks chahiye?` — cutoff nahi ghadna chahiye
- [ ] `add exam: कनिष्ठ अनुदेशक` — official mile to list me, na mile to URL maange
- [ ] `/remind study 07:05` — us minute par Hindi yaad (bot process chal raha ho)
- [ ] `/remind patwari 06-12-2026` — kai slots
- [ ] `/myreminders` aur `/cancelremind <id>`
- [ ] `/daily on patwari 07:10 5`
- [ ] `/forceupdate` admin — summary, site down ho to crash nahi
- [ ] User PDF bheje to reject. Admin bina official URL ke PDF bheje to reject
- [ ] `/broadcast` confirm ke bina nahi jata

---

## 5. Aage badhane ke ideas

- Test series: hafte ka full mock, negative marking jaisi us exam ki ho
- Leaderboard: weekly score, sirf opt-in naam
- Doubt group: bot se link, sawaal ko AI pehle chhane, phir group me
- Paid: ad-free, zyada AI MCQ, personal study plan. Free me official PDF aur seed MCQ rehne dein
- Subject-wise weak area: galat MCQ ka topic count
- Hindi TTS se roz ka 5-minute revision (alag voice tool)
- Jab official calendar PDF mile, usme se tarikh nikaal kar subscribed users ko confirm button den — apne aap remind mat set karein, kyunki PDF parse galat ho sakta hai

---

## Sample MCQs (quality check)

Yeh `exams_seed.py` ke sawaal hain. Bot inhe pehli baar dikhata hai, phir dohrata nahi.

**1.** राजस्थान दिवस कब मनाया जाता है?  
A) 18 मार्च  B) 30 मार्च  C) 1 नवम्बर  D) 26 जनवरी  
**सही: B.** 30 मार्च 1949 को वृहत्तर राजस्थान बना। 1 नवम्बर 1956 राज्य पुनर्गठन है।

**2.** मत्स्य संघ का गठन कब हुआ था?  
A) 17 मार्च 1948  B) 18 मार्च 1948  C) 25 मार्च 1948  D) 30 मार्च 1949  
**सही: B.** अलवर, भरतपुर, धौलपुर, करौली। राजधानी अलवर। 15 मई 1949 को मिला।

**3.** राजस्थान का राज्य पक्षी कौन सा है?  
A) मोर  B) सारस  C) गोडावण  D) तोता  
**सही: C.** राज्य वृक्ष खेजड़ी, राज्य पुष्प रोहिड़ा।

**4.** हल्दीघाटी का युद्ध किस वर्ष हुआ?  
A) 1527  B) 1556  C) 1576  D) 1707  
**सही: C.** खानवा 1527 (राणा सांगा–बाबर) से अलग।

**5.** लूनी नदी का उद्गम कहाँ से होता है?  
A) जनापाव पहाड़ी  B) नाग पहाड़, अजमेर  C) गुरु शिखर  D) पुष्कर झील  
**सही: B.** चंबल का उद्गम मध्य प्रदेश की जनापाव पहाड़ी है।

**6.** राजस्थान विधानसभा में कुल कितनी सीटें हैं?  
A) 150  B) 175  C) 200  D) 225  
**सही: C.** लोकसभा 25, राज्यसभा 10।

**7.** 'विद्यालय' शब्द में कौन-सी सन्धि है?  
A) गुण  B) दीर्घ  C) वृद्धि  D) यण  
**सही: B.** विद्या + आलय, अ + आ = आ।

**8.** RTE अधिनियम किस वर्ष पारित हुआ?  
A) 2002  B) 2005  C) 2009  D) 2020  
**सही: C.** NEP 2020 alag hai. Foundational stage 3–8 saal.

Expected AI behaviour, seed me cutoff number nahi:

- "patwari me kitne marks chahiye?" → cutoff mat banayo, official result PDF dikhao.
- "aaj ka current affairs" → khabar mat ghadho.

---

## PDF source verify karne ka tarika

Users ke liye `/verify <url>`:

| Jaanch | Theek | Galat |
| --- | --- | --- |
| Domain | rpsc.rajasthan.gov.in, rsmssb.rajasthan.gov.in, rssb.rajasthan.gov.in, police.rajasthan.gov.in, hcraj.nic.in, wcd / forest / education / recruitment / rajeduboard / rajswasthya .rajasthan.gov.in | adda247, testbook, telegram channel file |
| Signature | pehle bytes `%PDF-` | HTML page jiska naam .pdf ho |
| Date | caption me Last-Modified ya bot ki jaanch-tarikh | bina tarikh ki "latest" daava |
| Dubara | ETag / SHA256 badle to naya notice | purana link 404 do baar → status dead, user ko nahi bhejte |

Aap khud browser me official site khol kar PDF ka URL copy karein aur `/verify` chalaen. Jo link coaching page par "Download" dikhe, use tab tak official mat maanein jab tak final URL sarkari host par na ho.

Official portals (jaanche gaye entry points):

- https://rpsc.rajasthan.gov.in/
- https://rsmssb.rajasthan.gov.in/
- https://police.rajasthan.gov.in/
- https://hcraj.nic.in/
- https://rajeduboard.rajasthan.gov.in/
- https://recruitment.rajasthan.gov.in/

Vacancy aur exam date is repo me hardcode nahi hain. Coaching sites ek dusre se alag ank deti hain. Bot unhe fact ki tarah nahi dikhata.
