#!/usr/bin/env python3
"""
preview_charts.py — Export combined truck chart as PNG locally (no Telegram)
Run: python preview_charts.py
"""

import os
import matplotlib
matplotlib.use("Agg")
from truck_charts import load_stats, build_combined_chart

data = load_stats()
if not data:
    print("Няма данни в truck_stats.json")
    exit()

print(f"Заредени {len(data)} записа. Генериране...")
img  = build_combined_chart(data)
fname = "truck_charts_preview.png"
with open(fname, "wb") as f:
    f.write(img)
print(f"✓ Запазено: {fname}")
os.startfile(fname)