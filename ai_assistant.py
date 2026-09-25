"""Sawaal-jawaab. OpenAI-compatible ya Gemini. Bina key ke FAQ + MCQ bank."""

from __future__ import annotations

import json
import logging
import re

import httpx

import config
import database

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """आप राज परीक्षा गुरु हैं — राजस्थान की सरकारी परीक्षाओं के शिक्षक।
परीक्षाएँ: RPSC (RAS/RTS, व्याख्याता, AEn, सांख्यिकी), RSSB/RSMSSB (पटवारी, LDC, VDO, CET, JEn, REET, ग्रेड-2/3, वनरक्षक), पुलिस, उच्च न्यायालय, BSTC, नर्सिंग, आंगनवाड़ी, विश्वविद्यालय।

नियम:
1. जवाब सरल हिंदी में दें, जब तक उपयोगकर्ता अंग्रेज़ी न माँगे। परीक्षा-उन्मुख लिखें: तथ्य, छोटा कारण, और याद रखने की एक पंक्ति।
2. कटऑफ, रिक्ति, फॉर्म की अंतिम तिथि, एडमिट कार्ड और परिणाम न गढ़ें। पक्का न हो तो लिखें कि rpsc.rajasthan.gov.in / rsmssb.rajasthan.gov.in या संबंधित आधिकारिक साइट देखें।
3. आज का करेंट अफेयर्स न बनाएँ। उपयोगकर्ता शीर्षक दे तो उसकी व्याख्या करें, खबर गढ़ें नहीं।
4. लीक पेपर, परीक्षा के दौरान नकल, या अप्रकाशित प्रश्नपत्र न दें।
5. अनुमान को तथ्य की तरह न लिखें। 120 से 220 शब्द काफी हैं।
6. उपयोगकर्ता की भाषा में follow-up का संदर्भ रखें।"""

FAQ = [
    (
        ("मत्स्य", "matsya", "मत्स्य संघ"),
        "मत्स्य संघ 18 मार्च 1948 को बना था। इसमें चार रियासतें/जिले थे: अलवर, भरतपुर, धौलपुर और करौली। राजधानी अलवर थी। राजप्रमुख धौलपुर नरेश थे। 15 मई 1949 को यह वृहत्तर राजस्थान में मिला दिया गया।\n\nयाद रखें: राजस्थान दिवस 30 मार्च है (वृहत्तर राजस्थान, 1949), मत्स्य संघ की तारीख 18 मार्च 1948 है।\nअगर आपका प्रश्न 'मृत नदी' था, तो वह घग्गर है।",
    ),
    (
        ("मृत नदी", "mrit nadi", "घग्गर", "ghaggar"),
        "राजस्थान से जुड़ी 'मृत नदी' घग्गर को कहा जाता है। यह मौसमी नदी है और प्राचीन सरस्वती से जोड़ी जाती रही है। पूरा साल बहने वाली बड़ी नदी के रूप में इसे नहीं गिना जाता।\n\nअगर आप मत्स्य संघ पूछ रहे थे: गठन 18 मार्च 1948, जिले अलवर-भरतपुर-धौलपुर-करौली, राजधानी अलवर।",
    ),
    (
        ("कटऑफ", "cutoff", "cut off", "कितने मार्क्स", "kitne marks", "kitne number", "पासिंग मार्क्स"),
        "कटऑफ और 'कितने अंक चाहिए' हर भर्ती, वर्ग और वर्ष में बदलते हैं। मैं अनुमानित कटऑफ नहीं बताऊँगा, क्योंकि गलत अंक तैयारी बिगाड़ देते हैं।\n\nक्या करें:\n• आधिकारिक परिणाम/cutoff PDF खोलें — /papers <exam>\n• पैटर्न (कुल अंक) सिलेबस PDF में देखें — /syllabus <exam>\n• सुरक्षित रणनीति: पूरे अंक का मजबूत प्रयास, न कि पिछले साल की अफवाह।",
    ),
    (
        ("गोडावण", "राज्य पक्षी"),
        "राजस्थान का राज्य पक्षी गोडावण (Great Indian Bustard) है। राज्य वृक्ष खेजड़ी और राज्य पुष्प रोहिड़ा है।",
    ),
    (
        ("राजस्थान दिवस", "rajasthan diwas"),
        "राजस्थान दिवस 30 मार्च को मनाया जाता है। 30 मार्च 1949 को जयपुर, जोधपुर, जैसलमेर और बीकानेर मिलकर वृहत्तर राजस्थान बना। वर्तमान सीमाएँ 1 नवम्बर 1956 के राज्य पुनर्गठन से जुड़ी हैं।",
    ),
]


def has_llm() -> bool:
    return bool(config.OPENAI_API_KEY or config.GEMINI_API_KEY)


def _faq_answer(text: str) -> str | None:
    low = text.lower()
    for keys, answer in FAQ:
        if any(k.lower() in low for k in keys):
            return answer
    return None


def _strip_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?", "", raw, flags=re.I).strip()
    raw = re.sub(r"```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start : end + 1]
    start = raw.find("[")
    end = raw.rfind("]")
    if start >= 0 and end > start:
        return raw[start : end + 1]
    return raw


async def _openai_chat(messages: list[dict], temperature: float = 0.4) -> str:
    url = f"{config.OPENAI_BASE_URL}/chat/completions"
    payload = {
        "model": config.OPENAI_MODEL,
        "temperature": temperature,
        "messages": messages,
    }
    headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


async def _gemini_chat(messages: list[dict], temperature: float = 0.4) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}"
    )
    system = ""
    contents = []
    for msg in messages:
        if msg["role"] == "system":
            system += msg["content"] + "\n"
            continue
        role = "model" if msg["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    payload = {
        "systemInstruction": {"parts": [{"text": system or SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {"temperature": temperature},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


async def complete(messages: list[dict], temperature: float = 0.4) -> str:
    if config.OPENAI_API_KEY:
        return await _openai_chat(messages, temperature)
    if config.GEMINI_API_KEY:
        return await _gemini_chat(messages, temperature)
    raise RuntimeError("कोई AI कुंजी सेट नहीं है")


async def answer_question(user_db_id: int, text: str, exam_name: str | None = None) -> str:
    text = (text or "").strip()
    if not text:
        return "प्रश्न लिखें। उदाहरण: राजस्थान की मृत नदी कौन सी है?"

    leak = ("लीक पेपर", "leak paper", "आज का पेपर भेजो", "exam me answer batao live")
    if any(k in text.lower() for k in leak):
        return (
            "लीक या अभी चल रही परीक्षा का प्रश्नपत्र यहाँ नहीं मिलता। "
            "आधिकारिक पेपर जारी होने के बाद ही /papers में जोड़ा जाता है।"
        )

    history = await database.recent_chat(user_db_id, limit=8)
    await database.add_chat(user_db_id, "user", text)

    if not has_llm():
        faq = _faq_answer(text)
        if faq:
            reply = faq + "\n\n(ऑफलाइन उत्तर — पूरी व्याख्या के लिए .env में OPENAI_API_KEY या GEMINI_API_KEY डालें।)"
        else:
            hits = await database.search_mcq_text(text, limit=1)
            if hits:
                h = hits[0]
                letters = ["A", "B", "C", "D"]
                ans = h["options"][h["answer_index"]]
                reply = (
                    f"{h['explanation']}\n\n"
                    f"संबंधित अभ्यास: {h['question']}\n"
                    f"सही विकल्प: {letters[h['answer_index']]}) {ans}"
                )
            else:
                reply = (
                    "अभी AI कुंजी सेट नहीं है, इसलिए मैं इस प्रश्न का पूरा व्याख्याता-उत्तर नहीं दे सकता।\n"
                    "1) .env में OPENAI_API_KEY या GEMINI_API_KEY डालकर बॉट दोबारा चलाएँ\n"
                    "2) तब तक /mcq से अभ्यास करें\n"
                    "ताज़ा तिथि, रिक्ति और कटऑफ के लिए आधिकारिक वेबसाइट ही देखें।"
                )
        await database.add_chat(user_db_id, "assistant", reply)
        return reply

    usage = await database.get_usage(user_db_id)
    if usage["ai_calls"] >= config.AI_DAILY_LIMIT:
        reply = "आज की AI सीमा पूरी हो गई है। कल फिर पूछें, या /mcq से अभ्यास जारी रखें।"
        await database.add_chat(user_db_id, "assistant", reply)
        return reply

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if exam_name:
        messages.append({"role": "system", "content": f"उपयोगकर्ता इस परीक्षा की तैयारी कर रहा है: {exam_name}"})
    messages.extend(history)
    messages.append({"role": "user", "content": text})
    try:
        reply = (await complete(messages, temperature=0.3)).strip()
    except Exception as exc:
        logger.exception("AI answer failed")
        reply = f"AI सेवा अभी जवाब नहीं दे पाई। थोड़ी देर बाद कोशिश करें। (तकनीकी: {type(exc).__name__})"
    if not reply:
        reply = "इस प्रश्न का पक्का उत्तर मेरे पास नहीं है। आधिकारिक किताब या अधिसूचना से मिलाएँ।"
    await database.bump_usage(user_db_id, ai=1)
    await database.add_chat(user_db_id, "assistant", reply[:4000])
    return reply[:3500]


async def generate_mcqs(exam_name: str, topic: str, difficulty: str, n: int, avoid: list[str]) -> list[dict]:
    if not has_llm():
        return []
    avoid_txt = "\n".join(f"- {q}" for q in avoid[:15]) or "(कोई नहीं)"
    prompt = f"""राजस्थान परीक्षा '{exam_name}' के लिए {n} मूल हिंदी MCQ बनाएँ।
विषय: {topic}
कठिनाई: {difficulty}

नियम:
- प्रश्न मूल हों, किसी किताब या पुराने पेपर की नकल न हों।
- हर प्रश्न में ठीक 4 विकल्प। एक ही सही।
- answer_index 0, 1, 2 या 3।
- explanation एक या दो हिंदी वाक्य।
- करेंट अफेयर्स की ताज़ा खबर न गढ़ें। स्थिर राजस्थान GK, विषय और अवधारणाएँ इस्तेमाल करें।
- ये प्रश्न दोहराएँ नहीं:
{avoid_txt}

केवल JSON दें:
{{"questions":[{{"question":"...","options":["...","...","...","..."],"answer_index":0,"explanation":"...","difficulty":"{difficulty}","topic":"{topic}"}}]}}"""
    messages = [
        {"role": "system", "content": "आप हिंदी MCQ लेखक हैं। केवल वैध JSON लौटाएँ।"},
        {"role": "user", "content": prompt},
    ]
    raw = await complete(messages, temperature=0.8)
    data = json.loads(_strip_json(raw))
    questions = data.get("questions", data if isinstance(data, list) else [])
    clean = []
    for item in questions:
        if not isinstance(item, dict):
            continue
        options = item.get("options") or []
        if len(options) != 4:
            continue
        try:
            idx = int(item.get("answer_index"))
        except (TypeError, ValueError):
            continue
        if idx not in {0, 1, 2, 3}:
            continue
        question = str(item.get("question") or "").strip()
        if len(question) < 8:
            continue
        if not re.search(r"[\u0900-\u097F]", question):
            continue
        clean.append(
            {
                "question": question,
                "options": [str(o).strip()[:100] for o in options],
                "answer_index": idx,
                "explanation": str(item.get("explanation") or "").strip()[:500],
                "difficulty": difficulty if difficulty in {"easy", "medium", "hard"} else "medium",
                "topic": topic,
            }
        )
    return clean
