#!/usr/bin/env python3
"""
incident_logger.py — Incident Log for OSINT Border Monitor
Imported by border_news_monitor.py after every successful Telegram send.

Log file: incident_log.json
Each entry:
{
    "id":         "md5 fingerprint",
    "timestamp":  "2026-03-12T14:10:00+00:00",
    "date":       "12.03.2026",
    "time":       "14:10",
    "status":     "Критично" | "Важно" | "Информация",
    "location":   "Капитан Андреево",
    "type":       "наркотици" | "контрабанда" | "миграция" | "друго",
    "headline":   "Преведено заглавие от LLM",
    "sources":    ["marica.bg", "sabah.com.tr"],
    "langs":      {"bg": 2, "tr": 1, "en": 0},
    "confirmed":  true | false,
    "link":       "https://..."
}
"""

import os, json, re, hashlib
from datetime import datetime, timezone

LOG_FILE = "incident_log.json"

# ─── INCIDENT TYPE CLASSIFIER ─────────────────────────────────────────────────
# Keywords are sourced directly from border_news_monitor.py to stay in sync.
# We map subsets of the shared keywords to incident types.

TYPE_KEYWORDS = {
    "наркотици": [
        "наркотрафик", "наркот", "хашиш", "хероин", "кокаин", "марихуана",
        "uyuşturucu", "esrar", "eroin", "kokain", "narkotik", "skank",
        "drug trafficking",
    ],
    "контрабанда": [
        "контрабанда", "контрабанд", "злато", "оръжи", "телефон",
        "kaçakçılık", "gümrük", "telefon", "smuggling",
    ],
    "миграция": [
        "трафик на хора", "нелегална миграция", "трафикант", "мигрант",
        "göçmen", "kaçak", "human trafficking", "illegal migration",
    ],
    "задържане": [
        "задържан", "арест",
        "yakalandı",
        "arrested", "detained",
    ],
}

def classify_type(text: str) -> str:
    """Classify incident type using the same keyword taxonomy as the main bot."""
    text = text.lower()
    for incident_type, keywords in TYPE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return incident_type
    return "друго"

# ─── FIELD EXTRACTORS ─────────────────────────────────────────────────────────

def extract_status(analysis: str) -> str:
    m = re.search(r"Статус:\s*(Критично|Важно|Информация)", analysis)
    return m.group(1) if m else "Информация"

def extract_location(analysis: str) -> str:
    m = re.search(r"📍\s*(?:Локация:\s*)?(.+)", analysis)
    if m:
        return m.group(1).strip().split("\n")[0].strip()
    return "Неизвестно"

def extract_headline(analysis: str) -> str:
    """Extract the 📰 translated headline line."""
    m = re.search(r"📰\s*(.+)", analysis)
    if m:
        return m.group(1).strip().split("\n")[0].strip()
    return ""

# ─── LOAD / SAVE ──────────────────────────────────────────────────────────────

def load_log() -> list:
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_log(log: list):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

# ─── MAIN FUNCTION (called by border_news_monitor.py) ─────────────────────────

def log_incident(cluster: list[dict], analysis: str, confirmed: bool = False) -> dict:
    """
    Build and append an incident entry to the log.
    Returns the entry dict.
    """
    now        = datetime.now(timezone.utc)
    status     = extract_status(analysis)
    location   = extract_location(analysis)
    headline   = extract_headline(analysis)
    combined   = " ".join(a["title"] for a in cluster)
    inc_type   = classify_type(combined + " " + analysis)

    langs = {"bg": 0, "tr": 0, "en": 0}
    for a in cluster:
        lang = a.get("lang", "")
        if lang in langs:
            langs[lang] += 1

    sources = list({a.get("domain") or a.get("label", "") for a in cluster})
    link    = next((a["link"] for a in cluster if a.get("link") and "google.com" not in a.get("link","")), "")

    fingerprint = hashlib.md5((now.date().isoformat() + location + inc_type).encode()).hexdigest()[:12]

    entry = {
        "id":        fingerprint,
        "timestamp": now.isoformat(),
        "date":      now.strftime("%d.%m.%Y"),
        "time":      now.strftime("%H:%M"),
        "status":    status,
        "location":  location,
        "type":      inc_type,
        "headline":  headline,
        "sources":   sources,
        "langs":     langs,
        "confirmed": confirmed,
        "link":      link,
    }

    log = load_log()
    log.append(entry)
    save_log(log)
    return entry

# ─── QUERY HELPERS (used by pattern alerts + weekly summary) ──────────────────

def get_incidents(days_back: int = 7) -> list:
    """Return incidents from the last N days, newest first."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
    log = load_log()
    return [e for e in reversed(log) if e.get("timestamp", "") >= cutoff]

def get_incidents_by_location(location: str, days_back: int = 7) -> list:
    return [e for e in get_incidents(days_back) if location.lower() in e.get("location", "").lower()]

def get_incidents_by_type(inc_type: str, days_back: int = 7) -> list:
    return [e for e in get_incidents(days_back) if e.get("type") == inc_type]

def count_by_location(days_back: int = 7) -> dict:
    """Returns {location: count} sorted by count desc."""
    from collections import Counter
    counts = Counter(e["location"] for e in get_incidents(days_back))
    return dict(counts.most_common())

def count_by_type(days_back: int = 7) -> dict:
    from collections import Counter
    counts = Counter(e["type"] for e in get_incidents(days_back))
    return dict(counts.most_common())