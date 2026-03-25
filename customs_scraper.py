#!/usr/bin/env python3
"""
customs_scraper.py — Агенция Митници scraper
Runs independently every 30 minutes alongside border_news_monitor.py via run.py

Two data types:
  1. TRUCK STATS — /news-details/DD-MM-YYYY-kamioni
     URL is predictable, fetched directly with requests.

  2. NEWS ARTICLES — /news-details/DD-MM-YYYY-<slug>
     Slug is unpredictable. We open the media center index in a real
     Playwright browser (visible), scrape all news-details links,
     then visit each article page to extract content.

Only news articles mentioning the Bulgarian-Turkish border are forwarded
to the main bot via customs_queue.json.
Truck stats are sent directly to Telegram.
"""

import os, json, time, hashlib, logging, re
import requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

requests.packages.urllib3.disable_warnings()

# ─── CONFIG ───────────────────────────────────────────────────────────────────

QUEUE_FILE        = "customs_queue.json"
SEEN_FILE         = "customs_seen.json"
TRUCK_STATS_FILE  = "truck_stats.json"
CHECK_INTERVAL    = 30 * 60

BASE               = "https://customs.bg/wps/portal/agency/media-center"
NEWS_DETAILS_BASE  = "https://customs.bg/wps/portal/agency/media-center/news-details"
HEADERS            = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) OSINT-Monitor-BG"}
TIMEOUT_HTTP       = 15
TIMEOUT_PW         = 20_000   # ms

QUIET_START_HOUR  = 22
QUIET_END_HOUR    = 6
ANKARA_UTC_OFFSET = 3

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_IDS  = [
    cid.strip()
    for cid in os.getenv("TELEGRAM_CHAT_IDS", os.getenv("TELEGRAM_CHAT_ID", "")).split(",")
    if cid.strip()
]

# News filter — only Turkish border articles forwarded to main bot
# NOTE: Keep in sync with INCIDENT_KEYWORDS and BORDER_KEYWORDS in border_news_monitor.py
NEWS_INCIDENT_KEYWORDS = [
    # BG
    "килограм", "задържан", "задържаха", "задържа", "арест", "арестува",
    "наркотрафик", "наркот", "синтетич",
    "кокаин", "хероин", "хашиш", "марихуана", "скенк", "амфетамин",
    "контрабанда", "контрабанд", "трафикант", "трафик на хора",
    "нелегална миграция", "мигрант", "иззет", "иззеха", "иззе",
    "валута", "злато", "оръжи", "телефон", "блокада",
    "разкри", "установи", "откри", "намери", "спипа",
    "митнически", "гкпп", "гранич",
    # TR
    "uyuşturucu", "kaçakçılık", "kaçak", "esrar", "eroin", "kokain",
    "narkotik", "skank", "göçmen", "gümrük", "telefon",
    "yakalandı", "ele geçirildi",
    # EN
    "drug trafficking", "human trafficking", "smuggling",
    "illegal migration", "seized", "arrested", "detained",
]
TR_BORDER_LOCATIONS = [
    "капитан андреево", "лесово", "малко търново",
    "свиленград", "хасково", "харманли", "любимец",
    "турция", "турски",
    "kapıkule", "dereköy", "pazarkule", "edirne", "kırklareli",
]

TRUCK_KEYWORDS = [
    "обработени товарни превозни средства",
    "обработени товарни автомобили",
]
CHECKPOINTS = ["капитан андреево", "лесово", "калотина"]

# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CUSTOMS] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("customs_scraper.log", encoding="utf-8"),
    ]
)
log = logging.getLogger(__name__)

# ─── TIME ─────────────────────────────────────────────────────────────────────

def ankara_now():
    return datetime.now(timezone.utc) + timedelta(hours=ANKARA_UTC_OFFSET)

def is_quiet_hours() -> bool:
    h = ankara_now().hour
    return h >= QUIET_START_HOUR or h < QUIET_END_HOUR

# ─── PERSISTENCE ──────────────────────────────────────────────────────────────

def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def save_seen(seen: set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f)

def load_queue() -> list:
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_queue(queue: list):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

def load_truck_stats() -> list:
    if os.path.exists(TRUCK_STATS_FILE):
        try:
            with open(TRUCK_STATS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return sorted(data, key=lambda x: datetime.strptime(x["date"], "%d-%m-%Y"))
        except Exception:
            pass
    return []

def save_truck_stats(stats: list):
    with open(TRUCK_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

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
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
                timeout=10,
            )
            resp.raise_for_status()
            log.info(f"Telegram изпратено до {chat_id}.")
        except Exception as e:
            log.error(f"Telegram грешка ({chat_id}): {e}")

# ─── TRUCK STATS (direct HTTP — URL is predictable) ───────────────────────────

# All known truck URL slug variants — extended as new patterns are discovered
TRUCK_SLUGS = [
    "-kamioni",
    "-processed-trucks-bg",
    "-Processed-trucks",
    "%20-Processed-trucks",
    "-processed-trucks",
    "-Processed-Trucks",
]

def is_truck_url(url: str) -> bool:
    """Return True if a URL looks like a truck stats page."""
    url_lower = url.lower()
    return any(s.lower() in url_lower for s in TRUCK_SLUGS)

def fetch_truck_page(date_str: str, page, known_url: str | None = None) -> tuple | None:
    """
    Try all known truck slugs for a given date.
    If known_url is provided (discovered from media center index), try that first.
    """
    candidates = []
    if known_url:
        candidates.append(known_url)
    candidates += [f"{NEWS_DETAILS_BASE}/{date_str}{slug}" for slug in TRUCK_SLUGS]
    # Deduplicate preserving order
    seen_c = set()
    candidates = [u for u in candidates if not (u in seen_c or seen_c.add(u))]

    for url in candidates:
        try:
            page.goto(url, timeout=TIMEOUT_PW, wait_until="networkidle")
        except PWTimeout:
            log.debug(f"Timeout при {url}")
            continue
        except Exception as e:
            log.debug(f"Truck fetch грешка {url}: {e}")
            continue

        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        body = ""
        for sel in [".wpthemeMainContent", ".ibmMainContent", "main"]:
            tag = soup.select_one(sel)
            if tag:
                for noise in tag.select("nav, script, style"):
                    noise.decompose()
                body = tag.get_text(separator=" ", strip=True)
                break

        if not body:
            continue
        if not any(kw in body.lower() for kw in TRUCK_KEYWORDS):
            continue

        log.info(f"Kamioni {date_str}: намерена ({url.split('/')[-1]})")
        return url, body

    return None

def parse_truck_stats(body: str, url: str, date_str: str) -> dict | None:
    text = body.lower()
    stats = {"date": date_str, "url": url, "checkpoints": {}}
    for cp in CHECKPOINTS:
        idx = text.find(cp)
        if idx == -1:
            continue
        numbers = re.findall(r"\d{3,5}", text[idx: idx + 100])
        if len(numbers) >= 3:
            stats["checkpoints"][cp] = {
                "total": int(numbers[0]), "in": int(numbers[1]), "out": int(numbers[2])
            }
        elif len(numbers) == 1:
            stats["checkpoints"][cp] = {"total": int(numbers[0]), "in": None, "out": None}
    return stats if stats["checkpoints"] else None

def format_truck_message(stats: dict, prev: dict | None) -> str:
    date_display = stats["date"].replace("-", ".")
    lines = [f"🚛 <b>Товарни превозни средства — {date_display}</b>\n"]
    cp_display = {
        "капитан андреево": "Капитан Андреево",
        "лесово": "Лесово",
        "калотина": "Калотина",
    }
    for cp_key, cp_name in cp_display.items():
        cp = stats["checkpoints"].get(cp_key)
        if not cp:
            continue
        total = cp["total"]
        delta = ""
        if prev:
            prev_cp = prev["checkpoints"].get(cp_key)
            if prev_cp:
                diff = total - prev_cp["total"]
                arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
                delta = f"  <i>{arrow} {diff:+d} vs {prev['date'].replace('-','.')}</i>"
        if cp["in"] is not None:
            lines.append(
                f"📍 <b>{cp_name}</b>: {total:,} камиона{delta}\n"
                f"   ↳ Вход: {cp['in']:,} | Изход: {cp['out']:,}"
            )
        else:
            lines.append(f"📍 <b>{cp_name}</b>: {total:,} камиона{delta}")
    lines.append(f"\n🔗 <a href=\"{stats['url']}\">Агенция Митници</a>")
    return "\n".join(lines)

# ─── NEWS ARTICLES (Playwright — slug is unpredictable) ───────────────────────

def discover_news_articles(page) -> list[dict]:
    """
    Open the media center index in the browser.
    Extract article title + URL directly from .result-entry-title elements.
    Returns list of {"url": ..., "title": ...} dicts.
    """
    log.info("Playwright: зареждане на media center...")
    try:
        page.goto(BASE, timeout=TIMEOUT_PW, wait_until="networkidle")
    except PWTimeout:
        log.warning("Media center зареди бавно — продължаване с наличното.")

    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    articles = []
    truck_urls = []  # truck URLs discovered on the index page
    for div in soup.find_all("div", class_="result-entry-title"):
        a = div.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        if "/media-center/news-details/" not in href:
            continue
        full = href if href.startswith("http") else f"https://customs.bg{href}"
        if is_truck_url(full):
            truck_urls.append(full)  # capture for direct fetch
            continue
        title = a.get_text(strip=True)
        articles.append({"url": full, "title": title})

    log.info(f"Playwright: намерени {len(articles)} новинарски + {len(truck_urls)} камиони линка.")
    return list({a["url"]: a for a in articles}.values()), truck_urls


def is_news_relevant(text: str) -> bool:
    """Check article text against incident keywords."""
    text = text.lower()
    return any(kw in text for kw in NEWS_INCIDENT_KEYWORDS)


def fetch_article_title_and_body(page, url: str) -> tuple[str, str] | None:
    """
    Open the article page in the browser and extract the full title and body.
    Returns (title, body) or None if page fails to load.
    """
    try:
        page.goto(url, timeout=TIMEOUT_PW, wait_until="networkidle")
    except PWTimeout:
        try:
            page.goto(url, timeout=TIMEOUT_PW, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
        except Exception:
            return None

    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    for sel in ["h1.wpthemeHeading1", "h1", ".wpthemeMainContent h2", "h2"]:
        tag = soup.select_one(sel)
        if tag and len(tag.get_text(strip=True)) > 5:
            title = tag.get_text(strip=True)
            break

    body = ""
    for sel in [".wpthemeMainContent", ".ibmMainContent", "main"]:
        tag = soup.select_one(sel)
        if tag:
            for noise in tag.select("nav, script, style"):
                noise.decompose()
            body = tag.get_text(separator=" ", strip=True)
            break

    if not title and not body:
        return None
    return title, body[:800]

# ─── MAIN SCRAPE PASS ─────────────────────────────────────────────────────────

def scrape_once(seen: set, pw_browser) -> tuple:
    today = datetime.now(timezone.utc)
    new_news = []
    truck_history = load_truck_stats()
    sent_truck_dates = {s["date"] for s in truck_history}

    # ── 1 & 2. Single page object used for both truck stats and news ─────────
    page = pw_browser.new_page()
    try:
        # Truck stats (Playwright, last 3 days)
        for d in range(3):
            ds = (today - timedelta(days=d)).strftime("%d-%m-%Y")
            if ds in sent_truck_dates:
                continue
            result = fetch_truck_page(ds, page, known_url=None)
            if result:
                url, body = result
                stats = parse_truck_stats(body, url, ds)
                if stats:
                    sorted_history = sorted(truck_history, key=lambda x: datetime.strptime(x["date"], "%d-%m-%Y"))
                    prev = next((s for s in reversed(sorted_history) if s["date"] != ds), None)
                    dod_text = format_truck_message(stats, prev)
                    truck_history.append(stats)
                    save_truck_stats(truck_history)
                    sent_truck_dates.add(ds)
                    log.info(f"✅ Камиони {ds}: {stats['checkpoints']}")
                    try:
                        from truck_charts import generate_and_send_charts
                        generate_and_send_charts(dod_text=dod_text)
                    except Exception as e:
                        log.error(f"Грешка при генериране на графики: {e}")

        # News articles (Playwright) + discovered truck URLs from index
        articles_on_page, discovered_truck_urls = discover_news_articles(page)

        # Process any truck URLs found on the index page directly
        for truck_url in discovered_truck_urls:
            if truck_url in seen:
                log.info(f"  — вече видяна (камиони): {truck_url.split('/')[-1]}")
                continue
            seen.add(truck_url)
            import re as _re
            m = _re.search(r"(\d{2}-\d{2}-\d{4})", truck_url)
            if not m:
                continue
            ds = m.group(1)
            if ds in sent_truck_dates:
                continue
            result = fetch_truck_page(ds, page, known_url=truck_url)
            if result:
                url, body = result
                stats = parse_truck_stats(body, url, ds)
                if stats:
                    sorted_history = sorted(truck_history, key=lambda x: datetime.strptime(x["date"], "%d-%m-%Y"))
                    prev = next((s for s in reversed(sorted_history) if s["date"] != ds), None)
                    dod_text = format_truck_message(stats, prev)
                    truck_history.append(stats)
                    save_truck_stats(truck_history)
                    sent_truck_dates.add(ds)
                    log.info(f"✅ Камиони (от индекс) {ds}: {stats['checkpoints']}")
                    try:
                        from truck_charts import generate_and_send_charts
                        generate_and_send_charts(dod_text=dod_text)
                    except Exception as e:
                        log.error(f"Грешка при генериране на графики: {e}")

        for art in articles_on_page:
            url   = art["url"]
            title = art["title"]
            if url in seen:
                log.info(f"  — вече видяна: {url.split('/')[-1]}")
                continue
            seen.add(url)

                        # Fetch actual article page to get full title + body for reliable filtering
            article_data = fetch_article_title_and_body(page, url)
            if article_data is None:
                log.info(f"  — не може да се зареди: {url.split('/')[-1]}")
                continue

            full_title, full_body = article_data
            full_text = full_title + " " + full_body

            if not is_news_relevant(full_text):
                log.info(f"  — нерелевантна: {full_title[:60]}")
                continue

            log.info(f"✅ Новина: {full_title[:80]}")
            new_news.append({
                "id":       hashlib.md5(url.encode()).hexdigest(),
                "title":    f"[МИТНИЦИ] {full_title}",
                "summary":  full_body,
                "link":     url,
                "domain":   "customs.bg",
                "lang":     "bg",
                "label":    "customs.bg",
                "date":     datetime.now(timezone.utc).isoformat(),
                "date_str": datetime.now().strftime("%d.%m.%Y %H:%M"),
            })

    finally:
        page.close()

    return new_news, seen

# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

def main():
    log.info("=" * 50)
    log.info("Customs.bg Scraper стартиран (Playwright)")
    log.info(f"  Интервал:   {CHECK_INTERVAL // 60} мин")
    log.info(f"  News queue: {QUEUE_FILE}")
    log.info(f"  Truck log:  {TRUCK_STATS_FILE}")
    log.info("=" * 50)

    seen = load_seen()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        log.info("Браузър стартиран.")

        # ── Prime seen set on first run ───────────────────────────────────────
        # Mark everything currently on the site as already seen so we only
        # alert on articles that appear AFTER this script first starts.
        if not seen:
            log.info("Първо стартиране — зареждане на съществуващи линкове (без изпращане)...")
            page = browser.new_page()
            try:
                existing, _ = discover_news_articles(page)
                for art in existing:
                    seen.add(art["url"])
                # NOTE: kamioni URLs are NOT primed here — truck dedup is handled
                # by sent_truck_dates (truck_stats.json), so they always get fetched
                # and checked on first run.
                save_seen(seen)
                log.info(f"Прайминг завършен — {len(seen)} новинарски URL-а маркирани като видяни.")
            finally:
                page.close()

        try:
            while True:
                log.info("Проверка на customs.bg...")
                new_news, seen = scrape_once(seen, browser)
                save_seen(seen)

                if new_news:
                    queue = load_queue()
                    queue.extend(new_news)
                    queue = queue[-50:]
                    save_queue(queue)
                    log.info(f"Добавени {len(new_news)} новини в queue.")
                else:
                    log.info("Няма нови новини.")

                if is_quiet_hours():
                    now       = ankara_now()
                    wake_time = now.replace(hour=QUIET_END_HOUR, minute=0, second=0, microsecond=0)
                    if now.hour >= QUIET_START_HOUR:
                        wake_time += timedelta(days=1)
                    sleep_secs = max(60, (wake_time - now).total_seconds())
                    log.info(f"Тихи часове — спи до 0{QUIET_END_HOUR}:00 Анкара ({int(sleep_secs // 60)} мин).")
                    time.sleep(sleep_secs)
                else:
                    log.info(f"Почивка {CHECK_INTERVAL // 60} мин...")
                    time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            log.info("Спиране...")
        finally:
            browser.close()
            log.info("Браузър затворен.")


if __name__ == "__main__":
    main()