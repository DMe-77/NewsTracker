#!/usr/bin/env python3
"""
weekly_summary.py — Weekly incident summary for OSINT Border Monitor
Imported by border_news_monitor.py, checked every cycle.

Fires every Monday at 08:00 Ankara time (UTC+3).
Reads the last 7 days from incident_log.json and sends a structured
summary to Telegram. No LLM needed — pure data from the incident log.

State tracked in weekly_summary_state.json to ensure it fires exactly
once per Monday.
"""

import os, json, logging
from collections import Counter
from datetime import datetime, timezone, timedelta
from incident_logger import get_incidents

STATE_FILE        = "weekly_summary_state.json"
ANKARA_UTC_OFFSET = 3
FIRE_HOUR         = 8    # 08:00 Ankara
FIRE_WEEKDAY      = 0    # Monday (0=Mon … 6=Sun)

log = logging.getLogger(__name__)

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

def ankara_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=ANKARA_UTC_OFFSET)

def should_fire() -> bool:
    now = ankara_now()
    return now.weekday() == FIRE_WEEKDAY and now.hour == FIRE_HOUR

def already_sent_this_week(state: dict) -> bool:
    """Check if summary was already sent this Monday."""
    now   = ankara_now()
    # ISO week string e.g. "2026-W11"
    week  = now.strftime("%Y-W%W")
    return state.get("last_sent_week") == week

def mark_sent(state: dict) -> dict:
    now  = ankara_now()
    week = now.strftime("%Y-W%W")
    state["last_sent_week"] = week
    return state

# ─── SUMMARY BUILDER ──────────────────────────────────────────────────────────

TYPE_BG = {
    "наркотици":   "Наркотици",
    "контрабанда": "Контрабанда",
    "миграция":    "Миграция",
    "задържане":   "Задържания",
    "друго":       "Друго",
}

STATUS_EMOJI = {
    "Критично":   "🔴",
    "Важно":      "🟡",
    "Информация": "🔵",
}

def build_summary(incidents: list) -> str:
    if not incidents:
        return (
            "🇧🇬🇹🇷 <b>Седмичен доклад</b>\n\n"
            "📭 Няма регистрирани инциденти за изминалата седмица."
        )

    total      = len(incidents)
    confirmed  = sum(1 for e in incidents if e.get("confirmed"))

    # Date range
    dates      = sorted(e["date"] for e in incidents if e.get("date"))
    date_range = f"{dates[0]} – {dates[-1]}" if len(dates) > 1 else dates[0] if dates else "н/д"

    # By status
    by_status  = Counter(e.get("status", "Информация") for e in incidents)

    # By type
    by_type    = Counter(e.get("type", "друго") for e in incidents)

    # By location — top 3
    by_location = Counter(e.get("location", "Неизвестно") for e in incidents)
    top_locations = by_location.most_common(3)

    # Most active day
    by_day = Counter(
        datetime.fromisoformat(e["timestamp"]).strftime("%A")
        for e in incidents if e.get("timestamp")
    )
    DAY_BG = {
        "Monday": "Понеделник", "Tuesday": "Вторник", "Wednesday": "Сряда",
        "Thursday": "Четвъртък", "Friday": "Петък",
        "Saturday": "Събота", "Sunday": "Неделя",
    }
    busiest_day_en, busiest_count = by_day.most_common(1)[0] if by_day else ("—", 0)
    busiest_day = DAY_BG.get(busiest_day_en, busiest_day_en)

    # ── Build message ──────────────────────────────────────────────────────────
    now   = ankara_now()
    week  = now.strftime("%W")
    year  = now.strftime("%Y")

    lines = [
        f"🇧🇬🇹🇷 <b>Седмичен доклад — Седмица {week}, {year}</b>",
        f"📅 {date_range}",
        "",
        f"📊 <b>Общо инциденти: {total}</b>",
        f"   🔁 Потвърдени от 2+ езика: {confirmed}",
        "",
        "🚨 <b>По статус:</b>",
    ]

    for status in ["Критично", "Важно", "Информация"]:
        count = by_status.get(status, 0)
        if count:
            emoji = STATUS_EMOJI.get(status, "⚪")
            lines.append(f"   {emoji} {status}: {count}")

    lines += ["", "🔎 <b>По вид:</b>"]
    for inc_type, count in by_type.most_common():
        label = TYPE_BG.get(inc_type, inc_type)
        lines.append(f"   • {label}: {count}")

    lines += ["", "📍 <b>Топ локации:</b>"]
    for location, count in top_locations:
        lines.append(f"   • {location}: {count}")

    lines += [
        "",
        f"📆 <b>Най-активен ден:</b> {busiest_day} ({busiest_count} инцидента)",
    ]

    return "\n".join(lines)

# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────

def check_weekly_summary(send_fn) -> bool:
    """
    Check if it's time to send the weekly summary.
    Called every cycle from border_news_monitor.py.
    Returns True if summary was sent.
    """
    if not should_fire():
        return False

    state = load_state()
    if already_sent_this_week(state):
        return False

    log.info("[WEEKLY] Генериране на седмичен доклад...")
    incidents = get_incidents(days_back=7)
    message   = build_summary(incidents)

    try:
        send_fn(message)
        state = mark_sent(state)
        save_state(state)
        log.info(f"[WEEKLY] Изпратен — {len(incidents)} инцидента.")
        return True
    except Exception as e:
        log.error(f"[WEEKLY] Грешка при изпращане: {e}")
        return False