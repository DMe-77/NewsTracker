#!/usr/bin/env python3
"""
truck_charts.py — Generate and send a single combined YTD truck chart to Telegram
One tall PNG with 3 subplots (one per checkpoint), sent as a single image.
"""

import json, os, io
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as ticker
from datetime import datetime, timezone
import numpy as np
from PIL import Image

# ─── CONFIG ───────────────────────────────────────────────────────────────────

TRUCK_STATS_FILE   = "truck_stats.json"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_IDS  = [
    cid.strip()
    for cid in os.getenv("TELEGRAM_CHAT_IDS", os.getenv("TELEGRAM_CHAT_ID", "")).split(",")
    if cid.strip()
]

CHECKPOINTS = {
    "капитан андреево": "Капитан Андреево",
    "лесово":           "Лесово",
    "калотина":         "Калотина",
}

# ─── PALETTE ──────────────────────────────────────────────────────────────────

BG_DARK      = "#0d1117"
BG_CARD      = "#161b22"
GRID_COLOR   = "#21262d"
TEXT_PRIMARY = "#e6edf3"
TEXT_DIM     = "#8b949e"
ACCENT_IN    = "#3fb950"
ACCENT_OUT   = "#f78166"
BORDER_COLOR = "#30363d"

# ─── LOAD DATA ────────────────────────────────────────────────────────────────

def load_stats() -> list:
    if os.path.exists(TRUCK_STATS_FILE):
        with open(TRUCK_STATS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return sorted(data, key=lambda x: datetime.strptime(x["date"], "%d-%m-%Y"))
    return []

def prepare_series(data: list, cp_key: str):
    dates, ins, outs = [], [], []
    for e in data:
        cp = e["checkpoints"].get(cp_key)
        if not cp:
            continue
        try:
            d = datetime.strptime(e["date"], "%d-%m-%Y")
        except ValueError:
            continue
        dates.append(d)
        ins.append(cp["in"]   if cp.get("in")  is not None else np.nan)
        outs.append(cp["out"] if cp.get("out") is not None else np.nan)
    return dates, ins, outs

# ─── COMBINED CHART ───────────────────────────────────────────────────────────

def build_combined_chart(data: list) -> bytes:
    year    = datetime.now(timezone.utc).year
    x_start = datetime(year, 1, 1)
    today   = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    # Show up to 3 months ahead of latest data point, capped at Dec 31
    all_dates = []
    for cp_key in CHECKPOINTS:
        d, _, _ = prepare_series(data, cp_key)
        all_dates.extend(d)
    last_data = max(all_dates) if all_dates else today
    from dateutil.relativedelta import relativedelta
    x_end_raw = last_data + relativedelta(months=3)
    x_end     = min(x_end_raw, datetime(year, 12, 31))
    now_str = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")

    fig, axes = plt.subplots(
        3, 1,
        figsize=(13, 15),
        facecolor=BG_DARK,
    )
    fig.subplots_adjust(
        left=0.07, right=0.96,
        top=0.90, bottom=0.04,
        hspace=0.55,
    )

    # ── Logo top right ────────────────────────────────────────────────────────
    logo_path = "Logo.PNG"
    if not os.path.exists(logo_path):
        logo_path = "Logo.png"
    if os.path.exists(logo_path):
        logo_ax = fig.add_axes([0.84, 0.955, 0.13, 0.055], anchor="NE")
        logo_img = Image.open(logo_path).convert("RGBA")
        logo_ax.imshow(logo_img)
        logo_ax.axis("off")

    # ── Main title ────────────────────────────────────────────────────────────
    fig.text(
        0.07, 0.985,
        f"Товарни превозни средства — YTD {year}",
        color=TEXT_PRIMARY, fontsize=15, fontweight="bold",
        ha="left", va="top",
    )
    fig.text(
        0.07, 0.970,
        f"Агенция Митници  ·  OSINT Border Monitor @BG_TR_BorderBot  ·  {now_str}",
        color=TEXT_DIM, fontsize=8.5,
        ha="left", va="top",
    )

    for ax, (cp_key, cp_name) in zip(axes, CHECKPOINTS.items()):
        dates, ins, outs = prepare_series(data, cp_key)
        last_date = max(dates) if dates else today

        # Panel background & spines
        ax.set_facecolor(BG_CARD)
        ax.set_axisbelow(True)
        ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.7, linestyle="--", alpha=0.8)
        ax.xaxis.grid(True, color=GRID_COLOR, linewidth=0.4, linestyle=":", alpha=0.5)
        for spine in ax.spines.values():
            spine.set_color(BORDER_COLOR)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        # Lines
        if dates:
            ax.plot(dates, ins,  color=ACCENT_IN,  linewidth=1.8, marker="o",
                    markersize=3, label="Вход в България",   zorder=3)
            ax.plot(dates, outs, color=ACCENT_OUT, linewidth=1.8, marker="o",
                    markersize=3, label="Изход от България", zorder=3)
            ax.fill_between(dates, ins, outs, alpha=0.06, color=TEXT_DIM)

            # Latest value labels — placed to the right of the last point
            for series, color in [(ins, ACCENT_IN), (outs, ACCENT_OUT)]:
                last_val = next((v for v in reversed(series) if not np.isnan(v)), None)
                if last_val:
                    ax.annotate(
                        f"{int(last_val):,}",
                        xy=(last_date, last_val),
                        xytext=(7, 0),
                        textcoords="offset points",
                        color=color, fontsize=8, fontweight="bold",
                        va="center",
                    )

        # X axis — full year, month labels
        ax.set_xlim(x_start, x_end)
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        plt.setp(ax.xaxis.get_majorticklabels(), color=TEXT_DIM, fontsize=8.5)

        # Y axis
        ax.yaxis.set_major_formatter(
            ticker.FuncFormatter(lambda x, _: f"{int(x):,}")
        )
        plt.setp(ax.yaxis.get_majorticklabels(), color=TEXT_DIM, fontsize=8.5)
        ax.tick_params(colors=TEXT_DIM, which="both", length=3)

        # Today marker
        ax.axvline(today, color=TEXT_DIM, linewidth=0.8, linestyle="--", alpha=0.4, zorder=1)

        # Checkpoint title — above the axes area, no overlap
        ax.set_title(
            f"ГКПП {cp_name}",
            color=TEXT_PRIMARY, fontsize=11, fontweight="bold",
            loc="left", pad=10,
        )

        # Subtitle with data count — below x axis
        ax.text(
            0.0, -0.14,
            f"{len(dates)} дни с данни  ·  последна: {last_date.strftime('%d.%m.%Y')}",
            transform=ax.transAxes,
            color=TEXT_DIM, fontsize=7.5,
        )

        # Legend — inside plot, top right, small
        legend = ax.legend(
            loc="upper right",
            frameon=True,
            framealpha=0.2,
            edgecolor=BORDER_COLOR,
            labelcolor=TEXT_PRIMARY,
            fontsize=8,
            handlelength=1.5,
            borderpad=0.5,
        )
        legend.get_frame().set_facecolor(BG_CARD)



    buf = io.BytesIO()
    plt.savefig(
        buf, format="png", dpi=150,
        facecolor=BG_DARK, bbox_inches="tight", pad_inches=0.2,
    )
    plt.close(fig)
    buf.seek(0)
    return buf.read()

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

def send_chart(image_bytes: bytes, dod_text: str = ""):
    """Send chart image with DoD text as caption."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_IDS:
        print("Telegram не е конфигуриран (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_IDS).")
        return
    year = datetime.now(timezone.utc).year
    # Telegram caption limit is 1024 chars
    caption = (dod_text[:1020] + "…") if len(dod_text) > 1024 else dod_text
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"photo": ("truck_charts.png", image_bytes, "image/png")},
                timeout=30,
            )
        except Exception as e:
            print(f"Telegram грешка ({chat_id}): {e}")

# ─── ENTRY POINTS ─────────────────────────────────────────────────────────────

def generate_and_send_charts(data: list | None = None, dod_text: str = ""):
    """
    Generate combined chart and send with DoD text as caption.
    Pass dod_text from customs_scraper to merge into one message.
    """
    if data is None:
        data = load_stats()
    if not data:
        print("Няма данни в truck_stats.json")
        return
    print("Генериране на комбинирана графика...")
    img = build_combined_chart(data)
    send_chart(img, dod_text=dod_text)
    print("✓ Изпратено.")


if __name__ == "__main__":
    generate_and_send_charts()