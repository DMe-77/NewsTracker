#!/usr/bin/env python3
"""
pattern_alerts.py — Pattern detection for OSINT Border Monitor
Imported by border_news_monitor.py after every log_incident() call.

Patterns detected:
  1. Same location, 3+ unique incidents in 7 days
  2. Same type, 3+ unique incidents in 7 days
  3. 2+ Критично incidents in the last 24 hours

Each pattern fires at most once per calendar day to prevent spam.
State is stored in pattern_alerts_state.json.

Deduplication: counts are based on incident log entries, which are
already one-per-alert (not one-per-article), so cluster dedup is
inherited from the main bot's sent_events logic.
"""

import os, json, logging
from datetime import datetime, timezone, timedelta
from incident_logger import get_incidents, count_by_location, count_by_type

STATE_FILE = "pattern_alerts_state.json"
log = logging.getLogger(__name__)

# ─── THRESHOLDS ───────────────────────────────────────────────────────────────

LOCATION_THRESHOLD   = 3   # incidents at same location within 7 days
TYPE_THRESHOLD       = 3   # incidents of same type within 7 days
CRITICAL_THRESHOLD   = 2   # Критично incidents within 24 hours

# ─── STATE ────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def already_fired_today(state: dict, key: str) -> bool:
    """Return True if this pattern alert already fired today (UTC date)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return state.get(key) == today

def mark_fired(state: dict, key: str) -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state[key] = today
    return state

# ─── PATTERN CHECKS ───────────────────────────────────────────────────────────

def check_location_pattern(state: dict) -> list[str]:
    """Fire if any location has 3+ unique incidents in the last 7 days."""
    alerts = []
    counts = count_by_location(days_back=7)
    for location, count in counts.items():
        if count >= LOCATION_THRESHOLD:
            key = f"location:{location}"
            if not already_fired_today(state, key):
                alerts.append((key, (
                    f"⚠️ <b>Повишена активност</b>\n"
                    f"📍 {location} — {count} инцидента за последните 7 дни"
                )))
    return alerts


def check_type_pattern(state: dict) -> list[str]:
    """Fire if any incident type has 3+ unique incidents in the last 7 days."""
    TYPE_LABELS = {
        "наркотици":  "наркотици",
        "контрабанда": "контрабанда",
        "миграция":   "нелегална миграция",
        "задържане":  "задържания",
        "друго":      "инциденти",
    }
    alerts = []
    counts = count_by_type(days_back=7)
    for inc_type, count in counts.items():
        if count >= TYPE_THRESHOLD:
            key = f"type:{inc_type}"
            if not already_fired_today(state, key):
                label = TYPE_LABELS.get(inc_type, inc_type)
                alerts.append((key, (
                    f"📈 <b>Тенденция</b>\n"
                    f"🔎 {count} случая на {label} за последните 7 дни"
                )))
    return alerts


def check_critical_pattern(state: dict) -> list[str]:
    """Fire if 2+ Критично incidents occurred in the last 24 hours."""
    key = "critical:24h"
    if already_fired_today(state, key):
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent = [
        e for e in get_incidents(days_back=2)
        if e.get("status") == "Критично" and e.get("timestamp", "") >= cutoff
    ]
    if len(recent) >= CRITICAL_THRESHOLD:
        locations = ", ".join({e["location"] for e in recent})
        return [(key, (
            f"🔴 <b>Ескалация</b>\n"
            f"🚨 {len(recent)} критични инцидента за последните 24 часа\n"
            f"📍 {locations}"
        ))]
    return []

# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────

def check_patterns(send_fn) -> int:
    """
    Run all pattern checks and send alerts via send_fn(message).
    Returns number of alerts fired.
    Called by border_news_monitor.py after log_incident().

    send_fn should be the bot's send_telegram() function.
    """
    state   = load_state()
    fired   = 0
    alerts  = []

    alerts += check_location_pattern(state)
    alerts += check_type_pattern(state)
    alerts += check_critical_pattern(state)

    for key, message in alerts:
        try:
            full_message = f"🇧🇬🇹🇷 <b>OSINT — Засечена закономерност</b>\n\n{message}"
            send_fn(full_message)
            state = mark_fired(state, key)
            fired += 1
            log.info(f"[PATTERNS] Изпратен алерт: {key}")
        except Exception as e:
            log.error(f"[PATTERNS] Грешка при изпращане ({key}): {e}")

    if fired:
        save_state(state)

    return fired