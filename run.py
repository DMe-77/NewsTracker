#!/usr/bin/env python3
"""
run.py — Unified local launcher for NewsTracker.

Starts and supervises:
- border_news_monitor.py
- customs_scraper.py
- intelligence-dashboard dev server (http://localhost:3000/NewsTracker)
- local docs web server fallback (http://localhost:8080)
- optional Cloudflare quick tunnel (if cloudflared is installed)

Also regenerates docs/data.json periodically via generate_web_data.py.

Usage:
    python run.py
"""

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [LAUNCHER] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

PYTHON = sys.executable
BASE_DIR = Path(__file__).parent
DOCS_DIR = BASE_DIR / "docs"
DASHBOARD_DIR = BASE_DIR / "intelligence-dashboard"
RESTART_DELAY = 30  # seconds before restarting a crashed script
DASHBOARD_PORT = 3000
DOCS_PORT = 8080
DATA_REFRESH_INTERVAL = 5 * 60
ENV_FILES = [BASE_DIR / ".env", BASE_DIR / ".env.local"]

SCRIPT_TARGETS = [
    BASE_DIR / "border_news_monitor.py",
    BASE_DIR / "customs_scraper.py",
]


def launch_python_script(script: Path) -> subprocess.Popen:
    log.info(f"Стартиране: {script.name}")
    return subprocess.Popen(
        [PYTHON, str(script)],
        cwd=BASE_DIR,
    )


def launch_docs_server() -> subprocess.Popen:
    log.info(f"Стартиране: docs web server на порт {DOCS_PORT}")
    return subprocess.Popen(
        [PYTHON, "-m", "http.server", str(DOCS_PORT)],
        cwd=DOCS_DIR,
    )


def launch_dashboard_server() -> subprocess.Popen | None:
    npm_path = shutil.which("npm")
    if not npm_path:
        return None
    log.info(f"Стартиране: dashboard dev server на порт {DASHBOARD_PORT}")
    return subprocess.Popen(
        [npm_path, "run", "dev", "--", "--port", str(DASHBOARD_PORT)],
        cwd=DASHBOARD_DIR,
    )


def launch_cloudflared_tunnel(target_port: int) -> subprocess.Popen | None:
    cloudflared_path = shutil.which("cloudflared")
    if not cloudflared_path:
        log.info("cloudflared не е намерен в PATH — tunnel няма да се стартира.")
        return None
    log.info("Стартиране: Cloudflare quick tunnel")
    return subprocess.Popen(
        [cloudflared_path, "tunnel", "--url", f"http://localhost:{target_port}"],
        cwd=BASE_DIR,
    )


def load_local_env_files() -> None:
    for env_file in ENV_FILES:
        if not env_file.exists():
            continue
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                raw = line.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                key, value = raw.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
            log.info(f"Заредени env стойности от {env_file.name}")
        except Exception as exc:
            log.warning(f"Проблем при четене на {env_file.name}: {exc}")


def warn_if_telegram_not_configured() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chats = os.getenv("TELEGRAM_CHAT_IDS", os.getenv("TELEGRAM_CHAT_ID", "")).strip()
    if not token or not chats:
        log.warning(
            "Telegram липсва в средата. Добави TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_IDS в .env/.env.local."
        )


def data_refresh_loop(stop_event: threading.Event) -> None:
    script = BASE_DIR / "generate_web_data.py"
    while not stop_event.is_set():
        try:
            completed = subprocess.run(
                [PYTHON, str(script)],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0:
                if completed.stdout.strip():
                    log.info(completed.stdout.strip())
            else:
                stderr = completed.stderr.strip() if completed.stderr else "n/a"
                log.error(f"{script.name} failed (code {completed.returncode}): {stderr}")
        except Exception as exc:
            log.error(f"Грешка при {script.name}: {exc}")

        stop_event.wait(DATA_REFRESH_INTERVAL)


def main():
    load_local_env_files()
    warn_if_telegram_not_configured()

    log.info("=" * 50)
    log.info("NewsTracker Launcher стартиран")
    for s in SCRIPT_TARGETS:
        if not s.exists():
            log.error(f"Не е намерен файл: {s}")
            sys.exit(1)
    log.info("=" * 50)

    process_launchers: dict[str, callable] = {
        "border_news_monitor.py": lambda: launch_python_script(BASE_DIR / "border_news_monitor.py"),
        "customs_scraper.py": lambda: launch_python_script(BASE_DIR / "customs_scraper.py"),
    }

    dashboard_available = DASHBOARD_DIR.exists() and shutil.which("npm")
    web_target_port = DASHBOARD_PORT
    if dashboard_available:
        process_launchers["dashboard_dev_server"] = launch_dashboard_server
    else:
        if not DASHBOARD_DIR.exists():
            log.warning("intelligence-dashboard липсва — превключване към docs web server.")
        elif not shutil.which("npm"):
            log.warning("npm не е намерен — превключване към docs web server.")
        if not DOCS_DIR.exists():
            log.error(f"Не е намерена папка: {DOCS_DIR}")
            sys.exit(1)
        web_target_port = DOCS_PORT
        process_launchers["docs_http_server"] = launch_docs_server

    tunnel_proc = launch_cloudflared_tunnel(web_target_port)
    if tunnel_proc is not None:
        process_launchers["cloudflared_tunnel"] = lambda: launch_cloudflared_tunnel(web_target_port)

    processes: dict[str, subprocess.Popen] = {}
    for name, launcher in process_launchers.items():
        proc = launcher()
        if proc is not None:
            processes[name] = proc

    stop_event = threading.Event()
    refresher = threading.Thread(
        target=data_refresh_loop,
        args=(stop_event,),
        daemon=True,
    )
    refresher.start()

    try:
        while True:
            for name, proc in list(processes.items()):
                ret = proc.poll()
                if ret is not None:
                    log.warning(f"{name} спря (код {ret}). Рестарт след {RESTART_DELAY}с...")
                    time.sleep(RESTART_DELAY)
                    replacement = process_launchers[name]()
                    if replacement is not None:
                        processes[name] = replacement
            time.sleep(5)
    except KeyboardInterrupt:
        log.info("Спиране...")
        stop_event.set()
        for name, proc in processes.items():
            proc.terminate()
            log.info(f"  Спрян: {name}")


if __name__ == "__main__":
    main()