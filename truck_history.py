#!/usr/bin/env python3
"""
truck_history.py — YTD backfill with CAPTCHA recovery
Run once:  python truck_history.py

Tries all known slug variants per date. If a CAPTCHA is detected,
closes the browser, waits a random cooldown, then reopens and resumes
from the exact date it was on. Reports gaps at the end.

Add any manually found URLs to MANUAL_OVERRIDES if gaps remain.
"""

import json, os, re, time, random
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ─── CONFIG ───────────────────────────────────────────────────────────────────

TRUCK_STATS_FILE  = "truck_stats.json"
BASE              = "https://customs.bg/wps/portal/agency/media-center/news-details"
START_DATE        = datetime(2026, 1, 1, tzinfo=timezone.utc)
TIMEOUT_PW        = 15_000
DELAY_MIN         = 3.0    # min seconds between date fetches
DELAY_MAX         = 8.0    # max seconds between date fetches
CAPTCHA_COOLDOWN_MIN = 60  # min seconds to wait after CAPTCHA
CAPTCHA_COOLDOWN_MAX = 180 # max seconds to wait after CAPTCHA
MAX_CAPTCHA_RETRIES  = 5   # give up after this many CAPTCHAs in a row

CHECKPOINTS    = ["капитан андреево", "лесово", "калотина"]
TRUCK_KEYWORDS = [
    "обработени товарни превозни средства",
    "обработени товарни автомобили",
    "processed trucks",
]
CAPTCHA_SIGNALS = [
    "what code is in the image",
    "testing whether you are a human visitor",
    "prevent automated spam submission",
]

SLUG_VARIANTS = [
    "-kamioni",
    "-Processed-trucks",
    "%20-Processed-trucks",
    "-processed-trucks-bg",
    "-processed-trucks",
    "-Processed-Trucks",
    "-kamion",
]

MANUAL_OVERRIDES = {
    "27-02-2026": "https://customs.bg/wps/portal/agency/media-center/news-details/27-02-26-kamioni",
    "16-01-2026": "https://customs.bg/wps/portal/agency/media-center/news-details/16-01-2026-Preocessed-trucks",
}

# ─── LOAD / SAVE ──────────────────────────────────────────────────────────────

def load_stats() -> list:
    if os.path.exists(TRUCK_STATS_FILE):
        try:
            with open(TRUCK_STATS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_stats(stats: list):
    with open(TRUCK_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

# ─── BROWSER FACTORY ──────────────────────────────────────────────────────────

def new_browser(pw):
    browser = pw.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        locale="bg-BG",
        viewport={"width": 1366, "height": 768},
    )
    context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    page = context.new_page()
    return browser, context, page

# ─── CAPTCHA DETECTION ────────────────────────────────────────────────────────

def is_captcha(body: str) -> bool:
    body_lower = body.lower()
    return any(signal in body_lower for signal in CAPTCHA_SIGNALS)

# ─── FETCH & PARSE ────────────────────────────────────────────────────────────

CAPTCHA_BODY = "__CAPTCHA__"

def fetch_body(page, url: str) -> str | None:
    try:
        page.goto(url, timeout=TIMEOUT_PW, wait_until="networkidle")
    except PWTimeout:
        try:
            page.goto(url, timeout=TIMEOUT_PW, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
        except Exception:
            return None

    html  = page.content()

    # Check for CAPTCHA in raw HTML before any parsing
    if any(s in html.lower() for s in CAPTCHA_SIGNALS):
        return CAPTCHA_BODY

    soup = BeautifulSoup(html, "html.parser")
    for sel in [".wpthemeMainContent", ".ibmMainContent", "main"]:
        tag = soup.select_one(sel)
        if tag:
            for noise in tag.select("nav, script, style"):
                noise.decompose()
            body = tag.get_text(separator=" ", strip=True)
            if len(body) > 50:
                return body
    return None

def parse_body(body: str, url: str, date_str: str) -> dict | None:
    body_lower = body.lower()
    if not any(kw in body_lower for kw in TRUCK_KEYWORDS):
        return None

    stats = {"date": date_str, "url": url, "checkpoints": {}}
    for cp in CHECKPOINTS:
        idx = body_lower.find(cp)
        if idx == -1:
            continue
        numbers = re.findall(r"\d{3,5}", body_lower[idx: idx + 200])
        if len(numbers) >= 3:
            stats["checkpoints"][cp] = {
                "total": int(numbers[0]),
                "in":    int(numbers[1]),
                "out":   int(numbers[2]),
            }
        elif len(numbers) == 1:
            stats["checkpoints"][cp] = {
                "total": int(numbers[0]),
                "in":    None,
                "out":   None,
            }
    return stats if stats["checkpoints"] else None

# ─── TRY ONE DATE ─────────────────────────────────────────────────────────────

CAPTCHA_DETECTED = "CAPTCHA"

def try_date(page, ds: str) -> dict | str | None:
    """
    Try all slug variants for a date.
    Returns: parsed stats dict, "CAPTCHA" string, or None (not found).
    """
    if ds in MANUAL_OVERRIDES:
        url  = MANUAL_OVERRIDES[ds]
        body = fetch_body(page, url)
        if body:
            if is_captcha(body):
                return CAPTCHA_DETECTED
            return parse_body(body, url, ds)

    for slug in SLUG_VARIANTS:
        url  = f"{BASE}/{ds}{slug}"
        body = fetch_body(page, url)
        if body == CAPTCHA_BODY:
            return CAPTCHA_DETECTED
        if body:
            result = parse_body(body, url, ds)
            if result:
                return result
        time.sleep(random.uniform(0.3, 0.8))

    return None

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Truck History Backfill — YTD (CAPTCHA recovery enabled)")
    print("=" * 60)

    existing       = load_stats()
    existing_dates = {e["date"] for e in existing}

    today     = datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)

    dates, current = [], START_DATE
    while current <= yesterday:
        ds = current.strftime("%d-%m-%Y")
        if ds not in existing_dates:
            dates.append(ds)
        current += timedelta(days=1)

    print(f"Dates to fetch:  {len(dates)}  (skipping {len(existing_dates)} already in log)")
    print(f"Range: {START_DATE.strftime('%d.%m.%Y')} → {yesterday.strftime('%d.%m.%Y')}")
    print()

    fetched        = 0
    gaps           = []
    captcha_count  = 0
    i              = 0   # current index into dates — resumable

    with sync_playwright() as pw:
        browser, context, page = new_browser(pw)

        try:
            while i < len(dates):
                ds = dates[i]
                print(f"[{i+1:03d}/{len(dates)}] {ds} ... ", end="", flush=True)

                result = try_date(page, ds)

                if result == CAPTCHA_DETECTED:
                    captcha_count += 1
                    save_stats(existing)
                    print()
                    print("=" * 50)
                    print("⚠️  CAPTCHA открита!")
                    print("   1. Погледни браузъра")
                    print("   2. Въведи кода от картинката в полето")
                    print("   3. Натисни Submit/Изпрати в браузъра")
                    print("   4. Върни се тук и натисни ENTER")
                    print("=" * 50)
                    input("   [ENTER след като си решил CAPTCHA-та] ")

                    if captcha_count >= MAX_CAPTCHA_RETRIES:
                        print(f"Твърде много CAPTCHA-та ({captcha_count}). Спиране.")
                        break

                    print(f"  Продължаване от {ds}...")
                    # Don't advance i — retry same date
                    continue

                elif result:
                    existing.append(result)
                    existing_dates.add(ds)
                    slug_used = result["url"].split("/")[-1]
                    totals    = {cp: result["checkpoints"][cp]["total"]
                                 for cp in result["checkpoints"]}
                    print(f"✓  {slug_used}  {totals}")
                    fetched += 1
                    captcha_count = 0  # reset on success
                    if fetched % 5 == 0:
                        save_stats(existing)

                else:
                    print("— не е намерена")
                    gaps.append(ds)

                i += 1
                time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

        except KeyboardInterrupt:
            print("\nПрекъснато — записване...")
        finally:
            save_stats(existing)
            try:
                context.close()
            except Exception:
                pass

    print()
    print("=" * 60)
    print("Готово.")
    print(f"  ✓ Намерени и записани:   {fetched}")
    print(f"  Общо в truck_stats.json: {len(existing)}")
    print("=" * 60)

    if gaps:
        print(f"\n⚠️  Gaps ({len(gaps)} дати без данни):")
        print("   Добави в MANUAL_OVERRIDES ако намериш линковете:")
        for g in gaps:
            print(f"   \"{g}\": \"URL_ТУК\",")
    else:
        print("\n✅ Няма gaps!")

    print("\nСледваща стъпка: python truck_charts.py")


if __name__ == "__main__":
    main()