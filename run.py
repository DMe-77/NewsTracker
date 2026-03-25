#!/usr/bin/env python3
"""
run.py — Launcher for OSINT Border Monitor
Starts border_news_monitor.py and customs_scraper.py in parallel.
If either crashes it restarts it automatically after 30 seconds.

Usage:
    python run.py
"""

import subprocess
import sys
import time
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [LAUNCHER] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

PYTHON      = sys.executable
BASE_DIR    = Path(__file__).parent
RESTART_DELAY = 30  # seconds before restarting a crashed script

SCRIPTS = [
    BASE_DIR / "border_news_monitor.py",
    BASE_DIR / "customs_scraper.py",
]


def launch(script: Path) -> subprocess.Popen:
    log.info(f"Стартиране: {script.name}")
    return subprocess.Popen(
        [PYTHON, str(script)],
        cwd=BASE_DIR,
    )


def main():
    log.info("=" * 50)
    log.info("OSINT Launcher стартиран")
    for s in SCRIPTS:
        if not s.exists():
            log.error(f"Не е намерен файл: {s}")
            sys.exit(1)
    log.info("=" * 50)

    processes = {script: launch(script) for script in SCRIPTS}

    try:
        while True:
            for script, proc in list(processes.items()):
                ret = proc.poll()
                if ret is not None:
                    log.warning(f"{script.name} спря (код {ret}). Рестарт след {RESTART_DELAY}с...")
                    time.sleep(RESTART_DELAY)
                    processes[script] = launch(script)
            time.sleep(5)
    except KeyboardInterrupt:
        log.info("Спиране...")
        for script, proc in processes.items():
            proc.terminate()
            log.info(f"  Спрян: {script.name}")


if __name__ == "__main__":
    main()