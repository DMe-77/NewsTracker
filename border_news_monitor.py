#!/usr/bin/env python3
"""
OSINT Монитор: Българо-Турска Граница
- Google News RSS (БГ + TR + EN заявки)
- Клъстеризация на дублирани статии → един обобщен доклад
- Тихи часове: 23:00–05:00 Ankara (UTC+3)
- Хронологично сортиране
- Реални линкове (не Google редиректи)
"""

import os, time, logging, hashlib, json, re, urllib.parse, ctypes, sys
import requests, feedparser
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

try:
    from deep_translator import GoogleTranslator
    TRANSLATOR_AVAILABLE = True
except ImportError:
    TRANSLATOR_AVAILABLE = False
from incident_logger import log_incident
from pattern_alerts import check_patterns
from weekly_summary import check_weekly_summary


# ─── PREVENT WINDOWS SLEEP ───────────────────────────────────────────────────
# Tells Windows this process requires the system to stay awake (ES_CONTINUOUS
# | ES_SYSTEM_REQUIRED). Automatically released when the process exits.

ES_CONTINUOUS      = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

def prevent_sleep():
    if sys.platform == "win32":
        result = ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        )
        if result:
            log_early("Windows sleep prevention активиран.")
        else:
            log_early("Не можа да се активира sleep prevention.")

def allow_sleep():
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)

def log_early(msg):
    print(f"[STARTUP] {msg}")

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_IDS      = [
    cid.strip()
    for cid in os.getenv("TELEGRAM_CHAT_IDS", os.getenv("TELEGRAM_CHAT_ID", "")).split(",")
    if cid.strip()
]
OLLAMA_BASE_URL        = os.getenv("OLLAMA_BASE_URL",    "http://localhost:11434")
OLLAMA_MODEL           = os.getenv("OLLAMA_MODEL",       "qwen2.5:14b")
CHECK_INTERVAL_DAY     = 5 * 60    # 5 min during the day
CHECK_INTERVAL_NIGHT   = 60 * 60   # 1 hr during quiet hours (only for morning digest trigger)
SEEN_IDS_FILE          = "seen_articles.json"

# Quiet hours in Ankara time (UTC+3): 22:00–06:00
QUIET_START_HOUR = 22   # Ankara time
QUIET_END_HOUR   = 6    # Ankara time
ANKARA_UTC_OFFSET = 3

# Similarity threshold for clustering duplicate articles (0.0–1.0)
CLUSTER_SIMILARITY = 0.55

# ─── DIRECT RSS FEEDS (bypass Google News — near real-time) ──────────────────
# These are direct site RSS feeds, much faster than Google News indexing.
# Keyword filtering still applies via is_relevant().

DIRECT_RSS_FEEDS = [
    # ── Bulgarian direct RSS ──
    {"url": "https://marica.bg/rss",                            "lang": "bg", "label": "marica.bg"},
    {"url": "https://novinite.bg/rss",                          "lang": "bg", "label": "novinite.bg"},
    {"url": "https://dnevnik.bg/rss",                           "lang": "bg", "label": "dnevnik.bg"},
    {"url": "https://nova.bg/rss/latest",                       "lang": "bg", "label": "nova.bg"},
    {"url": "https://fakti.bg/feed",                            "lang": "bg", "label": "fakti.bg"},
    {"url": "https://www.edna.bg/rss",                          "lang": "bg", "label": "edna.bg"},
    {"url": "https://24chasa.bg/rss",                           "lang": "bg", "label": "24chasa.bg"},
    {"url": "https://www.bta.bg/en/news/bulgaria/rss",          "lang": "en", "label": "bta.bg Bulgaria"},
    {"url": "https://www.bta.bg/en/news/balkans/rss",           "lang": "en", "label": "bta.bg Balkans"},
    # ── Turkish direct RSS ──
    {"url": "https://rss.haberler.com/rss.asp",                 "lang": "tr", "label": "haberler.com"},
    {"url": "https://www.sabah.com.tr/rss/anasayfa.xml",        "lang": "tr", "label": "sabah.com.tr"},
    {"url": "https://cumhuriyet.com.tr/rss",                    "lang": "tr", "label": "cumhuriyet.com.tr"},
    {"url": "http://rss.sondakika.com/rss.asp",                 "lang": "tr", "label": "sondakika.com"},
    {"url": "https://haberturk.com/rss",                        "lang": "tr", "label": "haberturk.com"},
    {"url": "https://ensonhaber.com/rss.xml",                   "lang": "tr", "label": "ensonhaber.com"},
    {"url": "https://tr.euronews.com/rss",                      "lang": "tr", "label": "tr.euronews.com"},
    {"url": "https://milligazete.com.tr/rss",                   "lang": "tr", "label": "milligazete.com.tr"},
    {"url": "https://www.sozcu.com.tr/feeds-haberler",          "lang": "tr", "label": "sozcu.com.tr"},
    {"url": "https://www.aa.com.tr/en/rss/default?cat=live",    "lang": "en", "label": "aa.com.tr"},
    {"url": "https://www.ntv.com.tr/son-dakika.rss",            "lang": "tr", "label": "ntv.com.tr son dakika"},
    {"url": "https://www.ntv.com.tr/turkiye.rss",               "lang": "tr", "label": "ntv.com.tr türkiye"},
    {"url": "https://www.trthaber.com/manset_articles.rss",     "lang": "tr", "label": "trthaber.com manşet"},
    {"url": "https://www.trthaber.com/sondakika_articles.rss",  "lang": "tr", "label": "trthaber.com son dakika"},
    {"url": "https://www.trthaber.com/turkiye_articles.rss",    "lang": "tr", "label": "trthaber.com türkiye"},
]


# ─── KEYWORDS ─────────────────────────────────────────────────────────────────

ALL_KEYWORDS = [
    # BG
    "граница", "гкпп", "капитан андреево", "лесово", "малко търново",
    "зелена граница", "мвр", "митници", "наркотрафик", "трафик на хора",
    "нелегална миграция", "задържан", "арест", "хашиш", "хероин", "кокаин",
    "контрабанда", "трафикант", "блокада", "марихуана","злато", "оръжи", "телефон",
    # TR
    "sınır", "kapıkule", "bulgaristan", "kaçakçılık", "uyuşturucu",
    "göçmen", "kaçak", "gümrük", "edirne sınır", "kırklareli", "bulgar",
    "dereköy", "esrar", "eroin", "kokain", "narkotik", "skank", "pazarkule", "telefon",
    # EN
    "bulgarian border", "turkey border", "kapitan andreevo", "kapikule",
    "lesovo", "malko tarnovo", "drug trafficking", "human trafficking",
    "smuggling", "illegal migration", "border crossing", "bulgaria turkey",
]

# ─── LOGGING ──────────────────────────────────────────────────────────────────


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("border_monitor.log", encoding="utf-8"),
    ]
)
log = logging.getLogger(__name__)

# ─── QUIET HOURS & NIGHT DIGEST ──────────────────────────────────────────────

def ankara_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=ANKARA_UTC_OFFSET)

def is_quiet_hours() -> bool:
    h = ankara_now().hour
    return h >= QUIET_START_HOUR or h < QUIET_END_HOUR

def is_morning_digest_time() -> bool:
    """True during the 05:00 hour in Ankara time."""
    return ankara_now().hour == QUIET_END_HOUR


def load_seen_ids() -> set:
    if os.path.exists(SEEN_IDS_FILE):
        with open(SEEN_IDS_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen_ids(ids: set):
    with open(SEEN_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(ids), f)


def article_id(entry) -> str:
    return hashlib.md5((entry.get("link", "") + entry.get("title", "")).encode()).hexdigest()


# Borders that are NOT Bulgaria — filter these out before LLM
NON_BG_BORDERS = [
    "türkiye-iran", "turkiye-iran", "iran sınırı", "iran siniri",
    "türkiye-suriye", "turkiye-suriye", "suriye sınırı",
    "türkiye-irak", "turkiye-irak", "irak sınırı",
    "yunanistan sınırı",  # Greek border — unless Bulgaria also mentioned
]

# Turkish keywords that only count if Bulgaria is also explicitly mentioned
TR_REQUIRES_BULGARIA = [
    "ab sınır", "avrupa sınır", "sığınmacı", "mülteci",
    "geri itme", "pushback", "avrupa birliği sınır",
]

def is_relevant(title: str, summary: str) -> bool:
    text = (title + " " + summary).lower()
    # Pre-filter: skip articles about other Turkish borders
    if any(nb in text for nb in NON_BG_BORDERS):
        if "bulgar" not in text and "българ" not in text:
            return False
    # Pre-filter: generic EU/migration terms only relevant if Bulgaria mentioned
    if any(tr in text for tr in TR_REQUIRES_BULGARIA):
        if "bulgar" not in text and "българ" not in text and "kapıkule" not in text and "dereköy" not in text and "pazarkule" not in text and "edirne" not in text and "kırklareli" not in text:
            return False
    return any(kw in text for kw in ALL_KEYWORDS)


def parse_entry_date(entry) -> datetime | None:
    import email.utils
    for field in ("published_parsed", "updated_parsed"):
        val = entry.get(field)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    for field in ("published", "updated"):
        raw = entry.get(field)
        if raw:
            try:
                return email.utils.parsedate_to_datetime(raw).astimezone(timezone.utc)
            except Exception:
                pass
    return None


def resolve_google_url(google_url: str) -> str:
    """
    Extract the real article URL from a Google News RSS link.
    Tries two methods:
    1. Decode the base64-encoded URL embedded in the CBMi... article ID
    2. Follow HTTP redirect as fallback
    """
    import base64

    # Method 1: decode base64 article ID (works for most Google News RSS links)
    # Format: https://news.google.com/rss/articles/CBMi<base64>...
    try:
        if "news.google.com/rss/articles/" in google_url:
            encoded = google_url.split("/rss/articles/")[1].split("?")[0]
            # Google uses a modified base64: strip leading "CBMi" marker then decode
            # The actual URL starts after a few prefix bytes
            padded = encoded + "=" * (4 - len(encoded) % 4)
            decoded = base64.urlsafe_b64decode(padded)
            # Find http in the decoded bytes
            idx = decoded.find(b"http")
            if idx != -1:
                url = decoded[idx:].split(b"\x00")[0].decode("utf-8", errors="ignore")
                # Clean up any trailing garbage
                for stop in [" ", "\n", "\r", "\t"]:
                    url = url.split(stop)[0]
                if url.startswith("http") and "google.com" not in url:
                    return url
    except Exception:
        pass

    # Method 2: follow HTTP redirect
    try:
        resp = requests.get(
            google_url,
            allow_redirects=True,
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        final = resp.url
        if "google.com" not in final and final.startswith("http"):
            return final
    except Exception:
        pass

    return google_url


def title_similarity(a: str, b: str) -> float:
    """Compute similarity ratio between two titles (0.0–1.0)."""
    a = re.sub(r"[^\w\s]", "", a.lower())
    b = re.sub(r"[^\w\s]", "", b.lower())
    return SequenceMatcher(None, a, b).ratio()


def cluster_articles(articles: list[dict]) -> list[list[dict]]:
    """
    Group articles that are likely about the same event.
    Returns a list of clusters (each cluster is a list of articles).
    """
    clusters = []
    used = set()

    for i, art in enumerate(articles):
        if i in used:
            continue
        cluster = [art]
        used.add(i)
        for j, other in enumerate(articles):
            if j in used:
                continue
            sim = title_similarity(art["title"], other["title"])
            if sim >= CLUSTER_SIMILARITY:
                cluster.append(other)
                used.add(j)
        clusters.append(cluster)

    return clusters


# ─── FETCH ────────────────────────────────────────────────────────────────────

def fetch_articles() -> list[dict]:
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    seen_links = set()  # deduplicate by URL within this fetch

    for feed_cfg in DIRECT_RSS_FEEDS:
        url  = feed_cfg["url"]
        lang = feed_cfg["lang"]
        label = feed_cfg["label"]
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"})
            for entry in feed.entries:
                pub_date = parse_entry_date(entry)
                if pub_date and pub_date < cutoff:
                    continue
                title   = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                link    = entry.get("link", "")
                if not is_relevant(title, summary):
                    continue
                if link in seen_links:
                    continue
                seen_links.add(link)
                # Resolve real URL from Google redirect
                real_link = resolve_google_url(link)
                # Extract source domain
                try:
                    domain = urllib.parse.urlparse(real_link).netloc.replace("www.", "")
                except Exception:
                    domain = ""
                articles.append({
                    "id":      article_id(entry),
                    "title":   title,
                    "summary": summary[:1000],
                    "link":    real_link,
                    "domain":  domain,
                    "lang":    lang,
                    "label":   label,
                    "date":    pub_date,
                    "date_str": pub_date.strftime("%d.%m.%Y %H:%M") if pub_date else "н/д",
                })
        except Exception as e:
            log.warning(f"Грешка при {label}: {e}")

    # Sort chronologically (oldest first → newest last)
    articles.sort(key=lambda a: a["date"] or datetime.min.replace(tzinfo=timezone.utc))
    return articles


# ─── OLLAMA OSINT ANALYSIS ────────────────────────────────────────────────────

# Location name mapping — canonical Bulgarian names for known checkpoints
LOCATION_MAP = {
    "капитан андреево": "ГКПП Капитан Андреево",
    "kapitan andreevo": "ГКПП Капитан Андреево",
    "лесово": "ГКПП Лесово",
    "lesovo": "ГКПП Лесово",
    "малко търново": "ГКПП Малко Търново",
    "malko tarnovo": "ГКПП Малко Търново",
    "kapıkule": "ГКПП Капъкуле (TR)",
    "kapikule": "ГКПП Капъкуле (TR)",
    "dereköy": "ГКПП Дерекьой (TR)",
    "pazarkule": "ГКПП Пазаркуле (TR)",
    "edirne": "Eдирне (TR)",
    "зелена граница": "Зелена граница",
    "green border": "Зелена граница",
}

STATUS_MAP = {
    "critical": "Критично",
    "important": "Важно",
    "info": "Информация",
}

def detect_location(text: str) -> str:
    """Extract the most specific known location from article text."""
    text_lower = text.lower()
    for key, label in LOCATION_MAP.items():
        if key in text_lower:
            return label
    return "Българо-турска граница"

def detect_status(text: str) -> str:
    """Determine status from keywords — no LLM needed."""
    text_lower = text.lower()
    critical = ["иззет", "задържан", "арест", "seized", "arrested", "yakalandı",
                "ele geçirildi", "кг", "килограм", "kg", "кокаин", "хероин",
                "хашиш", "марихуана", "eroin", "kokain", "esrar"]
    important = ["контрабанд", "трафик", "мигрант", "нелегал", "kaçak",
                 "göçmen", "smuggl", "trafficking", "оръжи", "валута"]
    if any(kw in text_lower for kw in critical):
        return "Критично"
    if any(kw in text_lower for kw in important):
        return "Важно"
    return "Информация"


OSINT_PROMPT_TEMPLATE = """You are a border security analyst for the Bulgaria-Turkey border.

Your ONLY job: decide if the articles below are relevant to the Bulgaria-Turkey border.

RELEVANT means the article is specifically about:
- ГКПП Kapitan Andreevo, Lesovo, Malko Tarnovo or the green border between Bulgaria and Turkey
- Drug/weapons/goods seizures at these checkpoints
- Illegal migration crossing the Bulgaria-Turkey border
- Official announcements from Bulgarian customs, border police or MВР about this border

NOT RELEVANT:
- Turkey-Iran, Turkey-Syria, Turkey-Iraq, Turkey-Greece border (unless Bulgaria is explicitly mentioned)
- General crime news not involving the Bulgarian-Turkish border
- Oil prices, festivals, unrelated news

If relevant, respond with exactly one word: RELEVANT
If not relevant, respond with exactly one word: IRRELEVANT

Articles ({n}):
{articles_block}

Answer:"""


def translate_to_bulgarian(text: str) -> str:
    """
    Translate any text to Bulgarian using Google Translate via deep-translator.
    Falls back to original text if translation fails or library not available.
    """
    if not text or not TRANSLATOR_AVAILABLE:
        return text
    try:
        translated = GoogleTranslator(source="auto", target="bg").translate(text[:500])
        return translated or text
    except Exception as e:
        log.debug(f"Translation failed: {e}")
        return text


def build_articles_block(cluster: list[dict]) -> str:
    blocks = []
    for i, art in enumerate(cluster, 1):
        lang_tag = {"bg": "🇧🇬", "tr": "🇹🇷", "en": "🌐"}.get(art["lang"], "")
        blocks.append(
            f"[Статия {i}] {lang_tag} {art['domain'] or art['label']}\n"
            f"Заглавие: {art['title']}\n"
            f"Съдържание: {art['summary']}\n"
        )
    return "\n".join(blocks)


def is_irrelevant_response(result: str) -> bool:
    """
    Check if LLM gate response means irrelevant.
    LLM now only responds RELEVANT or IRRELEVANT.
    """
    if not result:
        return True
    cleaned = result.strip().upper().split()[0] if result.strip() else ""
    # Treat anything that isn't clearly RELEVANT as irrelevant
    return cleaned != "RELEVANT"


def assess_correlation(cluster: list[dict]) -> dict:
    langs = [a.get("lang", "") for a in cluster]
    bg_count = sum(1 for l in langs if l in ("bg", "en"))
    tr_count = sum(1 for l in langs if l == "tr")
    confirmed = bg_count >= 1 and tr_count >= 1
    return {
        "confirmed":        confirmed,
        "bg_count":         bg_count,
        "tr_count":         tr_count,
        "bump_to_critical": confirmed,
    }


def apply_correlation(analysis: str, corr: dict) -> str:
    if not corr["confirmed"]:
        return analysis
    analysis = re.sub(
        r"🚨 Статус: (Важно|Информация)",
        "🚨 Статус: Критично",
        analysis,
    )
    badge = f"🔁 <i>Потвърдено от {corr['bg_count'] + corr['tr_count']} източници ({corr['bg_count']} БГ/EN · {corr['tr_count']} TR)</i>"
    if "Потвърдено от" not in analysis:
        analysis = analysis.rstrip() + "\n" + badge
    return analysis


def analyze_cluster(cluster: list[dict]) -> str | None:
    """
    Pipeline:
    1. LLM does ONE job only: is this actually border-relevant? Yes/No.
    2. Python detects status and location from keywords.
    3. Google Translate translates the best headline to Bulgarian.
    4. Python assembles the final message — no Bulgarian writing by LLM.
    """
    # ── Step 1: LLM relevance gate ────────────────────────────────────────
    prompt = OSINT_PROMPT_TEMPLATE.format(
        n=len(cluster),
        articles_block=build_articles_block(cluster),
    )
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        llm_response = resp.json().get("response", "").strip()
        log.debug(f"LLM gate response: {llm_response[:120]}")

        if is_irrelevant_response(llm_response):
            log.info("    ↳ LLM: нерелевантно — пропуснато.")
            return None

    except Exception as e:
        log.error(f"Ollama грешка: {e}")
        return None

    # ── Step 2: Status & location via Python keywords ─────────────────────
    combined_text = " ".join(a["title"] + " " + a.get("summary", "") for a in cluster)
    status   = detect_status(combined_text)
    location = detect_location(combined_text)

    # ── Step 3: Translate best headline to Bulgarian ──────────────────────
    best = next((a for a in cluster if a.get("lang") in ("bg", "en")), cluster[0])
    headline_raw = best["title"]
    headline = translate_to_bulgarian(headline_raw)
    if not headline:
        headline = headline_raw
    log.info(f"    ↳ Заглавие: {headline[:80]}")

    # ── Step 4: Assemble message ──────────────────────────────────────────
    lines = [
        f"🚨 Статус: {status}",
        f"📍 Локация: {location}",
        f"📰 {headline}",
    ]

    # TR-exclusive: if TR source has quantity/arrest details missing from BG
    tr_arts = [a for a in cluster if a.get("lang") == "tr"]
    bg_arts = [a for a in cluster if a.get("lang") in ("bg", "en")]
    if tr_arts and bg_arts:
        tr_titles = " ".join(a["title"] for a in tr_arts).lower()
        bg_titles = " ".join(a["title"] for a in bg_arts).lower()
        quantity_words = ["kg", "кг", "gram", "lira", "pieces", "adet"]
        tr_has_extra = any(w in tr_titles for w in quantity_words) and not any(w in bg_titles for w in quantity_words)
        if tr_has_extra:
            tr_headline = translate_to_bulgarian(tr_arts[0]["title"])
            lines.append(f"🌐 Ексклузивно от Турция: {tr_headline}")

    result = "\n".join(lines)

    # ── Correlation badge ─────────────────────────────────────────────────
    corr = assess_correlation(cluster)
    if corr["confirmed"]:
        log.info(f"    ↳ Корелация: {corr['bg_count']} БГ/EN + {corr['tr_count']} TR → Критично")
        result = apply_correlation(result, corr)
        result = result.replace("🚨 Статус: Важно", "🚨 Статус: Критично")
        result = result.replace("🚨 Статус: Информация", "🚨 Статус: Критично")

    return result


# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_telegram(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_IDS:
        log.warning("Telegram не е конфигуриран (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_IDS).")
        return
    if len(message) > 4096:
        message = message[:4090] + "…"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": False},
                timeout=10,
            )
            resp.raise_for_status()
            log.info(f"Telegram изпратено до {chat_id}.")
        except Exception as e:
            log.error(f"Telegram грешка ({chat_id}): {e}")


def format_cluster_message(cluster: list[dict], analysis: str) -> str:
    now = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")

    # Date range of articles in cluster
    dates = [a["date"] for a in cluster if a["date"]]
    if dates:
        earliest = min(dates).strftime("%d.%m.%Y %H:%M")
        latest   = max(dates).strftime("%d.%m.%Y %H:%M")
        date_line = earliest if earliest == latest else f"{earliest} – {latest}"
    else:
        date_line = "н/д"

    # Links — one per unique URL; prefer resolved URLs, fall back to Google URLs
    seen_links: set[str] = set()
    link_lines = []
    google_fallbacks = []

    for a in cluster:
        link  = a.get("link", "").strip()
        title = a.get("title", "")
        domain = a.get("domain", "")
        if not link or link in seen_links:
            continue
        seen_links.add(link)
        label = esc(domain) if domain else esc(title[:60])
        if "google.com" in link:
            google_fallbacks.append(f'🔗 <a href="{link}">{esc(title[:60])}</a>')
        else:
            link_lines.append(f'🔗 <a href="{link}">{label}</a>')

    # Always show at least one link
    if not link_lines:
        link_lines = google_fallbacks[:3]

    links = "\n".join(link_lines) if link_lines else ""

    msg = (
        f"🇧🇬🇹🇷 <b>OSINT Доклад</b> — {now}\n\n"
        f"{esc(analysis)}\n\n"
        f"🕐 <i>{date_line}</i>"
    )
    if links:
        msg += f"\n\n{links}"
    return msg



# ─── NIGHT DIGEST LLM ────────────────────────────────────────────────────────

NIGHT_DIGEST_PROMPT = """Ти си OSINT анализатор на българо-турската граница.
Изминалата нощ (22:00–06:00 Анкара) беше наблюдавана автоматично.

{situation}

Напиши кратък нощен доклад на БЪЛГАРСКИ. НЕ измисляй дати — заглавието вече е зададено от системата.

{body_instruction}"""

def generate_night_digest(buffered_articles: list) -> str:
    today = ankara_now().strftime("%d.%m.%Y")
    header = f"🌙 <b>Нощен доклад: {today}</b>"

    if not buffered_articles:
        situation = "Не са засечени нови статии по темата през нощта."
        body_instruction = "Напиши ТОЧНО едно изречение (максимум 12 думи), че нощта е тиха. Без заглавие, без допълнения."
    else:
        clusters = cluster_articles(buffered_articles)
        lines = []
        for cl in clusters:
            titles = " / ".join(a["title"][:80] for a in cl)
            lines.append(f"- {titles}")
        situation = f"През нощта са засечени {len(buffered_articles)} статии в {len(clusters)} теми:\n" + "\n".join(lines)
        body_instruction = "Обобщи накратко всяка тема в 1–2 изречения. Посочи дали е имало критични инциденти. Без заглавие — само текста."

    prompt = NIGHT_DIGEST_PROMPT.format(situation=situation, body_instruction=body_instruction)
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        body = resp.json().get("response", "").strip()
        # Strip any header line the LLM hallucinated (e.g. "🌙 Нощен доклад: ...")
        lines = body.splitlines()
        lines = [l for l in lines if not l.strip().startswith("🌙") and "нощен доклад" not in l.lower()]
        body = "\n".join(lines).strip()
        # For quiet nights keep only the first sentence
        if not buffered_articles:
            sentences = [s.strip() for s in body.replace("!", ".").replace("?", ".").split(".") if s.strip()]
            body = sentences[0] + "." if sentences else body
        return header + "\n\n" + body
    except Exception as e:
        log.error(f"Ollama нощен доклад грешка: {e}")
        if buffered_articles:
            return header + "\n\nЗасечени " + str(len(buffered_articles)) + " статии — моля проверете ръчно."
        return header + "\n\nНощта премина спокойно на границата."


# ─── MAIN LOOP ────────────────────────────────────────────────────────────────

# Track whether we already sent the morning digest this cycle
_morning_digest_sent = False

def check_and_notify():
    global _morning_digest_sent
    ankara_time = ankara_now()
    quiet = is_quiet_hours()

    # ── Weekly summary (Monday 08:00 Ankara) ────────────────────────────────
    check_weekly_summary(send_telegram)

    # ── Morning digest: fetch overnight articles and report ─────────────────
    if is_morning_digest_time() and not _morning_digest_sent:
        log.info("06:00 Анкара — нощен доклад: извличане на статии от последните 6 часа...")
        seen_ids     = load_seen_ids()
        articles     = fetch_articles()
        new_articles = [a for a in articles if a["id"] not in seen_ids]
        for a in new_articles:
            seen_ids.add(a["id"])
        save_seen_ids(seen_ids)

        relevant_articles = []
        if new_articles:
            clusters = cluster_articles(new_articles)
            for cluster in clusters:
                analysis = analyze_cluster(cluster)
                if analysis:
                    send_telegram(format_cluster_message(cluster, analysis))
                    log_incident(cluster, analysis)
                    # check_patterns(send_telegram)  # disabled — re-enable when enough history
                    relevant_articles.extend(cluster)
                    time.sleep(3)

        if relevant_articles:
            digest = generate_night_digest(relevant_articles)
            send_telegram(digest)
        _morning_digest_sent = True
        log.info("Нощен доклад изпратен.")
        return

    # Reset flag once we leave the 05:00 hour
    if not is_morning_digest_time():
        _morning_digest_sent = False

    # ── Quiet hours: just sleep, fetch happens at 05:00 ─────────────────────
    if quiet:
        log.info(f"Тихи часове (Анкара: {ankara_time.strftime('%H:%M')}). Почивка до сутринта.")
        return

    # ── Normal hours: fetch & send ────────────────────────────────────────────
    log.info("Проверка за нови статии...")
    seen_ids     = load_seen_ids()
    articles     = fetch_articles()
    new_articles = [a for a in articles if a["id"] not in seen_ids]

    for a in new_articles:
        seen_ids.add(a["id"])
    save_seen_ids(seen_ids)

    if not new_articles:
        log.info("Няма нови статии.")
        return

    log.info(f"Намерени {len(new_articles)} нови статии. Клъстеризиране...")
    clusters = cluster_articles(new_articles)
    clusters.sort(key=lambda cl: min(
        (a["date"] for a in cl if a["date"]),
        default=datetime.min.replace(tzinfo=timezone.utc)
    ))
    log.info(f"Образувани {len(clusters)} клъстера.")

    reported = 0
    for cluster in clusters:
        log.info(f"  Клъстер ({len(cluster)}): {cluster[0]['title'][:70]}")
        analysis = analyze_cluster(cluster)
        if analysis is None:
            log.info("    ↳ Нерелевантен — пропуснат.")
            continue
        send_telegram(format_cluster_message(cluster, analysis))
        log_incident(cluster, analysis)
        # check_patterns(send_telegram)  # disabled — re-enable when enough history
        reported += 1
        time.sleep(3)

    if reported == 0:
        log.info("Всички клъстери са нерелевантни. Без съобщение.")
    else:
        log.info(f"Изпратени {reported} доклада.")


def main():
    log.info("=" * 60)
    log.info("OSINT Монитор: Българо-Турска Граница")
    log.info(f"  Модел:    {OLLAMA_MODEL} @ {OLLAMA_BASE_URL}")
    log.info("  Интервал: 5 мин (ден) / спи (нощ) | Тихи часове: 22:00–06:00 Анкара")
    log.info(f"  Заявки:   {len(DIRECT_RSS_FEEDS)} директни RSS")
    log.info("=" * 60)

    prevent_sleep()
    try:
        while True:
            try:
                check_and_notify()
            except Exception as e:
                log.error(f"Неочаквана грешка: {e}")
            interval = CHECK_INTERVAL_NIGHT if is_quiet_hours() else CHECK_INTERVAL_DAY
            log.info(f"Почивка {interval // 60} мин ({'нощ' if is_quiet_hours() else 'ден'})...")
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("Спиране по заявка на потребителя.")
    finally:
        allow_sleep()
        log.info("Windows sleep prevention деактивиран.")


if __name__ == "__main__":
    main()